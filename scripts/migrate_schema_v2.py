#!/usr/bin/env python3
"""
FraudMVP Schema Migration v2 — Phase 1 Alert Intelligence Enhancement

Adds:
- cross_references table (BNM/SC/SemakMule match cache)
- victim_signals table (financial loss, police reports, community warnings)
- entity_mentions table (daily mention tracking for trend detection)
- campaign_links table (explicit entity-to-campaign relationships)
- entity_relationships table (entity co-occurrence graph)
- Expanded entities CHECK constraint (add app_url, instagram_url, twitter_url)
- Expanded campaigns CHECK constraint (add loan_shark, romance, ecommerce, qr, macau)

Usage:
    python scripts/migrate_schema_v2.py              # Run migration
    python scripts/migrate_schema_v2.py --dry-run     # Preview changes
    python scripts/migrate_schema_v2.py --verify       # Verify schema after migration
"""

from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

# ─── Config ───────────────────────────────────────────────────────────────────

DB_PATH = Path(__file__).parent.parent / "db" / "fraud_mvp.db"
SCHEMA_PATH = Path(__file__).parent.parent / "db" / "schema.sql"
LOCK_PATH = DB_PATH.with_suffix(DB_PATH.suffix + ".migration.lock")

# ─── New entity types ────────────────────────────────────────────────────────

NEW_ENTITY_TYPES = ["app_url", "instagram_url", "twitter_url"]

ALL_ENTITY_TYPES = [
    "phone", "bank_account", "domain", "wallet", "url", "email", "ip",
    "company_name", "facebook_url", "facebook_page", "telegram_url",
    "telegram_channel", "whatsapp_link", "whatsapp_contact",
    "app_url", "instagram_url", "twitter_url",
]

# ─── New campaign types ──────────────────────────────────────────────────────

NEW_CAMPAIGN_TYPES = ["loan_shark", "romance", "ecommerce", "qr", "macau"]

ALL_CAMPAIGN_TYPES = [
    "investment", "job_task", "aid_gov", "phishing", "unknown",
    "loan_shark", "romance", "ecommerce", "qr", "macau",
]

# ─── DDL for new tables ──────────────────────────────────────────────────────

NEW_TABLES_DDL = """
-- Cross-reference results cache (BNM, SC, SemakMule matches)
CREATE TABLE IF NOT EXISTS cross_references (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_id INTEGER NOT NULL,
    source_db TEXT NOT NULL,              -- 'bnm', 'sc', 'semakmule', 'internal'
    source_entity_name TEXT,              -- Name from the source listing
    match_confidence REAL DEFAULT 0.0,    -- 0.0-1.0
    listed_date TEXT,                     -- When entity was listed
    status TEXT DEFAULT 'confirmed',      -- confirmed, suspected, verified
    checked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (entity_id) REFERENCES entities(id)
);
CREATE INDEX IF NOT EXISTS idx_cross_ref_entity ON cross_references(entity_id);
CREATE INDEX IF NOT EXISTS idx_cross_ref_source ON cross_references(source_db);

-- Victim signal detections (financial loss, police reports, etc.)
CREATE TABLE IF NOT EXISTS victim_signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id INTEGER,
    entity_id INTEGER,
    signal_type TEXT NOT NULL,             -- 'financial_loss', 'police_report', 'community_warning', 'emotional'
    pattern_matched TEXT,                  -- The regex pattern that matched
    extracted_text TEXT,                   -- The matching text snippet
    extracted_amount REAL,                 -- If monetary amount was extracted (e.g., 50000.0)
    weight INTEGER DEFAULT 0,              -- Signal weight for scoring
    detected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (message_id) REFERENCES scraped_messages(id),
    FOREIGN KEY (entity_id) REFERENCES entities(id)
);
CREATE INDEX IF NOT EXISTS idx_victim_signal_entity ON victim_signals(entity_id);
CREATE INDEX IF NOT EXISTS idx_victim_signal_type ON victim_signals(signal_type);

-- Entity mention tracking (for trend/spike detection)
CREATE TABLE IF NOT EXISTS entity_mentions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_id INTEGER NOT NULL,
    date DATE NOT NULL,
    mention_count INTEGER DEFAULT 1,
    channel_count INTEGER DEFAULT 0,
    platforms TEXT DEFAULT '[]',           -- JSON array of platforms seen
    FOREIGN KEY (entity_id) REFERENCES entities(id),
    UNIQUE(entity_id, date)
);
CREATE INDEX IF NOT EXISTS idx_mentions_entity_date ON entity_mentions(entity_id, date);

-- Campaign entity links (explicit entity-to-campaign relationships)
CREATE TABLE IF NOT EXISTS campaign_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id INTEGER NOT NULL,
    entity_id INTEGER NOT NULL,
    link_type TEXT NOT NULL,               -- 'co_occurrence', 'shared_phone', 'shared_domain', 'semantic', 'cross_reference'
    confidence REAL DEFAULT 1.0,           -- How confident the link is
    detected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (campaign_id) REFERENCES campaigns(id),
    FOREIGN KEY (entity_id) REFERENCES entities(id),
    UNIQUE(campaign_id, entity_id, link_type)
);
CREATE INDEX IF NOT EXISTS idx_campaign_links_campaign ON campaign_links(campaign_id);
CREATE INDEX IF NOT EXISTS idx_campaign_links_entity ON campaign_links(entity_id);

-- Entity relationships (co-occurrence graph)
CREATE TABLE IF NOT EXISTS entity_relationships (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_entity_id INTEGER NOT NULL,
    target_entity_id INTEGER NOT NULL,
    relationship_type TEXT NOT NULL,        -- 'co_occurs', 'shared_phone', 'shared_domain', 'same_campaign', 'registered_to'
    confidence REAL DEFAULT 1.0,
    evidence TEXT,                         -- JSON: message IDs, channels, dates
    first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    count INTEGER DEFAULT 1,
    FOREIGN KEY (source_entity_id) REFERENCES entities(id),
    FOREIGN KEY (target_entity_id) REFERENCES entities(id),
    UNIQUE(source_entity_id, target_entity_id, relationship_type)
);
CREATE INDEX IF NOT EXISTS idx_rel_source ON entity_relationships(source_entity_id);
CREATE INDEX IF NOT EXISTS idx_rel_target ON entity_relationships(target_entity_id);
CREATE INDEX IF NOT EXISTS idx_rel_type ON entity_relationships(relationship_type);
"""

