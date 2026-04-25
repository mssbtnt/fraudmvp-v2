#!/usr/bin/env python3
"""
Data Cleanup Script — Fix noise in FraudMVP DB + source data.

Fixes:
1. "Potential clone entity" misclassified as whatsapp_link/company_name → extract actual clone target
2. Garbage hash IDs from BNM scrape (e.g., B4miQKiWIqN6mu7C5LcYeJ) → remove
3. BNM date format: "2012/07/0013 Jul 2012" → "13 Jul 2012"
4. BNM multi-line company names → clean and split
5. Cross-reference index dates → clean

Usage:
    python scripts/cleanup_data.py              # Run cleanup
    python scripts/cleanup_data.py --dry-run     # Preview changes
"""

import json
import re
import sqlite3
import shutil
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "db" / "fraud_mvp.db"
BNM_PATH = Path(__file__).parent.parent / "data" / "bnm_consumer_alert_list.json"

# ─── BNM Date Normalisation ──────────────────────────────────────────────────

def normalise_bnm_date(raw: str) -> str:
    """
    Normalise BNM date format.
    Input:  "2012/07/0013 Jul 2012"
    Output: "13 Jul 2012"
    
    Also handles: "26 Dec 2025" (already clean), empty strings, etc.
    """
    if not raw:
        return ""
    
    raw = raw.strip()
    
    # Pattern: "YYYY/MM/DDnn Mon YYYY" where DD is zero-padded day
    match = re.match(r'\d{4}/\d{2}/(\d{2})\s+\d{1,2}\s+\w+\s+\d{4}', raw)
    if match:
        # Extract the day number and the readable date
        readable_match = re.search(r'(\d{1,2}\s+\w+\s+\d{4})$', raw)
        if readable_match:
            return readable_match.group(1)
    
    # Pattern: "YYYY/MM/DD" only
    match = re.match(r'^(\d{4})/(\d{2})/(\d{2})$', raw)
    if match:
        # Convert to readable format
        try:
            from datetime import datetime
            dt = datetime(int(match.group(1)), int(match.group(2)), int(match.group(3)))
            return dt.strftime("%d %b %Y")
        except ValueError:
            return raw
    
    # Already clean format: "26 Dec 2025"
    if re.match(r'^\d{1,2}\s+\w+\s+\d{4}$', raw):
        return raw
    
    return raw


# ─── BNM Name Normalisation ──────────────────────────────────────────────────

def normalise_bnm_name(raw: str) -> list[dict]:
    """
    Normalise BNM company names.
    
    Input:  "Dana Dividen\n\t\t\t948 OUD Asset Management (potential clone entity)"
    Output: [
        {"name": "Dana Dividen", "clone_target": "948 OUD Asset Management"},
    ]
    
    Handles:
    - Multi-line names (separated by \n\t)
    - "(potential clone entity)" suffix
    - "Potential clone entity – Target Name" format
    """
    if not raw:
        return []
    
    # Clean whitespace
    text = raw.replace('\t', ' ').replace('\n', ' ')
    text = re.sub(r'\s{2,}', ' ', text).strip()
    
    # Check for "potential clone entity" pattern
    clone_match = re.search(r'\(potential clone entity(?:\s*[-–]\s*(.+?))?\)', text, re.IGNORECASE)
    if clone_match:
        base_name = text[:clone_match.start()].strip()
        clone_target = clone_match.group(1)
        results = []
        if base_name:
            results.append({"name": base_name, "is_clone": True, "clone_target": clone_target})
        if clone_target:
            results.append({"name": clone_target.strip(), "is_clone": False, "clone_target": None})
        return results
    
    # Check for "Potential clone entity – Target" format (no parentheses)
    clone_match2 = re.search(r'potential clone entity\s*[–-]\s*(.+)', text, re.IGNORECASE)
    if clone_match2:
        base_name = text[:clone_match2.start()].strip()
        clone_target = clone_match2.group(1).strip()
        results = []
        if base_name:
            results.append({"name": base_name, "is_clone": True, "clone_target": clone_target})
        if clone_target:
            results.append({"name": clone_target, "is_clone": False, "clone_target": None})
        return results
    
    # Multi-line: "Company A  948 Company B" (double space separator from tab replacement)
    # Check if this is two companies concatenated
    parts = re.split(r'\s{2,}', text)
    if len(parts) > 1:
        results = []
        for part in parts:
            part = part.strip()
            if part and len(part) > 2:
                results.append({"name": part, "is_clone": False, "clone_target": None})
        return results
    
    # Single clean name
    return [{"name": text, "is_clone": False, "clone_target": None}]


# ─── Garbage ID Detection ────────────────────────────────────────────────────

