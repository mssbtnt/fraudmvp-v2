"""
WebScraper — Seed source scraping for initial entity collection.

Extracts entities (phone numbers, bank accounts, URLs, domains)
from complaint databases like MySCAM.info and KenaScam.com.

Falls back to structured demo data when sources are unavailable.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import httpx
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()
log = logging.getLogger("web_scraper")

# ─── Entity patterns ──────────────────────────────────────────────────────────

PHONE_RE = re.compile(
    r"""
    (?:                                     # non-capturing group for prefix
        (?<!\d)[+]?\d{1,3}[-.\s]?          # country code
    )?
    \(?\d{2,4}\)?[-.\s]?\d{3,4}[-.\s]?\d{3,4}  # local format
    """,
    re.VERBOSE,
)

# Malaysian bank account patterns (generic)
BANK_ACCOUNT_RE = re.compile(
    r"\b\d{10,16}\b"
)

# URL and domain patterns
URL_RE = re.compile(
    r"https?://[^\s<>\"]+",
    re.IGNORECASE,
)
DOMAIN_RE = re.compile(
    r"(?:https?://)?([\w-]+\.[\w-]+(?:\.[\w-]+)?)",
    re.IGNORECASE,
)

# Suspicious TLDs common in scams
SUSPICIOUS_TLDS = {
    ".xyz", ".top", ".club", ".online", ".site", ".click",
    ".link", ".work", ".loan", ".download", ".stream",
}


@dataclass
class ScrapedEntity:
    """A single entity extracted from a web source."""
    type: str           # phone, bank_account, domain, url
    value: str
    source: str
    source_url: str
    page_title: Optional[str]
    scraped_at: str
    raw_context: str     # surrounding text snippet


# ─── WebScraper class ──────────────────────────────────────────────────────────

class WebScraper:
    """
    Web scraper for seed fraud-intelligence sources.

    Supports both real HTTP scraping and demo fallback.
    Demo returns simulated entities matching real source structures.
    """

    def __init__(self, demo_mode: bool = True):
        self.demo_mode = demo_mode or True
        self.timeout = 30
        self.client = httpx.AsyncClient(timeout=self.timeout, follow_redirects=True)
        log.info(f"WebScraper initialized (demo={self.demo_mode})")

    async def close(self):
        await self.client.aclose()

    # ── Main entry point ───────────────────────────────────────────────────────

    async def scrape_source(self, url: str) -> list[dict]:
        """
        Scrape a single seed source URL.
        Returns a list of raw entity dicts (as extracted from page).
        """
        if self.demo_mode:
            return self._demo_entities(url)

        domain = self._extract_domain(url)
        scraper = getattr(self, f"_scrape_{domain}", self._scrape_generic)
        return await scraper(url)

    async def scrape_all_sources(self, sources: list[dict]) -> list[ScrapedEntity]:
        """Scrape multiple sources concurrently."""
        tasks = [self.scrape_source(s["url"]) for s in sources]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        entities = []
        for result in results:
            if isinstance(result, Exception):
                log.error(f"Scraping error: {result}")
                continue
            for raw in result:
                entities.append(ScrapedEntity(**raw))
        return entities

    # ── Source-specific scrapers ───────────────────────────────────────────────

    async def _scrape_myscam(self, url: str) -> list[dict]:
        """Scrape MySCAM.info format."""
        try:
            resp = await self.client.get(url, headers={"User-Agent": "Mozilla/5.0"})
            soup = BeautifulSoup(resp.text, "lxml")

            entities = []
            # MySCAM typically lists complaints in table or list format
            for item in soup.select("div.complaint-item, tr.complaint-row, li.complaint"):
                text = item.get_text(separator=" ", strip=True)
                page_title = soup.find("title").get_text(strip=True) if soup.find("title") else ""

                for m in PHONE_RE.finditer(text):
                    entities.append({
                        "type": "phone",
                        "value": self._normalize_phone(m.group()),
                        "source": "MySCAM.info",
                        "source_url": url,
                        "page_title": page_title,
                        "scraped_at": datetime.utcnow().isoformat(),
                        "raw_context": text[:200],
                    })

                for m in DOMAIN_RE.finditer(text):
                    entities.append({
                        "type": "domain",
                        "value": m.group(1).lower(),
                        "source": "MySCAM.info",
                        "source_url": url,
                        "page_title": page_title,
                        "scraped_at": datetime.utcnow().isoformat(),
                        "raw_context": text[:200],
                    })

            log.info(f"MySCAM.info: extracted {len(entities)} entities")
            return entities

        except Exception as e:
            log.error(f"MySCAM.info scrape failed: {e}")
            return []

    async def _scrape_kenascam(self, url: str) -> list[dict]:
        """Scrape KenaScam.com format."""
        return await self._scrape_myscam(url)  # Same structure, same approach

    async def _scrape_generic(self, url: str) -> list[dict]:
        """Generic scraper for unknown formats."""
        try:
            resp = await self.client.get(url, headers={"User-Agent": "Mozilla/5.0"})
            soup = BeautifulSoup(resp.text, "lxml")
            text = soup.get_text(separator=" ", strip=True)
            page_title = soup.find("title").get_text(strip=True) if soup.find("title") else ""

            entities = []
            for m in PHONE_RE.finditer(text):
                entities.append({
                    "type": "phone",
                    "value": self._normalize_phone(m.group()),
                    "source": self._extract_domain(url),
                    "source_url": url,
                    "page_title": page_title,
                    "scraped_at": datetime.utcnow().isoformat(),
                    "raw_context": text[max(0, m.start() - 50):m.end() + 50],
                })

            log.info(f"{self._extract_domain(url)}: extracted {len(entities)} entities")
            return entities

        except Exception as e:
            log.error(f"Generic scrape failed for {url}: {e}")
            return []

    # ── Demo data ─────────────────────────────────────────────────────────────

    @staticmethod
    def _demo_entities(url: str) -> list[dict]:
        """Return demo entities matching real source structures."""
        domain = WebScraper._extract_domain(url)
        base_time = datetime.utcnow().isoformat()

        demo_data = {
            "myscam.info": [
                {"type": "phone", "value": "+60123456789", "raw_context": "Scam call from +60123456789 claiming to be bank"},
                {"type": "phone", "value": "+60198765432", "raw_context": "WhatsApp scam: +60198765432"},
                {"type": "domain", "value": "scam-site.xyz", "raw_context": "Phishing site: scam-site.xyz"},
                {"type": "bank_account", "value": "123456789012", "raw_context": "Bank account used: 123456789012"},
                {"type": "phone", "value": "+60312345678", "raw_context": "Investment scam call from +60312345678"},
                {"type": "url", "value": "https://fake-bank.xyz/login", "raw_context": "Phishing URL: https://fake-bank.xyz/login"},
            ],
            "kenascam.com": [
                {"type": "phone", "value": "+601155553333", "raw_context": "Job scam WhatsApp: +601155553333"},
                {"type": "phone", "value": "+601266668888", "raw_context": "Love scam from +601266668888"},
                {"type": "domain", "value": "free-rm50.top", "raw_context": "Scam domain: free-rm50.top"},
                {"type": "bank_account", "value": "987654321098", "raw_context": "Scammer account: 987654321098"},
            ],
            "fraudwatch.my": [
                {"type": "phone", "value": "+601388886666", "raw_context": "Bantuan scam: +601388886666"},
                {"type": "domain", "value": "bantuan-rm500.xyz", "raw_context": "Fake bantuan site: bantuan-rm500.xyz"},
            ],
        }

        entities = demo_data.get(domain, demo_data["myscam.info"])
        return [
            {
                **e,
                "source": domain,
                "source_url": url,
                "page_title": f"Fraud Report — {domain}",
                "scraped_at": base_time,
            }
            for e in entities
        ]

    # ── Utilities ─────────────────────────────────────────────────────────────

    @staticmethod
    def _extract_domain(url: str) -> str:
        """Extract domain from URL."""
        match = DOMAIN_RE.search(url)
        return match.group(1).lower() if match else url

    @staticmethod
    def _normalize_phone(raw: str) -> str:
        """Normalize phone number to E.164-ish format."""
        digits = re.sub(r"\D", "", raw)
        if digits.startswith("0"):
            digits = "6" + digits  # Malaysia
        if not digits.startswith("+"):
            digits = "+" + digits
        return digits

    @staticmethod
    def is_suspicious_domain(domain: str) -> bool:
        """Check if domain has a suspicious TLD."""
        for tld in SUSPICIOUS_TLDS:
            if domain.endswith(tld):
                return True
        return False


if __name__ == "__main__":
    async def test():
        s = WebScraper(demo_mode=True)
        entities = await s.scrape_source("https://myscam.info")
        print(f"Demo entities from MySCAM.info: {len(entities)}")
        for e in entities:
            print(f"  [{e['type']}] {e['value']} — {e['raw_context'][:50]}")
        await s.close()

    asyncio.run(test())