# ─── Migration Functions ──────────────────────────────────────────────────────


def backup_db(db_path: Path) -> Path:
    """Create a timestamped backup of the database."""
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    backup_path = db_path.parent / f"fraud_mvp.db.backup-{timestamp}"
    shutil.copy2(db_path, backup_path)
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


def get_current_entity_types(conn: sqlite3.Connection) -> list[str]:
    """Extract current entity type CHECK constraint from entities table."""
    cursor = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='entities'"
    )
    row = cursor.fetchone()
    if not row:
        return []
    sql = row[0]
    # Extract CHECK(type IN (...)) — handles multiline with newlines/spaces
    import re
    match = re.search(r"CHECK\(type\s+IN\s*\((.+?)\)\)", sql, re.DOTALL)
    if not match:
        return []
    types_str = match.group(1)
    # Handle types across multiple lines, with or without spaces
    types_str = types_str.replace("\n", " ").replace("\r", " ")
    types = [t.strip().strip("'\"") for t in types_str.split(",") if t.strip()]
    return types


def get_current_campaign_types(conn: sqlite3.Connection) -> list[str]:
    """Extract current campaign_type CHECK constraint from campaigns table."""
    cursor = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='campaigns'"
    )
    row = cursor.fetchone()
    if not row:
        return []
    sql = row[0]
    # Extract CHECK(campaign_type IN (...)) — handles multiline
    import re
    match = re.search(r"CHECK\(campaign_type\s+IN\s*\((.+?)\)\)", sql, re.DOTALL)
    if not match:
        return []
    types_str = match.group(1)
    types_str = types_str.replace("\n", " ").replace("\r", " ")
    types = [t.strip().strip("'\"") for t in types_str.split(",") if t.strip()]
    return types


def needs_entity_migration(conn: sqlite3.Connection) -> bool:
    """Check if entities table CHECK constraint needs updating."""
    current = get_current_entity_types(conn)
    missing = [t for t in ALL_ENTITY_TYPES if t not in current]
    return len(missing) > 0


def needs_campaign_migration(conn: sqlite3.Connection) -> bool:
    """Check if campaigns table CHECK constraint needs updating."""
    current = get_current_campaign_types(conn)
    missing = [t for t in ALL_CAMPAIGN_TYPES if t not in current]
    return len(missing) > 0