def is_garbage_id(value: str) -> bool:
    """
    Detect BNM-internal element IDs that were scraped as entity values.
    Examples: "B4miQKiWIqN6mu7C5LcYeJ", "CfNy733sY2pCmpdEgpIBw6"
    Pattern: 20+ chars, no spaces, mixed alphanumeric, not a URL
    """
    if not value or len(value) < 10:
        return False
    
    # Must not contain spaces or be a URL
    if ' ' in value or value.startswith('http') or value.startswith('+'):
        return False
    
    # Must be mostly alphanumeric (no special chars except maybe - and _)
    if not re.match(r'^[A-Za-z0-9_-]+$', value):
        return False
    
    # Must have mixed case and digits (like a hash)
    has_upper = bool(re.search(r'[A-Z]', value))
    has_lower = bool(re.search(r'[a-z]', value))
    has_digit = bool(re.search(r'[0-9]', value))
    
    # Garbage IDs typically: 20+ chars, mixed case + digits, no spaces
    if len(value) >= 15 and has_upper and has_lower and has_digit:
        # Additional check: no real word patterns (consecutive vowels)
        vowels = len(re.findall(r'[aeiouAEIOU]', value))
        vowel_ratio = vowels / len(value) if len(value) > 0 else 0
        # Real words have ~30%+ vowels, hashes have ~10-15%
        if (vowel_ratio < 0.2 and len(value) >= 20) or (vowel_ratio < 0.1):
            return True
    
    return False


# ─── Cleanup Functions ────────────────────────────────────────────────────────

