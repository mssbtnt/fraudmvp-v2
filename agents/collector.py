"""
FraudCollectorAgent — OpenClaw-style collector for fraud intelligence.

Responsibilities:
- Scrape seed web sources (MySCAM.info, etc.) for initial entities
- Discover Telegram channels via keyword triggers
- Push raw messages to Redis queue for downstream processing
- Deduplicate by message hash
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import sys
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional

import yaml
from dotenv import load_dotenv

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from services.queue_handler import QueueHandler
from services.scraper.telegram_scraper import TelegramScraper
from services.scraper.web_scraper import WebScraper

# ─── Config ───────────────────────────────────────────────────────────────────

load_dotenv()
CONFIG_DIR = Path(__file__).parent.parent / "config"
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("collector")


# ─── RawMessage dataclass ──────────────────────────────────────────────────────

@dataclass
class RawMessage:
    """Normalized raw message from any platform."""

    platform: str          # telegram, web, facebook, etc.
    channel: str           # Channel name or source URL
    channel_id: Optional[str]
    sender_id: Optional[str]
    text: str
    member_count: Optional[int]
    timestamp: str
    message_hash: str       # SHA256 of normalized text
    raw_json: str           # Original JSON

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)

    @staticmethod
    def from_json(data: str) -> "RawMessage":
        return RawMessage(**json.loads(data))


def _to_dict(obj):
    """Convert a variety of object types to dict."""
    if isinstance(obj, dict):
        return obj
    if hasattr(obj, "__dict__"):
        return vars(obj)
    if hasattr(obj, "to_dict"):
        return obj.to_dict()
    try:
        from dataclasses import asdict
        return asdict(obj)
    except Exception:
        return {"repr": repr(obj)}


# ─── FraudCollectorAgent ──────────────────────────────────────────────────────

class FraudCollectorAgent:
    """
    Stateless collector agent that:
    1. Scrapes seed web sources for initial entities
    2. Discovers Telegram channels by keyword triggers
    3. Scrapes discovered channels for messages
    4. Pushes raw messages to Redis queue
    """

    def __init__(self, demo_mode: bool = True):
        self.demo_mode = demo_mode or os.getenv("DEMO_MODE", "true").lower() == "true"

        # Load configs
        with open(CONFIG_DIR / "sources.yaml", encoding="utf-8") as f:
            self.sources_cfg = yaml.safe_load(f)

        self.queue = QueueHandler()
        self.telegram = TelegramScraper(demo_mode=self.demo_mode)
        self.web = WebScraper()

        log.info(f"FraudCollectorAgent initialized (demo_mode={self.demo_mode})")

    # ── Seed source scraping ───────────────────────────────────────────────────

    async def scrape_seed_sources(self) -> int:
        """Scrape all configured seed sources. Returns total entities collected."""
        total = 0
        for source in self.sources_cfg.get("seed_sources", []):
            if source.get("platform") != "web":
                continue

            name = source["name"]
            url = source["url"]
            log.info(f"Scraping seed source: {name} ({url})")

            try:
                entities = await self.web.scrape_source(url)
                log.info(f"  → {len(entities)} raw entries from {name}")

                for entity in entities:
                    msg = RawMessage(
                        platform="web",
                        channel=name,
                        channel_id=url,
                        sender_id=None,
                        text=f"{entity.get('type', '')}: {entity.get('value', '')}",
                        member_count=None,
                        timestamp=datetime.utcnow().isoformat(),
                        message_hash=self._hash(entity.get("value", "")),
                        raw_json=json.dumps(entity, ensure_ascii=False),
                    )
                    self._push_message(msg)
                    total += 1

            except Exception as e:
                log.error(f"  ✗ Failed to scrape {name}: {e}")

        return total

    # ── Telegram channel discovery ───────────────────────────────────────────

    async def discover_telegram_channels(self) -> list[dict]:
        """Discover Telegram channels using keyword triggers. Returns list of channel info."""
        discovered = []
        keywords_by_type = self.sources_cfg.get("telegram_keywords", {})

        collection_cfg = self.sources_cfg.get("collection", {}).get("telegram", {})
        max_channels = collection_cfg.get("max_channels_per_keyword", 20)

        for campaign_type, keywords in keywords_by_type.items():
            log.info(f"Discovering channels for campaign type: {campaign_type}")

            for keyword in keywords:
                try:
                    channels = await self.telegram.find_channels_by_keyword(
                        keyword, limit=max_channels
                    )
                    log.info(f"  keyword='{keyword}' → {len(channels)} channels")

                    for ch in channels:
                        # Convert channel object to dict, handle both demo and real objects
                        ch_dict = _to_dict(ch)
                        # Ensure required fields exist
                        ch_info = {
                            "channel_id": ch_dict.get("channel_id") or ch_dict.get("id"),
                            "username": ch_dict.get("username") or ch_dict.get("username_"),
                            "title": ch_dict.get("title") or ch_dict.get("title_"),
                            "member_count": ch_dict.get("member_count") or ch_dict.get("participant_count") or ch_dict.get("member_count", 0),
                        }
                        ch_info["campaign_type"] = campaign_type
                        ch_info["discovery_keyword"] = keyword
                        discovered.append(ch_info)

                    # Rate limit between keywords
                    await asyncio.sleep(collection_cfg.get("rate_limit_seconds", 2))

                except Exception as e:
                    log.error(f"  ✗ Error searching '{keyword}': {e}")

        log.info(f"Total channels discovered: {len(discovered)}")
        return discovered

    # ── Telegram message scraping ─────────────────────────────────────────────

    async def scrape_channels(self, channels: list[dict]) -> int:
        """Scrape messages from a list of discovered channels. Returns total messages."""
        total = 0
        collection_cfg = self.sources_cfg.get("collection", {}).get("telegram", {})
        msg_limit = collection_cfg.get("messages_per_channel", 100)
        rate_limit = collection_cfg.get("rate_limit_seconds", 2)

        for ch in channels:
            username = ch.get("username") or ch.get("channel_id")
            if not username:
                continue

            try:
                messages = await self.telegram.get_channel_messages(
                    username, limit=msg_limit
                )
                log.info(f"  {username}: {len(messages)} messages")

                for msg in messages:
                    raw_msg = RawMessage(
                        platform="telegram",
                        channel=ch.get("title", username),
                        channel_id=ch.get("channel_id"),
                        sender_id=msg.get("sender_id"),
                        text=msg.get("text", ""),
                        member_count=ch.get("member_count"),
                        timestamp=msg.get("date", datetime.utcnow().isoformat()),
                        message_hash=self._hash(msg.get("text", "")),
                        raw_json=json.dumps(msg, ensure_ascii=False),
                    )
                    self._push_message(raw_msg)
                    total += 1

                await asyncio.sleep(rate_limit)

            except Exception as e:
                log.error(f"  ✗ Failed to scrape {username}: {e}")

        return total

    # ── Snowball: pivot on known entities ─────────────────────────────────────

    async def snowball_pivot(self, limit: int = 50) -> int:
        """
        Phase 2 of snowball expansion: search Telegram for entities
        already in the DB to find connected channels.
        """
        log.info("Running snowball pivot — searching for known entities in Telegram...")

        try:
            from db.database import Database
            db = Database()
            recent_entities = db.get_recent_entities(limit=limit)
            db.close()
        except Exception as e:
            log.warning(f"Could not load entities from DB: {e}")
            return 0

        total = 0
        for entity in recent_entities:
            value = entity["value"]
            etype = entity["type"]

            try:
                channels = await self.telegram.find_channels_by_keyword(value, limit=5)
                for ch in channels:
                    # Attach pivot info
                    ch_dict = _to_dict(ch)
                    ch_dict["pivot_entity"] = value
                    ch_dict["pivot_type"] = etype
                    # Convert back to dict (since we will use the dict directly)
                    ch_info = {
                        "channel_id": ch_dict.get("channel_id") or ch_dict.get("id"),
                        "username": ch_dict.get("username") or ch_dict.get("username_"),
                        "title": ch_dict.get("title") or ch_dict.get("title_"),
                        "member_count": ch_dict.get("member_count") or ch_dict.get("participant_count") or ch_dict.get("member_count", 0),
                        "campaign_type": "pivot",
                        "discovery_keyword": value,
                    }
                    discovered.append(ch_info)
                total += len(channels)
                await asyncio.sleep(2)

            except Exception as e:
                log.error(f"  ✗ Pivot search for '{value}' failed: {e}")

        log.info(f"Snowball pivot found {total} related channels")
        return total

    # ── Main run loop ─────────────────────────────────────────────────────────

    async def run(self):
        """
        Week 1 main entry point:
        1. Scrape seed sources
        2. Discover Telegram channels
        3. Scrape discovered channels
        4. (Optional) Snowball pivot
        """
        log.info("═══ FraudCollectorAgent starting ═══")

        # Step 1: Seed sources
        seed_count = await self.scrape_seed_sources()
        log.info(f"Seed scraping complete: {seed_count} messages queued")

        # Step 2: Discover Telegram channels
        channels = await self.discover_telegram_channels()
        log.info(f"Channel discovery complete: {len(channels)} channels found")

        # Step 3: Scrape discovered channels
        if channels and not self.demo_mode:
            msg_count = await self.scrape_channels(channels)
            log.info(f"Channel scraping complete: {msg_count} messages queued")
        elif self.demo_mode:
            log.info("Demo mode — skipping live channel scraping")

        # Step 4: Snowball pivot
        pivot_count = await self.snowball_pivot()
        log.info(f"Snowball pivot complete: {pivot_count} related channels")

        q_len = self.queue.get_queue_length("raw_messages")
        log.info(f"═══ Collection complete — {q_len} raw messages in queue ═══")

        return {
            "seed_messages": seed_count,
            "channels_discovered": len(channels),
            "pivot_channels": pivot_count,
            "queue_depth": q_len,
        }

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _push_message(self, msg: RawMessage) -> None:
        """Push a raw message to the Redis queue."""
        self.queue.push_to_queue("raw_messages", msg.to_json())

    @staticmethod
    def _hash(text: str) -> str:
        """Normalize and hash text for deduplication."""
        normalized = " ".join(text.lower().split())
        return hashlib.sha256(normalized.encode()).hexdigest()


# ─── CLI Entry Point ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    demo = os.getenv("DEMO_MODE", "true").lower() == "true"
    agent = FraudCollectorAgent(demo_mode=demo)

    result = asyncio.run(agent.run())
    print(json.dumps(result, indent=2))
