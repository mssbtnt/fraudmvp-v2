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
import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import yaml
from dotenv import load_dotenv

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from services.queue_handler import QueueHandler
from services.raw_message import RawMessage, stable_message_hash
from services.scraper.telegram_scraper import TelegramScraper
from services.scraper.web_scraper import WebScraper
from services.scraper.opensanctions_scraper import OpenSanctionsScraper
from db.database import Database

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

TELEGRAM_SESSION_RECOVERY_HINT = (
    "Telegram session not authorized for background collection. "
    "Run 'python3 scripts/bootstrap_telegram_session.py' manually in a terminal "
    "to refresh the Telethon session."
)


def _to_dict(obj):
    """Convert an object to dict, handling dataclasses, __dict__, and to_dict."""
    # Dataclasses have __dataclass_fields__; use asdict for correct field capture
    if hasattr(obj, "__dataclass_fields__"):
        from dataclasses import asdict as _asdict
        return _asdict(obj)
    if hasattr(obj, "to_dict"):
        return obj.to_dict()
    if hasattr(obj, "__dict__"):
        return vars(obj)
    if isinstance(obj, dict):
        return obj
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
        self.db = Database()
        self.telegram = TelegramScraper(demo_mode=self.demo_mode)
        self.web = WebScraper()
        self.opensanctions = OpenSanctionsScraper()

        # Accumulated Telegram refs from web scraping
        self._discovered_tg_refs: list[dict] = []

        log.info(f"FraudCollectorAgent initialized (demo_mode={self.demo_mode})")

    # ── Seed source scraping ───────────────────────────────────────────────────

    async def scrape_seed_sources(self) -> tuple[int, int]:
        """
        Scrape all configured seed web sources.
        Returns: (total_messages_queued, telegram_refs_found)
        """
        total = 0
        tg_refs = 0

        for source in self.sources_cfg.get("seed_sources", []):
            if source.get("platform") != "web":
                continue

            name = source["name"]
            url = source["url"]
            log.info(f"Scraping seed source: {name} ({url})")

            try:
                result = await self.web.scrape_source(url)
                log.info(f"  → {len(result.entities)} entities, "
                         f"{len(result.telegram_channels)} TG refs")

                # Push entities as raw messages
                for entity in result.entities:
                    entity_dict = {
                        "type": entity.type,
                        "value": entity.value,
                        "source": entity.source,
                        "page_title": entity.page_title,
                        "raw_context": entity.raw_context,
                        "is_suspicious": entity.is_suspicious,
                    }
                    msg = RawMessage(
                        platform="web",
                        channel=name,
                        channel_id=url,
                        sender_id=None,
                        text=f"{entity.type}: {entity.value}",
                        member_count=None,
                        timestamp=datetime.now(timezone.utc).isoformat(),
                        message_hash=self._hash(f"{entity.type}:{entity.value}"),
                        raw_json=json.dumps(entity_dict, ensure_ascii=False),
                    )
                    self._push_message(msg)
                    total += 1

                # Collect Telegram refs for discovery
                for username in result.telegram_channels:
                    if username not in [r.get("username") for r in self._discovered_tg_refs]:
                        self._discovered_tg_refs.append({
                            "username": username,
                            "source": name,
                            "source_url": url,
                            "discovery_method": "web_scrape",
                        })
                        tg_refs += 1

                # Recursively scrape paginated pages
                if result.next_page and result.pages_scraped < 3:
                    log.info(f"  → Following next page: {result.next_page}")
                    sub_result = await self.web.scrape_source(result.next_page)
                    for entity in sub_result.entities:
                        entity_dict = {
                            "type": entity.type, "value": entity.value,
                            "source": entity.source, "page_title": entity.page_title,
                            "raw_context": entity.raw_context,
                            "is_suspicious": entity.is_suspicious,
                        }
                        msg = RawMessage(
                            platform="web", channel=name, channel_id=url,
                            sender_id=None,
                            text=f"{entity.type}: {entity.value}",
                            member_count=None,
                            timestamp=datetime.now(timezone.utc).isoformat(),
                            message_hash=self._hash(f"{entity.type}:{entity.value}"),
                            raw_json=json.dumps(entity_dict, ensure_ascii=False),
                        )
                        self._push_message(msg)
                        total += 1

            except Exception as e:
                log.error(f"  ✗ Failed to scrape {name}: {e}")

        return total, tg_refs

    # ── OpenSanctions government alert list scraping ──────────────────────────

    async def scrape_opensanctions(self) -> tuple[int, int]:
        """
        Fetch and queue entities from OpenSanctions BNM + SC alert lists.

        These are government-authoritative lists of unlicensed financial service
        providers — highest reliability source in the pipeline.

        Returns: (messages_queued, tg_channels_discovered)
        """
        log.info("Fetching BNM + SC alert lists from OpenSanctions...")

        try:
            results = await self.opensanctions.fetch_all()
        except Exception as e:
            log.error(f"OpenSanctions fetch failed: {e}")
            return 0, 0

        total_queued = 0
        all_tg_channels: set[str] = set()

        for key, result in results.items():
            if result.error:
                log.warning(f"[{key}] OpenSanctions error: {result.error}")
                continue

            dataset_label = key.upper()
            log.info(
                f"[{key}] {result.records_parsed} records → "
                f"{len(result.entities)} entities, {len(result.telegram_channels)} TG channels"
            )

            for entity in result.entities:
                # Build descriptive text for the extractor
                parts = [f"[{dataset_label}] {entity.record_name}"]
                if entity.registration_number:
                    parts.append(f"Reg: {entity.registration_number}")
                if entity.telegram_channels:
                    tg_str = ", ".join(f"@{ch}" for ch in entity.telegram_channels)
                    parts.append(f"Telegram: {tg_str}")
                if entity.websites:
                    parts.append(f"URL: {', '.join(entity.websites)}")
                if entity.is_clone:
                    parts.append("⚠️ Clone entity")
                if entity.raw_context:
                    parts.append(entity.raw_context[:100])

                text = " | ".join(parts)
                msg = RawMessage(
                    platform="opensanctions",
                    channel=f"BNM_SC_ALERTS",
                    channel_id=key,
                    sender_id=None,
                    text=text,
                    member_count=None,
                    timestamp=entity.last_seen or datetime.now(timezone.utc).isoformat(),
                    message_hash=self._hash(text),
                    raw_json=json.dumps({
                        "type": entity.type,
                        "value": entity.value,
                        "dataset": entity.source_dataset,
                        "record_id": entity.record_id,
                        "record_name": entity.record_name,
                        "is_clone": entity.is_clone,
                        "websites": entity.websites,
                        "telegram_channels": entity.telegram_channels,
                        "registration_number": entity.registration_number,
                        "first_seen": entity.first_seen,
                        "last_seen": entity.last_seen,
                    }, ensure_ascii=False),
                )
                self._push_message(msg)
                total_queued += 1

            all_tg_channels.update(result.telegram_channels)

        log.info(
            f"OpenSanctions complete: {total_queued} messages queued, "
            f"{len(all_tg_channels)} TG channels"
        )
        return total_queued, len(all_tg_channels)

    # ── Discover Telegram channels from web-scraped refs ──────────────────────

    async def discover_from_web_tg_refs(self) -> list[dict]:
        """
        Resolve Telegram @usernames found during web scraping into ChannelInfo.
        Uses Telethon to validate and get channel metadata.
        """
        discovered = []

        for ref in self._discovered_tg_refs:
            username = ref.get("username", "")
            if not username:
                continue

            try:
                info = await self.telegram.get_channel_info(f"@{username}")
                discovered.append({
                    "channel_id": info.channel_id,
                    "username": info.username or username,
                    "title": info.title,
                    "member_count": info.member_count,
                    "discovery_method": "web_reference",
                    "source": ref.get("source", ""),
                    "source_url": ref.get("source_url", ""),
                })
                log.info(f"  TG ref resolved: @{username} → {info.title} "
                         f"({info.member_count} members)")
            except Exception as e:
                log.debug(f"  Could not resolve @{username}: {e}")
                discovered.append({
                    "channel_id": "",
                    "username": username,
                    "title": f"@{username}",
                    "member_count": 0,
                    "discovery_method": "web_reference",
                    "source": ref.get("source", ""),
                    "source_url": ref.get("source_url", ""),
                })

        return discovered

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
                    message = str(e)
                    if "Telegram session is not authorized" in message:
                        log.error("  ✗ Error searching '%s': %s", keyword, message)
                        log.error("  ↳ %s", TELEGRAM_SESSION_RECOVERY_HINT)
                    else:
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
                        timestamp=msg.get("date", datetime.now(timezone.utc).isoformat()),
                        message_hash=self._hash(msg.get("text", "")),
                        raw_json=json.dumps(msg, ensure_ascii=False),
                    )
                    self._push_message(raw_msg)
                    total += 1

                await asyncio.sleep(rate_limit)

            except Exception as e:
                message = str(e)
                if "Telegram session is not authorized" in message:
                    log.error("  ✗ Failed to scrape %s: %s", username, message)
                    log.error("  ↳ %s", TELEGRAM_SESSION_RECOVERY_HINT)
                else:
                    log.error(f"  ✗ Failed to scrape {username}: {e}")

        return total

    # ── Snowball: pivot on known entities ─────────────────────────────────────

    async def snowball_pivot(self, limit: int = 50) -> int:
        """
        Phase 2 of snowball expansion: search Telegram for entities
        already in the DB to find connected channels.
        """
        log.info("Running snowball pivot — searching for known entities in Telegram...")
        discovered: list[dict] = []

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
        1. Scrape seed web sources → entities + Telegram @refs
        2. Resolve Telegram refs found from web → channels
        3. Discover via keyword search
        4. Scrape discovered channels (if live)
        5. Snowball pivot
        """
        log.info("═══ FraudCollectorAgent starting ═══")

        # Step 1: Scrape seed web sources
        seed_count, tg_refs_found = await self.scrape_seed_sources()
        log.info(f"Seed scraping complete: {seed_count} messages queued, "
                 f"{tg_refs_found} TG refs found")

        # Step 1b: Fetch OpenSanctions BNM + SC government alert lists
        opensanctions_count, opensanctions_tg = await self.scrape_opensanctions()
        log.info(f"OpenSanctions complete: {opensanctions_count} messages queued, "
                 f"{opensanctions_tg} TG channels")

        # Step 2: Resolve TG refs found from web pages
        tg_channels = await self.discover_from_web_tg_refs()
        log.info(f"Web TG refs resolved: {len(tg_channels)} channels")

        # Step 3: Discover via keyword search (live Telegram search)
        keyword_channels = await self.discover_telegram_channels()
        log.info(f"Keyword discovery: {len(keyword_channels)} channels")

        # Combine all discovered channels
        all_channels = {ch["username"]: ch for ch in tg_channels + keyword_channels}
        all_channels_list = list(all_channels.values())
        log.info(f"Total unique channels: {len(all_channels_list)}")

        # Step 4: Scrape discovered channels (live)
        if all_channels_list and not self.demo_mode:
            msg_count = await self.scrape_channels(all_channels_list)
            log.info(f"Channel scraping complete: {msg_count} messages queued")
        elif self.demo_mode:
            log.info("Demo mode — skipping live channel scraping")

        # Step 4b: Scrape configured private groups (e.g., Asal Gombak)
        private_group_count = await self.scrape_private_groups()
        log.info(f"Private group scraping complete: {private_group_count} messages queued")

        # Step 5: Snowball pivot
        pivot_count = await self.snowball_pivot()
        log.info(f"Snowball pivot complete: {pivot_count} related channels")

        q_len = self.queue.get_queue_length("raw_messages")
        log.info(f"═══ Collection complete — {q_len} raw messages in queue ═══")

        return {
            "seed_messages": seed_count,
            "opensanctions_messages": opensanctions_count,
            "opensanctions_tg_channels": opensanctions_tg,
            "tg_refs_found": tg_refs_found,
            "channels_discovered": len(all_channels_list),
            "keyword_channels": len(keyword_channels),
            "web_tg_channels": len(tg_channels),
            "private_group_messages": private_group_count,
            "pivot_channels": pivot_count,
            "queue_depth": q_len,
        }

    async def run_scoped(
        self,
        *,
        web_only: bool = False,
        opensanctions_only: bool = False,
        telegram_only: bool = False,
        skip_snowball: bool = False,
    ) -> dict:
        """Run a collector subset for the daily pipeline composition."""
        if web_only:
            seed_count, tg_refs_found = await self.scrape_seed_sources()
            return {
                "mode": "web_only",
                "seed_messages": seed_count,
                "tg_refs_found": tg_refs_found,
                "queue_depth": self.queue.get_queue_length("raw_messages"),
            }

        if opensanctions_only:
            opensanctions_count, opensanctions_tg = await self.scrape_opensanctions()
            return {
                "mode": "opensanctions_only",
                "opensanctions_messages": opensanctions_count,
                "opensanctions_tg_channels": opensanctions_tg,
                "queue_depth": self.queue.get_queue_length("raw_messages"),
            }

        if telegram_only:
            tg_channels = await self.discover_from_web_tg_refs()
            keyword_channels = await self.discover_telegram_channels()
            all_channels = {ch["username"]: ch for ch in tg_channels + keyword_channels}
            all_channels_list = list(all_channels.values())

            msg_count = 0
            if all_channels_list and not self.demo_mode:
                msg_count = await self.scrape_channels(all_channels_list)
            elif self.demo_mode:
                log.info("Demo mode — skipping live channel scraping")

            private_group_count = await self.scrape_private_groups()
            pivot_count = 0 if skip_snowball else await self.snowball_pivot()

            return {
                "mode": "telegram_only",
                "channels_discovered": len(all_channels_list),
                "keyword_channels": len(keyword_channels),
                "web_tg_channels": len(tg_channels),
                "telegram_messages": msg_count,
                "private_group_messages": private_group_count,
                "pivot_channels": pivot_count,
                "queue_depth": self.queue.get_queue_length("raw_messages"),
            }

        return await self.run()

    # ── Private group scraping ─────────────────────────────────────────────────

    async def scrape_private_groups(self) -> int:
        """
        Scrape all configured private Telegram groups (by ID).
        These are groups the user account has already joined.
        """
        from services.scraper.telegram_scraper import PRIVATE_GROUPS

        if not PRIVATE_GROUPS:
            log.info("No private groups configured — skipping")
            return 0

        if self.demo_mode:
            log.info("Demo mode — skipping private group scraping")
            return 0

        total = 0
        collection_cfg = self.sources_cfg.get("collection", {}).get("telegram", {})
        msg_limit = collection_cfg.get("messages_per_channel", 100)

        for group_key, group_meta in PRIVATE_GROUPS.items():
            group_id = group_meta["channel_id"]
            group_title = group_meta["title"]
            log.info(f"Scraping private group: {group_title} (ID: {group_id})")

            try:
                messages = await self.telegram.get_channel_messages(group_id, limit=msg_limit)
                log.info(f"  {group_title}: {len(messages)} messages")

                for msg in messages:
                    msg_dict = _to_dict(msg) if not isinstance(msg, dict) else msg
                    raw_msg = RawMessage(
                        platform="telegram",
                        channel=group_title,
                        channel_id=str(group_id),
                        sender_id=msg_dict.get("sender_id"),
                        text=msg_dict.get("text", ""),
                        member_count=None,
                        timestamp=msg_dict.get("date", datetime.now(timezone.utc).isoformat()),
                        message_hash=self._hash(msg_dict.get("text", "")),
                        raw_json=json.dumps(msg_dict, ensure_ascii=False),
                    )
                    self._push_message(raw_msg)
                    total += 1

            except Exception as e:
                message = str(e)
                if "Telegram session is not authorized" in message:
                    log.error("  ✗ Failed to scrape %s: %s", group_title, message)
                    log.error("  ↳ %s", TELEGRAM_SESSION_RECOVERY_HINT)
                else:
                    log.error(f"  ✗ Failed to scrape {group_title}: {e}")

        return total

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _push_message(self, msg: RawMessage) -> None:
        """Persist then publish a raw message using the shared contract."""
        msg.ensure_message_hash()
        persisted = self.db.upsert_scraped_message(msg)
        queued = self.queue.push_to_queue("raw_messages", msg.to_json())
        if not queued:
            log.warning(
                "Failed to publish raw message to Redis",
                extra={"platform": msg.platform, "channel": msg.channel},
            )
        elif not persisted:
            log.debug("Duplicate raw message skipped in DB: %s", msg.message_hash)

    @staticmethod
    def _hash(text: str) -> str:
        """Normalize and hash text for deduplication."""
        return stable_message_hash(text)


# ─── CLI Entry Point ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="FraudMVP collector")
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument("--telegram-only", action="store_true", help="Run only Telegram discovery/scraping stages")
    mode_group.add_argument("--web-only", action="store_true", help="Run only seed web scraping stages")
    mode_group.add_argument("--opensanctions-only", action="store_true", help="Run only OpenSanctions collection")
    parser.add_argument("--skip-snowball", action="store_true", help="Skip Telegram pivot expansion")
    parser.add_argument("--demo-mode", action=argparse.BooleanOptionalAction, default=os.getenv("DEMO_MODE", "true").lower() == "true", help="Enable or disable demo mode")
    args = parser.parse_args()

    agent = FraudCollectorAgent(demo_mode=args.demo_mode)

    result = asyncio.run(
        agent.run_scoped(
            web_only=args.web_only,
            opensanctions_only=args.opensanctions_only,
            telegram_only=args.telegram_only,
            skip_snowball=args.skip_snowball,
        )
    )
    print(json.dumps(result, indent=2))
