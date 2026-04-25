"""
Print a reproducible local baseline for the FraudMVP pipeline.

Usage:
    python3 scripts/pipeline_baseline.py
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from db.database import Database
from services.queue_handler import QueueHandler


TABLES = [
    "entities",
    "entity_edges",
    "campaigns",
    "scraped_messages",
    "cross_references",
    "victim_signals",
    "entity_relationships",
    "entity_mentions",
]

QUEUES = ["raw_messages", "alerts"]


def main() -> None:
    db = Database()
    queue = QueueHandler()

    table_counts: dict[str, int | str] = {}
    schema_version: int | str = "unknown"
    with db.conn() as conn:
        schema_version = conn.execute("PRAGMA user_version").fetchone()[0]
        for table in TABLES:
            try:
                table_counts[table] = conn.execute(
                    f"SELECT COUNT(*) FROM {table}"
                ).fetchone()[0]
            except Exception as exc:
                table_counts[table] = f"error: {exc}"

    queue_lengths = {name: queue.get_queue_length(name) for name in QUEUES}

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "schema_version": schema_version,
        "tables": table_counts,
        "queue_backend": queue.status(),
        "queues": queue_lengths,
    }
    print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    main()
