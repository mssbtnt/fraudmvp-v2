"""
Group Search & Monitor — Telegram group keyword search and real-time monitoring.

Unlike the channel scraper (which iterates public broadcast channels),
these tools work with groups the account has JOINED, using the official
MTProto API for full read access.

Classes:
  - GroupSearcher : Historical keyword search across joined groups
  - GroupMonitor  : Real-time listener for new messages in joined groups
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Optional

from dotenv import load_dotenv

load_dotenv()
log = logging.getLogger("group_monitor")

DEMO_MODE = os.getenv("DEMO_MODE", "true").lower() == "true"


# ─── Config ───────────────────────────────────────────────────────────────────

# Keywords to scan for (from config/keywords.yaml — duplicated here to avoid circular imports)
DEFAULT_KEYWORDS = [
    "scam", "penipuan", "menipu", "fraud", "penipu",
    "bank transfer", "akaun bank", "transfer wang",
    "pelaburan", "invest", "profit", "bitcoin", "crypto",
    "job scam", "kerja tipu", "phishing", "fake",
]

# Demo groups for simulation
DEMO_GROUPS = [
    {"username": "pelaburan_vip", "title": "Pelaburan Crypto VIP Malaysia", "members": 450},
    {"username": "kerja_parttime_malaysia", "title": "Kerja Partime Malaysia", "members": 870},
    {"username": "scam_report_my", "title": "Scam Report Malaysia", "members": 1200},
]


# ─── Dataclasses ─────────────────────────────────────────────────────────────

@dataclass
class SearchHit:
    """A keyword match found in a group message."""
    group_username: str
    group_title: str
    keyword_matched: str
    message_id: int
    sender_id: Optional[int]
    timestamp: str
    text: str
    message_hash: str  # SHA256 of normalized text

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)

    @staticmethod
    def from_json(data: str) -> "SearchHit":
        return SearchHit(**json.loads(data))


@dataclass
class GroupInfo:
    """Metadata for a joined Telegram group."""
    username: str
    title: str
    member_count: int
    is_channel: bool = False  # True = broadcast channel, False = group


# ─── Group Searcher ───────────────────────────────────────────────────────────
# Uses SearchRequest to find historical messages matching keywords in joined groups.

class GroupSearcher:
    """
    Search historical messages in joined groups by keyword.

    Requires:
      - TELEGRAM_API_ID
      - TELEGRAM_API_HASH
      - Valid session file (session_name.session) for an account that has joined the groups

    Usage:
        searcher = GroupSearcher(session_name="intel_session")
        hits = await searcher.search_groups(
            groups=["group1", "group2"],
            keywords=["scam", "penipuan"],
            limit_per_keyword=50,
        )
    """

    def __init__(
        self,
        session_name: str = "telegram_session",
        rate_limit_pause: float = 2.0,
    ):
        self.session_name = session_name
        self.rate_limit_pause = rate_limit_pause  # seconds between searches (be polite)
        self._client = None

    async def _get_client(self):
        """Lazy init of Telethon client."""
        if self._client is None:
            from telethon import TelegramClient
            api_id = int(os.getenv("TELEGRAM_API_ID", "0"))
            api_hash = os.getenv("TELEGRAM_API_HASH", "")
            if not api_id or not api_hash:
                raise RuntimeError(
                    "TELEGRAM_API_ID and TELEGRAM_API_HASH must be set in .env"
                )
            self._client = TelegramClient(self.session_name, api_id, api_hash)
            await self._client.start()
        return self._client

    async def close(self):
        """Disconnect the Telethon client."""
        if self._client:
            await self._client.disconnect()
            self._client = None

    async def search_group(
        self,
        group_username: str,
        keyword: str,
        limit: int = 50,
        max_pages: int = 5,
    ) -> list[SearchHit]:
        """
        Search a single group for messages matching a keyword.

        Uses SearchRequest (messages.search) via Telethon.
        Works on joined groups/channels where the account has read access.
        Automatically paginates through up to max_pages * limit messages.

        Args:
            group_username: Username of the group/channel to search
            keyword: Keyword string to search for
            limit: Max messages per page (default 50)
            max_pages: Max pagination pages to fetch (default 5, so max 250 per group/kw)
        """
        client = await self._get_client()

        try:
            entity = await client.get_entity(group_username)
        except Exception as e:
            log.warning(f"Could not resolve group '{group_username}': {e}")
            return []

        hits = []
        fetched = 0
        # Track offset_id for pagination (Telegram returns 50 msgs per request)
        offset_id = 0
        try:
            # Use raw SearchRequest for proper offset_id pagination
            from telethon.tl.functions.messages import SearchRequest
            from telethon.tl.types import InputMessagesFilterEmpty

            for page_num in range(max_pages):
                result = await client(SearchRequest(
                    peer=entity,
                    q=keyword,
                    filter=InputMessagesFilterEmpty(),
                    min_date=None,
                    max_date=None,
                    offset_id=offset_id,
                    add_offset=0,
                    limit=limit,
                    max_id=0,
                    min_id=0,
                    hash=0,
                ))

                msgs = result.messages
                if not msgs:
                    break

                for msg in msgs:
                    if not msg.text or not msg.text.strip():
                        continue
                    text_normalized = " ".join(msg.text.lower().split())
                    msg_hash = hashlib.sha256(text_normalized.encode()).hexdigest()
                    hits.append(SearchHit(
                        group_username=group_username,
                        group_title=getattr(entity, "title", group_username),
                        keyword_matched=keyword,
                        message_id=msg.id,
                        sender_id=msg.sender_id,
                        timestamp=msg.date.isoformat() if msg.date else "",
                        text=msg.text,
                        message_hash=msg_hash,
                    ))
                    fetched += 1

                # offset_id=0 means Telegram returns newest results.
                # To get older messages, set offset_id to the last (oldest)
                # message's ID from this batch.
                offset_id = msgs[-1].id

                if fetched >= limit * max_pages:
                    break

                # Polite pause between pages
                if self.rate_limit_pause > 0:
                    await asyncio.sleep(self.rate_limit_pause)

        except Exception as e:
            log.error(f"Search failed for '{group_username}' kw='{keyword}': {e}")

        return hits

    async def search_groups(
        self,
        groups: list[str],
        keywords: list[str],
        limit_per_keyword: int = 50,
    ) -> list[SearchHit]:
        """
        Search multiple groups for multiple keywords.

        Args:
            groups: List of group usernames or channel usernames to search
            keywords: List of keyword strings to search for
            limit_per_keyword: Max messages per (group, keyword) pair

        Returns:
            List of SearchHit objects (deduplicated by message_hash)
        """
        all_hits: dict[str, SearchHit] = {}

        for group in groups:
            for keyword in keywords:
                hits = await self.search_group(group, keyword, limit_per_keyword)
                for hit in hits:
                    # Deduplicate by hash — first occurrence wins (earliest kw match)
                    if hit.message_hash not in all_hits:
                        all_hits[hit.message_hash] = hit

                if self.rate_limit_pause > 0:
                    await asyncio.sleep(self.rate_limit_pause)

        log.info(
            f"Search complete: {len(all_hits)} unique hits "
            f"across {len(groups)} groups × {len(keywords)} keywords"
        )
        return list(all_hits.values())

    async def get_joined_groups(self) -> list[GroupInfo]:
        """
        List all dialogs (groups/channels) the session account has joined.
        Useful for discovering which groups are available to search.
        """
        client = await self._get_client()
        groups = []

        async for dialog in client.iter_dialogs():
            entity = dialog.entity
            # Filter: only groups and channels (not private chats)
            if hasattr(entity, "title"):
                is_channel = getattr(entity, "broadcast", False)
                # Skip private chats and bots
                if hasattr(entity, "username") and entity.username:
                    groups.append(GroupInfo(
                        username=entity.username,
                        title=entity.title,
                        member_count=getattr(entity, "participant_count", 0) or 0,
                        is_channel=is_channel,
                    ))

        return groups


# ─── Group Monitor ───────────────────────────────────────────────────────────
# Real-time listener — watches joined groups for new messages matching keywords.

class GroupMonitor:
    """
    Real-time monitor for new messages in joined groups.

    Fires a callback whenever a message matches any keyword.
    Runs continuously until stop() is called.

    Usage:
        async def on_match(hit: SearchHit):
            print(f"[MATCH] {hit.group_title}: {hit.text[:80]}")

        monitor = GroupMonitor(
            session_name="listener_session",
            watched_groups=["group1", "group2"],
            keywords=["scam", "penipuan"],
        )
        monitor.on_match(on_match)
        await monitor.start()
        # ... later ...
        await monitor.stop()
    """

    def __init__(
        self,
        session_name: str = "listener_session",
        watched_groups: Optional[list[str]] = None,
        keywords: Optional[list[str]] = None,
        rate_limit_pause: float = 1.0,
    ):
        self.session_name = session_name
        self.watched_groups = watched_groups or []
        self.keywords = keywords or DEFAULT_KEYWORDS
        self.rate_limit_pause = rate_limit_pause
        self._client = None
        self._running = False
        self._callbacks: list[callable] = []
        self._compiled_pattern: Optional[re.Pattern] = None

        # Compile keyword regex once
        escaped = [re.escape(kw) for kw in self.keywords]
        self._compiled_pattern = re.compile(
            "|".join(escaped),
            re.IGNORECASE,
        )

    def on_match(self, callback: callable):
        """Register a callback to fire on keyword matches."""
        self._callbacks.append(callback)

    async def _get_client(self):
        """Lazy init of Telethon client."""
        if self._client is None:
            from telethon import TelegramClient
            api_id = int(os.getenv("TELEGRAM_API_ID", "0"))
            api_hash = os.getenv("TELEGRAM_API_HASH", "")
            if not api_id or not api_hash:
                raise RuntimeError(
                    "TELEGRAM_API_ID and TELEGRAM_API_HASH must be set in .env"
                )
            self._client = TelegramClient(self.session_name, api_id, api_hash)
            await self._client.start()
        return self._client

    async def start(self):
        """Start listening for new messages (blocking)."""
        client = await self._get_client()
        self._running = True

        from telethon import events

        log.info(
            f"Monitor started — watching {len(self.watched_groups)} groups "
            f"for {len(self.keywords)} keywords"
        )

        @client.on(events.NewMessage(chats=self.watched_groups))
        async def handler(event):
            text = event.message.text or ""
            if not text.strip():
                return

            match = self._compiled_pattern.search(text)
            if not match:
                return

            keyword_matched = match.group(0)
            text_normalized = " ".join(text.lower().split())
            msg_hash = hashlib.sha256(text_normalized.encode()).hexdigest()

            entity = await event.get_chat()

            hit = SearchHit(
                group_username=getattr(entity, "username", "") or str(entity.id),
                group_title=getattr(entity, "title", "Unknown"),
                keyword_matched=keyword_matched,
                message_id=event.message.id,
                sender_id=event.message.sender_id,
                timestamp=event.message.date.isoformat()
                if event.message.date else datetime.now(timezone.utc).isoformat(),
                text=text,
                message_hash=msg_hash,
            )

            for cb in self._callbacks:
                try:
                    if asyncio.iscoroutinefunction(cb):
                        await cb(hit)
                    else:
                        cb(hit)
                except Exception as e:
                    log.error(f"Callback error: {e}")

            if self.rate_limit_pause > 0:
                await asyncio.sleep(self.rate_limit_pause)

        await client.run_until_disconnected()

    async def stop(self):
        """Stop the monitor."""
        self._running = False
        if self._client:
            await self._client.disconnect()
            self._client = None
        log.info("Monitor stopped")


# ─── Demo implementations ─────────────────────────────────────────────────────

async def demo_search() -> list[SearchHit]:
    """Simulate group search without Telegram credentials."""
    await asyncio.sleep(0.5)
    hits = []
    kw_assigned = ["scam", "penipuan", "fraud", "menipu", "phishing"]
    for i, group in enumerate(DEMO_GROUPS):
        for j, kw in enumerate(kw_assigned[:3]):
            text = f"[DEMO] Sample message matching '{kw}' from {group['title']} — #{kw}"
            text_normalized = " ".join(text.lower().split())
            hits.append(SearchHit(
                group_username=group["username"],
                group_title=group["title"],
                keyword_matched=kw,
                message_id=1000 + i * 10 + j,
                sender_id=2000 + i,
                timestamp=datetime.now(timezone.utc).isoformat(),
                text=text,
                message_hash=hashlib.sha256(text_normalized.encode()).hexdigest(),
            ))
    return hits


# ─── CLI entry point ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    async def demo():
        print("=== Demo: GroupSearcher ===")
        hits = await demo_search()
        print(f"Found {len(hits)} demo hits:")
        for h in hits:
            print(f"  [{h.group_title}] {h.keyword_matched}: {h.text[:60]}")

    async def real_search():
        groups = os.getenv("WATCH_GROUPS", "").split(",")
        keywords = os.getenv("SCAN_KEYWORDS", "").split(",")
        if not groups or not keywords:
            print("Set WATCH_GROUPS and SCAN_KEYWORDS in .env first")
            return

        searcher = GroupSearcher()
        try:
            hits = await searcher.search_groups(groups, keywords)
            print(f"\nFound {len(hits)} matches:")
            for h in hits:
                print(f"\n[{h.group_title}] {h.keyword_matched}")
                print(f"  {h.text[:150]}")
        finally:
            await searcher.close()

    async def real_monitor():
        groups = os.getenv("WATCH_GROUPS", "").split(",")
        keywords = os.getenv("SCAN_KEYWORDS", "").split(",")

        async def on_hit(hit: SearchHit):
            print(f"\n⚡ [{hit.group_title}] {hit.keyword_matched}: {hit.text[:100]}")

        monitor = GroupMonitor(
            watched_groups=groups,
            keywords=keywords,
        )
        monitor.on_match(on_hit)
        print(f"Starting monitor on {len(groups)} groups...")
        await monitor.start()

    if "--demo" in sys.argv:
        asyncio.run(demo())
    elif "--monitor" in sys.argv:
        asyncio.run(real_monitor())
    else:
        asyncio.run(real_search())
