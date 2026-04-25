#!/usr/bin/env python3
"""QR login for FraudMVP Telegram user session — persistent."""
import asyncio, os, sys
from dotenv import load_dotenv
load_dotenv()
from telethon import TelegramClient
import qrcode

SESSION = '/home/mssbai/Desktop/fraud-mvp/fraudmvp_user_session'

async def main():
    client = TelegramClient(
        SESSION,
        int(os.getenv('TELEGRAM_API_ID')),
        os.getenv('TELEGRAM_API_HASH'),
    )
    await client.connect()

    # Check if already authenticated
    if await client.is_user_authorized():
        me = await client.get_me()
        print(f'Already logged in as: {me.first_name} (@{me.username or "N/A"})')
        await client.disconnect()
        return

    print('Creating QR login...', flush=True)
    qr = await client.qr_login()
    
    # Generate QR image and save
    img = qrcode.make(qr.url)
    qr_path = '/home/mssbai/Desktop/fraud-mvp/telegram_qr.png'
    img.save(qr_path)
    print(f'QR saved to: {qr_path}', flush=True)
    print(f'URL: {qr.url}', flush=True)

    # Wait for scan with 5 min timeout
    print('Waiting for QR scan (5 min timeout)...', flush=True)
    try:
        await qr.wait(timeout=300)
        print('AUTH_OK', flush=True)
        
        me = await client.get_me()
        print(f'Logged in as: {me.first_name} {me.last_name or ""} (@{me.username or "N/A"})', flush=True)
        print(f'Session file saved: {SESSION}.session', flush=True)

        # List groups to verify
        count = 0
        async for d in client.iter_dialogs():
            if hasattr(d.entity, 'title'):
                title = d.entity.title
                username = getattr(d.entity, 'username', 'N/A')
                print(f'  GROUP: {title} (@{username}) [ID: {d.id}]', flush=True)
                count += 1
        print(f'Total groups/channels: {count}', flush=True)

    except asyncio.TimeoutError:
        print('TIMEOUT: QR expired after 5 min', flush=True)
    except Exception as e:
        print(f'ERROR: {e}', flush=True)
    finally:
        await client.disconnect()

asyncio.run(main())