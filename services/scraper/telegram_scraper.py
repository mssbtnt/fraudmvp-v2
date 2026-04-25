"""
TelegramScraper — Telegram channel discovery and message scraping.

Supports:
- Finding channels by keyword search
- Scraping recent messages from public and private channels/groups
- Channel metadata (member count, title, username)
- Direct group ID scraping (for private groups without usernames)

Demo mode: simulates responses without real Telegram API credentials.
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Union

from dotenv import load_dotenv

load_dotenv()
log = logging.getLogger("telegram_scraper")

DEMO_MODE = os.getenv("DEMO_MODE", "true").lower() == "true"

# Persistent user session file (supports private groups)
# Use absolute path to avoid working directory issues
SESSION_NAME = "/home/mssbai/Desktop/fraud-mvp/fraudmvp_user_session"


@dataclass
class ChannelInfo:
    """Telegram channel metadata."""
    channel_id: str
    username: str
    title: str
    member_count: int
    campaign_type: Optional[str] = None
    discovery_keyword: Optional[str] = None


@dataclass
class Message:
    """A single Telegram message."""
    message_id: str
    sender_id: Optional[str]
    text: str
    date: str
    channel: str


# ─── Known channels and groups ────────────────────────────────────────────────

# Public channels (accessible by username)
KNOWN_SCAM_CHANNELS = [
    {"username": "MyScamInfo", "title": "MyScam Info Channel"},
]

# Seed dialogs for keyword discovery
KNOWN_SCAM_DIALOGS = [
    "MyScamInfo",
]

# Private groups (accessible by group ID only — no public username)
# These are groups the user account has already joined.
PRIVATE_GROUPS = {
    "asal_gombak": {
        "title": "Asal Gombak",
        "channel_id": -1001245182714,
    },
}


# ─── Telethon helper ──────────────────────────────────────────────────────────

def _get_client():
    """Create a Telethon client using the persistent user session."""
    from telethon import TelegramClient
    api_id = int(os.getenv("TELEGRAM_API_ID", "0"))
    api_hash = os.getenv("TELEGRAM_API_HASH", "")
    return TelegramClient(SESSION_NAME, api_id, api_hash)


async def _connect_authorized_client():
    """
    Connect a Telethon client without triggering interactive prompts.

    Background services must never call `client.start()` because Telethon will
    fall back to prompting for a phone number/code when the stored session is
    missing or unauthorized.
    """
    client = _get_client()
    await client.connect()

    try:
        authorized = await client.is_user_authorized()
    except Exception:
        await client.disconnect()
        raise

    if not authorized:
        await client.disconnect()
        raise RuntimeError(
            "Telegram session is not authorized. "
            "Refresh the session interactively before running the background service."
        )

    return client


# ─── Real Telethon scraping ──────────────────────────────────────────────────

async def _scrape_with_telethon(
    channel_ref: Union[str, int],
    limit: int = 100,
) -> tuple[list[Message], ChannelInfo]:
    """
    Scrape messages from a channel or group.
    
    channel_ref can be:
      - A public username string (e.g., "MyScamInfo")
      - A negative group ID integer (e.g., -1001245182714)
    """
    from telethon.tl.functions.channels import GetFullChannelRequest

    client = await _connect_authorized_client()

    try:
        # Resolve entity — supports both usernames and integer IDs
        if isinstance(channel_ref, int) or (isinstance(channel_ref, str) and channel_ref.lstrip("-").isdigit()):
            entity = await client.get_entity(int(channel_ref))
        else:
            entity = await client.get_entity(channel_ref)

        # Get full channel info
        try:
            full = await client(GetFullChannelRequest(channel=entity))
            member_count = full.full_chat.participants_count if hasattr(full, "full_chat") else 0
        except Exception:
            member_count = getattr(entity, "participant_count", 0) or 0

        info = ChannelInfo(
            channel_id=str(entity.id),
            username=getattr(entity, "username", "") or "",
            title=getattr(entity, "title", "") or str(channel_ref),
            member_count=member_count,
        )

        messages = []
        async for msg in client.iter_messages(entity, limit=limit):
            if msg.text:
                messages.append(
                    Message(
                        message_id=str(msg.id),
                        sender_id=str(msg.sender_id) if msg.sender_id else None,
                        text=msg.text,
                        date=msg.date.isoformat() if msg.date else datetime.now(timezone.utc).isoformat(),
                        channel=info.title or str(channel_ref),
                    )
                )

        return messages, info

    finally:
        await client.disconnect()


async def _find_channels_via_search(
    keyword: str,
    limit: int = 20,
) -> list[ChannelInfo]:
    """
    Discover Telegram channels by keyword.
    Uses the user session to search within known seed channels.
    """
    import re

    client = await _connect_authorized_client()

    mention_re = re.compile(r"@([a-zA-Z0-9_]{5,})")
    tme_re = re.compile(r"t\.me/([a-zA-Z0-9_]+)", re.IGNORECASE)
    extracted_usernames: dict[str, str] = {}

    try:
        # Step 1: Search within known seed channels
        for seed_username in KNOWN_SCAM_DIALOGS:
            try:
                entity = await client.get_entity(seed_username)
                async for msg in client.iter_messages(entity, limit=50, search=keyword):
                    if not msg.text:
                        continue
                    for uname in mention_re.findall(msg.text):
                        if uname.lower() not in extracted_usernames:
                            extracted_usernames[uname.lower()] = uname
                    for uname in tme_re.findall(msg.text):
                        if uname.lower() not in extracted_usernames:
                            extracted_usernames[uname.lower()] = uname
                    if len(extracted_usernames) >= limit * 2:
                        break
            except Exception as e:
                log.debug(f"Seed channel {seed_username} failed: {e}")
                continue

        # Step 2: Try direct resolve of keyword as username
        if not extracted_usernames:
            safe_keyword = keyword.replace(" ", "").lower()
            try:
                entity = await client.get_entity(f"@{safe_keyword}")
                extracted_usernames[safe_keyword] = safe_keyword
            except Exception:
                pass

        # Step 3: Resolve usernames into ChannelInfo
        channels: list[ChannelInfo] = []
        for _, username in list(extracted_usernames.items())[:limit]:
            try:
                entity = await client.get_entity(f"@{username}")
                if hasattr(entity, "title"):
                    channels.append(
                        ChannelInfo(
                            channel_id=str(entity.id),
                            username=getattr(entity, "username", "") or username,
                            title=entity.title,
                            member_count=getattr(entity, "participant_count", 0),
                        )
                    )
            except Exception:
                channels.append(
                    ChannelInfo(
                        channel_id="",
                        username=username,
                        title=f"@{username}",
                        member_count=0,
                    )
                )

        return channels

    finally:
        await client.disconnect()


# ─── Scrape private groups by ID ─────────────────────────────────────────────

async def _scrape_private_groups() -> list[tuple[list[Message], ChannelInfo]]:
    """
    Scrape all configured private groups using their integer IDs.
    Returns list of (messages, info) tuples.
    """
    results = []
    for group_key, group_meta in PRIVATE_GROUPS.items():
        group_id = group_meta["channel_id"]
        log.info(f"Scraping private group: {group_meta['title']} (ID: {group_id})")
        try:
            messages, info = await _scrape_with_telethon(group_id, limit=100)
            log.info(f"  → {group_meta['title']}: {len(messages)} messages")
            results.append((messages, info))
        except Exception as e:
            log.error(f"  ✗ Failed to scrape {group_meta['title']}: {e}")
    return results


# ─── Demo mode ────────────────────────────────────────────────────────────────

DEMO_CHANNELS = [
    ChannelInfo("1001", "pelaburan_vip", "Pelaburan Crypto VIP Malaysia", 4500),
    ChannelInfo("1002", "forex_signal_halal", "Forex Signal Halal", 3200),
    ChannelInfo("1003", "robot_trading_malaysia", "Robot Trading Malaysia", 2100),
    ChannelInfo("1004", "kerja_parttime_malaysia", "Kerja Partime Malaysia", 8700),
    ChannelInfo("1005", "bantuan_kerajaan_hq", "Bantuan Kerajaan HQ", 12000),
    ChannelInfo("1006", "rm500_boom", "RM500 Boom BKM", 5400),
    ChannelInfo("1007", "crypto_growth_my", "Crypto Growth MY", 1800),
    ChannelInfo("1008", "tiktok_earning_team", "TikTok Earning Team", 9300),
    ChannelInfo("1009", "forex_vip_club", "Forex VIP Club Malaysia", 2700),
    ChannelInfo("1010", "investment_scam_alert", "Investment Scam Alert", 650),
]

DEMO_MESSAGES = [
    ("Hai, tawaran pelaburan crypto dengan profit 30% sebulan. WhatsApp saya: +60123456789", "investment"),
    ("FREE RM50 untuk subscriber baru! Tekan link: https://bit.ly/free50", "job_task"),
    ("Bantuan kerajaan RM500 akan diagihkan. Register di: https://bantuan-kerajaan.my/register", "aid_gov"),
    ("Signal forex VIP hari ini: EUR/USD buy@1.0850 tp1.0900 sl1.0800. Join channel:", "investment"),
    ("Kerja part time senang je — like video TikTok boleh dapat RM30 sehari. WhatsApp:", "job_task"),
    ("Akaun anda telah disekat. Sila verifikasi di: https://secure-bank.my/verify", "phishing"),
    ("IPO private untuk syarikat terkenal! Minimum pelaburan RM1,000. Slots terhad!", "investment"),
    ("Permohonan bantuan BKM RM800 dibuka! Register sekarang sebelum habis:", "aid_gov"),
    ("Robot trading dengan 99% accuracy. Deposit RM500 boleh dapat RM2,000 seminggu.", "investment"),
    ("Task mudah: like dan share video boleh dapat RM20. Join: https://earn.tiktok.my", "job_task"),
]


async def _demo_find_channels(keyword: str, limit: int = 20) -> list[ChannelInfo]:
    """Demo: simulate channel search."""
    await asyncio.sleep(0.3)
    keyword_lower = keyword.lower()
    matched = [
        ch for ch in DEMO_CHANNELS
        if keyword_lower in ch.title.lower() or keyword_lower in ch.username.lower()
    ]
    return matched[:limit] if matched else DEMO_CHANNELS[:3]


async def _demo_get_messages(channel_username: str, limit: int = 100) -> list[Message]:
    """Demo: return simulated messages."""
    await asyncio.sleep(0.3)
    return [
        Message(
            message_id=f"{hash(channel_username + str(i)) % 100000}",
            sender_id=str(1000 + i),
            text=text,
            date=datetime.now(timezone.utc).isoformat(),
            channel=channel_username,
        )
        for i, (text, _) in enumerate(DEMO_MESSAGES[:limit])
    ]


# ─── Public API ──────────────────────────────────────────────────────────────

class TelegramScraper:
    """
    Unified Telegram scraper with demo-mode fallback.

    Usage:
        scraper = TelegramScraper(demo_mode=True)
        channels = await scraper.find_channels_by_keyword("pelaburan", limit=20)
        messages = await scraper.get_channel_messages("channel_username", limit=100)
    """

    def __init__(self, demo_mode: bool = False):
        self.demo_mode = demo_mode if demo_mode is not None else DEMO_MODE
        log.info(f"TelegramScraper initialized (demo={self.demo_mode})")

    async def find_channels_by_keyword(
        self, keyword: str, limit: int = 20
    ) -> list[ChannelInfo]:
        """Find Telegram channels matching a keyword."""
        if self.demo_mode:
            return await _demo_find_channels(keyword, limit)
        return await _find_channels_via_search(keyword, limit)

    async def get_channel_messages(
        self, channel_ref: Union[str, int], limit: int = 100
    ) -> list[Message]:
        """
        Get recent messages from a channel or group.
        
        Args:
            channel_ref: Public username (str) or group ID (int) for private groups.
        """
        if self.demo_mode:
            return await _demo_get_messages(str(channel_ref), limit)
        messages, _ = await _scrape_with_telethon(channel_ref, limit)
        return messages

    async def get_channel_info(self, channel_ref: Union[str, int]) -> ChannelInfo:
        """
        Get metadata for a channel or group.
        
        Args:
            channel_ref: Public username (str) or group ID (int) for private groups.
        """
        if self.demo_mode:
            await asyncio.sleep(0.1)
            for ch in DEMO_CHANNELS:
                if ch.username == str(channel_ref) or ch.title == str(channel_ref):
                    return ch
            return DEMO_CHANNELS[0]
        _, info = await _scrape_with_telethon(channel_ref, limit=1)
        return info

    async def scrape_private_groups(self) -> list[tuple[list[Message], ChannelInfo]]:
        """Scrape all configured private groups. Only works in live mode."""
        if self.demo_mode:
            log.warning("Private group scraping not available in demo mode")
            return []
        return await _scrape_private_groups()


if __name__ == "__main__":
    # Quick test
    async def test():
        s = TelegramScraper(demo_mode=True)
        channels = await s.find_channels_by_keyword("pelaburan", limit=5)
        print(f"Found {len(channels)} channels:")
        for ch in channels:
            print(f"  {ch.title} ({ch.username}) — {ch.member_count} members")

        msgs = await s.get_channel_messages("pelaburan_vip", limit=3)
        print(f"\nMessages from pelaburan_vip:")
        for m in msgs:
            print(f"  [{m.date}] {m.text[:60]}...")

    asyncio.run(test())
