#!/usr/bin/env python3
"""
Parse BNM FCA List JSON and insert into FraudMVP database.
- Inserts unauthorised entities into `entities` table
- Registers BNM as a source in `sources` table
- Extracts phone numbers, WhatsApp links, Facebook URLs from website column
"""
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DATA_PATH = Path("/home/mssbai/Desktop/fraud-mvp/data/bnm_consumer_alert_list.json")
DB_PATH = Path("/home/mssbai/Desktop/fraud-mvp/db/fraud_mvp.db")

# Entity extraction patterns
PHONE_RE = re.compile(r"(?:\+?6?01[0-9]\s*[-]?\s*[0-9]{3,4}\s*[-]?\s*[0-9]{4})")
WA_RE = re.compile(r"(?:wa\.me/|whatsapp\.com/send\?phone=|wasap\.my/|chat\.whatsapp\.com/)(\d+|[A-Za-z0-9]+)")
FB_RE = re.compile(r"(?:facebook\.com/[^\s]+|fb\.me/[^\s]+)")
URL_RE = re.compile(r"https?://[^\s<>\"']+")
CLONE_RE = re.compile(r"\(potential clone entity\)", re.IGNORECASE)


def parse_record(record: dict) -> list[dict]:
    """Parse a single BNM record into one or more entities."""
    entities = []

    # Extract fields
    name_raw = record.get("Name of unauthorised entities/individual", {})
    website_raw = record.get("Website", {})
    date_raw = record.get("Date Added to Alert List", {})

    name = name_raw.get("text", "").strip() if isinstance(name_raw, dict) else str(name_raw).strip()
    website = website_raw.get("text", "").strip() if isinstance(website_raw, dict) else str(website_raw).strip()
    date_added = date_raw.get("text", "").strip() if isinstance(date_raw, dict) else str(date_raw).strip()

    if not name:
        return entities

    # Clean up name (remove tabs, newlines)
    name = re.sub(r"\s+", " ", name).strip()

    # Detect entity type from name
    is_clone = bool(CLONE_RE.search(name))
    is_facebook = "(Facebook page)" in name or "Facebook" in name
    is_whatsapp = "WhatsApp" in name or "Whatsapp" in name
    is_telegram = "(Telegram" in name

    # Clean name — remove platform annotations
    clean_name = re.sub(r"\s*\(Facebook page\)", "", name, flags=re.IGNORECASE)
    clean_name = re.sub(r"\s*\(potential clone entity\)", "", clean_name, flags=re.IGNORECASE)
    clean_name = re.sub(r"\s*\(Telegram.*?\)", "", clean_name, flags=re.IGNORECASE)
    clean_name = re.sub(r"\s*\(WhatsApp.*?\)", "", clean_name, flags=re.IGNORECASE)
    clean_name = re.sub(r"\s*\(Website.*?\)", "", clean_name, flags=re.IGNORECASE)
    clean_name = re.sub(r"\s*\(App.*?\)", "", clean_name, flags=re.IGNORECASE)
    clean_name = clean_name.strip()

    # Parse date (BNM format: "2025/12/00 26 Dec 2025" or just "26 Dec 2025")
    date_str = None
    date_match = re.search(r"(\d{1,2}\s+\w{3}\s+\d{4})", date_added)
    if date_match:
        try:
            dt = datetime.strptime(date_match.group(1), "%d %b %Y")
            date_str = dt.isoformat()
        except ValueError:
            pass

    # Create metadata
    metadata = {
        "source": "bnm_fca_list",
        "is_clone_entity": is_clone,
        "is_facebook_page": is_facebook,
        "is_telegram": is_telegram,
        "date_added_to_fca": date_str,
        "original_name": name,
    }

    # Main entity — company/organisation name
    entity_type = "company_name"
    if is_facebook:
        entity_type = "facebook_page"
    elif is_telegram:
        entity_type = "telegram_channel"
    elif is_whatsapp:
        entity_type = "whatsapp_contact"

    entities.append({
        "value": clean_name,
        "type": entity_type,
        "metadata": metadata,
    })

    # Extract additional entities from website field
    combined_text = f"{name} {website}"

    # URLs
    urls = URL_RE.findall(combined_text)
    for url in urls:
        if "facebook.com" in url:
            entities.append({
                "value": url,
                "type": "facebook_url",
                "metadata": {**metadata, "parent_entity": clean_name},
            })
        elif "whatsapp.com" in url or "wa.me" in url or "wasap.my" in url:
            wa_match = WA_RE.search(url)
            phone = wa_match.group(1) if wa_match else None
            entities.append({
                "value": phone or url,
                "type": "whatsapp_link",
                "metadata": {**metadata, "parent_entity": clean_name, "full_url": url},
            })
        elif "t.me" in url or "telegram" in url:
            entities.append({
                "value": url,
                "type": "telegram_url",
                "metadata": {**metadata, "parent_entity": clean_name},
            })
        else:
            entities.append({
                "value": url,
                "type": "domain",
                "metadata": {**metadata, "parent_entity": clean_name},
            })

    # Phone numbers
    phones = PHONE_RE.findall(combined_text)
    for phone in phones:
        entities.append({
            "value": phone,
            "type": "phone",
            "metadata": {**metadata, "parent_entity": clean_name},
        })

    return entities


