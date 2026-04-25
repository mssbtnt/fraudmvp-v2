"""
Cross-Reference Engine — Check extracted entities against known-bad databases.

Data sources:
- BNM Consumer Alert List (575 unauthorised entities)
- SC Investor Alert List (1,474 entities)
- SemakMule (PDRM) — currently DOWN, graceful skip
- Internal pipeline (historically flagged entities)

When a cross-reference match is found, the entity gets a score boost:
- BNM match: +50 (confirmed by central bank)
- SC match: +45 (confirmed by securities commission)
- SemakMule match: +50 (police-verified)
- Internal match: +20 (previously flagged by our pipeline)
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

from db.database import Database

log = logging.getLogger("cross_reference")


# ─── Data Classes ─────────────────────────────────────────────────────────────


@dataclass
class MatchSource:
    """A source where the entity was found listed as fraudulent/unauthorised."""
    database: str        # 'bnm', 'sc', 'semakmule', 'internal'
    entity_name: str     # Name of the entity in the source listing
    listed_date: str     # Date the entity was listed (if available)
    status: str          # 'confirmed', 'suspected', 'verified'
    extra_urls: list[str] = field(default_factory=list)  # Associated URLs


@dataclass
class CrossReferenceResult:
    """Result of cross-referencing an entity against known-bad databases."""
    value: str                              # The entity value checked
    entity_type: str                        # phone, bank_account, domain, etc.
    matched: bool                           # Whether a match was found
    sources: list[MatchSource] = field(default_factory=list)
    related_entities: list[dict] = field(default_factory=list)
    confidence: float = 0.0                 # 0.0-1.0 match confidence
    risk_boost: int = 0                     # Score boost to apply


# ─── Cross-Reference Engine ───────────────────────────────────────────────────


class CrossReferenceEngine:
    """
    Check extracted entities against known-bad databases.
    
    Loads all known-bad entities into memory at startup for fast lookup.
    ~2,890 entities → ~500KB, negligible memory footprint.
    """

    # Score boosts by source
    SOURCE_BOOSTS = {
        "bnm": 50,
        "sc": 45,
        "semakmule": 50,
        "internal": 20,
    }

    # Confidence by match type
    CONFIDENCE = {
        "exact": 1.0,
        "normalized": 0.95,
        "fuzzy_domain": 0.85,
        "fuzzy_company": 0.75,
    }

    def __init__(self, db: Database, data_dir: str | Path | None = None):
        self.db = db
        self.data_dir = Path(data_dir) if data_dir else Path(__file__).parent.parent / "data"
        
        # In-memory indices for fast lookup
        self._bnm_index: dict[str, dict] = {}   # normalised_value → entity data
        self._sc_index: dict[str, dict] = {}     # normalised_value → entity data
        self._internal_index: dict[str, dict] = {}  # value → entity data
        
        self._loaded = False

    def load(self) -> None:
        """Load all known-bad databases into memory."""
        log.info("Loading known-bad databases into memory...")
        
        self._load_bnm()
        self._load_sc()
        self._load_internal()
        
        total = len(self._bnm_index) + len(self._sc_index) + len(self._internal_index)
        log.info(f"Loaded {total} known-bad entries "
                 f"(BNM: {len(self._bnm_index)}, SC: {len(self._sc_index)}, "
                 f"Internal: {len(self._internal_index)})")
        self._loaded = True

    def _load_bnm(self) -> None:
        """Load BNM Consumer Alert List."""
        bnm_path = self.data_dir / "bnm_consumer_alert_list.json"
        if not bnm_path.exists():
            log.warning(f"BNM data not found: {bnm_path}")
            return

        with open(bnm_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        records = data.get("data", data if isinstance(data, list) else [])
        for record in records:
            if not isinstance(record, dict):
                continue

            # Handle nested dict format: {"Name of unauthorised entities/individual": {"text": "..."}}
            name = self._extract_field(record, "Name of unauthorised entities/individual")
            if not name:
                # Try flat format
                name = record.get("name", record.get("entity_name", ""))
            if not name:
                continue

            # Clean name (remove \t, \n)
            name = name.replace("\t", " ").replace("\n", " ").strip()

            # Index by normalised name
            key = self._normalise_company(name)
            if key:
                self._bnm_index[key] = {
                    "name": name,
                    "type": "company_name",
                    "listed_date": self._extract_field(record, "Date Added to Alert List") or "",
                    "status": "confirmed",
                    "urls": [],
                }

            # Extract URLs from Website field
            website_text = self._extract_field(record, "Website") or ""
            urls = re.findall(r'https?://[^\s<>"\']+', website_text)
            for url in urls:
                url_key = self._normalise_url(url)
                if url_key:
                    self._bnm_index[url_key] = {
                        "name": name,
                        "type": "domain",
                        "listed_date": self._extract_field(record, "Date Added to Alert List") or "",
                        "status": "confirmed",
                        "urls": [url],
                    }

            # Extract phone numbers from Website or other fields
            full_text = " ".join(str(v) for v in record.values() if isinstance(v, (str, dict)))
            if isinstance(full_text, str):
                phones = re.findall(r'\+?6?01\d{8,9}', full_text)
                for phone in phones:
                    phone_key = self._normalise_phone(phone)
                    if phone_key and len(phone_key) >= 10:
                        self._bnm_index[phone_key] = {
                            "name": name,
                            "type": "phone",
                            "listed_date": self._extract_field(record, "Date Added to Alert List") or "",
                            "status": "confirmed",
                        }

        log.info(f"Loaded {len(self._bnm_index)} BNM index entries")

    def _load_sc(self) -> None:
        """Load SC Investor Alert List."""
        sc_path = self.data_dir / "sc_investor_alert_list.json"
        if not sc_path.exists():
            log.warning(f"SC data not found: {sc_path}")
            return

        with open(sc_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        for record in data.get("data", data if isinstance(data, list) else []):
            if isinstance(record, dict):
                name = record.get("name", "")
                if not name:
                    continue

                # Index by normalised name
                key = self._normalise_company(name)
                if key:
                    self._sc_index[key] = {
                        "name": name,
                        "type": record.get("type", "company_name"),
                        "listed_date": record.get("date_added", ""),
                        "status": "confirmed",
                        "urls": record.get("websites", []) + record.get("telegram_links", []),
                    }

                # Index associated URLs
                for url in record.get("websites", []):
                    url_key = self._normalise_url(url)
                    if url_key:
                        self._sc_index[url_key] = {
                            "name": name,
                            "type": "domain",
                            "listed_date": record.get("date_added", ""),
                            "status": "confirmed",
                            "urls": [url],
                        }

                for url in record.get("telegram_links", []):
                    url_key = self._normalise_url(url)
                    if url_key:
                        self._sc_index[url_key] = {
                            "name": name,
                            "type": "telegram_url",
                            "listed_date": record.get("date_added", ""),
                            "status": "confirmed",
                            "urls": [url],
                        }

                for url in record.get("facebook_links", []):
                    url_key = self._normalise_url(url)
                    if url_key:
                        self._sc_index[url_key] = {
                            "name": name,
                            "type": "facebook_url",
                            "listed_date": record.get("date_added", ""),
                            "status": "confirmed",
                            "urls": [url],
                        }

                for url in record.get("whatsapp_links", []):
                    url_key = self._normalise_url(url)
                    if url_key:
                        self._sc_index[url_key] = {
                            "name": name,
                            "type": "whatsapp_link",
                            "listed_date": record.get("date_added", ""),
                            "status": "confirmed",
                            "urls": [url],
                        }

        log.info(f"Loaded {len(self._sc_index)} SC index entries")

    def _load_internal(self) -> None:
        """Load internally flagged entities from DB."""
        with self.db.conn() as conn:
            cursor = conn.execute(
                "SELECT id, value, type, count, metadata FROM entities "
                "WHERE count >= 3 OR metadata LIKE '%flagged%'"
            )
            for row in cursor.fetchall():
                key = self._normalise_value(row[1], row[2])
                if key:
                    self._internal_index[key] = {
                        "name": row[1],
                        "type": row[2],
                        "count": row[3],
                        "status": "suspected",
                    }

        log.info(f"Loaded {len(self._internal_index)} internal index entries")

    # ─── Public API ────────────────────────────────────────────────────────────

    def check_entity(self, value: str, entity_type: str) -> CrossReferenceResult:
        """
        Check a single entity against all known-bad databases.
        
        Args:
            value: Entity value (phone number, domain, company name, etc.)
            entity_type: Entity type (phone, domain, company_name, etc.)
            
        Returns:
            CrossReferenceResult with match status, sources, and risk boost.
        """
        if not self._loaded:
            self.load()

        result = CrossReferenceResult(
            value=value,
            entity_type=entity_type,
            matched=False,
        )

        # Normalise the input value based on type
        normalised = self._normalise_value(value, entity_type)
        if not normalised:
            return result

        # Check each source
        for source_name, index, boost in [
            ("bnm", self._bnm_index, self.SOURCE_BOOSTS["bnm"]),
            ("sc", self._sc_index, self.SOURCE_BOOSTS["sc"]),
            ("internal", self._internal_index, self.SOURCE_BOOSTS["internal"]),
        ]:
            match = self._find_match(normalised, value, entity_type, index)
            if match:
                result.matched = True
                result.sources.append(MatchSource(
                    database=source_name,
                    entity_name=match.get("name", value),
                    listed_date=match.get("listed_date", ""),
                    status=match.get("status", "confirmed"),
                    extra_urls=match.get("urls", []),
                ))
                # Use the highest boost
                if boost > result.risk_boost:
                    result.risk_boost = boost
                # Use the highest confidence
                confidence = self._calculate_confidence(normalised, match, entity_type)
                if confidence > result.confidence:
                    result.confidence = confidence

        # Also check for related entities (same company in source but different type)
        if result.matched:
            for source_name, index in [("bnm", self._bnm_index), ("sc", self._sc_index)]:
                for src_key, src_data in index.items():
                    if src_data.get("name", "").lower() == result.sources[0].entity_name.lower() if result.sources else False:
                        if src_key != normalised:  # Don't include the match itself
                            result.related_entities.append({
                                "value": src_key,
                                "type": src_data.get("type", "unknown"),
                                "source": source_name,
                            })

        return result

    def check_batch(self, entities: list[dict]) -> list[CrossReferenceResult]:
        """
        Check multiple entities against known-bad databases.
        
        Args:
            entities: List of dicts with 'value' and 'type' keys.
            
        Returns:
            List of CrossReferenceResult objects.
        """
        return [self.check_entity(e["value"], e["type"]) for e in entities]

    # ─── Matching Logic ────────────────────────────────────────────────────────

    def _find_match(self, normalised: str, original: str, entity_type: str, 
                     index: dict) -> dict | None:
        """Find a match for an entity in the given index."""
        # 1. Exact match on normalised value
        if normalised in index:
            return index[normalised]

        # 2. Type-specific fuzzy matching
        if entity_type == "domain":
            return self._fuzzy_domain_match(original, index)
        elif entity_type == "company_name":
            return self._fuzzy_company_match(original, index)
        elif entity_type == "phone":
            # Already normalised — if exact didn't match, no match
            return None

        # 3. Try substring match for URLs
        if entity_type in ("telegram_url", "facebook_url", "whatsapp_link", "url"):
            return self._substring_url_match(original, index)

        return None

    def _fuzzy_domain_match(self, domain: str, index: dict) -> dict | None:
        """
        Fuzzy match domains — catch phishing domains that differ by 1-2 chars.
        e.g., 'maybank-my.com' vs 'maybank.com.my'
        """
        domain_clean = domain.lower().replace("www.", "").rstrip("/")
        
        # Check subdomain match (scammer uses legit domain as subdomain)
        for key, data in index.items():
            key_clean = key.lower().replace("www.", "").rstrip("/")
            if not key_clean:
                continue
            
            # Exact subdomain: scam.maybank.com.my contains maybank.com.my
            if domain_clean.endswith("." + key_clean):
                return data
            if key_clean.endswith("." + domain_clean):
                return data

        # Levenshtein distance for close matches (only for domains > 5 chars)
        if len(domain_clean) > 5:
            best_match = None
            best_dist = 999
            for key, data in index.items():
                key_clean = key.lower().replace("www.", "").rstrip("/")
                if not key_clean or len(key_clean) <= 5:
                    continue
                # Only compare similar-length domains (within 30%)
                if abs(len(domain_clean) - len(key_clean)) > len(domain_clean) * 0.3:
                    continue
                dist = self._levenshtein(domain_clean, key_clean)
                if dist < best_dist and dist <= 2:
                    best_dist = dist
                    best_match = data

            if best_match:
                return best_match

        return None

    def _fuzzy_company_match(self, company: str, index: dict) -> dict | None:
        """
        Fuzzy match company names using token overlap.
        e.g., 'ABC Investment Sdn Bhd' matches 'ABC Investment'
        """
        company_lower = company.lower().strip()
        # Remove common suffixes
        for suffix in ["sdn bhd", "bhd", "sdn", "pte ltd", "ltd", "inc", "llc", "corp"]:
            company_lower = company_lower.replace(suffix, "").strip()
        
        company_tokens = set(company_lower.split())
        if len(company_tokens) < 2:
            return None

        best_match = None
        best_overlap = 0.0

        for key, data in index.items():
            name_lower = data.get("name", key).lower().strip()
            for suffix in ["sdn bhd", "bhd", "sdn", "pte ltd", "ltd", "inc", "llc", "corp"]:
                name_lower = name_lower.replace(suffix, "").strip()
            
            name_tokens = set(name_lower.split())
            if len(name_tokens) < 2:
                continue

            # Token overlap ratio (Jaccard-like)
            intersection = company_tokens & name_tokens
            union = company_tokens | name_tokens
            overlap = len(intersection) / len(union) if union else 0

            # Require at least 2 matching tokens and 60% overlap
            if len(intersection) >= 2 and overlap > best_overlap and overlap >= 0.6:
                best_overlap = overlap
                best_match = data

        return best_match

    def _substring_url_match(self, url: str, index: dict) -> dict | None:
        """Match URLs by checking if the URL contains or is contained in an index key."""
        url_lower = url.lower().rstrip("/")
        for key, data in index.items():
            key_lower = key.lower().rstrip("/")
            if not key_lower:
                continue
            # URL contains the index key or vice versa
            if url_lower in key_lower or key_lower in url_lower:
                return data
        return None

    # ─── Normalisation ─────────────────────────────────────────────────────────

    @staticmethod
    def _extract_field(record: dict, field_name: str) -> str | None:
        """
        Extract a field value from a record that may be in nested or flat format.
        Nested: {"Field Name": {"text": "value", "href": "..."}}
        Flat: {"field_name": "value"}
        """
        # Try nested format first
        if field_name in record and isinstance(record[field_name], dict):
            return record[field_name].get("text", "")
        # Try flat format with exact key
        if field_name in record and isinstance(record[field_name], str):
            return record[field_name]
        # Try lowercase key
        lower_key = field_name.lower().replace(" ", "_")
        if lower_key in record:
            val = record[lower_key]
            if isinstance(val, dict):
                return val.get("text", "")
            return str(val)
        return None

    def _normalise_value(self, value: str, entity_type: str) -> str:
        """Normalise an entity value for matching based on type."""
        if not value:
            return ""
        if entity_type == "phone":
            return self._normalise_phone(value)
        elif entity_type == "bank_account":
            return self._normalise_bank_account(value)
        elif entity_type == "domain":
            return self._normalise_domain(value)
        elif entity_type == "company_name":
            return self._normalise_company(value)
        elif entity_type in ("telegram_url", "url", "facebook_url", "whatsapp_link"):
            return self._normalise_url(value)
        return value.lower().strip()

    @staticmethod
    def _normalise_phone(phone: str) -> str:
        """Normalise phone number: strip +60, spaces, dashes, parentheses."""
        digits = re.sub(r"[^\d]", "", phone)
        # Malaysian numbers: strip leading 60
        if digits.startswith("60") and len(digits) > 10:
            digits = digits[2:]
        return digits

    @staticmethod
    def _normalise_bank_account(account: str) -> str:
        """Normalise bank account: digits only."""
        return re.sub(r"[^\d]", "", account)

    @staticmethod
    def _normalise_domain(domain: str) -> str:
        """Normalise domain: lowercase, strip www., strip trailing slash."""
        return domain.lower().replace("www.", "").rstrip("/").strip()

    @staticmethod
    def _normalise_company(name: str) -> str:
        """Normalise company name: lowercase, strip common suffixes."""
        name_lower = name.lower().strip()
        for suffix in ["sdn bhd", "bhd", "sdn", "pte ltd", "ltd", "inc", "llc", "corp"]:
            name_lower = name_lower.replace(suffix, "").strip()
        # Remove punctuation
        name_lower = re.sub(r"[^\w\s]", "", name_lower)
        return name_lower

    @staticmethod
    def _normalise_url(url: str) -> str:
        """Normalise URL: lowercase, strip trailing slash, strip www."""
        url = url.lower().strip()
        if url.startswith("https://www."):
            url = "https://" + url[12:]
        elif url.startswith("http://www."):
            url = "http://" + url[11:]
        url = url.rstrip("/")
        return url

    # ─── Utilities ─────────────────────────────────────────────────────────────

    @staticmethod
    def _levenshtein(s1: str, s2: str) -> int:
        """Compute Levenshtein distance between two strings."""
        if len(s1) < len(s2):
            return CrossReferenceEngine._levenshtein(s2, s1)

        if len(s2) == 0:
            return len(s1)

        previous_row = range(len(s2) + 1)
        for i, c1 in enumerate(s1):
            current_row = [i + 1]
            for j, c2 in enumerate(s2):
                insertions = previous_row[j + 1] + 1
                deletions = current_row[j] + 1
                substitutions = previous_row[j] + (c1 != c2)
                current_row.append(min(insertions, deletions, substitutions))
            previous_row = current_row

        return previous_row[-1]

    @staticmethod
    def _calculate_confidence(normalised: str, match: dict, entity_type: str) -> float:
        """Calculate match confidence based on type."""
        if entity_type == "phone":
            return 1.0  # Exact phone match is high confidence
        if entity_type == "bank_account":
            return 1.0
        if entity_type == "domain":
            return 0.95
        if entity_type == "company_name":
            return 0.85
        if entity_type in ("telegram_url", "facebook_url", "whatsapp_link"):
            return 0.90
        return 0.80


# ─── Convenience ──────────────────────────────────────────────────────────────

def create_cross_reference_engine(db: Database | None = None,
                                   data_dir: str | Path | None = None) -> CrossReferenceEngine:
    """Create a CrossReferenceEngine with a Database connection."""
    if db is None:
        db = Database()
    engine = CrossReferenceEngine(db=db, data_dir=data_dir)
    engine.load()
    return engine


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    
    db = Database()
    engine = create_cross_reference_engine(db=db)
    
    # Test with some known BNM/SC entities
    test_entities = [
        {"value": "+6012345678", "type": "phone"},
        {"value": "ABC Capital", "type": "company_name"},
        {"value": "maybank2u.com.my", "type": "domain"},
        {"value": "https://t.me/scam_channel", "type": "telegram_url"},
    ]
    
    results = engine.check_batch(test_entities)
    for entity, result in zip(test_entities, results):
        print(f"\n{entity['value']} ({entity['type']}):")
        print(f"  Matched: {result.matched}")
        print(f"  Confidence: {result.confidence}")
        print(f"  Risk Boost: {result.risk_boost}")
        for source in result.sources:
            print(f"  Source: {source.database} — {source.entity_name} ({source.status})")