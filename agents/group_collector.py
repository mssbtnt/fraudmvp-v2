"""
GroupCollectorAgent — Telegram group keyword search + queue ingestion.

Collects messages from joined groups by keyword search, deduplicates
by message hash, and pushes raw messages to the Redis queue.

Pipeline position: same as FraudCollectorAgent, but focused on
joined-group search rather than public channel discovery.

Usage:
    python -m agents.group_collector
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from pathlib import Path

import yaml
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent.parent))

from services.queue_handler import QueueHandler
from services.raw_message import RawMessage
from services.scraper.group_monitor import GroupSearcher, demo_search, SearchHit
from db.database import Database

load_dotenv()
CONFIG_DIR = Path(__file__).parent.parent / "config"
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
DEMO_MODE = os.getenv("DEMO_MODE", "true").lower() == "true"

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("group_collector")


# ─── Config ───────────────────────────────────────────────────────────────────

def _load_keywords() -> list[str]:
    kw_path = CONFIG_DIR / "keywords.yaml"
    if kw_path.exists():
        try:
            with open(kw_path) as f:
                data = yaml.safe_load(f) or {}
            flat = []
            for category in data.get("categories", {}).values():
                flat.extend(category.get("keywords", []))
            return flat
        except Exception as e:
            log.warning(f"Failed to load keywords.yaml: {e}")
    # Fallback
    return [
        "scam", "penipuan", "menipu", "fraud", "penipu",
        "bank transfer", "akaun bank", "transfer wang",
        "pelaburan", "invest", "profit", "bitcoin", "crypto",
        "job scam", "kerja tipu", "phishing", "fake",
    ]


def _load_groups() -> list[str]:
    groups_env = os.getenv("WATCH_GROUPS", "")
    if groups_env:
        return [g.strip() for g in groups_env.split(",") if g.strip()]
    # Fallback: load from sources.yaml if available
    src_path = CONFIG_DIR / "sources.yaml"
    if src_path.exists():
        try:
            with open(src_path) as f:
                data = yaml.safe_load(f) or {}
            return data.get("telegram", {}).get("joined_groups", [])
        except Exception:
            pass
    return []


# ─── Agent ────────────────────────────────────────────────────────────────────

async def run_group_collector():
    """
    Main entry point. Runs group search and pushes hits to Redis queue.
    """
    keywords = _load_keywords()
    groups = _load_groups()

    if not groups:
        log.error("No groups configured. Set WATCH_GROUPS in .env or joined_groups in sources.yaml")
        return

    if not keywords:
        log.error("No keywords configured. Check keywords.yaml or SCAN_KEYWORDS env var.")
        return

    log.info(f"GroupCollector starting — {len(groups)} groups, {len(keywords)} keywords")
    log.info(f"Groups: {groups}")
    log.info(f"Keywords: {keywords}")
    log.info(f"Demo mode: {DEMO_MODE}")

    queue = QueueHandler()
    hits: list[SearchHit] = []

    if DEMO_MODE:
        log.info("Running in DEMO mode — using simulated data")
        hits = await demo_search()
    else:
        session_name = os.getenv("GROUP_SESSION", "group_session")
        rate_limit = float(os.getenv("GROUP_SEARCH_PAUSE", "2.0"))

        searcher = GroupSearcher(session_name=session_name, rate_limit_pause=rate_limit)
        try:
            hits = await searcher.search_groups(groups, keywords)
        finally:
            await searcher.close()

    # Deduplicate by message_hash (handles same message matching multiple keywords)
    seen: dict[str, SearchHit] = {}
    for hit in hits:
        if hit.message_hash not in seen:
            seen[hit.message_hash] = hit

    log.info(f"Unique hits after dedup: {len(seen)}")

    pushed = 0
    db = Database()

    for hit in seen.values():
        raw = RawMessage(
            platform="telegram_group",
            channel=hit.group_username,
            channel_id="",  # GroupSearcher doesn't return channel_id
            sender_id=str(hit.sender_id) if hit.sender_id else None,
            text=hit.text,
            member_count=None,
            timestamp=hit.timestamp,
            message_hash=hit.message_hash,
            raw_json=hit.to_json(),
        )

        persisted = db.upsert_scraped_message(raw)
        if not persisted:
            continue

        if queue.push_to_queue("raw_messages", raw.to_json()):
            pushed += 1
        else:
            log.warning("Failed to queue group message %s", raw.message_hash)

    log.info(f"GroupCollector complete — pushed {pushed} messages to queue")

    # Return stats for logging
    return {
        "groups_scanned": len(groups),
        "keywords_used": len(keywords),
        "total_hits": len(hits),
        "unique_hits": len(seen),
        "pushed_to_queue": pushed,
    }


# ─── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    result = asyncio.run(run_group_collector())
    if result:
        print(json.dumps(result, indent=2))
