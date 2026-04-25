#!/usr/bin/env python3
"""
Parse SC Investor Alert List from the full text extraction.
Structures entity names, types, descriptions, and websites.
"""
import json
import re
from pathlib import Path

INPUT_PATH = Path("/home/mssbai/Desktop/fraud-mvp/data/sc_full_text.txt")
OUTPUT_PATH = Path("/home/mssbai/Desktop/fraud-mvp/data/sc_investor_alert_list.json")

# Known UI/nav text to skip
SKIP_PATTERNS = [
    'navigation', 'home', 'search', 'filter', 'page', 'copyright',
    'facebook twitter', 'linkedin', 'instagram', 'youtube', 'wechat',
    'scroll', 'back to top', 'cookie', 'privacy policy', 'terms of use',
    'subscribe', 'newsletter', 'footer', 'sitemap', 'accessibility',
    'capital market stability review', 'bonds & sukuk market',
    'investment checker', 'scam meter', 'beware of scams',
    'capital market service related complaints', 'islamic capital market',
    'sustainable and responsible investment', 'venture capital',
    'capital markets and services act', 'info on finfluencer',
    'social exchange', 'digital', 'international',
]


def parse_sc_entities(text: str) -> list[dict]:
    """Parse SC Investor Alert entities from extracted text."""
    entities = []
    lines = text.split('\n')
    
    # Find the start of the entity list
    # SC format: entities are listed after "Unauthorised Website / Products / Entities / Individual"
    # or start with a number or company name
    
    in_entity_section = False
    current_entity = None
    
    for i, line in enumerate(lines):
        line = line.strip()
        if not line:
            continue
        
        # Skip known UI text
        if any(skip in line.lower() for skip in SKIP_PATTERNS):
            continue
        
        # Detect start of entity section
        if 'unauthorised' in line.lower() and ('website' in line.lower() or 'entity' in line.lower() or 'products' in line.lower()):
            in_entity_section = True
            continue
        
        # Skip header lines
        if line.startswith('Some entities') or line.startswith('Potential clone'):
            if 'potential clone' in line.lower():
                in_entity_section = True
            continue
        
        # Skip disclaimer/info lines
        if line.startswith('•') or line.startswith('-') or line.startswith('*'):
            # This is a description line, attach to current entity
            if current_entity:
                current_entity['description'] += ' ' + line.lstrip('•-* ').strip()
            continue
        
        # Skip very short lines (likely UI elements)
        if len(line) < 3:
            continue
        
        # Skip line numbers
        line = re.sub(r'^\d+\.\s*', '', line)
        
        # Detect entity names (typically: Company Name or Company Name (type))
        # Types: (Facebook page), (Website), (Telegram), (WhatsApp), (potential clone entity), (App)
        entity_match = re.match(r'^(.+?)\s*\((?:Facebook\s+page|Website|Telegram|WhatsApp|App|potential\s+clone\s+entity(?:\s*[-–]\s*.+)?)\)\s*$', line, re.IGNORECASE)
        
        if entity_match and in_entity_section:
            # Save previous entity
            if current_entity:
                entities.append(current_entity)
            
            entity_name = entity_match.group(1).strip()
            entity_type = re.search(r'\((.+?)\)', line).group(1).strip()
            
            current_entity = {
                'name': entity_name,
                'type': entity_type,
                'description': '',
                'websites': [],
                'telegram_links': [],
                'whatsapp_links': [],
                'facebook_links': [],
                'other_links': [],
            }
            continue
        
        # Detect URL lines
        url_match = re.match(r'^https?://', line)
        if url_match and in_entity_section:
            # Split multiple URLs separated by |
            urls = re.split(r'\s*\|\s*', line)
            for url in urls:
                url = url.strip()
                if not url:
                    continue
                if 't.me' in url or 'telegram' in url:
                    if current_entity:
                        current_entity['telegram_links'].append(url)
                elif 'whatsapp.com' in url or 'wa.me' in url or 'wasap.my' in url:
                    if current_entity:
                        current_entity['whatsapp_links'].append(url)
                elif 'facebook.com' in url or 'fb.me' in url:
                    if current_entity:
                        current_entity['facebook_links'].append(url)
                elif 'instagram.com' in url or 'twitter.com' in url or 'x.com' in url:
                    if current_entity:
                        current_entity['other_links'].append(url)
                else:
                    if current_entity:
                        current_entity['websites'].append(url)
            continue
        
        # Detect description lines (contain keywords like "carrying on", "operating", "illegal")
        desc_keywords = ['carrying on', 'operating', 'illegal', 'unlicensed', 'unauthorised', 'without', 'scheme', 'activities']
        if any(kw in line.lower() for kw in desc_keywords) and in_entity_section:
            if current_entity:
                current_entity['description'] += ' ' + line.strip()
            continue
        
        # Detect "Potential clone entity – Target Name" pattern
        clone_match = re.match(r'Potential\s+clone\s+entity\s*[–-]\s*(.+)', line, re.IGNORECASE)
        if clone_match and in_entity_section:
            if current_entity:
                entities.append(current_entity)
            current_entity = {
                'name': clone_match.group(1).strip(),
                'type': 'potential clone entity',
                'description': f'Clone of {clone_match.group(1).strip()}',
                'websites': [],
                'telegram_links': [],
                'whatsapp_links': [],
                'facebook_links': [],
                'other_links': [],
            }
            continue
        
        # Plain company name (no type in parentheses)
        if in_entity_section and len(line) > 3 and len(line) < 200:
            # Check if it looks like a company name (not a URL, not a description)
            if not line.startswith('http') and not any(kw in line.lower() for kw in desc_keywords):
                # Likely a company name
                if current_entity and current_entity['name']:
                    entities.append(current_entity)
                current_entity = {
                    'name': line.strip(),
                    'type': 'unauthorised',
                    'description': '',
                    'websites': [],
                    'telegram_links': [],
                    'whatsapp_links': [],
                    'facebook_links': [],
                    'other_links': [],
                }
    
    # Don't forget the last entity
    if current_entity:
        entities.append(current_entity)
    
    # Deduplicate by name
    seen = set()
    unique = []
    for e in entities:
        key = e['name'].lower().strip()
        if key not in seen and len(key) > 2:
            seen.add(key)
            unique.append(e)
    
    return unique


