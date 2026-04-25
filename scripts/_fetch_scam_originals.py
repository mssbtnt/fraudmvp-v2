#!/usr/bin/env python3
"""Fetch original messages that received 'scam' replies."""
import asyncio, os, json
from dotenv import load_dotenv
load_dotenv()
from telethon import TelegramClient
from telethon.tl.types import PeerChannel

CHANNEL_ID = -1001245182714  # Asal Gombak
KEYWORD = "scam"
LIMIT = 100

async def main():
    client = TelegramClient('group_session', int(os.getenv('TELEGRAM_API_ID')), os.getenv('TELEGRAM_API_HASH'))
    await client.connect()
    
    entity = await client.get_entity(PeerChannel(channel_id=CHANNEL_ID))
    
    print(f'Fetching "{KEYWORD}" messages and their originals...\n')
    
    # Collect scam replies and their original messages
    scam_pairs = []
    seen_originals = set()
    
    async for msg in client.iter_messages(entity, search=KEYWORD, limit=LIMIT):
        if not msg.reply_to:
            continue
        
        reply_to_id = msg.reply_to.reply_to_msg_id
        if reply_to_id in seen_originals:
            continue
        
        # Fetch the original message
        try:
            original = await client.get_messages(entity, ids=reply_to_id)
            if original and original.text:
                seen_originals.add(reply_to_id)
                scam_pairs.append({
                    "scam_flag": {
                        "message_id": msg.id,
                        "date": str(msg.date),
                        "text": msg.text,
                    },
                    "original_message": {
                        "message_id": original.id,
                        "date": str(original.date),
                        "sender_id": original.sender_id,
                        "text": original.text,
                    }
                })
        except Exception as e:
            print(f"Error fetching original {reply_to_id}: {e}")
    
    print(f"Found {len(scam_pairs)} scam-flagged message pairs\n")
    print("=" * 80)
    
    # Print summary
    for i, pair in enumerate(scam_pairs[:15], 1):
        orig = pair["original_message"]
        flag = pair["scam_flag"]
        print(f"\n{i}. ORIGINAL MESSAGE (ID: {orig['message_id']})")
        print(f"   Date: {orig['date']}")
        print(f"   Sender: {orig['sender_id']}")
        print(f"   Content:\n   {orig['text'][:500]}...")
        print(f"\n   FLAGGED AS: \"{flag['text']}\"")
        print("-" * 80)
    
    # Save full results
    output_path = '/home/mssbai/Desktop/fraud-mvp/db/asal_gombak_scammessages.json'
    with open(output_path, 'w') as f:
        json.dump(scam_pairs, f, indent=2, ensure_ascii=False, default=str)
    print(f"\n✅ Saved {len(scam_pairs)} scam message pairs to {output_path}")
    
    # Extract entities from original messages
    import re
    
    phone_re = re.compile(r'\+?6?01\d{8,9}')
    bank_re = re.compile(r'\b\d{10,16}\b')
    url_re = re.compile(r'https?://[^\s]+')
    email_re = re.compile(r'[\w.+-]+@[\w-]+\.[\w.-]+')
    
    entities = {"phones": set(), "banks": set(), "urls": set(), "emails": set()}
    
    for pair in scam_pairs:
        text = pair["original_message"]["text"]
        
        for m in phone_re.finditer(text):
            entities["phones"].add(m.group())
        for m in bank_re.finditer(text):
            if len(m.group()) >= 10:
                entities["banks"].add(m.group())
        for m in url_re.finditer(text):
            entities["urls"].add(m.group())
        for m in email_re.finditer(text):
            entities["emails"].add(m.group())
    
    print("\n" + "=" * 80)
    print("EXTRACTED ENTITIES FROM SCAM MESSAGES:")
    print("=" * 80)
    if entities["phones"]:
        print(f"\n📞 Phone Numbers ({len(entities['phones'])}):")
        for p in sorted(entities["phones"]):
            print(f"   {p}")
    if entities["banks"]:
        print(f"\n🏦 Bank Accounts ({len(entities['banks'])}):")
        for b in sorted(entities["banks"]):
            print(f"   {b}")
    if entities["urls"]:
        print(f"\n🔗 URLs ({len(entities['urls'])}):")
        for u in sorted(entities["urls"]):
            print(f"   {u}")
    if entities["emails"]:
        print(f"\n📧 Emails ({len(entities['emails'])}):")
        for e in sorted(entities["emails"]):
            print(f"   {e}")
    
    await client.disconnect()

asyncio.run(main())