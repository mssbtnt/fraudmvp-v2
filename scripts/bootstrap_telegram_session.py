#!/usr/bin/env python3
"""
Interactive helper to refresh the Telethon user session for background services.

Run this manually from a terminal whenever the saved Telegram session expires
or the background pipeline reports that the session is not authorized.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
load_dotenv(PROJECT_ROOT / ".env")

from services.scraper.telegram_scraper import SESSION_NAME, _get_client


async def main() -> None:
    client = _get_client()
    print(f"Using Telethon session: {SESSION_NAME}.session")
    print("This command is interactive and should be run manually.")

    await client.start()
    me = await client.get_me()
    identifier = getattr(me, "username", None) or getattr(me, "id", "unknown")
    print(f"Telegram session authorized for: {identifier}")
    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