def migrate_entities_table(conn: sqlite3.Connection, dry_run: bool = False) -> bool:
    """
    Migrate entities table to expand CHECK constraint.
    Uses dump-recreate-reimport pattern since SQLite can't ALTER constraints.
    """
    current_types = get_current_entity_types(conn)
    missing_types = [t for t in ALL_ENTITY_TYPES if t not in current_types]
    if not missing_types:
        print(f"  [SKIP] entities CHECK constraint already up-to-date")
        return False

    print(f"  [MIGRATE] entities: adding types {missing_types}")
    print(f"  Current types: {current_types}")
    print(f"  New types: {ALL_ENTITY_TYPES}")

    if dry_run:
        print(f"  [DRY-RUN] Would recreate entities table with expanded CHECK constraint")
        return True

    # Build new CREATE TABLE with expanded CHECK
    types_list = ", ".join(f"'{t}'" for t in ALL_ENTITY_TYPES)
    new_sql = f"""CREATE TABLE entities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    value TEXT NOT NULL,
    type TEXT NOT NULL CHECK(type IN ({types_list})),
    first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    count INTEGER DEFAULT 1,
    campaign_id INTEGER,
    metadata TEXT,
    UNIQUE(value, type)
)"""

    # Step 1: Rename old table
    conn.execute("ALTER TABLE entities RENAME TO entities_old")

    # Step 2: Create new table
    conn.execute(new_sql)

    # Step 3: Copy data
    conn.execute("""
        INSERT INTO entities (id, value, type, first_seen, last_seen, count, campaign_id, metadata)
        SELECT id, value, type, first_seen, last_seen, count, campaign_id, metadata
        FROM entities_old
    """)

    # Step 4: Drop old table
    conn.execute("DROP TABLE entities_old")

    # Step 5: Recreate indexes (they reference the old table)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_entities_campaign ON entities(campaign_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_entities_value ON entities(value)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_entities_type ON entities(type)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_entities_last_seen ON entities(last_seen)")

    conn.commit()
    return True


