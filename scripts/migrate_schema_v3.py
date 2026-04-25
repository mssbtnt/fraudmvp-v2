#!/usr/bin/env python3
"""
FraudMVP Schema Migration v2 → v3

Adds Phase 2 columns to campaigns table:
  - name TEXT DEFAULT ''
  - scam_type_tier TEXT DEFAULT 'keyword'
  - scam_type_confidence REAL DEFAULT 0.0
  - relationship_boost REAL DEFAULT 0.0
  - trend_status TEXT DEFAULT 'stable'

Also verifies campaign_type CHECK constraint supports all 10 canonical types.

Usage:
    python scripts/migrate_schema_v3.py              # Run migration
    python scripts/migrate_schema_v3.py --verify       # Verify schema
    python scripts/migrate_schema_v3.py --dry-run      # Preview changes
"""

from __future__ import annotations

import argparse
import logging
import os
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("migrate_v3")

DB_PATH = Path(__file__).parent.parent / "db" / "fraud_mvp.db"
SCHEMA_PATH = Path(__file__).parent.parent / "db" / "schema.sql"
LOCK_PATH = DB_PATH.with_suffix(DB_PATH.suffix + ".migration.lock")

# New columns to add
NEW_COLUMNS = [
    ("name", "TEXT DEFAULT ''"),
    ("scam_type_tier", "TEXT DEFAULT 'keyword'"),
    ("scam_type_confidence", "REAL DEFAULT 0.0"),
    ("relationship_boost", "REAL DEFAULT 0.0"),
    ("trend_status", "TEXT DEFAULT 'stable'"),
]

# Valid values for new columns
VALID_TIERS = {"keyword", "llm", "cross_reference"}
VALID_TREND_STATUSES = {"spike", "rising", "increasing", "stable", "declining"}
VALID_CAMPAIGN_TYPES = {
    "investment", "job_task", "aid_gov", "phishing", "loan_shark",
    "romance", "ecommerce", "qr", "macau", "unknown"
}


def backup_db(db_path: Path) -> Path:
    """Create a timestamped backup of the database."""
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    backup_path = db_path.parent / f"fraud_mvp.db.backup-v3-{timestamp}"
    shutil.copy2(db_path, backup_path)
    log.info(f"Backup: {backup_path}")
    return backup_path


def acquire_migration_lock(lock_path: Path) -> None:
    """Create a simple file lock so runtime workers fail fast during migration."""
    try:
        fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise RuntimeError(
            f"Migration lock already exists: {lock_path}. "
            "Do not run concurrent schema migrations or pipeline jobs."
        )
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(f"pid={os.getpid()} started_at={datetime.now().isoformat()}\n")


def release_migration_lock(lock_path: Path) -> None:
    if lock_path.exists():
        lock_path.unlink()


