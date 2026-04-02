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
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Generator, Optional

from dotenv import load_dotenv

load_dotenv()
log = logging.getLogger("database")

DB_PATH = os.getenv("DATABASE_URL", "sqlite:///./db/fraud_mvp.db").replace(
    "sqlite:///", ""
)


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

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        """Run schema.sql if tables don't exist yet."""
        if not self.SCHEMA_SQL.exists():
            log.warning("schema.sql not found — skipping auto-migrate")
            return

        with self.conn() as conn:
            existing = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
            table_names = {r[0] for r in existing}

            schema = self.SCHEMA_SQL.read_text()
            for statement in schema.split(";"):
                stmt = stmt.strip()
                if not stmt or stmt.startswith("--"):
                    continue
                # Get table name from CREATE TABLE
                if stmt.startswith("CREATE TABLE"):
                    match = [t for t in table_names if t in stmt]
                    if not match:
                        conn.executescript(stmt)
                        log.info(f"Created table: {match[0] if match else 'unknown'}")

    @contextmanager
    def conn(self) -> Generator[sqlite3.Connection, None, None]:
        """Context manager for a database connection."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
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
        now = datetime.utcnow().isoformat()
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
        """Record a (entity, channel) appearance."""
        now = datetime.utcnow().isoformat()
        with self.conn() as conn:
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
        """Get all channel appearances for an entity."""
        with self.conn() as conn:
            rows = conn.execute(
                "SELECT * FROM entity_edges WHERE entity_id=? ORDER BY timestamp DESC",
                (entity_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_cross_channel_count(self, entity_id: int, hours: int = 24) -> int:
        """Count distinct channels an entity appeared in within N hours."""
        since = datetime.utcnow().isoformat()
        # NOTE: datetime subtraction not portable in SQLite; use raw SQL with strftime
        with self.conn() as conn:
            row = conn.execute(
                f"""
                SELECT COUNT(DISTINCT channel) as cnt FROM entity_edges
                WHERE entity_id=?
                  AND timestamp >= datetime('{since}', '-{hours} hours')
                """,
                (entity_id,),
            ).fetchone()
            return row["cnt"] if row else 0

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
        """Insert or update a campaign."""
        now = datetime.utcnow().isoformat()
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
            return cur.lastrowid

    def mark_alert_sent(self, campaign_id: int) -> None:
        """Mark a campaign alert as sent."""
        with self.conn() as conn:
            conn.execute(
                "UPDATE campaigns SET alert_sent=1, alert_sent_at=? WHERE id=?",
                (datetime.utcnow().isoformat(), campaign_id),
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
        """Insert or update a tracked source."""
        with self.conn() as conn:
            cur = conn.execute(
                """
                INSERT INTO sources (name, url, platform, reliability_score, tags)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    last_scraped = CURRENT_TIMESTAMP,
                    reliability_score = excluded.reliability_score
                """,
                (name, url, platform, reliability_score, json.dumps(tags) if tags else None),
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


if __name__ == "__main__":
    db = Database()
    print("Stats:", db.stats())

    # Quick insert test
    eid = db.upsert_entity("+60123456789", "phone", {"source": "test"})
    print(f"Inserted entity id={eid}")

    edge_id = db.add_entity_edge(eid, "test_channel", "telegram", message_hash="abc")
    print(f"Added edge id={edge_id}")

    print("Recent entities:", db.get_recent_entities(limit=5))