def rebuild_entity_edges_table(conn: sqlite3.Connection, dry_run: bool = False) -> bool:
    """
    Rebuild entity_edges so its foreign key points at entities, not entities_old.
    """
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='entity_edges'"
    ).fetchone()
    if not row or "entities_old" not in (row[0] or ""):
        print("  [SKIP] entity_edges foreign key already references entities")
        return False

    print("  [REBUILD] entity_edges foreign key references entities_old")
    if dry_run:
        print("  [DRY-RUN] Would recreate entity_edges with a correct foreign key")
        return True

    conn.execute("ALTER TABLE entity_edges RENAME TO entity_edges_old")
    conn.execute(
        """
        CREATE TABLE entity_edges (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entity_id INTEGER NOT NULL,
            channel TEXT NOT NULL,
            platform TEXT NOT NULL DEFAULT 'telegram',
            channel_id TEXT,
            member_count INTEGER DEFAULT 0,
            message_hash TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (entity_id) REFERENCES entities(id) ON DELETE CASCADE
        )
        """
    )
    conn.execute(
        """
        INSERT INTO entity_edges
            (id, entity_id, channel, platform, channel_id, member_count, message_hash, timestamp)
        SELECT id, entity_id, channel, platform, channel_id, member_count, message_hash, timestamp
        FROM entity_edges_old
        """
    )
    conn.execute("DROP TABLE entity_edges_old")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_entity_edges_entity ON entity_edges(entity_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_entity_edges_channel ON entity_edges(channel)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_entity_edges_timestamp ON entity_edges(timestamp)")
    conn.commit()
    return True


def migrate_campaigns_table(conn: sqlite3.Connection, dry_run: bool = False) -> bool:
    """
    Migrate campaigns table to expand CHECK constraint.
    Uses dump-recreate-reimport pattern.
    """
    current_types = get_current_campaign_types(conn)
    missing_types = [t for t in ALL_CAMPAIGN_TYPES if t not in current_types]
    if not missing_types:
        print(f"  [SKIP] campaigns CHECK constraint already up-to-date")
        return False

    print(f"  [MIGRATE] campaigns: adding types {missing_types}")
    print(f"  Current types: {current_types}")
    print(f"  New types: {ALL_CAMPAIGN_TYPES}")

    if dry_run:
        print(f"  [DRY-RUN] Would recreate campaigns table with expanded CHECK constraint")
        return True

    # Build new CREATE TABLE with expanded CHECK
    types_list = ", ".join(f"'{t}'" for t in ALL_CAMPAIGN_TYPES)
    new_sql = f"""CREATE TABLE campaigns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    score INTEGER NOT NULL,
    risk_level TEXT NOT NULL CHECK(risk_level IN (
        'low', 'medium', 'high', 'critical'
    )),
    campaign_type TEXT NOT NULL CHECK(campaign_type IN ({types_list})),
    entity_ids TEXT NOT NULL,
    channel_ids TEXT NOT NULL,
    keywords TEXT,
    reason TEXT,
    script_sample TEXT,
    first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    alert_sent BOOLEAN DEFAULT 0,
    alert_sent_at TIMESTAMP
)"""

    # Step 1: Rename old table
    conn.execute("ALTER TABLE campaigns RENAME TO campaigns_old")

    # Step 2: Create new table
    conn.execute(new_sql)

    # Step 3: Copy data
    conn.execute("""
        INSERT INTO campaigns (id, score, risk_level, campaign_type, entity_ids, channel_ids,
                                keywords, reason, script_sample, first_seen, last_seen,
                                alert_sent, alert_sent_at)
        SELECT id, score, risk_level, campaign_type, entity_ids, channel_ids,
               keywords, reason, script_sample, first_seen, last_seen,
               alert_sent, alert_sent_at
        FROM campaigns_old
    """)

    # Step 4: Drop old table
    conn.execute("DROP TABLE campaigns_old")

    # Step 5: Recreate indexes
    conn.execute("CREATE INDEX IF NOT EXISTS idx_campaigns_score ON campaigns(score)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_campaigns_risk ON campaigns(risk_level)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_campaigns_type ON campaigns(campaign_type)")

    conn.commit()
    return True


def create_new_tables(conn: sqlite3.Connection, dry_run: bool = False) -> list[str]:
    """Create new tables for Phase 1."""
    created = []
    for statement in NEW_TABLES_DDL.strip().split(";"):
        statement = statement.strip()
        if not statement or statement.startswith("--"):
            continue
        # Extract table name
        import re
        match = re.search(r"CREATE TABLE IF NOT EXISTS (\w+)", statement)
        if not match:
            continue
        table_name = match.group(1)

        # Check if table already exists
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table_name,),
        )
        if cursor.fetchone():
            print(f"  [SKIP] Table {table_name} already exists")
            continue

        if dry_run:
            print(f"  [DRY-RUN] Would create table {table_name}")
            created.append(table_name)
            continue

        conn.execute(statement)
        created.append(table_name)
        print(f"  [CREATE] Table {table_name}")

    if created and not dry_run:
        conn.commit()
    return created


