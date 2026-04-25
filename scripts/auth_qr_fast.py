#!/usr/bin/env python3
"""QR login — generates QR, sends via bot, then waits for scan."""
import asyncio, os, sys, qrcode
from dotenv import load_dotenv
load_dotenv()
from telethon import TelegramClient

SESSION = '/home/mssbai/Desktop/fraud-mvp/fraudmvp_user_session'
BOT_TOKEN = os.getenv('ALERT_BOT_TOKEN', '')
CHAT_ID = '7684441863'

async def main():
    client = TelegramClient(
        SESSION,
        int(os.getenv('TELEGRAM_API_ID')),
        os.getenv('TELEGRAM_API_HASH'),
    )
    await client.connect()

    if await client.is_user_authorized():
        me = await client.get_me()
        print(f'Already logged in as: {me.first_name} (@{me.username or "N/A"})')
        await client.disconnect()
        return

    # Generate QR
    qr = await client.qr_login()
    img = qrcode.make(qr.url)
    qr_path = '/tmp/tg_qr_latest.png'
    img.save(qr_path)
    print(f'QR generated, URL: {qr.url}', flush=True)

    # Send QR via bot API IMMEDIATELY
    import urllib.request
    import json
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
    import http.client
    import mimetypes
    from io import BytesIO
    
    # Use curl for reliability
    import subprocess
    result = subprocess.run([
        'curl', '-s', '-X', 'POST',
        f'https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto',
        '-F', f'chat_id={CHAT_ID}',
        '-F', f'photo=@{qr_path}',
        '-F', 'caption=🔍 Scan NOW — expires in ~2 min!',
    ], capture_output=True, text=True)
    print(f'Bot send result: {result.stdout[:200]}', flush=True)

    # Now wait for scan
    print('Waiting for QR scan...', flush=True)
    try:
        await qr.wait(timeout=120)
        print('AUTH_OK', flush=True)
        me = await client.get_me()
        print(f'Logged in as: {me.first_name} (@{me.username or "N/A"})', flush=True)
    except asyncio.TimeoutError:
        print('TIMEOUT: QR expired', flush=True)
    except Exception as e:
        print(f'ERROR: {e}', flush=True)
    finally:
        await client.disconnect()

asyncio.run(main())