import asyncio
import os
from telethon import TelegramClient
from dotenv import load_dotenv
import qrcode
from PIL import Image

load_dotenv()

async def main():
    api_id = int(os.getenv("TELEGRAM_API_ID", "0"))
    api_hash = os.getenv("TELEGRAM_API_HASH", "")
    
    client = TelegramClient("fraudmvp_user_session", api_id, api_hash)
    await client.connect()
    
    try:
        # Request QR login
        qr_login = await client.sign_in()
        
        # Telethon's sign_in() returns the QR hash/link logic internally
        # We need the actual QR string to generate the image
        # In newer Telethon, we use client.send_code_request or sign_in
        # Let's use the specific QR link generation
        
        # For QR login, Telethon provides the string that represents the QR
        # We'll use a helper to generate a standard Telegram QR URL
        # Format: tg://login?token=...
        
        # Note: Telethon's sign_in() for QR is a bit internal. 
        # We will use the QR hash provided by the library.
        qr_hash = qr_login.qr_hash
        qr_url = f"tg://login?token={qr_hash}"
        
        print(f"QR URL generated: {qr_url}")
        
        # Generate QR Image
        img = qrcode.make(qr_url)
        qr_path = "/home/mssbai/Desktop/telegram_qr.png"
        img.save(qr_path)
        
        print(f"✅ QR Code saved to: {qr_path}")
        print("Waiting for you to scan the QR code...")
        
        # Wait for authentication (timeout 300s / 5 mins)
        try:
            await client.wait_for_signin(timeout=300)
            me = await client.get_me()
            print(f"\n✅ Successfully logged in as: {me.first_name} (@{me.username})")
        except asyncio.TimeoutError:
            print("\n❌ QR Code expired (5 minute timeout).")
            
    except Exception as e:
        print(f"Error during QR login: {e}")
    finally:
        await client.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
