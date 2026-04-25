import asyncio
import os
from telethon import TelegramClient
from dotenv import load_dotenv

load_dotenv()

async def main():
    api_id = int(os.getenv("TELEGRAM_API_ID", "0"))
    api_hash = os.getenv("TELEGRAM_API_HASH", "")
    
    client = TelegramClient("telegram_session", api_id, api_hash)
    await client.start()
    
    print("Searching for 'Asal Gombak' in your dialogs...")
    async for dialog in client.iter_dialogs():
        if "asal gombak" in dialog.name.lower():
            print(f"FOUND IT!")
            print(f"Name: {dialog.name}")
            print(f"ID: {dialog.id}")
            return
    
    print("Group not found in dialogs. Please make sure the account is definitely in the group.")

asyncio.run(main())