def update_schema_file(dry_run: bool = False) -> bool:
    """Update db/schema.sql to reflect the new schema."""
    if dry_run:
        print(f"  [DRY-RUN] Would update {SCHEMA_PATH}")
        return True

    # Build the full schema SQL
    types_list = ", ".join(f"'{t}'" for t in ALL_ENTITY_TYPES)
    campaign_types_list = ", ".join(f"'{t}'" for t in ALL_CAMPAIGN_TYPES)

    schema_sql = f"""-- Fraud MVP SQLite Schema v2 — Alert Intelligence Enhancement
-- Run with: sqlite3 db/fraud_mvp.db < db/schema.sql
-- Migration: python scripts/migrate_schema_v2.py

CREATE TABLE IF NOT EXISTS entities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    value TEXT NOT NULL,
    type TEXT NOT NULL CHECK(type IN (
        {types_list}
    )),
    first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    count INTEGER DEFAULT 1,
    campaign_id INTEGER,
    metadata TEXT,  -- JSON blob for extra data
    UNIQUE(value, type)
);

CREATE TABLE IF NOT EXISTS entity_edges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_id INTEGER NOT NULL,
    channel TEXT NOT NULL,
    platform TEXT NOT NULL DEFAULT 'telegram',
    channel_id TEXT,
    member_count INTEGER DEFAULT 0,
    message_hash TEXT,  -- dedup
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (entity_id) REFERENCES entities(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS campaigns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    score INTEGER NOT NULL,
    risk_level TEXT NOT NULL CHECK(risk_level IN (
        'low', 'medium', 'high', 'critical'
    )),
    campaign_type TEXT NOT NULL CHECK(campaign_type IN (
        {campaign_types_list}
    )),
    entity_ids TEXT NOT NULL,  -- JSON array of entity IDs
    channel_ids TEXT NOT NULL,  -- JSON array of channel identifiers
    keywords TEXT,  -- JSON array of matched keywords
    reason TEXT,
    script_sample TEXT,  -- Sample text for similarity matching
    first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    alert_sent BOOLEAN DEFAULT 0,
    alert_sent_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    url TEXT,
    platform TEXT NOT NULL DEFAULT 'web',
    type TEXT DEFAULT 'complaint_db',
    reliability_score REAL DEFAULT 0.5,
    tags TEXT,  -- JSON array
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_scraped TIMESTAMP,
    is_active BOOLEAN DEFAULT 1
);

CREATE TABLE IF NOT EXISTS scraped_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    platform TEXT NOT NULL,
    channel TEXT NOT NULL,
    channel_id TEXT,
    message_id TEXT,
    sender_id TEXT,
    text TEXT,
    text_hash TEXT UNIQUE,  -- dedup
    raw_json TEXT,  -- Full message JSON
    scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS alert_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id INTEGER,
    alert_level TEXT NOT NULL,
    message TEXT,
    sent_to TEXT,  -- Telegram chat ID or channel
    sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    status TEXT DEFAULT 'pending',
    response TEXT
);

-- ─── Phase 1: Cross-Reference Tables ────────────────────────────────────────

CREATE TABLE IF NOT EXISTS cross_references (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_id INTEGER NOT NULL,
    source_db TEXT NOT NULL,              -- 'bnm', 'sc', 'semakmule', 'internal'
    source_entity_name TEXT,              -- Name from the source listing
    match_confidence REAL DEFAULT 0.0,    -- 0.0-1.0
    listed_date TEXT,                     -- When entity was listed
    status TEXT DEFAULT 'confirmed',      -- confirmed, suspected, verified
    checked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (entity_id) REFERENCES entities(id)
);
CREATE INDEX IF NOT EXISTS idx_cross_ref_entity ON cross_references(entity_id);
CREATE INDEX IF NOT EXISTS idx_cross_ref_source ON cross_references(source_db);

-- ─── Phase 1: Victim Signal Tables ───────────────────────────────────────────

CREATE TABLE IF NOT EXISTS victim_signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id INTEGER,
    entity_id INTEGER,
    signal_type TEXT NOT NULL,             -- 'financial_loss', 'police_report', 'community_warning', 'emotional'
    pattern_matched TEXT,                  -- The regex pattern that matched
    extracted_text TEXT,                   -- The matching text snippet
    extracted_amount REAL,                 -- If monetary amount was extracted
    weight INTEGER DEFAULT 0,             -- Signal weight for scoring
    detected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (message_id) REFERENCES scraped_messages(id),
    FOREIGN KEY (entity_id) REFERENCES entities(id)
);
CREATE INDEX IF NOT EXISTS idx_victim_signal_entity ON victim_signals(entity_id);
CREATE INDEX IF NOT EXISTS idx_victim_signal_type ON victim_signals(signal_type);

-- ─── Phase 3: Trend Detection Tables ────────────────────────────────────────

CREATE TABLE IF NOT EXISTS entity_mentions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_id INTEGER NOT NULL,
    date DATE NOT NULL,
    mention_count INTEGER DEFAULT 1,
    channel_count INTEGER DEFAULT 0,
    platforms TEXT DEFAULT '[]',           -- JSON array of platforms seen
    FOREIGN KEY (entity_id) REFERENCES entities(id),
    UNIQUE(entity_id, date)
);
CREATE INDEX IF NOT EXISTS idx_mentions_entity_date ON entity_mentions(entity_id, date);

-- ─── Phase 2: Campaign Clustering Tables ────────────────────────────────────

CREATE TABLE IF NOT EXISTS campaign_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id INTEGER NOT NULL,
    entity_id INTEGER NOT NULL,
    link_type TEXT NOT NULL,               -- 'co_occurrence', 'shared_phone', 'shared_domain', 'semantic', 'cross_reference'
    confidence REAL DEFAULT 1.0,           -- How confident the link is
    detected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (campaign_id) REFERENCES campaigns(id),
    FOREIGN KEY (entity_id) REFERENCES entities(id),
    UNIQUE(campaign_id, entity_id, link_type)
);
CREATE INDEX IF NOT EXISTS idx_campaign_links_campaign ON campaign_links(campaign_id);
CREATE INDEX IF NOT EXISTS idx_campaign_links_entity ON campaign_links(entity_id);

-- ─── Phase 3: Entity Relationship Graph ──────────────────────────────────────

CREATE TABLE IF NOT EXISTS entity_relationships (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_entity_id INTEGER NOT NULL,
    target_entity_id INTEGER NOT NULL,
    relationship_type TEXT NOT NULL,        -- 'co_occurs', 'shared_phone', 'shared_domain', 'same_campaign', 'registered_to'
    confidence REAL DEFAULT 1.0,
    evidence TEXT,                          -- JSON: message IDs, channels, dates
    first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    count INTEGER DEFAULT 1,
    FOREIGN KEY (source_entity_id) REFERENCES entities(id),
    FOREIGN KEY (target_entity_id) REFERENCES entities(id),
    UNIQUE(source_entity_id, target_entity_id, relationship_type)
);
CREATE INDEX IF NOT EXISTS idx_rel_source ON entity_relationships(source_entity_id);
CREATE INDEX IF NOT EXISTS idx_rel_target ON entity_relationships(target_entity_id);
CREATE INDEX IF NOT EXISTS idx_rel_type ON entity_relationships(relationship_type);

-- ─── Indexes for original tables ─────────────────────────────────────────────

CREATE INDEX IF NOT EXISTS idx_entities_campaign ON entities(campaign_id);
CREATE INDEX IF NOT EXISTS idx_entities_value ON entities(value);
CREATE INDEX IF NOT EXISTS idx_entities_type ON entities(type);
CREATE INDEX IF NOT EXISTS idx_entities_last_seen ON entities(last_seen);
CREATE INDEX IF NOT EXISTS idx_entity_edges_entity ON entity_edges(entity_id);
CREATE INDEX IF NOT EXISTS idx_entity_edges_channel ON entity_edges(channel);
CREATE INDEX IF NOT EXISTS idx_entity_edges_timestamp ON entity_edges(timestamp);
CREATE INDEX IF NOT EXISTS idx_campaigns_score ON campaigns(score);
CREATE INDEX IF NOT EXISTS idx_campaigns_risk ON campaigns(risk_level);
CREATE INDEX IF NOT EXISTS idx_campaigns_type ON campaigns(campaign_type);
CREATE INDEX IF NOT EXISTS idx_scraped_messages_hash ON scraped_messages(text_hash);
CREATE INDEX IF NOT EXISTS idx_scraped_messages_platform ON scraped_messages(platform);
CREATE INDEX IF NOT EXISTS idx_scraped_messages_channel ON scraped_messages(channel);
CREATE INDEX IF NOT EXISTS idx_alert_log_campaign ON alert_log(campaign_id);

-- ─── FTS5 for full-text search on messages ────────────────────────────────────

CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
    text,
    channel,
    content='scraped_messages',
    content_rowid='id'
);
"""

    SCHEMA_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(SCHEMA_PATH, "w", encoding="utf-8") as f:
        f.write(schema_sql)

    print(f"  [WRITE] Updated {SCHEMA_PATH}")
    return True