def insert_into_db(all_entities: list[dict], db_path: Path):
    """Insert parsed entities into the FraudMVP database."""
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()

    # Register BNM as a source
    cursor.execute("""
        INSERT OR IGNORE INTO sources (name, url, platform, type, reliability_score, tags, created_at, last_scraped, is_active)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        "BNM Financial Consumer Alert List",
        "https://www.bnm.gov.my/financial-consumer-alert-list",
        "web",
        "gov_alert_list",
        0.95,
        "bnm,government,unauthorised_entities,clone_entities,high_priority",
        datetime.now(timezone.utc).isoformat(),
        datetime.now(timezone.utc).isoformat(),
        1,
    ))

    # Insert entities (skip duplicates)
    inserted = 0
    skipped = 0

    for entity in all_entities:
        # Check if entity already exists
        cursor.execute(
            "SELECT id FROM entities WHERE value = ? AND type = ?",
            (entity["value"], entity["type"])
        )
        existing = cursor.fetchone()

        if existing:
            # Update last_seen and increment count
            cursor.execute(
                "UPDATE entities SET last_seen = ?, count = count + 1 WHERE id = ?",
                (datetime.now(timezone.utc).isoformat(), existing[0])
            )
            skipped += 1
        else:
            # Insert new entity
            cursor.execute("""
                INSERT INTO entities (value, type, first_seen, last_seen, count, metadata)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                entity["value"],
                entity["type"],
                entity["metadata"].get("date_added_to_fca") or datetime.now(timezone.utc).isoformat(),
                datetime.now(timezone.utc).isoformat(),
                1,
                json.dumps(entity["metadata"], ensure_ascii=False),
            ))
            inserted += 1

    conn.commit()
    conn.close()

    return inserted, skipped


if __name__ == "__main__":
    # Load BNM data
    with open(DATA_PATH, encoding="utf-8") as f:
        bnm_data = json.load(f)

    records = bnm_data.get("data", [])
    print(f"BNM records to process: {len(records)}")

    # Parse all records
    all_entities = []
    for record in records:
        entities = parse_record(record)
        all_entities.extend(entities)

    print(f"Total entities extracted: {len(all_entities)}")

    # Type breakdown
    type_counts = {}
    for e in all_entities:
        type_counts[e["type"]] = type_counts.get(e["type"], 0) + 1

    print("\nEntity type breakdown:")
    for etype, count in sorted(type_counts.items(), key=lambda x: x[1], reverse=True):
        print(f"  {etype}: {count}")

    # Insert into DB
    inserted, skipped = insert_into_db(all_entities, DB_PATH)

    print(f"\n{'='*50}")
    print(f"  DB INSERT COMPLETE")
    print(f"{'='*50}")
    print(f"New entities inserted:  {inserted}")
    print(f"Existing entities updated: {skipped}")
    print(f"Total processed:       {len(all_entities)}")

    # Verify
    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()
    cursor.execute("SELECT type, COUNT(*) FROM entities GROUP BY type ORDER BY COUNT(*) DESC")
    print(f"\nCurrent DB entity counts:")
    for row in cursor.fetchall():
        print(f"  {row[0]}: {row[1]}")
    cursor.execute("SELECT COUNT(*) FROM sources")
    print(f"\nSources: {cursor.fetchone()[0]}")
    conn.close()