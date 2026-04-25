#!/usr/bin/env python3
"""QR login - simpler version without HTTP server."""
import asyncio, os
from dotenv import load_dotenv
load_dotenv()
from telethon import TelegramClient
import qrcode

SESSION = 'group_session'

async def main():
    client = TelegramClient(
        SESSION,
        int(os.getenv('TELEGRAM_API_ID')),
        os.getenv('TELEGRAM_API_HASH'),
    )
    await client.connect()

    print('Creating QR login...', flush=True)
    qr = await client.qr_login()
    
    # Generate QR image
    img = qrcode.make(qr.url)
    img.save('/tmp/telegram_qr.png')
    print('QR_SAVED:/tmp/telegram_qr.png', flush=True)
    print(f'URL:{qr.url}', flush=True)

    # Wait for scan with 5 min timeout
    print('WAITING_FOR_SCAN...', flush=True)
    try:
        await qr.wait(timeout=300)
        print('AUTH_OK', flush=True)
        
        me = await client.get_me()
        print(f'USER:{me.first_name} {me.last_name or ""} (@{me.username or "N/A"})', flush=True)

        # List groups
        count = 0
        async for d in client.iter_dialogs():
            if hasattr(d.entity, 'title') and d.entity.username:
                print(f'GROUP:@{d.entity.username} — {d.entity.title}', flush=True)
                count += 1
        print(f'TOTAL_GROUPS:{count}', flush=True)

    except asyncio.TimeoutError:
        print('TIMEOUT:QR expired after 5 min', flush=True)
    except Exception as e:
        print(f'ERROR:{e}', flush=True)
    finally:
        await client.disconnect()

asyncio.run(main())