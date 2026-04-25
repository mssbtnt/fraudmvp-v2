#!/usr/bin/env python3
"""
Telegram Real-Time Monitor for FraudMVP

Listens to configured Telegram groups/channels and pushes new messages
to Redis queue for processing by the extraction pipeline.

Architecture:
    Telethon Event Handler → Redis Queue → Extractor Agent

Performance:
    - Event-driven (no polling)
    - Rate-limited message processing
    - Minimal CPU when idle
"""

import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from telethon import TelegramClient, events

sys.path.insert(0, str(Path(__file__).parent.parent))

from db.database import Database
from services.queue_handler import QueueHandler
from services.raw_message import RawMessage

# ─── Config ───────────────────────────────────────────────────────────────────

load_dotenv()
CONFIG_DIR = Path(__file__).parent.parent / "config"
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("telegram_monitor")

# ─── Monitor Class ─────────────────────────────────────────────────────────────


class TelegramMonitor:
    """
    Real-time Telegram message monitor.
    
    Usage:
        monitor = TelegramMonitor()
        await monitor.start()
    """

    def __init__(self):
        self.api_id = int(os.getenv("TELEGRAM_API_ID", "0"))
        self.api_hash = os.getenv("TELEGRAM_API_HASH", "")
        self.session_name = os.getenv("TELEGRAM_SESSION", "group_session")
        
        self.client: Optional[TelegramClient] = None
        self.queue = QueueHandler()
        self.db = Database()
        self.watch_groups: list[int] = []
        self.watch_usernames: list[str] = []
        
        self._load_config()

    def _load_config(self):
        """Load watch groups from .env and config."""
        # From .env: WATCH_GROUPS=group1,group2,group3
        watch_env = os.getenv("WATCH_GROUPS", "")
        if watch_env:
            self.watch_usernames = [g.strip().lstrip("@") for g in watch_env.split(",")]
            log.info(f"Watch groups from .env: {self.watch_usernames}")
        
        # From config: keywords.yaml (future: group-specific keywords)
        keywords_path = CONFIG_DIR / "keywords.yaml"
        if keywords_path.exists():
            log.info(f"Loaded keywords config from {keywords_path}")

    async def _resolve_groups(self):
        """Resolve group usernames to IDs."""
        if not self.watch_usernames:
            log.warning("No watch groups configured. Set WATCH_GROUPS in .env")
            return
        
        log.info(f"Resolving {len(self.watch_usernames)} group(s)...")
        
        async for dialog in self.client.iter_dialogs():
            username = getattr(dialog.entity, "username", None)
            if username and username in self.watch_usernames:
                self.watch_groups.append(dialog.id)
                log.info(f"  @{username} → ID {dialog.id}")
        
        # Also support direct channel/group IDs
        for uname in self.watch_usernames:
            if uname.lstrip("-").isdigit():
                self.watch_groups.append(int(uname))
        
        log.info(f"Monitoring {len(self.watch_groups)} group(s)")

    async def _handle_new_message(self, event):
        """Process incoming message and push to Redis queue."""
        try:
            sender = await event.get_sender()
            chat = await event.get_chat()
            
            # Extract message data
            message_data = {
                "message_id": event.message.id,
                "text": event.message.text or "",
                "date": event.message.date.isoformat() if event.message.date else None,
                "sender_id": sender.id if sender else None,
                "sender_name": getattr(sender, "first_name", None) or getattr(sender, "title", "Unknown"),
                "chat_id": event.chat_id,
                "chat_title": getattr(chat, "title", None) or getattr(chat, "first_name", "Unknown"),
                "chat_username": getattr(chat, "username", None),
                "platform": "telegram",
                "has_media": event.message.media is not None,
            }

            raw_message = self._build_raw_message(message_data)
            persisted = self.db.upsert_scraped_message(raw_message)
            queued = self.queue.push_to_queue("raw_messages", raw_message.to_json())

            if not queued:
                log.warning("Failed to queue message %s from %s", raw_message.message_id, raw_message.channel)
            log.debug(
                "Processed message %s from %s (persisted=%s queued=%s)",
                raw_message.message_id,
                raw_message.channel,
                persisted,
                queued,
            )
            
        except Exception as e:
            log.error(f"Error processing message: {e}")

    def _build_raw_message(self, message_data: dict) -> RawMessage:
        """Convert Telethon event payload into the canonical RawMessage envelope."""
        timestamp = message_data.get("date")
        if timestamp:
            try:
                parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                timestamp = parsed.isoformat()
            except ValueError:
                timestamp = datetime.now(timezone.utc).isoformat()
        else:
            timestamp = datetime.now(timezone.utc).isoformat()

        channel_id = message_data.get("chat_id")
        channel_name = (
            message_data.get("chat_username")
            or message_data.get("chat_title")
            or str(channel_id or "unknown")
        )

        return RawMessage(
            platform="telegram",
            channel=str(channel_name),
            channel_id=str(channel_id) if channel_id is not None else None,
            sender_id=str(message_data.get("sender_id")) if message_data.get("sender_id") is not None else None,
            text=message_data.get("text", ""),
            member_count=None,
            timestamp=timestamp,
            message_hash="",
            raw_json=json.dumps(message_data, ensure_ascii=False, default=str),
            message_id=str(message_data.get("message_id")) if message_data.get("message_id") is not None else None,
        ).ensure_message_hash()

    async def start(self):
        """Start the monitor."""
        log.info("Starting Telegram monitor...")
        
        # Initialize Telegram client
        self.client = TelegramClient(
            self.session_name,
            self.api_id,
            self.api_hash,
        )
        await self.client.connect()
        
        if not await self.client.is_user_authorized():
            log.error("Not authorized. Run _qr_login.py first.")
            return
        
        me = await self.client.get_me()
        log.info(f"Authorized as: {me.first_name} (@{me.username or 'N/A'})")
        
        # Resolve groups to monitor
        await self._resolve_groups()
        
        if not self.watch_groups:
            log.warning("No groups to monitor. Add groups to WATCH_GROUPS in .env")
            return
        
        # Register event handler
        @self.client.on(events.NewMessage(chats=self.watch_groups))
        async def handler(event):
            await self._handle_new_message(event)
        
        log.info(f"Listening for messages in {len(self.watch_groups)} group(s)...")
        log.info("Press Ctrl+C to stop")
        
        # Keep running
        await self.client.run_until_disconnected()

    async def stop(self):
        """Stop the monitor."""
        log.info("Stopping Telegram monitor...")
        if self.client:
            await self.client.disconnect()


# ─── Entry Point ─────────────────────────────────────────────────────────────

async def main():
    monitor = TelegramMonitor()
    
    try:
        await monitor.start()
    except KeyboardInterrupt:
        log.info("Interrupted by user")
    finally:
        await monitor.stop()


if __name__ == "__main__":
    asyncio.run(main())