def migrate(db_path: Path, dry_run: bool = False) -> dict:
    """Run v2 → v3 migration."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    stats = {"columns_added": 0, "columns_existing": 0, "rows_updated": 0}

    # Get existing columns
    cursor = conn.execute("PRAGMA table_info(campaigns)")
    existing_columns = {row[1] for row in cursor.fetchall()}
    log.info(f"Existing campaigns columns: {sorted(existing_columns)}")

    # Add new columns
    for col_name, col_type in NEW_COLUMNS:
        if col_name in existing_columns:
            log.info(f"  Column '{col_name}' already exists — skipping")
            stats["columns_existing"] += 1
        else:
            sql = f"ALTER TABLE campaigns ADD COLUMN {col_name} {col_type}"
            log.info(f"  Adding column: {col_name} ({col_type})")
            if not dry_run:
                conn.execute(sql)
            stats["columns_added"] += 1

    if not dry_run:
        conn.execute("PRAGMA user_version = 3")
        conn.commit()

    # Verify campaign_type CHECK constraint supports 10 types
    # SQLite doesn't support ALTER CHECK, so we verify existing data
    log.info("Verifying campaign_type values...")
    type_counts = {}
    rows = conn.execute(
        "SELECT campaign_type, COUNT(*) as cnt FROM campaigns GROUP BY campaign_type"
    ).fetchall()
    for row in rows:
        ct = row["campaign_type"]
        cnt = row["cnt"]
        type_counts[ct] = cnt
        if ct not in VALID_CAMPAIGN_TYPES:
            log.warning(f"  Unknown campaign_type '{ct}' ({cnt} rows) — should be normalized")
        else:
            log.info(f"  campaign_type '{ct}': {cnt} rows")

    conn.close()
    return stats


def verify(db_path: Path) -> dict:
    """Verify v3 schema is correct."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    results = {"ok": True, "checks": []}

    # Check all tables exist
    tables = {row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()}
    
    expected_tables = {
        "entities", "entity_edges", "campaigns", "sources", "scraped_messages",
        "alert_log", "cross_references", "victim_signals", "entity_mentions",
        "campaign_links", "entity_relationships",
    }
    
    for t in expected_tables:
        if t in tables:
            results["checks"].append(f"[OK] Table {t} exists")
        else:
            results["checks"].append(f"[FAIL] Table {t} missing")
            results["ok"] = False

    # Check new columns
    cursor = conn.execute("PRAGMA table_info(campaigns)")
    existing_columns = {row[1] for row in cursor.fetchall()}
    
    for col_name, _ in NEW_COLUMNS:
        if col_name in existing_columns:
            results["checks"].append(f"[OK] Column campaigns.{col_name} exists")
        else:
            results["checks"].append(f"[FAIL] Column campaigns.{col_name} missing")
            results["ok"] = False

    # Check indexes
    indexes = {row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()}
    
    expected_indexes = {
        "idx_entities_campaign", "idx_entities_value", "idx_entities_type",
        "idx_entities_last_seen", "idx_entity_edges_entity", "idx_entity_edges_channel",
        "idx_entity_edges_timestamp", "idx_campaigns_score", "idx_campaigns_risk",
        "idx_campaigns_type", "idx_scraped_messages_hash", "idx_scraped_messages_platform",
        "idx_scraped_messages_channel", "idx_alert_log_campaign",
        "idx_cross_ref_entity", "idx_cross_ref_source",
        "idx_victim_signal_entity", "idx_victim_signal_type",
        "idx_mentions_entity_date", "idx_campaign_links_campaign",
        "idx_campaign_links_entity", "idx_rel_source", "idx_rel_target", "idx_rel_type",
    }
    
    for idx in expected_indexes:
        if idx in indexes:
            results["checks"].append(f"[OK] Index {idx}")
        else:
            results["checks"].append(f"[FAIL] Index {idx} missing")
            results["ok"] = False

    # Check data integrity
    entity_count = conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
    results["checks"].append(f"[OK] Entity count: {entity_count}")

    campaign_count = conn.execute("SELECT COUNT(*) FROM campaigns").fetchone()[0]
    results["checks"].append(f"[OK] Campaign count: {campaign_count}")

    # Check campaign_type values
    invalid_types = conn.execute(
        "SELECT DISTINCT campaign_type FROM campaigns WHERE campaign_type NOT IN "
        "('investment','job_task','aid_gov','phishing','loan_shark','romance','ecommerce','qr','macau','unknown')"
    ).fetchall()
    if invalid_types:
        results["checks"].append(f"[WARN] Invalid campaign types: {[r[0] for r in invalid_types]}")
    else:
        results["checks"].append("[OK] All campaign_type values valid")

    # Check FTS table
    fts_exists = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='messages_fts'"
    ).fetchone()
    if fts_exists:
        results["checks"].append("[OK] FTS5 table messages_fts exists")
    else:
        results["checks"].append("[WARN] FTS5 table messages_fts missing")

    conn.close()
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="FraudMVP Schema Migration v2 → v3")
    parser.add_argument("--verify", action="store_true", help="Verify v3 schema")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without applying")
    args = parser.parse_args()

    if not DB_PATH.exists():
        print(f"ERROR: Database not found at {DB_PATH}")
        exit(1)

    if args.verify:
        print(f"\n{'='*60}")
        print(f"  FraudMVP Schema Verification (v3)")
        print(f"  DB: {DB_PATH}")
        print(f"{'='*60}\n")
        results = verify(DB_PATH)
        for check in results["checks"]:
            print(f"  {check}")
        print(f"\n  Result: {'✅ PASS' if results['ok'] else '❌ FAIL'}")
        print(f"{'='*60}\n")
    else:
        print(f"\n{'='*60}")
        print(f"  FraudMVP Schema Migration v2 → v3")
        print(f"  {'DRY RUN' if args.dry_run else 'LIVE'}")
        print(f"  DB: {DB_PATH}")
        print(f"{'='*60}\n")

        if not args.dry_run:
            backup_db(DB_PATH)
            acquire_migration_lock(LOCK_PATH)

        try:
            stats = migrate(DB_PATH, dry_run=args.dry_run)
            print(f"\n  Columns added: {stats['columns_added']}")
            print(f"  Columns existing: {stats['columns_existing']}")

            print(f"\n  Verifying...")
            results = verify(DB_PATH)
            for check in results["checks"]:
                print(f"  {check}")

            print(f"\n  Result: {'✅ PASS' if results['ok'] else '❌ FAIL'}")
        finally:
            if not args.dry_run:
                release_migration_lock(LOCK_PATH)
        print(f"{'='*60}\n")
