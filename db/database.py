"""
Database — SQLite wrapper for the Fraud MVP.

Provides typed helpers for all schema tables.
Upgrade path: swap connect() for psycopg2 when moving to PostgreSQL.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from collections import defaultdict
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Generator, Optional

from dotenv import load_dotenv

from services.campaign_types import normalize_campaign_type
from services.raw_message import RawMessage

load_dotenv()
log = logging.getLogger("database")

DB_PATH = os.getenv("DATABASE_URL", "sqlite:///./db/fraud_mvp.db").replace(
    "sqlite:///", ""
)
EXPECTED_CORE_TABLES = {
    "entities",
    "entity_edges",
    "campaigns",
    "sources",
    "scraped_messages",
    "alert_log",
}
EXPECTED_CAMPAIGN_COLUMNS = {
    "id",
    "score",
    "risk_level",
    "campaign_type",
    "entity_ids",
    "channel_ids",
}


class Database:
    """
    SQLite database wrapper with context-manager support.

    Usage:
        db = Database()
        with db.conn() as conn:
            cur = conn.execute("SELECT * FROM entities LIMIT 10")
            rows = cur.fetchall()
        db.close()
    """

    SCHEMA_SQL = Path(__file__).parent.parent / "db" / "schema.sql"
    _initialized_paths: set[str] = set()

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        if db_path not in self._initialized_paths:
            self._ensure_schema()
            self._initialized_paths.add(db_path)

    @property
    def migration_lock_path(self) -> Path:
        return Path(f"{self.db_path}.migration.lock")

    def _ensure_schema(self) -> None:
        """
        Run schema migrations for any tables that don't exist yet.

        Uses CREATE TABLE IF NOT EXISTS so it's idempotent.
        Run on every Database() instantiation — fast when tables exist.
        """
        if self.migration_lock_path.exists():
            raise RuntimeError(
                f"Database migration lock present at {self.migration_lock_path}. "
                "Do not run the pipeline while a schema migration is active."
            )

        # ── Tables ─────────────────────────────────────────────────────────────
        tables = {
            "entities": """
                CREATE TABLE IF NOT EXISTS entities (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    value TEXT NOT NULL,
                    type TEXT NOT NULL CHECK(type IN (
                        'phone', 'bank_account', 'domain', 'wallet', 'url', 'email', 'ip',
                        'company_name', 'facebook_url', 'facebook_page', 'telegram_url',
                        'telegram_channel', 'whatsapp_link', 'whatsapp_contact', 'app_url',
                        'instagram_url', 'twitter_url'
                    )),
                    first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    count INTEGER DEFAULT 1,
                    campaign_id INTEGER,
                    metadata TEXT,
                    UNIQUE(value, type)
                )""",
            "entity_edges": """
                CREATE TABLE IF NOT EXISTS entity_edges (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    entity_id INTEGER NOT NULL,
                    channel TEXT NOT NULL,
                    platform TEXT NOT NULL DEFAULT 'telegram',
                    channel_id TEXT,
                    member_count INTEGER DEFAULT 0,
                    message_hash TEXT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (entity_id) REFERENCES entities(id) ON DELETE CASCADE
                )""",
            "campaigns": """
                CREATE TABLE IF NOT EXISTS campaigns (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    score INTEGER NOT NULL,
                    risk_level TEXT NOT NULL CHECK(risk_level IN (
                        'low','medium','high','critical'
                    )),
                    campaign_type TEXT NOT NULL CHECK(campaign_type IN (
                        'investment', 'job_task', 'aid_gov', 'phishing', 'unknown',
                        'loan_shark', 'romance', 'ecommerce', 'qr', 'macau'
                    )),
                    entity_ids TEXT NOT NULL,
                    channel_ids TEXT NOT NULL,
                    keywords TEXT,
                    reason TEXT,
                    script_sample TEXT,
                    first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    alert_sent BOOLEAN DEFAULT 0,
                    alert_sent_at TIMESTAMP
                )""",
            "sources": """
                CREATE TABLE IF NOT EXISTS sources (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    url TEXT,
                    platform TEXT NOT NULL DEFAULT 'web',
                    type TEXT DEFAULT 'complaint_db',
                    reliability_score REAL DEFAULT 0.5,
                    tags TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_scraped TIMESTAMP,
                    is_active BOOLEAN DEFAULT 1
                )""",
            "scraped_messages": """
                CREATE TABLE IF NOT EXISTS scraped_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    platform TEXT NOT NULL,
                    channel TEXT NOT NULL,
                    channel_id TEXT,
                    message_id TEXT,
                    sender_id TEXT,
                    text TEXT,
                    text_hash TEXT UNIQUE,
                    raw_json TEXT,
                    scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )""",
            "alert_log": """
                CREATE TABLE IF NOT EXISTS alert_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    campaign_id INTEGER,
                    alert_level TEXT NOT NULL,
                    message TEXT,
                    sent_to TEXT,
                    sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    status TEXT DEFAULT 'pending',
                    response TEXT
                )""",
            "cross_references": """
                CREATE TABLE IF NOT EXISTS cross_references (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    entity_id INTEGER NOT NULL,
                    source_db TEXT NOT NULL,
                    source_entity_name TEXT,
                    match_confidence REAL DEFAULT 0.0,
                    listed_date TEXT,
                    status TEXT DEFAULT 'confirmed',
                    checked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (entity_id) REFERENCES entities(id)
                )""",
            "victim_signals": """
                CREATE TABLE IF NOT EXISTS victim_signals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    message_id INTEGER,
                    entity_id INTEGER,
                    signal_type TEXT NOT NULL,
                    pattern_matched TEXT,
                    extracted_text TEXT,
                    extracted_amount REAL,
                    weight INTEGER DEFAULT 0,
                    detected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (message_id) REFERENCES scraped_messages(id),
                    FOREIGN KEY (entity_id) REFERENCES entities(id)
                )""",
            "entity_mentions": """
                CREATE TABLE IF NOT EXISTS entity_mentions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    entity_id INTEGER NOT NULL,
                    date DATE NOT NULL,
                    mention_count INTEGER DEFAULT 1,
                    channel_count INTEGER DEFAULT 0,
                    platforms TEXT DEFAULT '[]',
                    FOREIGN KEY (entity_id) REFERENCES entities(id),
                    UNIQUE(entity_id, date)
                )""",
            "campaign_links": """
                CREATE TABLE IF NOT EXISTS campaign_links (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    campaign_id INTEGER NOT NULL,
                    entity_id INTEGER NOT NULL,
                    link_type TEXT NOT NULL,
                    confidence REAL DEFAULT 1.0,
                    detected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (campaign_id) REFERENCES campaigns(id),
                    FOREIGN KEY (entity_id) REFERENCES entities(id),
                    UNIQUE(campaign_id, entity_id, link_type)
                )""",
            "entity_relationships": """
                CREATE TABLE IF NOT EXISTS entity_relationships (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_entity_id INTEGER NOT NULL,
                    target_entity_id INTEGER NOT NULL,
                    relationship_type TEXT NOT NULL,
                    confidence REAL DEFAULT 1.0,
                    evidence TEXT,
                    first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    count INTEGER DEFAULT 1,
                    FOREIGN KEY (source_entity_id) REFERENCES entities(id),
                    FOREIGN KEY (target_entity_id) REFERENCES entities(id),
                    UNIQUE(source_entity_id, target_entity_id, relationship_type)
                )""",
        }

        # ── Indexes ────────────────────────────────────────────────────────────
        indexes = [
            "CREATE INDEX IF NOT EXISTS idx_entities_value ON entities(value)",
            "CREATE INDEX IF NOT EXISTS idx_entities_type ON entities(type)",
            "CREATE INDEX IF NOT EXISTS idx_entities_last_seen ON entities(last_seen)",
            "CREATE INDEX IF NOT EXISTS idx_entities_campaign ON entities(campaign_id)",
            "CREATE INDEX IF NOT EXISTS idx_entity_edges_entity ON entity_edges(entity_id)",
            "CREATE INDEX IF NOT EXISTS idx_entity_edges_channel ON entity_edges(channel)",
            "CREATE INDEX IF NOT EXISTS idx_entity_edges_timestamp ON entity_edges(timestamp)",
            "CREATE INDEX IF NOT EXISTS idx_campaigns_score ON campaigns(score)",
            "CREATE INDEX IF NOT EXISTS idx_campaigns_risk ON campaigns(risk_level)",
            "CREATE INDEX IF NOT EXISTS idx_campaigns_type ON campaigns(campaign_type)",
            "CREATE INDEX IF NOT EXISTS idx_scraped_messages_hash ON scraped_messages(text_hash)",
            "CREATE INDEX IF NOT EXISTS idx_alert_log_campaign ON alert_log(campaign_id)",
            "CREATE INDEX IF NOT EXISTS idx_cross_ref_entity ON cross_references(entity_id)",
            "CREATE INDEX IF NOT EXISTS idx_cross_ref_source ON cross_references(source_db)",
            "CREATE INDEX IF NOT EXISTS idx_victim_signal_entity ON victim_signals(entity_id)",
            "CREATE INDEX IF NOT EXISTS idx_victim_signal_type ON victim_signals(signal_type)",
            "CREATE INDEX IF NOT EXISTS idx_mentions_entity_date ON entity_mentions(entity_id, date)",
            "CREATE INDEX IF NOT EXISTS idx_campaign_links_campaign ON campaign_links(campaign_id)",
            "CREATE INDEX IF NOT EXISTS idx_campaign_links_entity ON campaign_links(entity_id)",
            "CREATE INDEX IF NOT EXISTS idx_rel_source ON entity_relationships(source_entity_id)",
            "CREATE INDEX IF NOT EXISTS idx_rel_target ON entity_relationships(target_entity_id)",
            "CREATE INDEX IF NOT EXISTS idx_rel_type ON entity_relationships(relationship_type)",
        ]

        with self.conn() as conn:
            for name, ddl in tables.items():
                conn.execute(ddl)
            for ddl in indexes:
                conn.execute(ddl)

            # ── Additional indexes (may already exist from schema.sql) ──
            extra_indexes = [
                "CREATE INDEX IF NOT EXISTS idx_scraped_messages_platform ON scraped_messages(platform)",
                "CREATE INDEX IF NOT EXISTS idx_scraped_messages_channel ON scraped_messages(channel)",
            ]
            for ddl in extra_indexes:
                conn.execute(ddl)
            current_version = conn.execute("PRAGMA user_version").fetchone()[0]
            if current_version == 0:
                conn.execute("PRAGMA user_version = 1")

        self._verify_schema_compatibility()
        log.info("Schema migration complete")

    def _verify_schema_compatibility(self) -> None:
        """Fail fast on obviously incompatible or in-flight schema states."""
        with self.conn() as conn:
            schema_version = conn.execute("PRAGMA user_version").fetchone()[0]
            schema_rows = conn.execute(
                "SELECT type, name, sql FROM sqlite_master WHERE sql IS NOT NULL"
            ).fetchall()
            table_names = {row["name"] for row in schema_rows if row["type"] == "table"}

            incompatible_reasons: list[str] = []

            if "entities_old" in table_names or "campaigns_old" in table_names:
                incompatible_reasons.append(
                    "temporary migration tables detected (entities_old/campaigns_old)"
                )

            missing_tables = sorted(EXPECTED_CORE_TABLES - table_names)
            if missing_tables:
                incompatible_reasons.append(
                    f"missing core tables: {', '.join(missing_tables)}"
                )

            if "campaigns" in table_names:
                campaign_columns = {
                    row["name"] for row in conn.execute("PRAGMA table_info(campaigns)")
                }
                missing_campaign_columns = sorted(
                    EXPECTED_CAMPAIGN_COLUMNS - campaign_columns
                )
                if missing_campaign_columns:
                    incompatible_reasons.append(
                        "campaigns table missing columns: "
                        + ", ".join(missing_campaign_columns)
                    )

            stale_references = [
                row["name"]
                for row in schema_rows
                if "entities_old" in row["sql"] or "campaigns_old" in row["sql"]
            ]
            if stale_references:
                incompatible_reasons.append(
                    "schema objects still reference migration tables: "
                    + ", ".join(sorted(stale_references))
                )

            log.info(
                "Schema check: user_version=%s tables=%s",
                schema_version,
                len(table_names),
            )

            if incompatible_reasons:
                raise RuntimeError(
                    "Incompatible database schema detected: "
                    + "; ".join(incompatible_reasons)
                )

    @contextmanager
    def conn(self) -> Generator[sqlite3.Connection, None, None]:
        """Context manager for a database connection with optimal SQLite settings."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.execute("PRAGMA busy_timeout = 5000")
        conn.execute("PRAGMA cache_size = -64000")  # 64MB cache
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def close(self) -> None:
        pass  # Context manager handles closing

    # ── Entities ───────────────────────────────────────────────────────────────

    def upsert_entity(
        self,
        value: str,
        etype: str,
        metadata: Optional[dict] = None,
    ) -> int:
        """Insert or update an entity. Returns entity ID."""
        now = datetime.now(timezone.utc).isoformat()
        with self.conn() as conn:
            cur = conn.execute(
                """
                INSERT INTO entities (value, type, count, last_seen, metadata)
                VALUES (?, ?, 1, ?, ?)
                ON CONFLICT(value, type) DO UPDATE SET
                    count = count + 1,
                    last_seen = excluded.last_seen,
                    metadata = excluded.metadata
                WHERE excluded.last_seen > entities.last_seen
                """,
                (value, etype, now, json.dumps(metadata) if metadata else None),
            )
            # Fetch the ID (lastrowid may not work with ON CONFLICT)
            row = conn.execute(
                "SELECT id FROM entities WHERE value=? AND type=?", (value, etype)
            ).fetchone()
            return row["id"] if row else cur.lastrowid

    def get_recent_entities(
        self, etype: Optional[str] = None, limit: int = 100
    ) -> list[dict]:
        """Get recently seen entities."""
        with self.conn() as conn:
            if etype:
                rows = conn.execute(
                    "SELECT * FROM entities WHERE type=? ORDER BY last_seen DESC LIMIT ?",
                    (etype, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM entities ORDER BY last_seen DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [dict(r) for r in rows]

    def get_entity_by_value(self, value: str, etype: str) -> Optional[dict]:
        """Lookup a single entity."""
        with self.conn() as conn:
            row = conn.execute(
                "SELECT * FROM entities WHERE value=? AND type=?",
                (value, etype),
            ).fetchone()
            return dict(row) if row else None

    def get_entities_missing_edges(self, limit: int = 1000) -> list[dict]:
        """Return entities that currently have no entity_edges rows."""
        with self.conn() as conn:
            rows = conn.execute(
                """
                SELECT e.*
                FROM entities e
                LEFT JOIN entity_edges ee ON ee.entity_id = e.id
                WHERE ee.entity_id IS NULL
                ORDER BY e.last_seen DESC, e.id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]

    def update_entity_metadata(self, entity_id: int, updates: dict) -> None:
        """Merge JSON metadata updates into an entity row."""
        with self.conn() as conn:
            row = conn.execute(
                "SELECT metadata FROM entities WHERE id=?",
                (entity_id,),
            ).fetchone()
            current = {}
            if row and row["metadata"]:
                try:
                    current = json.loads(row["metadata"])
                except json.JSONDecodeError:
                    current = {}
            current.update(updates)
            conn.execute(
                "UPDATE entities SET metadata=? WHERE id=?",
                (json.dumps(current), entity_id),
            )

    # ── Entity Edges ───────────────────────────────────────────────────────────

    def add_entity_edge(
        self,
        entity_id: int,
        channel: str,
        platform: str = "telegram",
        channel_id: Optional[str] = None,
        member_count: int = 0,
        message_hash: Optional[str] = None,
    ) -> int:
        """Record a (entity, channel) appearance, avoiding duplicate message edges."""
        now = datetime.now(timezone.utc).isoformat()
        with self.conn() as conn:
            if message_hash:
                existing = conn.execute(
                    """
                    SELECT id FROM entity_edges
                    WHERE entity_id=? AND channel=? AND platform=? AND message_hash=?
                    ORDER BY id DESC
                    LIMIT 1
                    """,
                    (entity_id, channel, platform, message_hash),
                ).fetchone()
                if existing:
                    return existing["id"]
            cur = conn.execute(
                """
                INSERT INTO entity_edges
                    (entity_id, channel, platform, channel_id, member_count, message_hash, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (entity_id, channel, platform, channel_id, member_count, message_hash, now),
            )
            return cur.lastrowid

    def get_edges_for_entity(self, entity_id: int) -> list[dict]:
        """Get all channel appearances for a single entity."""
        with self.conn() as conn:
            rows = conn.execute(
                "SELECT * FROM entity_edges WHERE entity_id=? ORDER BY timestamp DESC",
                (entity_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_edges_for_entities(self, entity_ids: list[int]) -> dict[int, list[dict]]:
        """Get all channel appearances for multiple entities in one query."""
        if not entity_ids:
            return {}
        placeholders = ",".join("?" * len(entity_ids))
        with self.conn() as conn:
            rows = conn.execute(
                f"SELECT * FROM entity_edges WHERE entity_id IN ({placeholders}) ORDER BY entity_id, timestamp DESC",
                entity_ids,
            ).fetchall()
        result: dict[int, list[dict]] = {eid: [] for eid in entity_ids}
        for r in rows:
            result[r["entity_id"]].append(dict(r))
        return result

    def get_cross_channel_count(self, entity_id: int, hours: int = 24) -> int:
        """Count distinct channels an entity appeared in within N hours."""
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        with self.conn() as conn:
            row = conn.execute(
                "SELECT COUNT(DISTINCT channel) as cnt FROM entity_edges WHERE entity_id=? AND timestamp >= ?",
                (entity_id, cutoff),
            ).fetchone()
            return row["cnt"] if row else 0

    # ── Scraped Messages ──────────────────────────────────────────────────────

    def upsert_scraped_message(self, raw_message: RawMessage) -> bool:
        """Persist a canonical raw message envelope idempotently by text hash."""
        msg = raw_message.ensure_message_hash()
        with self.conn() as conn:
            before = conn.total_changes
            conn.execute(
                """
                INSERT OR IGNORE INTO scraped_messages
                    (platform, channel, channel_id, message_id, sender_id, text, text_hash, raw_json, scraped_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    msg.platform,
                    msg.channel,
                    msg.channel_id,
                    msg.message_id,
                    msg.sender_id,
                    msg.text,
                    msg.message_hash,
                    msg.raw_json,
                    msg.timestamp,
                ),
            )
            return conn.total_changes > before

    def reset_derived_tables(self) -> dict[str, int]:
        """Clear replay-derived tables so they can be rebuilt deterministically."""
        cleared: dict[str, int] = {}
        with self.conn() as conn:
            for table in (
                "cross_references",
                "victim_signals",
                "entity_relationships",
                "entity_mentions",
            ):
                count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                conn.execute(f"DELETE FROM {table}")
                cleared[table] = count
        return cleared

    # ── Campaigns ──────────────────────────────────────────────────────────────

    def upsert_campaign(
        self,
        score: int,
        risk_level: str,
        campaign_type: str,
        entity_ids: list[int],
        channel_ids: list[str],
        keywords: Optional[list[str]] = None,
        reason: Optional[str] = None,
        script_sample: Optional[str] = None,
    ) -> int:
        """Insert or update a campaign and tag its entities."""
        now = datetime.now(timezone.utc).isoformat()
        campaign_type = normalize_campaign_type(campaign_type)
        with self.conn() as conn:
            cur = conn.execute(
                """
                INSERT INTO campaigns
                    (score, risk_level, campaign_type, entity_ids, channel_ids, keywords, reason, script_sample, first_seen, last_seen)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    score, risk_level, campaign_type,
                    json.dumps(entity_ids), json.dumps(channel_ids),
                    json.dumps(keywords) if keywords else None,
                    reason, script_sample, now, now,
                ),
            )
            cid = cur.lastrowid
            # Tag entities so they aren't re-clustered
            if entity_ids:
                placeholders = ",".join("?" * len(entity_ids))
                conn.execute(
                    f"UPDATE entities SET campaign_id=? WHERE id IN ({placeholders})",
                    [cid] + entity_ids,
                )
            return cid

    def mark_alert_sent(self, campaign_id: int) -> None:
        """Mark a campaign alert as sent."""
        with self.conn() as conn:
            conn.execute(
                "UPDATE campaigns SET alert_sent=1, alert_sent_at=? WHERE id=?",
                (datetime.now(timezone.utc).isoformat(), campaign_id),
            )

    def get_recent_campaigns(self, limit: int = 50) -> list[dict]:
        """Get recent campaigns."""
        with self.conn() as conn:
            rows = conn.execute(
                "SELECT * FROM campaigns ORDER BY last_seen DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]

    # ── Sources ────────────────────────────────────────────────────────────────

    def upsert_source(
        self,
        name: str,
        platform: str,
        url: Optional[str] = None,
        reliability_score: float = 0.5,
        tags: Optional[list[str]] = None,
    ) -> int:
        """Insert or update a tracked source without requiring a unique index."""
        tags_json = json.dumps(tags) if tags else None
        with self.conn() as conn:
            existing = conn.execute(
                """
                SELECT id FROM sources
                WHERE name = ? AND platform = ?
                ORDER BY id ASC
                LIMIT 1
                """,
                (name, platform),
            ).fetchone()
            if existing:
                conn.execute(
                    """
                    UPDATE sources
                    SET url = COALESCE(?, url),
                        reliability_score = ?,
                        tags = COALESCE(?, tags),
                        last_scraped = CURRENT_TIMESTAMP,
                        is_active = 1
                    WHERE id = ?
                    """,
                    (url, reliability_score, tags_json, existing["id"]),
                )
                return existing["id"]

            cur = conn.execute(
                """
                INSERT INTO sources
                    (name, url, platform, reliability_score, tags, last_scraped, is_active)
                VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP, 1)
                """,
                (name, url, platform, reliability_score, tags_json),
            )
            return cur.lastrowid

    # ── Stats ──────────────────────────────────────────────────────────────────

    def stats(self) -> dict:
        """Return high-level counts."""
        with self.conn() as conn:
            entities = conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
            campaigns = conn.execute("SELECT COUNT(*) FROM campaigns").fetchone()[0]
            sources = conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0]
            alerts_sent = conn.execute(
                "SELECT COUNT(*) FROM campaigns WHERE alert_sent=1"
            ).fetchone()[0]
            return {
                "entities": entities,
                "campaigns": campaigns,
                "sources": sources,
                "alerts_sent": alerts_sent,
            }


    def log_alert(
        self,
        campaign_id: int,
        alert_level: str,
        message: str,
        sent_to: str,
        status: str = "delivered",
        response: Optional[str] = None,
    ) -> int:
        """Record a sent alert in alert_log."""
        with self.conn() as conn:
            cur = conn.execute(
                """
                INSERT INTO alert_log (campaign_id, alert_level, message, sent_to, status, response)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (campaign_id, alert_level, message, sent_to, status, response),
            )
            return cur.lastrowid


if __name__ == "__main__":
    db = Database()
    print("Stats:", db.stats())

    # Quick insert test
    eid = db.upsert_entity("+60123456789", "phone", {"source": "test"})
    print(f"Inserted entity id={eid}")

    edge_id = db.add_entity_edge(eid, "test_channel", "telegram", message_hash="abc")
    print(f"Added edge id={edge_id}")

    print("Recent entities:", db.get_recent_entities(limit=5))