def verify_schema(conn: sqlite3.Connection) -> bool:
    """Verify all tables and constraints are correct."""
    all_ok = True

    # Check all expected tables exist
    expected_tables = [
        "entities", "entity_edges", "campaigns", "sources", "scraped_messages",
        "alert_log", "cross_references", "victim_signals", "entity_mentions",
        "campaign_links", "entity_relationships",
    ]

    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    )
    existing_tables = {row[0] for row in cursor.fetchall()}

    for table in expected_tables:
        if table in existing_tables:
            print(f"  [OK] Table {table} exists")
        else:
            print(f"  [MISSING] Table {table} does NOT exist")
            all_ok = False

    # Check entities CHECK constraint
    entity_types = get_current_entity_types(conn)
    missing_entity = [t for t in ALL_ENTITY_TYPES if t not in entity_types]
    if missing_entity:
        print(f"  [MISSING] Entity types: {missing_entity}")
        all_ok = False
    else:
        print(f"  [OK] Entity types: all {len(entity_types)} types present")

    # Check campaigns CHECK constraint
    campaign_types = get_current_campaign_types(conn)
    missing_campaign = [t for t in ALL_CAMPAIGN_TYPES if t not in campaign_types]
    if missing_campaign:
        print(f"  [MISSING] Campaign types: {missing_campaign}")
        all_ok = False
    else:
        print(f"  [OK] Campaign types: all {len(campaign_types)} types present")

    # Check indexes
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' ORDER BY name"
    )
    existing_indexes = {row[0] for row in cursor.fetchall()}

    expected_indexes = [
        "idx_entities_campaign", "idx_entities_value", "idx_entities_type",
        "idx_entities_last_seen", "idx_entity_edges_entity", "idx_entity_edges_channel",
        "idx_entity_edges_timestamp", "idx_campaigns_score", "idx_campaigns_risk",
        "idx_campaigns_type", "idx_scraped_messages_hash", "idx_scraped_messages_platform",
        "idx_scraped_messages_channel", "idx_alert_log_campaign",
        "idx_cross_ref_entity", "idx_cross_ref_source",
        "idx_victim_signal_entity", "idx_victim_signal_type",
        "idx_mentions_entity_date",
        "idx_campaign_links_campaign", "idx_campaign_links_entity",
        "idx_rel_source", "idx_rel_target", "idx_rel_type",
    ]

    for idx in expected_indexes:
        if idx in existing_indexes:
            print(f"  [OK] Index {idx}")
        else:
            print(f"  [MISSING] Index {idx}")
            all_ok = False

    # Check row counts
    cursor = conn.execute("SELECT count(*) FROM entities")
    entity_count = cursor.fetchone()[0]
    print(f"  [INFO] entities: {entity_count} rows")

    return all_ok


