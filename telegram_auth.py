#!/usr/bin/env python3
"""
Interactive Telegram authentication script.
Run with: python telegram_auth.py
Enter the OTP when prompted (sent to your Telegram app).
"""
import sys, os
from pathlib import Path
sys.path.insert(0, os.path.dirname(__file__))
from dotenv import load_dotenv
load_dotenv()  # loads .env by default
# Also load .secrets.env from the project directory
_secrets = Path(__file__).parent / ".secrets.env"
if _secrets.exists():
    load_dotenv(_secrets, override=False)

from telethon import TelegramClient
import asyncio

API_ID = int(os.getenv('TELEGRAM_API_ID', '0'))
API_HASH = os.getenv('TELEGRAM_API_HASH', '')
PHONE = os.getenv('TELEGRAM_PHONE', '')  # from .secrets.env
SESSION = 'telegram_user_session'

print(f"Logging into Telegram as {PHONE}...")
print(f"API ID: {API_ID}")
print()

client = TelegramClient(SESSION, API_ID, API_HASH)

async def main():
    await client.start(PHONE)
    me = await client.get_me()
    print()
    print("=" * 50)
    print(f"✅ SUCCESS! Logged in as:")
    print(f"   Name: {me.first_name} {me.last_name or ''}")
    print(f"   Username: @{me.username}")
    print(f"   Phone: {me.phone}")
    print(f"   User ID: {me.id}")
    print("=" * 50)
    print()
    print("Session saved. You can now use the Telegram scraper.")
    print("Run the collector: python -m agents.collector")

asyncio.run(main())
