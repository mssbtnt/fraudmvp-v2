#!/usr/bin/env python3
"""Verify group_session works after pexpect login."""
import asyncio, os
from dotenv import load_dotenv
load_dotenv()
from telethon import TelegramClient

async def main():
    client = TelegramClient(
        'group_session',
        int(os.getenv('TELEGRAM_API_ID')),
        os.getenv('TELEGRAM_API_HASH'),
    )
    await client.connect()
    print(f"Authorized: {await client.is_user_authorized()}")
    if await client.is_user_authorized():
        print('DONE_AUTH')
        count = 0
        async for d in client.iter_dialogs():
            if hasattr(d.entity, 'title') and d.entity.username:
                print(f'  @{d.entity.username}  —  {d.entity.title}')
                count += 1
        print(f'Total: {count} groups')
    await client.disconnect()

asyncio.run(main())
