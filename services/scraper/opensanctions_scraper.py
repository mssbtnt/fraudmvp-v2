"""
OpenSanctions Scraper — Downloads and parses Malaysia government alert lists
mirrored by OpenSanctions (data.opensanctions.org).

Datasets:
  - BNM Financial Consumer Alert List   (my_consumer_alert_list)
      Source: https://www.bnm.gov.my/financial-consumer-alert-list
      ~1,170 entities of unlicensed financial service providers
  - SC Investor Alert List              (my_investor_alert_list)
      Source: https://www.sc.com.my/investor-alert
      ~1,855 entities of unregistered investment platforms

Updated daily by OpenSanctions.
Format: targets.nested.json — structured entity records with websites, Telegram,
        aliases, registration numbers, and BNM/SC source URLs.

Usage:
    scraper = OpenSanctionsScraper()
    for entity in scraper.get_entities("bnm"):
        print(entity.type, entity.value)
    await scraper.close()
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import httpx
from dotenv import load_dotenv

sys.path.insert(0, str(__file__).rsplit("/services/scraper/", 1)[0])
from services.scraper.web_scraper import WebScraper

load_dotenv()
log = logging.getLogger("opensanctions_scraper")

# ─── OpenSanctions URL patterns ─────────────────────────────────────────────────

# Date-stable URL: the dataset slug doesn't change even if the date does.
# Use latest known working date; files are updated daily at the same path.
_BASE_URL = "https://data.opensanctions.org/datasets/{date}/{dataset}/targets.nested.json"

DATASETS: dict[str, dict] = {
    "bnm": {
        "dataset": "my_consumer_alert_list",
        "name": "BNM Financial Consumer Alert",
        "source_url": "https://www.bnm.gov.my/financial-consumer-alert-list",
        "description": "Unlicensed financial service providers flagged by Bank Negara Malaysia",
        "reliability": 0.95,
    },
    "sc": {
        "dataset": "my_investor_alert_list",
        "name": "SC Investor Alert",
        "source_url": "https://www.sc.com.my/investor-alert",
        "description": "Unregistered investment platforms flagged by Securities Commission Malaysia",
        "reliability": 0.90,
    },
}

# Known legitimate domains found in BNM/SC lists that are NOT scammer infra
LEGIT_DOMAINS: set[str] = {
    "bnm.gov.my", "sc.com.my", "malaysian.gov.my",
    "maybank.com", "cimb.com", "publicbank.com", "rhb.com.my",
    "bankislam.com", "banknegara.gov.my", "asekrt.com",
}

# Telegram words to filter from usernames
BLOCKED_TG_USERNAMES: set[str] = {
    "join", "group", "channel", "chat", "telegram", "bot",
    "official", "support", "admin", "help", "info",
}


# ─── Dataclasses ───────────────────────────────────────────────────────────────

@dataclass
class OpensanctionsEntity:
    """A structured entity extracted from an OpenSanctions record."""
    type: str           # phone, bank_account, domain, url, telegram_channel, company_name
    value: str
    source_dataset: str  # "bnm" or "sc"
    source_url: str      # BNM or SC source page
    record_id: str       # OpenSanctions entity ID
    record_name: str     # Primary name of the entity
    websites: list[str] = field(default_factory=list)
    telegram_channels: list[str] = field(default_factory=list)
    registration_number: Optional[str] = None
    aliases: list[str] = field(default_factory=list)
    first_seen: Optional[str] = None
    last_seen: Optional[str] = None
    is_clone: bool = False   # True if flagged as "potential clone entity"
    raw_context: str = ""


@dataclass
class OpensanctionsResult:
    """Result from scraping a single OpenSanctions dataset."""
    dataset: str              # "bnm" or "sc"
    url: str
    entities: list[OpensanctionsEntity] = field(default_factory=list)
    telegram_channels: list[str] = field(default_factory=list)
    records_parsed: int = 0
    error: Optional[str] = None


# ─── OpenSanctionsScraper ─────────────────────────────────────────────────────

class OpenSanctionsScraper:
    """
    Fetch and parse Malaysia BNM + SC alert lists from OpenSanctions.

    Downloads targets.nested.json for each dataset and extracts:
    - Website URLs and domains
    - Telegram channel @usernames and t.me links
    - Phone numbers
    - Bank account numbers (from notes/registration numbers)
    - Company names with registration numbers (e.g. "Sdn Bhd (123456-W)")

    OpenSanctions blocks direct browser access but allows direct JSON downloads.
    """

    DEFAULT_HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/122.0.0.0 Safari/537.36",
        "Accept": "application/json",
        "Accept-Encoding": "gzip, deflate",
    }

    REQUEST_DELAY = (1.0, 3.0)  # polite delay between retries

    def __init__(self, date: Optional[str] = None):
        """
        Initialize scraper.

        Args:
            date: ISO date string e.g. "20260404". Defaults to yesterday's date.
                  The date doesn't affect which records are returned — OpenSanctions
                  always serves the current dataset at the stable slug path.
        """
        self.date = date or self._yesterday_date()
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(60.0, connect=15.0),
            follow_redirects=True,
            headers=self.DEFAULT_HEADERS,
        )
        self._cache: dict[str, dict] = {}  # dataset → parsed JSON

    def _yesterday_date(self) -> str:
        """Return yesterday's date as YYYYMMDD."""
        from datetime import timedelta
        return (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y%m%d")

    # ── Public API ──────────────────────────────────────────────────────────────

    async def fetch_dataset(self, key: str) -> OpensanctionsResult:
        """
        Fetch and parse one dataset by key ("bnm" or "sc").
        Results are cached on the dataset key.
        """
        if key in self._cache:
            log.info(f"[{key}] Using cached data ({len(self._cache[key])} records)")
            return self._parse_dataset(key, self._cache[key])

        url = _BASE_URL.format(date=self.date, dataset=DATASETS[key]["dataset"])
        log.info(f"[{key}] Fetching {url}")

        try:
            data = await self._fetch_with_retry(url)
            self._cache[key] = data
            return self._parse_dataset(key, data)
        except Exception as e:
            log.error(f"[{key}] Failed to fetch: {e}")
            return OpensanctionsResult(dataset=key, url=url, error=str(e))

    async def fetch_all(self) -> dict[str, OpensanctionsResult]:
        """Fetch both BNM and SC datasets."""
        results = {}
        for key in DATASETS:
            results[key] = await self.fetch_dataset(key)
        return results

    def get_entities(self, key: str) -> list[OpensanctionsEntity]:
        """Return all entities for a dataset (from cache)."""
        return self._cache.get(key, {}).get("entities", [])

    async def close(self):
        await self.client.aclose()

    # ── Fetch with retry ────────────────────────────────────────────────────────

    async def _fetch_with_retry(self, url: str, retries: int = 3) -> dict:
        for attempt in range(retries):
            try:
                await asyncio.sleep(random.uniform(*self.REQUEST_DELAY))
                resp = await self.client.get(url, headers=self.DEFAULT_HEADERS)
                resp.raise_for_status()

                # OpenSanctions returns newline-delimited JSON (NDJSON) —
                # one JSON object per line, not a single JSON array.
                text = resp.text.strip()
                if not text:
                    return {}
                records = []
                for line in text.split("\n"):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
                return {"data": records, "raw_count": len(records)}

            except httpx.HTTPStatusError as e:
                if e.response.status_code == 403:
                    headers = dict(self.DEFAULT_HEADERS)
                    headers["User-Agent"] = (
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/124.0.0.0 Safari/537.36"
                    )
                    resp = await self.client.get(url, headers=headers)
                    resp.raise_for_status()
                    text = resp.text.strip()
                    records = []
                    for line in text.split("\n"):
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            records.append(json.loads(line))
                        except json.JSONDecodeError:
                            continue
                    return {"data": records, "raw_count": len(records)}
                if attempt < retries - 1:
                    await asyncio.sleep(2 ** attempt)
                raise
            except (httpx.TimeoutException, httpx.ConnectError) as e:
                if attempt < retries - 1:
                    await asyncio.sleep(2 ** attempt)
                else:
                    raise

    # ── Parsing ────────────────────────────────────────────────────────────────

    def _parse_dataset(self, key: str, data: dict) -> OpensanctionsResult:
        """Parse the nested JSON into OpensanctionsEntity objects."""
        cfg = DATASETS[key]
        records = data.get("data", data.get("results", []))
        if not records:
            # Try unwrapped structure
            records = data if isinstance(data, list) else []

        entities: list[OpensanctionsEntity] = []
        all_tg: set[str] = set()

        for record in records:
            opensanctions_id = record.get("id", "")
            props = record.get("properties", {}) or {}
            names = props.get("name", []) or []
            if isinstance(names, str):
                names = [names]
            caption = record.get("caption", names[0] if names else opensanctions_id)
            aliases = props.get("aliases", []) or []
            if isinstance(aliases, str):
                aliases = [aliases]

            # Clone detection
            is_clone = any(
                "clone" in str(v).lower()
                for v in [caption] + aliases
            )

            # Registration numbers (e.g. "1234567-W" or "SSCM-2024-0001")
            reg_numbers = self._extract_registration_numbers(caption, aliases, props)

            # Websites
            websites = self._extract_websites(props, caption)

            # Telegram channels
            tg_channels = self._extract_telegram_refs(props)

            # Phone numbers (from notes and all text)
            phones = self._extract_phones_from_props(props)

            # Notes text for context
            notes_list = props.get("notes", []) or []
            if isinstance(notes_list, str):
                notes_list = [notes_list]
            notes_text = " | ".join(str(n) for n in notes_list)

            # Build entity per website URL
            for website in websites:
                domain = self._extract_domain(website)
                if not domain or domain in LEGIT_DOMAINS:
                    continue

                entities.append(OpensanctionsEntity(
                    type="domain",
                    value=domain,
                    source_dataset=key,
                    source_url=cfg["source_url"],
                    record_id=opensanctions_id,
                    record_name=caption,
                    websites=[website],
                    telegram_channels=tg_channels,
                    registration_number=reg_numbers[0] if reg_numbers else None,
                    aliases=aliases,
                    first_seen=record.get("first_seen"),
                    last_seen=record.get("last_seen"),
                    is_clone=is_clone,
                    raw_context=notes_text[:200],
                ))

                # URL entity
                entities.append(OpensanctionsEntity(
                    type="url",
                    value=website,
                    source_dataset=key,
                    source_url=cfg["source_url"],
                    record_id=opensanctions_id,
                    record_name=caption,
                    websites=[website],
                    telegram_channels=tg_channels,
                    registration_number=reg_numbers[0] if reg_numbers else None,
                    aliases=aliases,
                    first_seen=record.get("first_seen"),
                    last_seen=record.get("last_seen"),
                    is_clone=is_clone,
                    raw_context=notes_text[:200],
                ))

            # Telegram channels as entities
            for username in tg_channels:
                all_tg.add(username)
                entities.append(OpensanctionsEntity(
                    type="telegram_channel",
                    value=username,
                    source_dataset=key,
                    source_url=cfg["source_url"],
                    record_id=opensanctions_id,
                    record_name=caption,
                    telegram_channels=tg_channels,
                    registration_number=reg_numbers[0] if reg_numbers else None,
                    aliases=aliases,
                    first_seen=record.get("first_seen"),
                    last_seen=record.get("last_seen"),
                    is_clone=is_clone,
                    raw_context=notes_text[:200],
                ))

            # Phone entities
            for phone in phones:
                entities.append(OpensanctionsEntity(
                    type="phone",
                    value=phone,
                    source_dataset=key,
                    source_url=cfg["source_url"],
                    record_id=opensanctions_id,
                    record_name=caption,
                    telegram_channels=tg_channels,
                    registration_number=reg_numbers[0] if reg_numbers else None,
                    aliases=aliases,
                    first_seen=record.get("first_seen"),
                    last_seen=record.get("last_seen"),
                    is_clone=is_clone,
                    raw_context=notes_text[:200],
                ))

            # Company name entity (for correlation by name)
            if caption and len(caption) > 2 and not caption.startswith("http"):
                entities.append(OpensanctionsEntity(
                    type="company_name",
                    value=caption,
                    source_dataset=key,
                    source_url=cfg["source_url"],
                    record_id=opensanctions_id,
                    record_name=caption,
                    telegram_channels=tg_channels,
                    registration_number=reg_numbers[0] if reg_numbers else None,
                    aliases=aliases,
                    first_seen=record.get("first_seen"),
                    last_seen=record.get("last_seen"),
                    is_clone=is_clone,
                    raw_context=notes_text[:200],
                ))

        # Deduplicate
        seen: set[tuple[str, str]] = set()
        unique_entities: list[OpensanctionsEntity] = []
        for ent in entities:
            key_tuple = (ent.type, ent.value)
            if key_tuple not in seen:
                seen.add(key_tuple)
                unique_entities.append(ent)

        log.info(
            f"[{key}] Parsed {len(records)} records → "
            f"{len(unique_entities)} unique entities, "
            f"{len(all_tg)} TG channels"
        )
        return OpensanctionsResult(
            dataset=key,
            url=_BASE_URL.format(date=self.date, dataset=DATASETS[key]["dataset"]),
            entities=unique_entities,
            telegram_channels=list(all_tg),
            records_parsed=len(records),
        )

    # ── Extraction helpers ─────────────────────────────────────────────────────

    def _extract_websites(self, props: dict, caption: str) -> list[str]:
        """Extract clean website URLs from record properties."""
        raw_urls: list[str] = []
        for field_name in ("website", "websites", "url", "urls"):
            val = props.get(field_name, [])
            if isinstance(val, str):
                raw_urls.append(val)
            elif isinstance(val, list):
                raw_urls.extend(val)

        websites = []
        for url in raw_urls:
            url = str(url).strip()
            if url.startswith("http://") or url.startswith("https://"):
                if any(blocked in url.lower() for blocked in LEGIT_DOMAINS):
                    continue
                websites.append(url.rstrip("/"))

        return websites

    def _extract_telegram_refs(self, props: dict) -> list[str]:
        """Extract Telegram @usernames and t.me links from record properties."""
        refs: set[str] = set()
        text_fields = ["telegram", "telegram_channels", "channel", "contact_info",
                       "notes", "source_url", "description"]

        for field_name in text_fields:
            val = props.get(field_name, [])
            if isinstance(val, str):
                val = [val]
            if not isinstance(val, list):
                continue
            for item in val:
                refs.update(self._parse_telegram_from_text(str(item)))

        return list(refs)

    def _parse_telegram_from_text(self, text: str) -> list[str]:
        """Extract @usernames and t.me/xxx from arbitrary text."""
        refs: list[str] = []

        # t.me/username or t.me/joinchat/xxx
        tg_link_re = re.compile(
            r"t\.me/(?:joinchat/|\+)?([a-zA-Z0-9_]{5,35})", re.IGNORECASE
        )
        for m in tg_link_re.finditer(text):
            username = m.group(1).lower()
            if username not in BLOCKED_TG_USERNAMES and len(username) >= 5:
                refs.append(username)

        # @username
        mention_re = re.compile(r"@([a-zA-Z0-9_]{5,35})")
        for m in mention_re.finditer(text):
            username = m.group(1).lower()
            if username not in BLOCKED_TG_USERNAMES:
                refs.append(username)

        return refs

    def _extract_phones_from_props(self, props: dict) -> list[str]:
        """Extract phone numbers from notes/contact fields."""
        phones: list[str] = []
        phone_re = re.compile(
            r"""
            (?:(?<!\d)[+]?\d{1,3}[-.\s]?)?
            \(?\d{2,4}\)?[-.\s]?\d{3,4}[-.\s]?\d{3,4}
            """,
            re.VERBOSE,
        )
        malaysia_phone_re = re.compile(
            r"""(?:(?<!\d)[+]?6?01[2-9]\d[\s\-]?\d{3,4}[\s\-]?\d{3,4})""",
            re.VERBOSE,
        )

        text_fields = ["notes", "phone", "phones", "contact", "description"]
        for field_name in text_fields:
            val = props.get(field_name, [])
            if isinstance(val, str):
                val = [val]
            if not isinstance(val, list):
                continue
            for item in val:
                for m in malaysia_phone_re.finditer(str(item)):
                    phones.append(self._normalize_phone(m.group()))
                for m in phone_re.finditer(str(item)):
                    phones.append(self._normalize_phone(m.group()))

        return list(set(phones))

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

    def _extract_registration_numbers(self, caption: str, aliases: list, props: dict) -> list[str]:
        """Extract Malaysian company registration numbers (e.g. 1234567-W)."""
        numbers: list[str] = []
        # SSM format: 6-10 digits followed by optional -letter
        ssm_re = re.compile(r"\b(\d{6,10}-[A-Z])\b")
        for text in [caption] + aliases + [str(v) for v in props.values()]:
            for m in ssm_re.finditer(str(text)):
                numbers.append(m.group(1))
        return list(set(numbers))

    @staticmethod
    def _extract_domain(url: str) -> Optional[str]:
        """Extract domain from URL. Skip Telegram web URLs."""
        # Skip Telegram web URLs
        if "t.me" in url or "telegram.me" in url:
            return None
        domain_re = re.compile(r"(?:https?://)?([\w-]+\.[\w-]+(?:\.[\w-]+)?)", re.IGNORECASE)
        match = domain_re.search(url)
        return match.group(1).lower() if match else None


# ─── CLI ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    async def test():
        scraper = OpenSanctionsScraper()
        results = await scraper.fetch_all()

        for key, result in results.items():
            cfg = DATASETS[key]
            print(f"\n=== {cfg['name']} ===")
            print(f"  Records parsed: {result.records_parsed}")
            print(f"  Entities: {len(result.entities)}")
            print(f"  TG channels: {result.telegram_channels}")
            print(f"  Error: {result.error}")

            # Group by type
            by_type: dict[str, int] = {}
            for e in result.entities:
                by_type[e.type] = by_type.get(e.type, 0) + 1
            print(f"  By type: {by_type}")

            # Show samples
            for e in result.entities[:3]:
                print(f"  [{e.type}] {e.value} | clone={e.is_clone} | {e.record_name}")

        await scraper.close()

    asyncio.run(test())