def run_migration(dry_run: bool = False) -> None:
    """Run the full migration."""
    print(f"\n{'='*60}")
    print(f"  FraudMVP Schema Migration v2")
    print(f"  {'DRY RUN' if dry_run else 'LIVE'}")
    print(f"{'='*60}\n")

    if not DB_PATH.exists():
        print(f"  [ERROR] Database not found: {DB_PATH}")
        sys.exit(1)

    # Step 1: Backup
    if not dry_run:
        backup_path = backup_db(DB_PATH)
        print(f"  [BACKUP] Created: {backup_path}")
        acquire_migration_lock(LOCK_PATH)
    else:
        print(f"  [DRY-RUN] Would backup {DB_PATH}")

    # Step 2: Connect and migrate
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    try:
        # Migrate entities table (expand CHECK constraint)
        print(f"\n  ── Migrating entities table ──")
        entities_migrated = migrate_entities_table(conn, dry_run)

        # Migrate campaigns table (expand CHECK constraint)
        print(f"\n  ── Migrating campaigns table ──")
        campaigns_migrated = migrate_campaigns_table(conn, dry_run)

        # Repair dependent tables that may still reference entities_old
        print(f"\n  ── Rebuilding dependent foreign keys ──")
        entity_edges_rebuilt = rebuild_entity_edges_table(conn, dry_run)

        # Create new tables
        print(f"\n  ── Creating new tables ──")
        new_tables = create_new_tables(conn, dry_run)

        # Update schema.sql
        print(f"\n  ── Updating schema.sql ──")
        update_schema_file(dry_run)

        # Verify
        print(f"\n  ── Verifying schema ──")
        if verify_schema(conn):
            print(f"\n  ✅ Schema verification PASSED")
        else:
            print(f"\n  ⚠️  Schema verification found issues — review above")

        if not dry_run:
            conn.execute("PRAGMA user_version = 2")
            conn.commit()

        print(f"\n{'='*60}")
        print(f"  Migration {'would be' if dry_run else ''} complete!")
        print(f"  Entities migrated: {'Yes' if entities_migrated else 'No (skipped)'}")
        print(f"  Campaigns migrated: {'Yes' if campaigns_migrated else 'No (skipped)'}")
        print(f"  Entity edges rebuilt: {'Yes' if entity_edges_rebuilt else 'No (skipped)'}")
        print(f"  New tables: {new_tables if new_tables else 'None (skipped)'}")
        print(f"{'='*60}\n")

    except Exception as e:
        print(f"\n  [ERROR] Migration failed: {e}")
        conn.rollback()
        raise
    finally:
        conn.close()
        if not dry_run:
            release_migration_lock(LOCK_PATH)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="FraudMVP Schema Migration v2")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without applying")
    parser.add_argument("--verify", action="store_true", help="Verify schema only (no migration)")
    args = parser.parse_args()

    if args.verify:
        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row
        ok = verify_schema(conn)
        conn.close()
        sys.exit(0 if ok else 1)
    else:
        run_migration(dry_run=args.dry_run)
