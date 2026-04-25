#!/usr/bin/env python3
"""Search for 'scam' in Asal Gombak and analyze reply chains."""
import asyncio, os, json
from dotenv import load_dotenv
load_dotenv()
from telethon import TelegramClient
from telethon.tl.types import PeerChannel, Message

CHANNEL_ID = -1001245182714  # Asal Gombak
KEYWORD = "scam"
LIMIT = 50

async def main():
    client = TelegramClient('group_session', int(os.getenv('TELEGRAM_API_ID')), os.getenv('TELEGRAM_API_HASH'))
    await client.connect()
    
    print(f'Searching for "{KEYWORD}" in Asal Gombak...\n')
    
    # Get the channel entity
    entity = await client.get_entity(PeerChannel(channel_id=CHANNEL_ID))
    
    # Search for messages containing "scam"
    scam_messages = []
    async for msg in client.iter_messages(entity, search=KEYWORD, limit=LIMIT):
        if msg.text:
            scam_messages.append(msg)
    
    print(f'Found {len(scam_messages)} messages containing "{KEYWORD}"\n')
    print('=' * 80)
    
    # Analyze each message and its reply chain
    analyzed = []
    for msg in scam_messages[:20]:  # Limit to first 20
        entry = {
            "message_id": msg.id,
            "date": str(msg.date),
            "sender_id": msg.sender_id,
            "text": msg.text[:500] if msg.text else None,
            "is_reply": msg.reply_to is not None,
            "reply_to_id": None,
            "replied_message": None,
        }
        
        # If this message is a reply, fetch the original
        if msg.reply_to:
            try:
                reply_to_id = msg.reply_to.reply_to_msg_id
                entry["reply_to_id"] = reply_to_id
                
                # Fetch the original message
                original = await client.get_messages(entity, ids=reply_to_id)
                if original and original.text:
                    entry["replied_message"] = {
                        "message_id": original.id,
                        "date": str(original.date),
                        "sender_id": original.sender_id,
                        "text": original.text[:500],
                    }
            except Exception as e:
                entry["reply_error"] = str(e)
        
        analyzed.append(entry)
        
        # Print formatted
        print(f'\n📌 Message {msg.id} ({msg.date})')
        print(f'   Sender: {msg.sender_id}')
        print(f'   Text: {msg.text[:200]}...' if len(msg.text or '') > 200 else f'   Text: {msg.text}')
        
        if msg.reply_to:
            print(f'   ↩️  REPLY TO message {entry["reply_to_id"]}')
            if entry.get("replied_message"):
                orig = entry["replied_message"]
                print(f'   📄 Original ({orig["message_id"]}):')
                print(f'      {orig["text"][:200]}')
        print('-' * 60)
    
    # Save to JSON
    output_path = '/home/mssbai/Desktop/fraud-mvp/db/asal_gombak_scam_analysis.json'
    with open(output_path, 'w') as f:
        json.dump(analyzed, f, indent=2, ensure_ascii=False, default=str)
    print(f'\n✅ Saved {len(analyzed)} analyzed messages to {output_path}')
    
    await client.disconnect()

asyncio.run(main())