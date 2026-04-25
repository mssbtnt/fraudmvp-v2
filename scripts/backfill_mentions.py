#!/usr/bin/env python3
"""
Entity Mentions Backfill — Populate entity_mentions from historical entity_edges data.

Aggregates existing edge timestamps by entity_id + date to create historical daily
mention counts. This gives the TrendDetector the data it needs to compute EMA.

Usage:
    python scripts/backfill_mentions.py              # Run backfill
    python scripts/backfill_mentions.py --dry-run    # Preview
    python scripts/backfill_mentions.py --since 2026-01-01  # Only after date
"""

from __future__ import annotations

import argparse
import logging
import sqlite3
from collections import defaultdict
from datetime import datetime
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("backfill_mentions")

DB_PATH = Path(__file__).parent.parent / "db" / "fraud_mvp.db"


def backfill_mentions(db_path: Path, dry_run: bool = False, since: str = "") -> dict:
    """
    Populate entity_mentions from entity_edges timestamps.
    
    Groups edges by (entity_id, date) and counts occurrences.
    """
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    stats = {
        "edges_scanned": 0,
        "mention_records_created": 0,
        "mention_records_updated": 0,
        "entities_covered": 0,
        "dates_covered": 0,
    }

    # Get all entity edges with timestamps
    query = """
        SELECT entity_id, DATE(timestamp) as mention_date, 
               platform, COUNT(*) as daily_count
        FROM entity_edges
        WHERE timestamp IS NOT NULL
    """
    params = []
    if since:
        query += " AND DATE(timestamp) >= ?"
        params.append(since)

    query += " GROUP BY entity_id, DATE(timestamp), platform"

    rows = conn.execute(query, params).fetchall()
    stats["edges_scanned"] = len(rows)

    if not rows:
        log.info("No entity edges found for backfill")
        conn.close()
        return stats

    # Aggregate by (entity_id, date)
    mentions = defaultdict(lambda: defaultdict(lambda: {"count": 0, "platforms": set()}))
    for row in rows:
        eid = row["entity_id"]
        d = row["mention_date"]
        if d:  # Skip NULL dates
            mentions[eid][d]["count"] += row["daily_count"]
            mentions[eid][d]["platforms"].add(row["platform"] or "unknown")

    stats["entities_covered"] = len(mentions)
    stats["dates_covered"] = sum(len(dates) for dates in mentions.values())

    log.info(f"Found {stats['edges_scanned']} edge records → "
             f"{stats['entities_covered']} entities × "
             f"{stats['dates_covered']} date entries")

    if dry_run:
        # Preview: show sample
        for i, (eid, dates) in enumerate(list(mentions.items())[:5]):
            entity = conn.execute(
                "SELECT value, type FROM entities WHERE id = ?", (eid,)
            ).fetchone()
            if entity:
                for d, info in list(dates.items())[:3]:
                    print(f"  {entity['value'][:40]} ({entity['type']}) → "
                          f"{d}: {info['count']} mentions ({', '.join(info['platforms'])})")
        conn.close()
        return stats

    # Insert into entity_mentions
    import json
    for eid, dates in mentions.items():
        for d, info in dates.items():
            try:
                # Check if record exists
                existing = conn.execute(
                    "SELECT id, mention_count FROM entity_mentions "
                    "WHERE entity_id = ? AND date = ?",
                    (eid, d),
                ).fetchone()

                platforms_json = json.dumps(sorted(info["platforms"]))

                if existing:
                    conn.execute(
                        "UPDATE entity_mentions SET mention_count = ?, platforms = ? "
                        "WHERE id = ?",
                        (info["count"], platforms_json, existing["id"]),
                    )
                    stats["mention_records_updated"] += 1
                else:
                    conn.execute(
                        "INSERT INTO entity_mentions (entity_id, date, mention_count, platforms) "
                        "VALUES (?, ?, ?, ?)",
                        (eid, d, info["count"], platforms_json),
                    )
                    stats["mention_records_created"] += 1
            except Exception as e:
                log.debug(f"Failed to insert mention for entity {eid} on {d}: {e}")

    conn.commit()
    conn.close()

    return stats


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Entity Mentions Backfill")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes")
    parser.add_argument("--since", type=str, default="", help="Only process after date (YYYY-MM-DD)")
    args = parser.parse_args()

    print(f"\n{'='*60}")
    print(f"  Entity Mentions Backfill")
    print(f"  {'DRY RUN' if args.dry_run else 'LIVE'}")
    print(f"{'='*60}\n")

    stats = backfill_mentions(DB_PATH, dry_run=args.dry_run, since=args.since)

    print(f"\n  Edges scanned: {stats['edges_scanned']}")
    print(f"  Entities covered: {stats['entities_covered']}")
    print(f"  Date entries: {stats['dates_covered']}")
    print(f"  Records created: {stats['mention_records_created']}")
    print(f"  Records updated: {stats['mention_records_updated']}")
    print(f"{'='*60}\n")