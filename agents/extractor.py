"""
FraudExtractorAgent — Entity extraction from raw scraped messages.

Responsibilities:
- Pull raw messages from Redis queue (raw_messages)
- Extract: phone numbers, bank accounts, domains, URLs, email addresses
- Classify scam type using keyword matching + LLM (optional)
- Deduplicate entities (by value+type)
- Write entities to DB
- Push extracted entities to scored_entities queue
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import sys
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import yaml
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent.parent))

from db.database import Database
from services.queue_handler import QueueHandler
from services.llm_similarity import KeywordExtractor

# ─── Config ───────────────────────────────────────────────────────────────────

load_dotenv()
CONFIG_DIR = Path(__file__).parent.parent / "config"
DATA_DIR = Path(__file__).parent.parent / "_docs" / "data"
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%d-%H:%M:%S",
)
log = logging.getLogger("extractor")


# ─── Phone number length data ──────────────────────────────────────────────────

def _load_phone_length_data() -> dict[str, tuple[int, int]]:
    """Load phone number length ranges by country code from data files.

    Returns dict mapping country_code (str) -> (min_length, max_length)
    for national phone numbers (without country code).
    """
    result: dict[str, tuple[int, int]] = {}
    try:
        lengths_path = DATA_DIR / "phone-number-length-by-country-2026.json"
        codes_path = DATA_DIR / "phone-number-code-by-country-2026.json"
        if lengths_path.exists() and codes_path.exists():
            with open(lengths_path, encoding="utf-8") as f:
                lengths = json.load(f)
            with open(codes_path, encoding="utf-8") as f:
                codes = json.load(f)
            # Build country_code -> flagCode mapping
            code_map: dict[str, str] = {}
            for item in codes:
                code = str(item.get("phoneNumberLengthByCountry_CountryCode", ""))
                flag = item.get("flagCode", "")
                if code and flag:
                    code_map[flag] = code
            # Build country_code -> (min_length, max_length) mapping
            for item in lengths:
                flag = item.get("flagCode", "")
                if flag in code_map:
                    code = code_map[flag]
                    min_len = item.get("phoneNumberLengthByCountry_phLengthMin")
                    max_len = item.get("phoneNumberLengthByCountry_phLengthMax")
                    if min_len and max_len:
                        result[code] = (min_len, max_len)
            log.info(f"Loaded phone length data for {len(result)} country codes")
    except Exception as e:
        log.warning(f"Failed to load phone length data: {e}")
    return result


PHONE_LENGTH_BY_CODE: dict[str, tuple[int, int]] = _load_phone_length_data()


# ─── Entity patterns ───────────────────────────────────────────────────────────

# Tightened phone regex to avoid picking up YYYYMMDD dates
# Requires at least one digit that isn't just a year prefix and avoids generic long numbers
PHONE_RE = re.compile(
    r"""
    (?:(?<!\d)[+]?\d{1,3}[-.\s]?)?
    \(?\d{2,4}\)?[-.\s]?\d{3,4}[-.\s]?\d{3,4}
    """,
    re.VERBOSE,
)

# Malaysian mobile format: +601x, 601x, 01x
# Includes all valid prefixes: 010, 011, 012-019
MY_PHONE_RE = re.compile(
    r"""
    (?:(?<!\d)[+]?6?01[0-9]\d[\s\-]?\d{3,4}[\s\-]?\d{3,4})
    """,
    re.VERBOSE,
)

# Malaysian bank accounts: 10-19 digits
BANK_ACCOUNT_RE = re.compile(r"\b\d{10,19}\b")

# IBAN (Malaysian MY + 2 letters + 16-30 alphanum)
IBAN_RE = re.compile(r"\bMY[A-Z]{2}\d{16,30}\b", re.IGNORECASE)

BANK_CODE_PREFIXES: dict[str, str] = {
    "0227": "Maybank",
    "0226": "UOB Malaysia",
    "0205": "CIMB Bank",
    "0233": "Public Bank",
    "0218": "RHB Bank",
    "0212": "Alliance Bank",
    "0208": "AmBank",
    "0224": "Hong Leong Bank",
    "0232": "Affin Bank",
    "0245": "Bank Islam",
    "0341": "Bank Muamalat",
    "0350": "Al Rajhi Bank",
    "0346": "Kuwait Finance House",
    "1602": "Bank Rakyat",
    "1601": "Bank Simpanan Nasional (BSN)",
    "3306": "Agrobank",
    "0352": "MBSB Bank",
    "0229": "OCBC Bank",
    "0214": "Standard Chartered",
    "0222": "HSBC Malaysia",
    "0217": "Citibank Malaysia",
    "0242": "Bank of China",
    "0265": "China Construction Bank",
    "0259": "ICBC Malaysia",
}

URL_RE = re.compile(r"https?://[^\s<>\[\]()\"']+", re.IGNORECASE)
DOMAIN_RE = re.compile(r"(?:https?://)?([\w-]+\.[\w-]+(?:\.[\w-]+)?)", re.IGNORECASE)
SUSPICIOUS_TLDS = {
    ".xyz", ".top", ".club", ".online", ".site", ".click",
    ".link", ".work", ".loan", ".download", ".stream",
    ".cfd", ".gq", ".ml", ".tk", ".pw",
}
EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b", re.IGNORECASE)
WA_LINK_RE = re.compile(r"(?:https?://)?(?:wa\.me/|api\.whatsapp\.com/send\?phone=)(\d{8,15})", re.IGNORECASE)
WASAP_MY_RE = re.compile(r"(?:https?://)?(?:www\.)?wasap\.my/(\d+)", re.IGNORECASE)
MY_PHONE_LOCAL_RE = re.compile(r"\b(01[0-9]\d{7,8})\b", re.IGNORECASE)
QR_MENTION_RE = re.compile(r"\b(scan|skan)\s*qr\b", re.IGNORECASE)
DEPOSIT_RE = re.compile(r"\b(deposit|bayar\s*dahulu|bayar\s*dulu)\b", re.IGNORECASE)
GUARANTEED_RE = re.compile(r"\b(janji|jamin)\s*[\d%]+\s*(untung|faedah|pulangan)\b", re.IGNORECASE)
JOB_SCAM_RE = re.compile(r"\b(jawatan\s*kosong|kerja\s*sambilan|kerusi\s*kosong)\b", re.IGNORECASE)
SCAM_FLAG_RE = re.compile(r"\b(scam|penipu|tipu|kantoi|tertipu|kena\s*tipu)\b", re.IGNORECASE)
TNG_RE = re.compile(r"\b(?:touch[\s']?n[\s']?go|tng|t[\s-]?n[\s-]?g)\b", re.IGNORECASE)
DUITNOW_RE = re.compile(r"\bduitnow\b", re.IGNORECASE)
MACAU_SCAM_RE = re.compile(r"\b(?:macau[\s-]?scam|scam[\s-]?macau|panggil[\s-]?telefon[\s-]?macau|panggilan[\s-]?macau)\b", re.IGNORECASE)
AH_LONG_RE = re.compile(r"\b(?:ah[\s-]?long|loan[\s-]?shark|pinjaman[\s-]?ilegal|along[\s-]?malaysia|potong[\s-]?ayam)\b", re.IGNORECASE)
FAKE_GOV_AID_RE = re.compile(r"\b(?:bantuan[\s-]?kerajaan[\s-]?tipu|bantuan[\s-]?palsu|bkm[\s-]?tipu|bpr[\s-]?tipu|str[\s-]?tipu|bsh[\s-]?tipu)\b", re.IGNORECASE)
URGENCY_RE = re.compile(r"\b(?:sekarang[\s-]?je|terhad[\s-]?je|last[\s-]?slot|slot[\s-]?terhad|cepat[\s-]?daftar|daftar[\s-]?sekarang)\b", re.IGNORECASE)
TRANSFER_PRESSURE_RE = re.compile(r"\b(?:transfer[\s-]?dulu|bank[\s-]?in[\s-]?dulu|bayar[\s-]?dulu|hantar[\s-]?duit[\s-]?dulu)\b", re.IGNORECASE)
TELEGRAM_INVITE_RE = re.compile(r"(?:https?://)?(?:t\.me/joinchat/|t\.me/\+)[^\s]+", re.IGNORECASE)


@dataclass
class ExtractedEntity:
    type: str
    value: str
    source_platform: str
    source_channel: str
    source_message: str
    message_hash: str
    timestamp: str
    is_suspicious: bool
    raw_value: str
    bank_name: str | None = None
    entity_id: int | None = None

    def to_json(self) -> str:
        obj = asdict(self)
        return json.dumps(obj, ensure_ascii=False)

    @staticmethod
    def from_json(data: str) -> "ExtractedEntity":
        kwargs = json.loads(data)
        kwargs.setdefault("entity_id", None)
        return ExtractedEntity(**kwargs)


class FraudExtractorAgent:
    BATCH_SIZE = 50

    def __init__(self):
        self.queue = QueueHandler()
        self.db = Database()
        self.keyword_extractor = KeywordExtractor()
        cfg_path = CONFIG_DIR / "scoring_rules.yaml"
        if cfg_path.exists():
            with open(cfg_path, encoding="utf-8") as f:
                self.scoring_cfg = yaml.safe_load(f)
        else:
            self.scoring_cfg = {}
        log.info("FraudExtractorAgent initialized")

    def _digits(self, value: str) -> str:
        return re.sub(r"\D", "", value)

    def _identify_bank(self, account_digits: str) -> str | None:
        n = len(account_digits)
        for key_len in [4, 3]:
            prefix = account_digits[:key_len]
            if prefix in BANK_CODE_PREFIXES:
                return BANK_CODE_PREFIXES[prefix]
        if n == 12: return "Maybank"
        if n == 16: return "Bank Simpanan Nasional (BSN)"
        if n == 10: return "Public Bank (probable)"
        if n == 11: return "Hong Leong Bank (probable)"
        if n in (13, 14, 15): return f"Unknown (valid {n}-digit account)"
        return None

    # Country codes for phone number detection (sorted by length descending for greedy matching)
    COUNTRY_CODES: dict[str, str] = {
        "855": "Cambodia", "856": "Laos", "95": "Myanmar",
        "60": "Malaysia", "61": "Australia", "62": "Indonesia",
        "63": "Philippines", "65": "Singapore", "66": "Thailand",
        "81": "Japan", "82": "South Korea", "84": "Vietnam",
        "86": "China", "91": "India", "1": "US/Canada", "44": "UK",
        "7": "Russia", "20": "Egypt", "27": "South Africa",
        "34": "Spain", "49": "Germany", "33": "France",
        "39": "Italy", "55": "Brazil", "52": "Mexico",
        "90": "Turkey", "92": "Pakistan", "93": "Afghanistan",
        "94": "Sri Lanka", "98": "Iran", "212": "Morocco",
        "234": "Nigeria", "375": "Belarus", "380": "Ukraine",
        "381": "Serbia", "853": "Macau",
    }

    COMPLAINT_SOURCES: set[str] = {
        "Consumers Association of Penang",
        "consumer.org.my",
        "Consumers Association of Malaysia",
    }

    def _is_complaint_source(self, channel: str) -> bool:
        return any(cs.lower() in channel.lower() for cs in self.COMPLAINT_SOURCES)

    def _looks_like_phone(self, digits: str) -> bool:
        """Check if a digit string is more likely a phone number than a bank account.

        Uses country code detection and phone length data to distinguish phones
        from bank accounts. Returns True if the digits match known phone patterns.
        """
        n = len(digits)

        # Malaysian mobile: +601x, 601x, 01x, or just 1x (10-12 digits total)
        # Includes prefixes 010, 011, 012-019 (all valid Malaysian mobile prefixes)
        if re.match(r"^6?01[0-9]\d{7,8}$", digits):
            return True

        # Malaysian mobile without leading 0: 1x-xxxxxxx (9-11 digits)
        if re.match(r"^1[0-9]\d{7,9}$", digits):
            return True

        # International phone: starts with known country code + valid national length
        for code in sorted(self.COUNTRY_CODES.keys(), key=len, reverse=True):
            if digits.startswith(code):
                national = digits[len(code):]
                # Check against phone length data if available
                if code in PHONE_LENGTH_BY_CODE:
                    min_len, max_len = PHONE_LENGTH_BY_CODE[code]
                    if min_len <= len(national) <= max_len:
                        return True
                # Fallback: valid national number length (7-15 digits per ITU)
                elif 7 <= len(national) <= 15:
                    return True

        # Numbers starting with 01 that are 10-12 digits (Malaysian mobile local format)
        if re.match(r"^01[0-9]", digits) and 10 <= n <= 12:
            return True

        return False

    def _strip_country_code(self, digits: str) -> str | None:
        """Strip international country code from digit string, return national number.

        Returns None if no known country code prefix is found or the result
        is not a plausible national number length.
        """
        for code in sorted(self.COUNTRY_CODES.keys(), key=len, reverse=True):
            if digits.startswith(code):
                national = digits[len(code):]
                if 7 <= len(national) <= 15:
                    return national
        return None

    def _is_legit_org_email(self, email: str) -> bool:
        email = email.lower()
        legit_domains = {
            "consumer.org.my", "maybank.com", "cimb.com", "publicbank.com",
            "rhb.com.my", "bankislam.com", "bnm.gov.my", "pdrm.gov.my",
            "macc.gov.my", "bkm.gov.my", "malaysia.gov.my", ".gov.my",
            "touch n go", "touchngo.com", "duitnow.com", "bigpay.my",
        }
        if any(domain in email for domain in legit_domains): return True
        if email.startswith("info@") or email.startswith("contact@"): return True
        return False

    def extract_from_text(self, text: str, platform: str, channel: str, msg_hash: str, timestamp: str) -> list[ExtractedEntity]:
        entities = []
        seen: set[tuple[str, str]] = set()
        is_complaint = self._is_complaint_source(channel)

        def add(type_: str, value: str, raw: str, suspicious: bool = False, bank_name: str | None = None):
            # --- VALIDATION TO STOP DATE EXTRACTION ---
            digits = self._digits(value)
            
            # Reject patterns that look like YYYYMMDD (e.g., 20250101, 20260408)
            if len(digits) == 8 and (digits.startswith("2025") or digits.startswith("2026")):
                log.debug(f"Rejected date-like string as {type_}: {value}")
                return

            # Guard: Malaysian phones are 9-12 digits max
            if type_ == "phone" and len(digits) > 12:
                return

            key = (type_, value)
            if key in seen: return
            seen.add(key)

            if len(digits) >= 9:
                for (prev_type, prev_val) in list(seen):
                    if prev_type != type_:
                        prev_digits = self._digits(prev_val)
                        # Exact match: same digits, different type
                        if prev_digits == digits:
                            return
                        # Cross-type phone/bank dedup: check if one contains the other
                        # after stripping country codes
                        if (prev_type == "phone" and type_ == "bank_account") or \
                           (prev_type == "bank_account" and type_ == "phone"):
                            phone_digits = prev_digits if prev_type == "phone" else digits
                            bank_digits = prev_digits if prev_type == "bank_account" else digits
                            # Strip country code from phone and compare to bank
                            phone_national = self._strip_country_code(phone_digits)
                            if phone_national:
                                # Phone national number matches bank exactly
                                if phone_national == bank_digits:
                                    log.debug(f"Cross-type dedup: phone {phone_digits} national={phone_national} == bank {bank_digits}")
                                    return
                                # Phone national number is contained in bank (or vice versa)
                                # Handles cases like phone +617900052144 vs bank 17900052144
                                if phone_national in bank_digits or bank_digits in phone_national:
                                    # Only dedup if the overlap is significant (>80% of shorter string)
                                    shorter = min(len(phone_national), len(bank_digits))
                                    longer = max(len(phone_national), len(bank_digits))
                                    if shorter / longer > 0.8:
                                        log.debug(f"Cross-type dedup: phone national {phone_national} overlaps bank {bank_digits}")
                                        return

            entities.append(ExtractedEntity(
                type=type_, value=value, raw_value=raw, source_platform=platform,
                source_channel=channel, source_message=text[:200], message_hash=msg_hash,
                timestamp=timestamp, is_suspicious=suspicious, bank_name=bank_name,
            ))

        for m in BANK_ACCOUNT_RE.finditer(text):
            val = m.group()
            stripped = self._digits(val)
            # Skip Malaysian phone numbers (already caught by MY_PHONE_RE)
            # Includes prefixes 010, 011, 012-019 (all valid Malaysian mobile prefixes)
            if re.match(r"^6?01[0-9]\d{7,8}$", stripped): continue
            # Skip date patterns (YYYYMMDD)
            if not re.match(r"^(19|20)\d{2}$", stripped):
                bank_name = self._identify_bank(stripped)
                # Reject numbers that look like phone numbers unless they have a
                # valid Malaysian bank prefix (not just a length-based guess)
                has_valid_prefix = False
                for key_len in [4, 3]:
                    if stripped[:key_len] in BANK_CODE_PREFIXES:
                        has_valid_prefix = True
                        break
                if self._looks_like_phone(stripped) and not has_valid_prefix:
                    log.debug(f"Rejected phone-like number as bank_account: {val} (digits={stripped})")
                    continue
                add("bank_account", val, val, bank_name=bank_name)

        for m in IBAN_RE.finditer(text):
            add("bank_account", m.group().upper(), m.group())

        for m in MY_PHONE_RE.finditer(text):
            phone = self._normalize_phone(m.group())
            add("phone", phone, m.group())
        for m in PHONE_RE.finditer(text):
            phone = self._normalize_phone(m.group())
            add("phone", phone, m.group())

        for m in URL_RE.finditer(text):
            url = m.group().rstrip(".,;:)")
            domain_m = DOMAIN_RE.search(url)
            if domain_m:
                domain = domain_m.group(1).lower()
                is_susp = self._is_suspicious_domain(domain)
                add("url", url, url, suspicious=is_susp)
                add("domain", domain, domain, suspicious=is_susp)

        for m in EMAIL_RE.finditer(text):
            email_val = m.group().lower()
            if is_complaint and self._is_legit_org_email(email_val): continue
            add("email", email_val, m.group())

        for m in WA_LINK_RE.finditer(text):
            phone_digits = m.group(1)
            normalized = self._normalize_phone(phone_digits)
            add("phone", normalized, m.group(), suspicious=True)

        for m in MY_PHONE_LOCAL_RE.finditer(text):
            phone = self._normalize_phone(m.group())
            add("phone", phone, m.group())

        # ── Malaysian-specific scam patterns ───────────────────────────────────

        for m in WASAP_MY_RE.finditer(text):
            phone_digits = m.group(1)
            normalized = self._normalize_phone(phone_digits)
            add("phone", normalized, m.group(), suspicious=True)

        for m in TNG_RE.finditer(text):
            add("keyword", "touch_n_go", m.group(), suspicious=True)

        for m in DUITNOW_RE.finditer(text):
            add("keyword", "duitnow", m.group(), suspicious=True)

        for m in MACAU_SCAM_RE.finditer(text):
            add("keyword", "macau_scam", m.group(), suspicious=True)

        for m in AH_LONG_RE.finditer(text):
            add("keyword", "ah_long", m.group(), suspicious=True)

        for m in FAKE_GOV_AID_RE.finditer(text):
            add("keyword", "fake_gov_aid", m.group(), suspicious=True)

        for m in URGENCY_RE.finditer(text):
            add("keyword", "urgency", m.group(), suspicious=True)

        for m in TRANSFER_PRESSURE_RE.finditer(text):
            add("keyword", "transfer_pressure", m.group(), suspicious=True)

        for m in TELEGRAM_INVITE_RE.finditer(text):
            add("url", m.group().rstrip(".,;:)"), m.group(), suspicious=True)

        return entities

    @staticmethod
    def _normalize_phone(raw: str) -> str:
        digits = re.sub(r"\D", "", raw)
        if digits.startswith("0"): digits = "6" + digits
        elif digits.startswith("1") and len(digits) <= 11: digits = "6" + digits
        if not digits.startswith("+"): digits = "+" + digits
        return digits

    @staticmethod
    def _is_suspicious_domain(domain: str) -> bool:
        for tld in SUSPICIOUS_TLDS:
            if domain.endswith(tld): return True
        return False

    def classify(self, text: str) -> tuple[str, float, list[str]]:
        category, score = self.keyword_extractor.top_category(text)
        matches = self.keyword_extractor.extract(text)
        all_keywords = [kw for kws in matches.values() for kw, _ in kws]
        return category, score, all_keywords

    def write_to_db(self, entity: ExtractedEntity) -> int:
        metadata = {"platform": entity.source_platform, "channel": entity.source_channel, "is_suspicious": entity.is_suspicious}
        if entity.bank_name: metadata["bank_name"] = entity.bank_name
        eid = self.db.upsert_entity(value=entity.value, etype=entity.type, metadata=metadata)
        entity.entity_id = eid
        self.db.add_entity_edge(entity_id=eid, channel=entity.source_channel, platform=entity.source_platform, message_hash=entity.message_hash)
        return eid

    def process_message(self, raw_json: str) -> tuple[int, list[ExtractedEntity]]:
        try: msg = json.loads(raw_json)
        except json.JSONDecodeError: return 0, []
        text = msg.get("text", "")
        if not text.strip(): return 0, []
        entities = self.extract_from_text(text=text, platform=msg.get("platform", "unknown"), channel=msg.get("channel", "unknown"), msg_hash=msg.get("message_hash", ""), timestamp=msg.get("timestamp", datetime.now().isoformat()))
        count = 0
        for entity in entities:
            try: self.write_to_db(entity); count += 1
            except Exception as e: log.error(f"DB write failed for {entity.value}: {e}")
        return count, entities

    def process_batch(self, batch_size: int = BATCH_SIZE) -> dict:
        extracted, messages_processed = 0, 0
        entity_types: dict[str, int] = {}
        queued_entities: list[str] = []
        for _ in range(batch_size):
            raw = self.queue.pop_from_queue("raw_messages")
            if raw is None: break
            count, entities = self.process_message(raw)
            if count > 0:
                extracted += count
                messages_processed += 1
                for entity in entities: entity_types[entity.type] = entity_types.get(entity.type, 0) + 1
                queued_entities.extend(entity.to_json() for entity in entities)
        if queued_entities:
            self.queue.push_to_queue_batch("extracted_entities", queued_entities)
        return {"messages_processed": messages_processed, "entities_extracted": extracted, "by_type": entity_types, "queue_remaining": self.queue.get_queue_length("raw_messages")}

    def run(self, batch_size: int = BATCH_SIZE, max_batches: int = 100) -> dict:
        log.info(f"═══ FraudExtractorAgent starting (batch={batch_size}, max={max_batches}) ═══")
        total_extracted, total_messages = 0, 0
        all_type_counts: dict[str, int] = {}
        for i in range(max_batches):
            result = self.process_batch(batch_size)
            extracted, messages = result["entities_extracted"], result["messages_processed"]
            if extracted == 0: break
            total_extracted += extracted
            total_messages += messages
            for k, v in result["by_type"].items(): all_type_counts[k] = all_type_counts.get(k, 0) + v
            log.info(f"Batch {i+1}: {messages} msgs → {extracted} entities (total: {total_extracted} entities from {total_messages} msgs)")
        log.info(f"═══ Extraction complete: {total_extracted} entities from {total_messages} msgs ═══")
        return {"total_entities": total_extracted, "total_messages": total_messages, "by_type": all_type_counts}

if __name__ == "__main__":
    agent = FraudExtractorAgent()
    result = agent.run()
    print(json.dumps(result, indent=2))
