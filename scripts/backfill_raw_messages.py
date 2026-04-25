#!/usr/bin/env python3
"""
Backfill canonical scraped_messages rows for historical entities with no edges.

This creates explicit synthetic provenance records for reference-import and
message-backed historical entities so replay/enrichment can operate from
persisted source messages.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from db.database import Database
from services.provenance import build_backfill_raw_message, classify_entity_provenance


def run_backfill(limit: int, dry_run: bool = False, all_entities: bool = False) -> dict:
    db = Database()
    if all_entities:
        entities = db.get_recent_entities(limit=limit)
    else:
        entities = db.get_entities_missing_edges(limit=limit)
    stats = defaultdict(int)

    for entity in entities:
        provenance = classify_entity_provenance(entity)
        stats[f"class_{provenance['provenance_class']}"] += 1
        raw_message = build_backfill_raw_message(entity)
        if raw_message is None:
            continue

        stats["eligible"] += 1
        if dry_run:
            continue

        persisted = db.upsert_scraped_message(raw_message)
        if not persisted:
            with db.conn() as conn:
                conn.execute(
                    """
                    UPDATE scraped_messages
                    SET platform = ?, channel = ?, channel_id = ?, message_id = ?,
                        sender_id = ?, text = ?, raw_json = ?, scraped_at = ?
                    WHERE text_hash = ?
                    """,
                    (
                        raw_message.platform,
                        raw_message.channel,
                        raw_message.channel_id,
                        raw_message.message_id,
                        raw_message.sender_id,
                        raw_message.text,
                        raw_message.raw_json,
                        raw_message.timestamp,
                        raw_message.message_hash,
                    ),
                )
        db.update_entity_metadata(
            entity["id"],
            {
                "provenance_class": provenance["provenance_class"],
                "provenance_platform": raw_message.platform,
                "provenance_channel": raw_message.channel,
                "provenance_message_hash": raw_message.message_hash,
                "provenance_source": provenance["source"],
                "provenance_backfilled_at": datetime.now(timezone.utc).isoformat(),
                "provenance_synthetic": True,
            },
        )
        if persisted:
            stats["scraped_messages_created"] += 1
        else:
            stats["scraped_messages_existing"] += 1

    return dict(stats)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill scraped_messages from historical entities")
    parser.add_argument("--limit", type=int, default=5000, help="Max missing-edge entities to inspect")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    parser.add_argument("--all-entities", action="store_true", help="Refresh provenance-backed scraped_messages for all recent entities, not just missing-edge ones")
    args = parser.parse_args()

    result = run_backfill(limit=args.limit, dry_run=args.dry_run, all_entities=args.all_entities)
    print(json.dumps(result, indent=2, default=str))
