#!/usr/bin/env python3
"""Test: Read recent messages from Asal Gombak group."""
import asyncio, os
from dotenv import load_dotenv
load_dotenv()
from telethon import TelegramClient

SESSION = '/home/mssbai/Desktop/fraud-mvp/fraudmvp_user_session'
ASAL_GOMBAK_ID = -1001245182714

async def main():
    client = TelegramClient(
        SESSION,
        int(os.getenv('TELEGRAM_API_ID')),
        os.getenv('TELEGRAM_API_HASH'),
    )
    await client.start()

    entity = await client.get_entity(ASAL_GOMBAK_ID)
    print(f"Group: {entity.title}")
    print(f"ID: {entity.id}")
    print(f"Members: {getattr(entity, 'participant_count', 'N/A')}")
    print()

    count = 0
    async for msg in client.iter_messages(entity, limit=5):
        if msg.text:
            count += 1
            date = msg.date.strftime("%Y-%m-%d %H:%M") if msg.date else "N/A"
            print(f"[{date}] {msg.text[:120]}...")
    
    print(f"\nTotal messages read: {count}")
    await client.disconnect()

asyncio.run(main())