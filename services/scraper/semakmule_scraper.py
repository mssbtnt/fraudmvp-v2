"""
SemakMuleScraper — PDRM CCID SemakMule API scraper.

Source: https://semakmule.rmp.gov.my (CCID Malaysia)
API:   https://semakmule.rmp.gov.my/api/mule/get_search_data.php

Data:  288,239 scam bank accounts + 227,125 scam phone numbers (as of Apr 2026)
       Official government source, updated daily.

Strategy: Verification lookup — entities extracted from other sources
          are checked against SemakMule to confirm scam association.
          Also fetches top-10 lists and stats for early signal.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

sys_path = str(Path(__file__).parent.parent)
sys.path.insert(0, sys_path)

from services.queue_handler import QueueHandler
from db.database import Database
from services.raw_message import RawMessage, stable_message_hash

log = logging.getLogger("semakmule")

# ─── API config ────────────────────────────────────────────────────────────────

BASE_URL = "https://semakmule.rmp.gov.my"
API_URL = f"{BASE_URL}/api/mule/get_search_data.php"
STATS_URL = f"{BASE_URL}/api/mule/get_homepage_stats"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/122.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Content-Type": "application/json",
    "Referer": f"{BASE_URL}/",
    "Origin": BASE_URL,
}

TLS_V1 = {"tls": False}  # Use --tlsv1.0 workaround (server requires TLS 1.0/1.1)


@dataclass
class MuleAccount:
    """A verified scam bank account or phone number."""
    category: str          # "bank" or "telefon"
    value: str             # account number or phone
    report_count: int      # number of reports
    source: str = "PDRM CCID SemakMule"
    scraped_at: str = ""


@dataclass
class SemakMuleStats:
    total_bank_accounts: int = 0
    total_phone_numbers: int = 0
    total_visitors: int = 0
    today_visitors: int = 0
    total_searches: int = 0
    last_updated: str = ""
    top_banks: list = field(default_factory=list)
    top_phones: list = field(default_factory=list)

    def __post_init__(self):
        if self.top_banks is None:
            self.top_banks = []
        if self.top_phones is None:
            self.top_phones = []


# ─── Scraper ──────────────────────────────────────────────────────────────────

class SemakMuleScraper:
    """
    Scrape PDRM CCID SemakMule for scam bank accounts & phone numbers.

    Uses TLS 1.0 workaround (server doesn't support TLS 1.2+).
    API endpoint: POST /api/mule/get_search_data.php
    Body format:   {"data": {"category": "bank"|"telefon", ...field...: value}}
    """

    CHECK_COOLDOWN_HOURS = int(os.getenv("SEMAKMULE_CHECK_COOLDOWN_HOURS", "24"))
    MAX_RETRIES = int(os.getenv("SEMAKMULE_MAX_RETRIES", "2"))
    BACKOFF_SECONDS = float(os.getenv("SEMAKMULE_BACKOFF_SECONDS", "1.0"))
    HTTP_TIMEOUT_SECONDS = float(os.getenv("SEMAKMULE_HTTP_TIMEOUT_SECONDS", "8"))
    CURL_TIMEOUT_SECONDS = int(float(os.getenv("SEMAKMULE_CURL_TIMEOUT_SECONDS", "8")))
    VERIFY_LIMIT = int(os.getenv("SEMAKMULE_VERIFY_LIMIT", "25"))
    ENABLE_ENTITY_VERIFICATION = os.getenv("SEMAKMULE_VERIFY_RECENT_ENTITIES", "true").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }

    def __init__(self):
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(self.HTTP_TIMEOUT_SECONDS, connect=min(5.0, self.HTTP_TIMEOUT_SECONDS)),
            follow_redirects=True,
        )
        self.queue = QueueHandler()
        self.db = Database()
        log.info("SemakMuleScraper initialized")

    async def close(self):
        await self.client.aclose()

    def _queue_raw_message(self, raw_message: RawMessage) -> bool:
        """Persist then publish a canonical raw message."""
        self.db.upsert_scraped_message(raw_message)
        queued = self.queue.push_to_queue("raw_messages", raw_message.to_json())
        if not queued:
            log.warning(
                "SemakMule could not publish to Redis; message persisted only: %s",
                raw_message.message_hash,
            )
        return queued

    # ── TLS workaround ──────────────────────────────────────────────────────

    async def _post(self, url: str, json_body: dict) -> dict | None:
        """POST with TLS 1.0 fallback."""
        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                resp = await self.client.post(
                    url, json=json_body, headers=HEADERS, timeout=15.0
                )
                if resp.status_code == 200 and resp.text:
                    try:
                        return resp.json()
                    except Exception:
                        log.debug("SemakMule POST returned non-JSON on attempt %s", attempt)
                else:
                    log.warning("SemakMule POST status %s on attempt %s", resp.status_code, attempt)
            except Exception as exc:
                log.warning("SemakMule POST failed on attempt %s: %s", attempt, exc)

            fallback = await self._curl_tls_post(url, json_body)
            if fallback is not None:
                return fallback

            if attempt < self.MAX_RETRIES:
                await asyncio.sleep(self.BACKOFF_SECONDS * attempt)
        return None

    async def _curl_tls_post(self, url: str, json_body: dict) -> dict | None:
        """Use curl with --tlsv1.0 as fallback for servers with weak TLS."""
        import json, subprocess
        data = json.dumps(json_body)
        cmd = [
            "curl", "-s", "--tlsv1.0", "-k",
            "-X", "POST", url,
            "-H", f"Content-Type: application/json",
            "-H", f"Referer: {BASE_URL}/",
            "-H", f"Origin: {BASE_URL}/",
            "-H", f"User-Agent: {HEADERS['User-Agent']}",
            "-H", f"Accept: application/json",
            "-d", data,
        ]
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.CURL_TIMEOUT_SECONDS,
            )
            if result.stdout:
                return json.loads(result.stdout)
        except Exception as e:
            log.debug(f"curl fallback failed: {e}")
        return None

    # ── Stats ───────────────────────────────────────────────────────────────

    async def fetch_stats(self) -> SemakMuleStats | None:
        """Fetch homepage statistics and top-10 lists."""
        data = None
        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                resp = await self.client.get(STATS_URL, headers=HEADERS, timeout=15.0)
                if resp.status_code == 200:
                    data = resp.json()
                    break
                log.warning("SemakMule stats returned HTTP %s on attempt %s", resp.status_code, attempt)
            except Exception as exc:
                log.warning("SemakMule stats fetch failed on attempt %s: %s", attempt, exc)

            try:
                import subprocess

                cmd = [
                    "curl", "-s", "--tlsv1.0", "-k", STATS_URL,
                    "-H", f"User-Agent: {HEADERS['User-Agent']}",
                    "-H", f"Accept: application/json",
                ]
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=self.CURL_TIMEOUT_SECONDS,
                )
                if result.stdout:
                    data = json.loads(result.stdout)
                    break
            except Exception as exc:
                log.debug("SemakMule curl stats fallback failed on attempt %s: %s", attempt, exc)

            if attempt < self.MAX_RETRIES:
                await asyncio.sleep(self.BACKOFF_SECONDS * attempt)

        if data is None:
            log.error("SemakMule stats fetch failed after %s attempts", self.MAX_RETRIES)
            return None

        if data.get("status") != 1:
            return None

        stats = SemakMuleStats(
            total_bank_accounts=int(data.get("data", {}).get("total_rekod_penipu", 0) or 0),
            total_phone_numbers=int(data.get("data", {}).get("total_rekod_telefon_penipu", 0) or 0),
            total_visitors=int(data.get("data", {}).get("pelawat", 0) or 0),
            today_visitors=int(data.get("data", {}).get("pelawat_hari_ini", 0) or 0),
            total_searches=int(data.get("data", {}).get("carian", 0) or 0),
            last_updated=data.get("data", {}).get("last_updated", ""),
            top_banks=data.get("data", {}).get("top10scammers", []),
            top_phones=data.get("data", {}).get("top10telefon", []),
        )
        return stats

    # ── Search ──────────────────────────────────────────────────────────────

    async def _search_batch(self, entries: list[dict]) -> dict[str, int]:
        """
        Check multiple bank accounts OR phone numbers in parallel.
        entries: [{"type": "bank", "value": "512802774281"}, ...]
        Returns {normalized_value: report_count} for confirmed matches.
        """
        if not entries:
            return {}

        # Launch all requests concurrently
        tasks = [self._verify_one(e["type"], e["value"]) for e in entries]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        confirmed: dict[str, int] = {}
        for entry, result in zip(entries, results):
            if isinstance(result, Exception):
                log.debug(f"Semakmule lookup error: {result}")
                continue
            if result is not None:
                # result is (digits, count) tuple
                _, count = result
                confirmed[entry["value"]] = count
        return confirmed

    async def _verify_one(self, category: str, value: str) -> tuple[str, int] | None:
        """Single async lookup, returns (normalized_value, report_count) or None."""
        digits = re.sub(r"\D", "", str(value).strip())
        min_len = 7 if category == "telefon" else 8
        if len(digits) < min_len:
            return None

        if category == "bank":
            body = {"data": {"category": "bank", "bankAccount": digits}}
        else:
            body = {"data": {"category": "telefon", "telNo": digits}}

        result = await self._post(API_URL, body)
        if not result or result.get("status") != 1:
            return None
        table = result.get("table_data", [])
        if not table:
            return None
        return (digits, int(table[0][1]))

    async def search_account(self, account: str) -> MuleAccount | None:
        """Search for a bank account number. Returns MuleAccount if found."""
        result = await self._verify_one("bank", account)
        if result is None:
            return None
        digits, count = result
        return MuleAccount(
            category="bank",
            value=digits,
            report_count=count,
            scraped_at=datetime.now(timezone.utc).isoformat(),
        )

    async def search_phone(self, phone: str) -> MuleAccount | None:
        """Search for a phone number. Returns MuleAccount if found."""
        result = await self._verify_one("telefon", phone)
        if result is None:
            return None
        digits, count = result
        return MuleAccount(
            category="telefon",
            value=digits,
            report_count=count,
            scraped_at=datetime.now(timezone.utc).isoformat(),
        )

    async def verify_entity(self, entity_type: str, value: str) -> MuleAccount | None:
        """
        Verify an entity (phone or bank account) against SemakMule DB.
        Returns MuleAccount if found, None otherwise.
        """
        if entity_type == "phone":
            return await self.search_phone(value)
        elif entity_type in ("bank_account", "bank"):
            return await self.search_account(value)
        return None

    def _entity_due_for_verification(self, entity: dict) -> bool:
        """Skip entities that were checked recently to reduce repeated lookups."""
        metadata_raw = entity.get("metadata")
        if not metadata_raw:
            return True
        try:
            metadata = json.loads(metadata_raw)
        except json.JSONDecodeError:
            return True

        checked_at = metadata.get("semakmule_checked_at")
        if not checked_at:
            return True
        try:
            checked_dt = datetime.fromisoformat(checked_at)
        except ValueError:
            return True

        cutoff = datetime.now(timezone.utc) - timedelta(hours=self.CHECK_COOLDOWN_HOURS)
        return checked_dt <= cutoff

    # ── DB-backed verifier ───────────────────────────────────────────────────

    async def process_entities(self, limit: int | None = None) -> dict:
        """
        Verify recent DB entities instead of competing with the scorer for
        ownership of the extracted_entities queue.
        """
        if not self.ENABLE_ENTITY_VERIFICATION:
            log.info("SemakMule entity verification disabled for this run")
            return {
                "checked": 0,
                "confirmed": 0,
                "by_type": {"bank_account": 0, "phone": 0},
            }

        limit = limit or self.VERIFY_LIMIT
        checked = 0
        confirmed = 0
        confirmed_types = {"bank_account": 0, "phone": 0}
        recent_entities = self.db.get_recent_entities(limit=limit)

        for entity in recent_entities:
            if entity["type"] not in ("phone", "bank_account"):
                continue
            if not self._entity_due_for_verification(entity):
                continue

            value = re.sub(r"\D", "", entity["value"])
            if len(value) < 7:
                continue

            verified = await self.verify_entity(entity["type"], value)
            checked += 1
            metadata_update = {
                "semakmule_checked_at": datetime.now(timezone.utc).isoformat(),
            }

            if verified:
                confirmed += 1
                confirmed_types[entity["type"]] = confirmed_types.get(entity["type"], 0) + 1
                metadata_update.update(
                    {
                        "semakmule_verified": True,
                        "semakmule_report_count": verified.report_count,
                        "semakmule_verified_at": verified.scraped_at,
                    }
                )

                raw_msg = RawMessage(
                    platform="semakmule",
                    channel="PDRM CCID SemakMule",
                    channel_id=None,
                    sender_id=None,
                    text=(
                        f"PDRM CCID SemakMule confirmed scam: "
                        f"{entity['type']}={verified.value} "
                        f"reported {verified.report_count}x"
                    ),
                    member_count=None,
                    timestamp=verified.scraped_at,
                    message_hash=f"semakmule:{entity['id']}:{verified.value}:{verified.report_count}",
                    raw_json=json.dumps(asdict(verified), ensure_ascii=False),
                )
                self._queue_raw_message(raw_msg)

                log.info(
                    f"CONFIRMED SCAM: {verified.category}={verified.value} "
                    f"({verified.report_count} reports)"
                )
            else:
                metadata_update["semakmule_verified"] = False

            self.db.update_entity_metadata(entity["id"], metadata_update)

            if checked % 50 == 0:
                log.info(f"  Checked {checked} entities...")

        return {
            "checked": checked,
            "confirmed": confirmed,
            "by_type": confirmed_types,
        }

    # ── Full run ────────────────────────────────────────────────────────────

    async def run(self) -> dict:
        """
        Full scrape:
        1. Fetch stats
        2. Push top-10 banks + phones to queue
        3. Verify recent DB entities without queue contention
        """
        log.info("═══ SemakMuleScraper starting ═══")

        # Step 1: Stats
        stats = await self.fetch_stats()
        stats_dict = asdict(stats) if stats else {}
        if stats:
            log.info(
                f"Stats: {stats.total_bank_accounts:,} bank accounts, "
                f"{stats.total_phone_numbers:,} phone numbers | "
                f"Updated: {stats.last_updated}"
            )

            # Push top-10 bank accounts
            for bank in stats.top_banks:
                account = bank.get("nombor", "")
                count = int(bank.get("count", 0))
                if account and account != "000" and count > 0:
                    text = f"Top scam bank account: {account} — {count} reports"
                    raw = RawMessage(
                        platform="semakmule",
                        channel="PDRM CCID SemakMule",
                        channel_id="top10_bank",
                        sender_id=None,
                        text=text,
                        member_count=None,
                        timestamp=datetime.now(timezone.utc).isoformat(),
                        message_hash=stable_message_hash(text, fallback_seed=f"top10_bank:{account}:{count}"),
                        raw_json=json.dumps(bank, ensure_ascii=False),
                    )
                    self._queue_raw_message(raw)

            # Push top-10 phones
            for phone in stats.top_phones:
                number = phone.get("nombor", "")
                count = int(phone.get("count", 0))
                if number and count > 0:
                    text = f"Top scam phone number: {number} — {count} reports"
                    raw = RawMessage(
                        platform="semakmule",
                        channel="PDRM CCID SemakMule",
                        channel_id="top10_phone",
                        sender_id=None,
                        text=text,
                        member_count=None,
                        timestamp=datetime.now(timezone.utc).isoformat(),
                        message_hash=stable_message_hash(text, fallback_seed=f"top10_phone:{number}:{count}"),
                        raw_json=json.dumps(phone, ensure_ascii=False),
                    )
                    self._queue_raw_message(raw)

            log.info(f"  Queued top-10 banks + phones")

        # Step 2: Verify recent DB entities
        result = await self.process_entities()

        q_final = self.queue.get_queue_length("raw_messages")
        log.info(
            f"═══ SemakMuleScraper done: checked={result['checked']} "
            f"confirmed={result['confirmed']} queue_depth={q_final} ═══"
        )

        return {
            "stats": stats_dict,
            "verified": result,
            "queue_depth": q_final,
        }


# ─── CLI ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import json

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    )

    scraper = SemakMuleScraper()
    result = asyncio.run(scraper.run())
    asyncio.run(scraper.close())

    print("\n📊 SemakMule Summary:")
    if result["stats"]:
        s = result["stats"]
        print(f"   Bank accounts in DB:  {s.get('total_bank_accounts', '?')}")
        print(f"   Phone numbers in DB: {s.get('total_phone_numbers', '?')}")
        print(f"   Last updated:        {s.get('last_updated', '?')}")
    print(f"   Entities verified:   {result['verified']['checked']}")
    print(f"   Confirmed scams:     {result['verified']['confirmed']}")
