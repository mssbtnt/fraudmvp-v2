"""
TelegramScraper — Telegram channel discovery and message scraping.

Supports:
- Finding channels by keyword search
- Scraping recent messages from public channels
- Channel metadata (member count, title, username)

Demo mode: simulates responses without real Telegram API credentials.
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from dotenv import load_dotenv

load_dotenv()
log = logging.getLogger("telegram_scraper")

DEMO_MODE = os.getenv("DEMO_MODE", "true").lower() == "true"


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


# ─── Telethon-based implementation ────────────────────────────────────────────

async def _scrape_with_telethon(
    channel_username: str,
    limit: int = 100,
) -> tuple[list[Message], ChannelInfo]:
    """
    Real Telethon implementation.
    Requires TELEGRAM_API_ID and TELEGRAM_API_HASH in environment.
    """
    from telethon import TelegramClient
    from telethon.tl.functions.channels import GetFullChannelRequest

    api_id = int(os.getenv("TELEGRAM_API_ID", "0"))
    api_hash = os.getenv("TELEGRAM_API_HASH", "")

    client = TelegramClient("telegram_session", api_id, api_hash)
    await client.start()

    try:
        entity = await client.get_entity(channel_username)
        full = await client(GetFullChannelRequest(channel=entity))

        info = ChannelInfo(
            channel_id=str(entity.id),
            username=getattr(entity, "username", "") or "",
            title=entity.title,
            member_count=full.full_user_.participants_count
            if hasattr(full, "full_user_")
            else 0,
        )

        messages = []
        async for msg in client.iter_messages(entity, limit=limit):
            if msg.text:
                messages.append(
                    Message(
                        message_id=str(msg.id),
                        sender_id=str(msg.sender_id) if msg.sender_id else None,
                        text=msg.text,
                        date=msg.date.isoformat() if msg.date else datetime.utcnow().isoformat(),
                        channel=channel_username,
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
    Search Telegram for channels matching a keyword.
    Uses the Telethon dialog search.
    """
    from telethon import TelegramClient

    api_id = int(os.getenv("TELEGRAM_API_ID", "0"))
    api_hash = os.getenv("TELEGRAM_API_HASH", "")

    client = TelegramClient("telegram_session", api_id, api_hash)
    await client.start()

    try:
        channels = []
        async for dialog in client.iter_dialogs():
            entity = dialog.entity
            if hasattr(entity, "title") and keyword.lower() in entity.title.lower():
                channels.append(
                    ChannelInfo(
                        channel_id=str(entity.id),
                        username=getattr(entity, "username", "") or entity.title,
                        title=entity.title,
                        member_count=getattr(entity, "participant_count", 0),
                    )
                )
                if len(channels) >= limit:
                    break

        return channels

    finally:
        await client.disconnect()


# ─── Demo mode ────────────────────────────────────────────────────────────────

DEMO_CHANNELS = [
    ChannelInfo("1001", "pelaburan_vip", "Pelaburan Crypto VIP Malaysia", 4500),
    ChannelInfo("1002", "forex_signal_ halal", "Forex Signal Halal", 3200),
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
    await asyncio.sleep(0.3)  # Simulate API delay
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
            date=datetime.utcnow().isoformat(),
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

    def __init__(self, demo_mode: bool = True):
        self.demo_mode = demo_mode or DEMO_MODE
        log.info(f"TelegramScraper initialized (demo={self.demo_mode})")

    async def find_channels_by_keyword(
        self, keyword: str, limit: int = 20
    ) -> list[ChannelInfo]:
        """Find Telegram channels matching a keyword."""
        if self.demo_mode:
            return await _demo_find_channels(keyword, limit)

        return await _find_channels_via_search(keyword, limit)

    async def get_channel_messages(
        self, channel_username: str, limit: int = 100
    ) -> list[Message]:
        """Get recent messages from a channel."""
        if self.demo_mode:
            return await _demo_get_messages(channel_username, limit)

        messages, _ = await _scrape_with_telethon(channel_username, limit)
        return messages

    async def get_channel_info(self, channel_username: str) -> ChannelInfo:
        """Get metadata for a single channel."""
        if self.demo_mode:
            await asyncio.sleep(0.1)
            for ch in DEMO_CHANNELS:
                if ch.username == channel_username or ch.title == channel_username:
                    return ch
            return DEMO_CHANNELS[0]

        _, info = await _scrape_with_telethon(channel_username, limit=1)
        return info


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
