import asyncio
import os
from telethon import TelegramClient
from dotenv import load_dotenv

load_dotenv()

async def main():
    api_id = int(os.getenv("TELEGRAM_API_ID", "0"))
    api_hash = os.getenv("TELEGRAM_API_HASH", "")
    
    # Use a dedicated session file for the User account
    client = TelegramClient("fraudmvp_user_session", api_id, api_hash)
    
    print("--- Telegram User Authentication ---")
    print("Connecting to Telegram...")
    await client.start()
    
    me = await client.get_me()
    print(f"\n✅ Successfully logged in as: {me.first_name} (@{me.username})")
    print("Session saved to fraudmvp_user_session.session")

if __name__ == "__main__":
    asyncio.run(main())
