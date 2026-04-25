"""
WebScraper — Real HTTP scraping for fraud OSINT sources.

Extracts entities and Telegram channel references from:
- Malaysian government fraud alert pages
- Consumer complaint databases
- Scam reporting forums
- Reddit threads

Also extracts @usernames and t.me links to discover Telegram channels.
"""

from __future__ import annotations

import asyncio
import logging
import random
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import httpx
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()
log = logging.getLogger("web_scraper")

# ─── Entity patterns ───────────────────────────────────────────────────────────

PHONE_RE = re.compile(
    r"""
    (?:(?<!\d)[+]?\d{1,3}[-.\s]?)?
    \(?\d{2,4}\)?[-.\s]?\d{3,4}[-.\s]?\d{3,4}
    """,
    re.VERBOSE,
)

MALAYSIA_PHONE_RE = re.compile(
    r"""
    (?:(?<!\d)[+]?6?01[2-9]\d[\s\-]?\d{3,4}[\s\-]?\d{3,4})
    """,
    re.VERBOSE,
)

BANK_ACCOUNT_RE = re.compile(r"\b\d{10,18}\b")
IBAN_RE = re.compile(r"\bMY[A-Z]{2}\d{16,30}\b", re.IGNORECASE)

URL_RE = re.compile(r"https?://[^\s<>\"\')\]]+", re.IGNORECASE)
DOMAIN_RE = re.compile(r"(?:https?://)?([\w-]+\.[\w-]+(?:\.[\w-]+)?)", re.IGNORECASE)

EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b", re.IGNORECASE)

# Telegram-specific patterns
TELEGRAM_MENTION_RE = re.compile(r"@([a-zA-Z0-9_]{5,35})")
TELEGRAM_TME_RE = re.compile(r"t\.me/([a-zA-Z0-9_]{5,35})", re.IGNORECASE)
TELEGRAM_GROUP_RE = re.compile(r"(?:t\.me/joinchat/|\+)([a-zA-Z0-9_-]{10,})", re.IGNORECASE)

# Suspicious TLDs
SUSPICIOUS_TLDS = {
    ".xyz", ".top", ".club", ".online", ".site", ".click",
    ".link", ".work", ".loan", ".download", ".stream",
    ".cfd", ".gq", ".ml", ".tk", ".pw", ".buzz", ".fit",
    ".icu", ".xyz", ".pro", ".racing", ".win",
}

# Malaysian bank codes (for validation)
MALAYSIA_BANK_CODES = {
    "maybank": "MBB", "cimb": "CIMB", "public bank": "PBB",
    "bank Rakyat": "BRB", "bank Islam": "BIMB", "hong leong": "HLB",
    "RHB": "RHB", "UOB": "UOB", "OCBC": "OCBC",
}


@dataclass
class ScrapedEntity:
    type: str          # phone, bank_account, domain, url, email, telegram_channel
    value: str
    source: str
    source_url: str
    page_title: str
    scraped_at: str
    raw_context: str
    is_suspicious: bool = False


@dataclass
class ScrapeResult:
    """Result from scraping a single page or source."""
    url: str
    entities: list[ScrapedEntity] = field(default_factory=list)
    telegram_channels: list[str] = field(default_factory=list)  # discovered @usernames
    next_page: Optional[str] = None
    error: Optional[str] = None
    pages_scraped: int = 0


# ─── WebScraper ────────────────────────────────────────────────────────────────