if __name__ == "__main__":
    with open(INPUT_PATH, 'r', encoding='utf-8', errors='ignore') as f:
        text = f.read()
    
    entities = parse_sc_entities(text)
    
    # Stats
    type_counts = {}
    total_urls = 0
    total_tg = 0
    total_wa = 0
    total_fb = 0
    
    for e in entities:
        t = e['type']
        type_counts[t] = type_counts.get(t, 0) + 1
        total_urls += len(e['websites'])
        total_tg += len(e['telegram_links'])
        total_wa += len(e['whatsapp_links'])
        total_fb += len(e['facebook_links'])
    
    result = {
        "source": "Securities Commission Malaysia - Investor Alert List",
        "url": "https://www.sc.com.my/investor-alert-list",
        "scraped_at": __import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat(),
        "total_entities": len(entities),
        "total_websites": total_urls,
        "total_telegram_links": total_tg,
        "total_whatsapp_links": total_wa,
        "total_facebook_links": total_fb,
        "entity_types": type_counts,
        "data": entities,
    }
    
    with open(OUTPUT_PATH, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    
    print(f"\n{'='*60}")
    print(f"  SC Investor Alert List — Parse Complete")
    print(f"{'='*60}")
    print(f"Total entities:       {len(entities)}")
    print(f"Total websites:       {total_urls}")
    print(f"Total Telegram links: {total_tg}")
    print(f"Total WhatsApp links: {total_wa}")
    print(f"Total Facebook links: {total_fb}")
    print(f"\nEntity types:")
    for t, c in sorted(type_counts.items(), key=lambda x: x[1], reverse=True):
        print(f"  {t}: {c}")
    
    print(f"\n--- Sample entities ---")
    for e in entities[:10]:
        print(f"\n  Name: {e['name'][:80]}")
        print(f"  Type: {e['type']}")
        if e['websites']:
            print(f"  Websites: {e['websites'][:2]}")
        if e['telegram_links']:
            print(f"  Telegram: {e['telegram_links'][:2]}")
        if e['description']:
            print(f"  Desc: {e['description'][:100]}")