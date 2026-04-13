"""
FraudExtractorAgent — Entity extraction from raw scraped messages.

Responsibilities:
- Pull raw messages from Redis queue (raw_messages)
- Extract: phone numbers, bank accounts, domains, URLs, email addresses
- Classify scam type using keyword matching + LLM (optional)
- Deduplicate entities (by value+type)
- Write entities to DB
- Optionally push extracted entities to extracted_entities queue
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
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("extractor")


# ─── Entity patterns ───────────────────────────────────────────────────────────

PHONE_RE = re.compile(
    r"""
    (?:(?<!\d)[+]?\d{1,3}[-.\s]?)?
    \(?\d{2,4}\)?[-.\s]?\d{3,4}[-.\s]?\d{3,4}
    """,
    re.VERBOSE,
)

# Malaysian mobile format: +601x, 601x, 01x
MY_PHONE_RE = re.compile(
    r"""
    (?:(?<!\d)[+]?6?01[2-9]\d[\s\-]?\d{3,4}[\s\-]?\d{3,4})
    """,
    re.VERBOSE,
)

# Generic bank account (10-16 digits)
BANK_ACCOUNT_RE = re.compile(r"\b\d{10,18}\b")

# IBAN (Malaysian MY + 2 letters + 16-30 alphanum)
IBAN_RE = re.compile(r"\bMY[A-Z]{2}\d{16,30}\b", re.IGNORECASE)

# URLs
URL_RE = re.compile(r"https?://[^\s<>\"\']+", re.IGNORECASE)

# Domain (no scheme)
DOMAIN_RE = re.compile(
    r"(?:https?://)?([\w-]+\.[\w-]+(?:\.[\w-]+)?)",
    re.IGNORECASE,
)

# Suspicious TLDs
SUSPICIOUS_TLDS = {
    ".xyz", ".top", ".club", ".online", ".site", ".click",
    ".link", ".work", ".loan", ".download", ".stream",
    ".cfd", ".gq", ".ml", ".tk", ".pw",
}

# Email
EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b", re.IGNORECASE)


# ─── ExtractedEntity dataclass ────────────────────────────────────────────────

@dataclass
class ExtractedEntity:
    """A structured entity extracted from a message."""
    type: str           # phone, bank_account, domain, url, email
    value: str         # normalized value
    source_platform: str
    source_channel: str
    source_message: str  # truncated original text (for similarity)
    message_hash: str
    timestamp: str
    is_suspicious: bool  # suspicious TLD or pattern
    raw_value: str       # original matched string

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)

    @staticmethod
    def from_json(data: str) -> "ExtractedEntity":
        return ExtractedEntity(**json.loads(data))


# ─── FraudExtractorAgent ────────────────────────────────────────────────────────

class FraudExtractorAgent:
    """
    Extracts structured entities from raw scraped messages.

    Pipeline:
    1. Pop batch of raw messages from Redis (raw_messages queue)
    2. For each message, extract all entity types via regex
    3. Normalize and deduplicate
    4. Classify scam type via KeywordExtractor
    5. Write to DB (entities table)
    6. Optionally push to extracted_entities queue
    """

    BATCH_SIZE = 50

    def __init__(self):
        self.queue = QueueHandler()
        self.db = Database()
        self.keyword_extractor = KeywordExtractor()

        # Load scoring rules for source weights
        cfg_path = CONFIG_DIR / "scoring_rules.yaml"
        if cfg_path.exists():
            with open(cfg_path, encoding="utf-8") as f:
                self.scoring_cfg = yaml.safe_load(f)
        else:
            self.scoring_cfg = {}

        log.info("FraudExtractorAgent initialized")

    # ── Entity extraction ───────────────────────────────────────────────────────

    def extract_from_text(
        self, text: str, platform: str, channel: str, msg_hash: str, timestamp: str
    ) -> list[ExtractedEntity]:
        """
        Extract all entity types from a single text.
        Returns a list of ExtractedEntity objects.
        """
        entities = []
        seen: set[tuple[str, str]] = set()

        def add(type_: str, value: str, raw: str, suspicious: bool = False):
            key = (type_, value)
            if key in seen:
                return
            seen.add(key)
            entities.append(ExtractedEntity(
                type=type_,
                value=value,
                raw_value=raw,
                source_platform=platform,
                source_channel=channel,
                source_message=text[:200],
                message_hash=msg_hash,
                timestamp=timestamp,
                is_suspicious=suspicious,
            ))

        # Phone numbers (Malaysian first, then generic)
        for m in MY_PHONE_RE.finditer(text):
            phone = self._normalize_phone(m.group())
            add("phone", phone, m.group())
        for m in PHONE_RE.finditer(text):
            phone = self._normalize_phone(m.group())
            add("phone", phone, m.group())

        # Bank accounts — only in text that doesn't look like phone numbers
        for m in BANK_ACCOUNT_RE.finditer(text):
            val = m.group()
            # Skip if this looks like a phone number
            if re.match(r"^6?01[2-9]\d{7,9}$", val):
                continue
            # Filter out years, IDs that look like years
            if not re.match(r"^(19|20)\d{2}$", val):
                add("bank_account", val, val)

        # IBAN
        for m in IBAN_RE.finditer(text):
            add("bank_account", m.group().upper(), m.group())

        # URLs
        for m in URL_RE.finditer(text):
            url = m.group().rstrip(".,;:)")
            domain_m = DOMAIN_RE.search(url)
            if domain_m:
                domain = domain_m.group(1).lower()
                is_susp = self._is_suspicious_domain(domain)
                add("url", url, url, suspicious=is_susp)
                add("domain", domain, domain, suspicious=is_susp)

        # Emails
        for m in EMAIL_RE.finditer(text):
            add("email", m.group().lower(), m.group())

        return entities

    # ── Normalization ─────────────────────────────────────────────────────────

    @staticmethod
    def _normalize_phone(raw: str) -> str:
        """Normalize to E.164-ish Malaysian format."""
        digits = re.sub(r"\D", "", raw)
        if digits.startswith("0"):
            digits = "6" + digits
        elif digits.startswith("1") and len(digits) <= 11:
            digits = "6" + digits
        if not digits.startswith("+"):
            digits = "+" + digits
        return digits

    @staticmethod
    def _is_suspicious_domain(domain: str) -> bool:
        """Check if domain has a suspicious TLD."""
        for tld in SUSPICIOUS_TLDS:
            if domain.endswith(tld):
                return True
        return False

    # ── Scam classification ───────────────────────────────────────────────────

    def classify(self, text: str) -> tuple[str, float, list[str]]:
        """
        Classify scam type based on keywords.
        Returns: (campaign_type, keyword_score, matched_keywords)
        """
        category, score = self.keyword_extractor.top_category(text)
        matches = self.keyword_extractor.extract(text)
        all_keywords = [kw for kws in matches.values() for kw, _ in kws]
        return category, score, all_keywords

    # ── DB write ─────────────────────────────────────────────────────────────

    def write_to_db(self, entity: ExtractedEntity) -> int:
        """Upsert entity and add an edge. Returns entity_id."""
        metadata = {
            "platform": entity.source_platform,
            "channel": entity.source_channel,
            "is_suspicious": entity.is_suspicious,
        }
        eid = self.db.upsert_entity(
            value=entity.value,
            etype=entity.type,
            metadata=metadata,
        )
        self.db.add_entity_edge(
            entity_id=eid,
            channel=entity.source_channel,
            platform=entity.source_platform,
            message_hash=entity.message_hash,
        )
        return eid

    # ── Processing ───────────────────────────────────────────────────────────

    def process_message(self, raw_json: str) -> tuple[int, list[ExtractedEntity]]:
        """
        Extract entities from a single raw message JSON.
        Returns: (entity_count, list of ExtractedEntity)
        """
        try:
            msg = json.loads(raw_json)
        except json.JSONDecodeError:
            log.warning(f"Invalid JSON in queue: {raw_json[:80]}")
            return 0, []

        text = msg.get("text", "")
        if not text.strip():
            return 0, []

        entities = self.extract_from_text(
            text=text,
            platform=msg.get("platform", "unknown"),
            channel=msg.get("channel", "unknown"),
            msg_hash=msg.get("message_hash", ""),
            timestamp=msg.get("timestamp", datetime.now().isoformat()),
        )

        count = 0
        for entity in entities:
            try:
                self.write_to_db(entity)
                count += 1
            except Exception as e:
                log.error(f"DB write failed for {entity.value}: {e}")

        return count, entities

    def process_batch(
        self,
        batch_size: int = BATCH_SIZE,
        write_to_queue: bool = True,
    ) -> dict:
        """
        Pop a batch from the queue and process.
        Returns stats dict.
        """
        extracted = 0
        messages_processed = 0
        entity_types: dict[str, int] = {}
        queued_payloads: list[str] = []

        for _ in range(batch_size):
            raw = self.queue.pop_from_queue("raw_messages")
            if raw is None:
                break

            count, entities = self.process_message(raw)
            if count > 0:
                extracted += count
                messages_processed += 1

                for entity in entities:
                    entity_types[entity.type] = entity_types.get(entity.type, 0) + 1

                if write_to_queue:
                    queued_payloads.extend(entity.to_json() for entity in entities)

        if write_to_queue and queued_payloads:
            self.queue.push_to_queue_batch("extracted_entities", queued_payloads)

        return {
            "messages_processed": messages_processed,
            "entities_extracted": extracted,
            "by_type": entity_types,
            "queue_remaining": self.queue.get_queue_length("raw_messages"),
        }

    # ── Run loop ─────────────────────────────────────────────────────────────

    def run(
        self,
        batch_size: int = BATCH_SIZE,
        max_batches: int = 100,
        write_to_queue: bool = True,
    ) -> dict:
        """
        Process all messages currently in the queue.
        Runs up to max_batches iterations.
        """
        log.info(f"═══ FraudExtractorAgent starting (batch={batch_size}, max={max_batches}) ═══")

        total_extracted = 0
        total_messages = 0
        all_type_counts: dict[str, int] = {}

        for i in range(max_batches):
            result = self.process_batch(batch_size, write_to_queue=write_to_queue)
            extracted = result["entities_extracted"]
            messages = result["messages_processed"]

            if messages == 0:
                log.info("Queue empty — stopping")
                break

            total_extracted += extracted
            total_messages += messages

            for k, v in result["by_type"].items():
                all_type_counts[k] = all_type_counts.get(k, 0) + v

            log.info(
                f"Batch {i+1}: {messages} msgs → {extracted} entities "
                f"(total: {total_extracted} entities from {total_messages} msgs)"
            )

        log.info(f"═══ Extraction complete: {total_extracted} entities from {total_messages} msgs ═══")
        return {
            "total_entities": total_extracted,
            "total_messages": total_messages,
            "by_type": all_type_counts,
        }


# ─── CLI Entry Point ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    agent = FraudExtractorAgent()
    result = agent.run()
    print(json.dumps(result, indent=2))