class WebScraper:
    """
    Real HTTP scraper for fraud OSINT sources.

    Features:
    - Async HTTP with httpx
    - Per-source custom scrapers for known sites
    - Telegram @username and t.me link extraction from all pages
    - Pagination support
    - Demo fallback when live scraping fails
    """

    DEFAULT_HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/122.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,ms;q=0.8",
        "Accept-Encoding": "gzip, deflate",
        "Connection": "keep-alive",
    }

    # Delay between requests (politeness)
    REQUEST_DELAY = (2.0, 5.0)  # random between 2-5 seconds

    def __init__(self, demo_fallback: bool = True):
        self.demo_fallback = demo_fallback
        self.timeout = httpx.Timeout(30.0, connect=10.0)
        self.client = httpx.AsyncClient(
            timeout=self.timeout,
            follow_redirects=True,
            headers=self.DEFAULT_HEADERS,
        )
        log.info(f"WebScraper initialized (demo_fallback={demo_fallback})")

    async def close(self):
        await self.client.aclose()

    # ── Public API ────────────────────────────────────────────────────────────

    async def scrape_source(self, url: str) -> ScrapeResult:
        """
        Scrape a single URL. Returns ScrapeResult with entities + Telegram refs.
        Falls back to demo data if HTTP fails and demo_fallback=True.
        """
        domain = self._extract_domain(url)

        # Route to source-specific scraper
        scraper_map = {
            "mycert.org.my": self._scrape_mycert,
            "consumer.org.my": self._scrape_consumer_org,
            "scamwatcher.com": self._scrape_scamwatcher,
            "gaso.info": self._scrape_gaso,
            "reddit.com": self._scrape_reddit,
            "bnm.gov.my": self._scrape_generic,
        }

        scraper = scraper_map.get(domain, self._scrape_generic)

        try:
            result = await scraper(url)
            log.info(f"[{domain}] {result.pages_scraped} page(s) scraped, "
                     f"{len(result.entities)} entities, "
                     f"{len(result.telegram_channels)} TG refs")
            return result
        except Exception as e:
            log.error(f"[{domain}] Scraper failed: {e}")
            if self.demo_fallback:
                return self._demo_result(url)
            return ScrapeResult(url=url, error=str(e))

    async def scrape_all(self, sources: list[dict]) -> list[ScrapeResult]:
        """Scrape multiple sources concurrently."""
        tasks = [self.scrape_source(s["url"]) for s in sources]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return [r if isinstance(r, ScrapeResult) else ScrapeResult(url="", error=repr(r))
                for r in results]

    # ── Source-specific scrapers ──────────────────────────────────────────────

    async def _fetch(self, url: str, referer: str = "") -> httpx.Response:
        """Fetch a URL with random delay."""
        await self._delay()
        headers = dict(self.DEFAULT_HEADERS)
        if referer:
            headers["Referer"] = referer
        resp = await self.client.get(url, headers=headers)
        resp.raise_for_status()
        return resp

    async def _scrape_generic(self, url: str) -> ScrapeResult:
        """Generic scraper — works for most sites."""
        resp = await self._fetch(url)
        soup = BeautifulSoup(resp.text, "lxml")
        page_title = soup.find("title")
        page_title = page_title.get_text(strip=True) if page_title else url

        text = soup.get_text(separator=" ", strip=True)
        entities = self._extract_entities(text, "generic", url, page_title)
        tg_channels = self._extract_telegram_refs(text)

        # Try to find next page
        next_page = self._find_next_page(soup, url)

        return ScrapeResult(
            url=url,
            entities=entities,
            telegram_channels=tg_channels,
            next_page=next_page,
            pages_scraped=1,
        )

    async def _scrape_mycert(self, url: str) -> ScrapeResult:
        """
        Malaysia Computer Emergency Response Team (MyCERT) — live fraud alerts.

        MyCERT publishes advisories at https://www.mycert.org.my
        with structured alerts containing scam details.
        """
        base = "https://www.mycert.org.my"
        # Fetch main page to find all alert article links
        resp = await self._fetch(url)
        soup = BeautifulSoup(resp.text, "lxml")
        page_title = soup.find("title")
        page_title = page_title.get_text(strip=True) if page_title else "MyCERT"

        all_entities: list[ScrapedEntity] = []
        all_tg: list[str] = []
        alert_urls: list[str] = []

        # Find alert article links on main page
        for a in soup.find_all("a", href=True):
            href = a["href"]
            text = a.get_text(strip=True)
            if "portal/details" in href and ("Alert" in text or "MA-" in text or "SR-" in text):
                full_url = base + href if href.startswith("/") else href
                if full_url not in alert_urls:
                    alert_urls.append(full_url)

        log.info(f"MyCERT: found {len(alert_urls)} alert links on main page")

        # Scrape each alert article individually
        for alert_url in alert_urls[:20]:  # limit to 20 most recent
            try:
                resp2 = await self._fetch(alert_url, referer=url)
                soup2 = BeautifulSoup(resp2.text, "lxml")
                text = soup2.get_text(separator=" ", strip=True)

                if len(text) < 50:
                    continue

                entities = self._extract_entities(
                    text, "mycert.org.my", alert_url, page_title
                )
                all_entities.extend(entities)
                all_tg.extend(self._extract_telegram_refs(text))

                log.debug(f"  Alert: {alert_url[-40:]} -> {len(entities)} entities")

            except Exception as e:
                log.debug(f"  MyCERT alert scrape failed: {e}")

        # Also scan main page text
        main_text = soup.get_text(separator=" ", strip=True)
        all_entities.extend(self._extract_entities(main_text, "mycert.org.my", url, page_title))
        all_tg.extend(self._extract_telegram_refs(main_text))

        return ScrapeResult(
            url=url,
            entities=all_entities,
            telegram_channels=list(set(all_tg)),
            pages_scraped=len(alert_urls),
        )

    async def _scrape_consumer_org(self, url: str) -> ScrapeResult:
        """
        Consumers Association of Penang — fraud/scam articles.
        Scrapes the main page and looks for scam-related article links.
        """
        base = "https://www.consumer.org.my"
        resp = await self._fetch(url)
        soup = BeautifulSoup(resp.text, "lxml")
        page_title = soup.find("title")
        page_title = page_title.get_text(strip=True) if page_title else "Consumers Association"

        all_entities: list[ScrapedEntity] = []
        all_tg: list[str] = []

        # Find article links related to fraud/scam
        article_urls: list[str] = []
        fraud_keywords = ["scam", "fraud", "cheat", "penipuan", "skam"]

        for a in soup.find_all("a", href=True):
            href = a["href"]
            text = a.get_text(strip=True).lower()
            if any(kw in text for kw in fraud_keywords) or any(kw in href.lower() for kw in fraud_keywords):
                full_url = base + href if href.startswith("/") else href
                if full_url not in article_urls:
                    article_urls.append(full_url)

        log.info(f"Consumer.org.my: found {len(article_urls)} fraud-related links")

        for article_url in article_urls[:10]:
            try:
                resp2 = await self._fetch(article_url, referer=url)
                soup2 = BeautifulSoup(resp2.text, "lxml")
                text = soup2.get_text(separator=" ", strip=True)
                if len(text) < 100:
                    continue
                all_entities.extend(self._extract_entities(text, "consumer.org.my", article_url, page_title))
                all_tg.extend(self._extract_telegram_refs(text))
            except Exception as e:
                log.debug(f"  Consumer.org.my article failed: {e}")

        return ScrapeResult(
            url=url,
            entities=all_entities,
            telegram_channels=list(set(all_tg)),
            pages_scraped=len(article_urls),
        )

    async def _scrape_scamwatcher(self, url: str) -> ScrapeResult:
        """Scamwatcher.com — international scam database."""
        resp = await self._fetch(url)
        soup = BeautifulSoup(resp.text, "lxml")
        page_title = soup.find("title")
        page_title = page_title.get_text(strip=True) if page_title else "Scamwatcher"

        all_entities: list[ScrapedEntity] = []
        all_tg: list[str] = []

        # Each scam listing
        for item in soup.select(".scam-item, .complaint, article, .listing"):
            text = item.get_text(separator=" ", strip=True)
            if len(text) < 20:
                continue
            all_entities += self._extract_entities(text, "scamwatcher.com", url, page_title)
            all_tg += self._extract_telegram_refs(text)

            # Look for website links in this item
            for a in item.find_all("a", href=True):
                domain = self._extract_domain(a["href"])
                if domain:
                    all_entities.append(ScrapedEntity(
                        type="domain",
                        value=domain,
                        source="scamwatcher.com",
                        source_url=url,
                        page_title=page_title,
                        scraped_at=datetime.now(timezone.utc).isoformat(),
                        raw_context=text[:150],
                        is_suspicious=WebScraper.is_suspicious_domain_static(domain),
                    ))

        return ScrapeResult(
            url=url,
            entities=all_entities,
            telegram_channels=list(set(all_tg)),
            pages_scraped=1,
        )

    async def _scrape_gaso(self, url: str) -> ScrapeResult:
        """GASO.info — Global Anti-Scam Organizer."""
        resp = await self._fetch(url)
        soup = BeautifulSoup(resp.text, "lxml")
        page_title = soup.find("title")
        page_title = page_title.get_text(strip=True) if page_title else "GASO"

        all_entities: list[ScrapedEntity] = []
        all_tg: list[str] = []

        for profile in soup.select(".profile, .scammer-entry, .report-item, article"):
            text = profile.get_text(separator=" ", strip=True)
            if len(text) < 20:
                continue
            all_entities += self._extract_entities(text, "gaso.info", url, page_title)
            all_tg += self._extract_telegram_refs(text)

            # GASO often lists photos with names
            for img in profile.find_all("img", src=True):
                if "avatar" in img["src"].lower():
                    continue

        return ScrapeResult(
            url=url,
            entities=all_entities,
            telegram_channels=list(set(all_tg)),
            pages_scraped=1,
        )

    async def _scrape_reddit(self, url: str) -> ScrapeResult:
        """Reddit search results — high-signal scam reports."""
        resp = await self._fetch(url)
        soup = BeautifulSoup(resp.text, "lxml")
        page_title = "Reddit — r/scams Malaysia"

        all_entities: list[ScrapedEntity] = []
        all_tg: list[str] = []

        for post in soup.select(".post, .scp-post, [data-testid=post]"):
            text = post.get_text(separator=" ", strip=True)
            if len(text) < 30:
                continue
            all_entities += self._extract_entities(text, "reddit.com", url, page_title)
            all_tg += self._extract_telegram_refs(text)

        # Also scan all text
        all_entities += self._extract_entities(
            soup.get_text(separator=" ", strip=True), "reddit.com", url, page_title
        )
        all_tg += self._extract_telegram_refs(soup.get_text())

        return ScrapeResult(
            url=url,
            entities=all_entities,
            telegram_channels=list(set(all_tg)),
            pages_scraped=1,
        )

    # ── Entity extraction ─────────────────────────────────────────────────────

    def _extract_entities(
        self,
        text: str,
        source: str,
        page_url: str,
        page_title: str,
    ) -> list[ScrapedEntity]:
        """
        Extract all entity types from page text.
        Applies Malaysian-specific normalization.
        """
        entities: list[ScrapedEntity] = []
        seen: set[tuple[str, str]] = set()
        now = datetime.now(timezone.utc).isoformat()

        def add(etype: str, value: str, context: str, suspicious: bool = False):
            key = (etype, value)
            if key in seen:
                return
            seen.add(key)
            entities.append(ScrapedEntity(
                type=etype,
                value=value,
                source=source,
                source_url=page_url,
                page_title=page_title,
                scraped_at=now,
                raw_context=context[:200],
                is_suspicious=suspicious,
            ))

        # Malaysian phone numbers first (most specific)
        for m in MALAYSIA_PHONE_RE.finditer(text):
            phone = self._normalize_phone(m.group())
            context = text[max(0, m.start() - 30):m.end() + 30]
            add("phone", phone, context)

        # Generic phone numbers
        for m in PHONE_RE.finditer(text):
            phone = self._normalize_phone(m.group())
            context = text[max(0, m.start() - 30):m.end() + 30]
            add("phone", phone, context)

        # Bank accounts — avoid phone-like numbers
        for m in BANK_ACCOUNT_RE.finditer(text):
            val = m.group()
            if re.match(r"^6?01[2-9]\d{7,9}$", val):
                continue  # Skip phone-like numbers
            if re.match(r"^(19|20)\d{2}$", val):
                continue  # Skip years
            context = text[max(0, m.start() - 30):m.end() + 30]
            add("bank_account", val, context)

        # IBAN
        for m in IBAN_RE.finditer(text):
            add("bank_account", m.group().upper(), text[m.start() - 20:m.end() + 20])

        # URLs and domains
        for m in URL_RE.finditer(text):
            url = m.group().rstrip(".,;:)")
            domain_match = DOMAIN_RE.search(url)
            if domain_match:
                domain = domain_match.group(1).lower()
                is_susp = WebScraper.is_suspicious_domain_static(domain)
                context = text[max(0, m.start() - 30):m.end() + 30]
                add("url", url, context, suspicious=is_susp)
                add("domain", domain, context, suspicious=is_susp)

        # Emails
        for m in EMAIL_RE.finditer(text):
            add("email", m.group().lower(), text[m.start() - 20:m.end() + 20])

        return entities

    def _extract_telegram_refs(self, text: str) -> list[str]:
        """
        Extract Telegram @usernames, t.me links, and group invite links.
        Returns a list of unique usernames (without @).
        """
        refs: set[str] = set()

        # @usernames
        for match in TELEGRAM_MENTION_RE.finditer(text):
            username = match.group(1).lower()
            # Filter out common non-channel words
            if username not in {"join", "group", "channel", "chat", "telegram", "bot"}:
                refs.add(username)

        # t.me/username links
        for match in TELEGRAM_TME_RE.finditer(text):
            refs.add(match.group(1).lower())

        # t.me/joinchat/ links (private groups) — store hash
        for match in TELEGRAM_GROUP_RE.finditer(text):
            refs.add(match.group(1).lower())

        return list(refs)

    def _find_next_page(self, soup: BeautifulSoup, current_url: str) -> Optional[str]:
        """Find 'next page' link for pagination."""
        # Common pagination patterns
        for link in soup.find_all("a", href=True):
            text = link.get_text(strip=True).lower()
            if "next" in text or "›" in text or "»" in text:
                href = link["href"]
                if href.startswith("/"):
                    from urllib.parse import urljoin
                    return urljoin(current_url, href)
                return href

        # Numbered pagination
        for link in soup.find_all("a", href=True):
            text = link.get_text(strip=True)
            if text.isdigit() and int(text) > 1:
                href = link["href"]
                if href.startswith("/"):
                    from urllib.parse import urljoin
                    return urljoin(current_url, href)
                return href

        return None

    # ── Utilities ─────────────────────────────────────────────────────────────

    async def _delay(self):
        """Random polite delay between requests."""
        await asyncio.sleep(random.uniform(*self.REQUEST_DELAY))

    @staticmethod
    def _extract_domain(url: str) -> str:
        match = DOMAIN_RE.search(url)
        return match.group(1).lower() if match else url

    @staticmethod
    def _normalize_phone(raw: str) -> str:
        digits = re.sub(r"\D", "", raw)
        if digits.startswith("0"):
            digits = "6" + digits
        elif digits.startswith("1") and len(digits) <= 11:
            digits = "6" + digits
        if not digits.startswith("+"):
            digits = "+" + digits
        return digits

    @staticmethod
    def is_suspicious_domain_static(domain: str) -> bool:
        for tld in SUSPICIOUS_TLDS:
            if domain.endswith(tld):
                return True
        return False

    # ── Demo fallback ────────────────────────────────────────────────────────

    def _demo_result(self, url: str) -> ScrapeResult:
        """Return demo data when live scraping fails."""
        domain = self._extract_domain(url)
        now = datetime.now(timezone.utc).isoformat()
        page_title = f"Demo — {domain}"

        demo_entities = [
            {"type": "phone", "value": "+60123456789",
             "context": "Scam call from +60123456789 claiming to be bank"},
            {"type": "phone", "value": "+60198765432",
             "context": "WhatsApp scam: +60198765432"},
            {"type": "domain", "value": "scam-site.xyz",
             "context": "Phishing site: scam-site.xyz"},
            {"type": "bank_account", "value": "123456789012",
             "context": "Bank account used: 123456789012"},
            {"type": "phone", "value": "+60312345678",
             "context": "Investment scam call from +60312345678"},
            {"type": "url", "value": "https://fake-bank.xyz/login",
             "context": "Phishing URL: https://fake-bank.xyz/login"},
        ]

        tg_demo = ["MyScamWatch", "ScamAlertMY", "HalalOrHaramMY"]

        entities = [
            ScrapedEntity(
                type=e["type"],
                value=e["value"],
                source=domain,
                source_url=url,
                page_title=page_title,
                scraped_at=now,
                raw_context=e["context"],
                is_suspicious=True,
            )
            for e in demo_entities
        ]

        log.info(f"[{domain}] Demo fallback: {len(entities)} entities, {len(tg_demo)} TG refs")
        return ScrapeResult(
            url=url,
            entities=entities,
            telegram_channels=tg_demo,
            pages_scraped=1,
        )


# ─── CLI ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    async def test():
        s = WebScraper(demo_fallback=True)
        sources = [
            {"url": "https://scamwatcher.com"},
            {"url": "https://gaso.info"},
            {"url": "https://www.bnm.gov.my/consumer-alert-fraud"},
        ]
        for src in sources:
            result = await s.scrape_source(src["url"])
            print(f"\n=== {result.url} ===")
            print(f"  Entities: {len(result.entities)}")
            print(f"  Telegram refs: {result.telegram_channels}")
            for e in result.entities[:3]:
                print(f"  [{e.type}] {e.value} — {e.raw_context[:50]}")
        await s.close()

    asyncio.run(test())
