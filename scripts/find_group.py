#!/usr/bin/env python3
"""Find Asal Gombak group ID from user's Telegram dialogs."""
import asyncio, os
from dotenv import load_dotenv
load_dotenv()
from telethon import TelegramClient

SESSION = '/home/mssbai/Desktop/fraud-mvp/fraudmvp_user_session'

async def main():
    client = TelegramClient(
        SESSION,
        int(os.getenv('TELEGRAM_API_ID')),
        os.getenv('TELEGRAM_API_HASH'),
    )
    await client.start()

    print("Searching for 'Asal Gombak' in your dialogs...\n")
    async for dialog in client.iter_dialogs():
        name = dialog.name or ""
        if "asal gombak" in name.lower() or "gombak" in name.lower():
            entity = dialog.entity
            print(f"FOUND: {name}")
            print(f"  ID:       {dialog.id}")
            print(f"  Username: @{getattr(entity, 'username', 'N/A')}")
            print(f"  Type:     {type(entity).__name__}")
            print(f"  Members:  {getattr(entity, 'participant_count', 'N/A')}")

    await client.disconnect()

asyncio.run(main())