def cleanup_bnm_source_data(dry_run: bool = False) -> dict:
    """Clean up BNM source JSON data (dates, names)."""
    if not BNM_PATH.exists():
        return {"error": "BNM data not found"}
    
    with open(BNM_PATH, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    stats = {"dates_fixed": 0, "names_cleaned": 0, "clone_entities_extracted": 0}
    
    for record in data.get('data', []):
        # Fix date
        date_field = record.get('Date Added to Alert List', {})
        if isinstance(date_field, dict) and 'text' in date_field:
            old_date = date_field['text']
            new_date = normalise_bnm_date(old_date)
            if old_date != new_date:
                stats['dates_fixed'] += 1
                if not dry_run:
                    date_field['text'] = new_date
        
        # Fix name
        name_field = record.get('Name of unauthorised entities/individual', {})
        if isinstance(name_field, dict) and 'text' in name_field:
            old_name = name_field['text']
            new_names = normalise_bnm_name(old_name)
            if len(new_names) > 1 or (new_names and new_names[0]['name'] != old_name.replace('\t', ' ').replace('\n', ' ').strip()):
                stats['names_cleaned'] += 1
                if any(n.get('is_clone') for n in new_names):
                    stats['clone_entities_extracted'] += 1
                if not dry_run:
                    # Use the first (primary) name
                    name_field['text'] = new_names[0]['name']
                    if new_names[0].get('is_clone'):
                        record['_clone_target'] = new_names[0].get('clone_target')
    
    if not dry_run:
        # Save cleaned data
        with open(BNM_PATH, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    
    return stats


def cleanup_db_entities(dry_run: bool = False) -> dict:
    """Clean up noisy entities in the DB."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    
    stats = {
        "garbage_ids_removed": 0,
        "clone_entities_fixed": 0,
        "dates_normalised": 0,
        "bnm_names_cleaned": 0,
        "multi_line_names_split": 0,
    }
    
    # 1. Remove garbage hash IDs
    rows = conn.execute("SELECT id, value, type FROM entities").fetchall()
    garbage_ids = []
    for row in rows:
        if is_garbage_id(row['value']):
            garbage_ids.append(row['id'])
    
    stats['garbage_ids_removed'] = len(garbage_ids)
    if garbage_ids and not dry_run:
        ph = ",".join("?" * len(garbage_ids))
        conn.execute(f"DELETE FROM entities WHERE id IN ({ph})", garbage_ids)
        conn.execute(f"DELETE FROM entity_edges WHERE entity_id IN ({ph})", garbage_ids)
        conn.commit()
    
    # 2. Fix "Potential clone entity" misclassified as whatsapp_link/telegram_url
    clone_rows = conn.execute("""
        SELECT id, value, type FROM entities 
        WHERE lower(value) LIKE '%potential clone entity%'
    """).fetchall()
    
    for row in clone_rows:
        old_value = row['value']
        names = normalise_bnm_name(old_value)
        
        if names:
            primary = names[0]
            new_type = 'company_name'
            
            if not dry_run:
                conn.execute(
                    "UPDATE entities SET value = ?, type = ? WHERE id = ?",
                    (primary['name'], new_type, row['id']),
                )
                # If there's a clone target, insert it as a separate entity
                if primary.get('clone_target'):
                    try:
                        conn.execute(
                            "INSERT INTO entities (value, type, first_seen, last_seen, count, metadata) "
                            "VALUES (?, 'company_name', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 1, ?)",
                            (primary['clone_target'], json.dumps({
                                "source": "bnm_fca_list",
                                "is_clone_target": True,
                                "cloned_by": primary['name'],
                            })),
                        )
                    except sqlite3.IntegrityError:
                        pass  # Already exists
            
            stats['clone_entities_fixed'] += 1
    
    if clone_rows and not dry_run:
        conn.commit()
    
    # 3. Normalise BNM dates in metadata
    rows = conn.execute("""
        SELECT id, value, metadata FROM entities 
        WHERE metadata LIKE '%bnm%' AND metadata LIKE '%date_added%'
    """).fetchall()
    
    for row in rows:
        try:
            meta = json.loads(row['metadata'])
            if 'date_added' in meta:
                old_date = meta['date_added']
                new_date = normalise_bnm_date(old_date)
                if old_date != new_date:
                    meta['date_added'] = new_date
                    stats['dates_normalised'] += 1
                    if not dry_run:
                        conn.execute(
                            "UPDATE entities SET metadata = ? WHERE id = ?",
                            (json.dumps(meta), row['id']),
                        )
        except (json.JSONDecodeError, TypeError):
            continue
    
    # 4. Clean BNM multi-line company names
    rows = conn.execute("""
        SELECT id, value, type FROM entities 
        WHERE type = 'company_name' 
        AND (value LIKE '%  %' OR value LIKE '%\t%' OR value LIKE '%\n%')
    """).fetchall()
    
    # (Already 0 from earlier check, but let's be safe)
    for row in rows:
        names = normalise_bnm_name(row['value'])
        if names:
            new_name = names[0]['name']
            if new_name != row['value']:
                stats['bnm_names_cleaned'] += 1
                if not dry_run:
                    conn.execute(
                        "UPDATE entities SET value = ? WHERE id = ?",
                        (new_name, row['id']),
                    )
    
    if not dry_run:
        conn.commit()
    
    # 5. Verify - check remaining noise
    remaining_garbage = conn.execute("""
        SELECT count(*) FROM entities 
        WHERE length(value) >= 15 
        AND value NOT LIKE 'http%' 
        AND value NOT LIKE '+%'
        AND value NOT LIKE 'RM%'
        AND value NOT LIKE '% %'
        AND value GLOB '[A-Za-z0-9_-]*'
    """).fetchone()[0]
    
    conn.close()
    stats['remaining_potential_garbage'] = remaining_garbage
    
    return stats


def rebuild_cross_reference_index(dry_run: bool = False) -> dict:
    """Rebuild cross-reference engine index after data cleanup."""
    if dry_run:
        return {"action": "Would rebuild cross-reference index (skip in dry-run)"}
    
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))
    
    from db.database import Database
    from services.cross_reference import CrossReferenceEngine
    
    db = Database()
    engine = CrossReferenceEngine(db=db)
    engine.load()
    
    return {
        "bnm_index": len(engine._bnm_index),
        "sc_index": len(engine._sc_index),
        "internal_index": len(engine._internal_index),
        "total": len(engine._bnm_index) + len(engine._sc_index) + len(engine._internal_index),
    }


# ─── Main ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="FraudMVP Data Cleanup")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without applying")
    args = parser.parse_args()
    
    print(f"\n{'='*60}")
    print(f"  FraudMVP Data Cleanup")
    print(f"  {'DRY RUN' if args.dry_run else 'LIVE'}")
    print(f"{'='*60}\n")
    
    # Step 1: Backup DB
    if not args.dry_run:
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        backup_path = DB_PATH.parent / f"fraud_mvp.db.backup-cleanup-{timestamp}"
        shutil.copy2(DB_PATH, backup_path)
        print(f"📦 DB backup: {backup_path}")
    
    # Step 2: Clean BNM source data
    print(f"\n── Cleaning BNM source data ──")
    bnm_stats = cleanup_bnm_source_data(dry_run=args.dry_run)
    for k, v in bnm_stats.items():
        print(f"  {k}: {v}")
    
    # Step 3: Clean DB entities
    print(f"\n── Cleaning DB entities ──")
    db_stats = cleanup_db_entities(dry_run=args.dry_run)
    for k, v in db_stats.items():
        print(f"  {k}: {v}")
    
    # Step 4: Rebuild cross-reference index
    print(f"\n── Rebuilding cross-reference index ──")
    cr_stats = rebuild_cross_reference_index(dry_run=args.dry_run)
    for k, v in cr_stats.items():
        print(f"  {k}: {v}")
    
    print(f"\n{'='*60}")
    print(f"  Cleanup {'would be' if args.dry_run else ''} complete!")
    print(f"{'='*60}\n")