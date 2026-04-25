#!/usr/bin/env python3
"""Step 1: Request OTP code, save hash, wait for OTP, then sign in + list."""
import asyncio, os
from dotenv import load_dotenv
load_dotenv()
from telethon import TelegramClient

SESSION = 'group_session'
PHONE = '+601173251590'
OTP_FILE = '/tmp/telegram_otp.txt'
HASH_FILE = '/tmp/telegram_code_hash.txt'

async def main():
    client = TelegramClient(
        SESSION,
        int(os.getenv('TELEGRAM_API_ID')),
        os.getenv('TELEGRAM_API_HASH'),
    )
    await client.connect()

    # Request fresh code
    result = await client.send_code_request(PHONE)
    phone_code_hash = result.phone_code_hash

    # Save hash so external tools know the hash being used
    with open(HASH_FILE, 'w') as f:
        f.write(phone_code_hash)

    print(f'CODE_REQUESTED:{phone_code_hash}', flush=True)

    # Wait for OTP
    for _ in range(600):  # up to 10 min
        if os.path.exists(OTP_FILE):
            with open(OTP_FILE) as f:
                code = f.read().strip()
            break
        await asyncio.sleep(1)
    else:
        print("TIMEOUT waiting for OTP")
        return

    # Sign in
    try:
        await client.sign_in(phone=PHONE, code=code, phone_code_hash=phone_code_hash)
    except Exception as e:
        print(f"SIGNIN_ERROR:{e}")
        return

    print('AUTH_OK', flush=True)
    async for d in client.iter_dialogs():
        if hasattr(d.entity, 'title') and d.entity.username:
            print(f'  @{d.entity.username}  —  {d.entity.title}', flush=True)
    print('TOTAL_DONE', flush=True)
    await client.disconnect()

asyncio.run(main())
