#!/usr/bin/env python3
"""
Backfill entity_edges for historical entities using stored provenance metadata.
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
from services.provenance import classify_entity_provenance, parse_entity_metadata


def run_backfill(limit: int, dry_run: bool = False) -> dict:
    db = Database()
    entities = db.get_entities_missing_edges(limit=limit)
    stats = defaultdict(int)

    for entity in entities:
        metadata = parse_entity_metadata(entity)
        provenance = classify_entity_provenance(entity)
        stats[f"class_{provenance['provenance_class']}"] += 1

        message_hash = metadata.get("provenance_message_hash")
        platform = metadata.get("provenance_platform") or provenance.get("platform")
        channel = metadata.get("provenance_channel") or provenance.get("channel")

        if not message_hash or not platform or not channel:
            stats["missing_provenance"] += 1
            continue

        stats["eligible"] += 1
        if dry_run:
            continue

        db.add_entity_edge(
            entity_id=entity["id"],
            channel=channel,
            platform=platform,
            channel_id=str(entity["id"]),
            message_hash=message_hash,
        )
        db.update_entity_metadata(
            entity["id"],
            {
                "provenance_edge_backfilled_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        stats["edges_created"] += 1

    return dict(stats)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill entity_edges from provenance metadata")
    parser.add_argument("--limit", type=int, default=5000, help="Max missing-edge entities to inspect")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    args = parser.parse_args()

    result = run_backfill(limit=args.limit, dry_run=args.dry_run)
    print(json.dumps(result, indent=2, default=str))
