"""
RSSCollectorAgent — Polls RSS/Atom feeds for scam-related articles.

Target feeds (all confirmed accessible):
  - Lowyat.NET, The Vocket (Malaysian, tech/viral)
  - Sinar Harian, Astro Awani (Malaysian news, BM)
  - Free Malaysia Today (Malaysian, EN)
  - Scambusters.org (scam-specific, global)
  - Google Alerts (6 Malaysia-focused feeds, via Kem's account)

Pushes to: Redis raw_messages queue
"""

from __future__ import annotations

import asyncio
import feedparser
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

sys_path = str(Path(__file__).parent.parent)
import sys
sys.path.insert(0, sys_path)

from services.queue_handler import QueueHandler
from services.raw_message import RawMessage, stable_message_hash
from db.database import Database

log = logging.getLogger("rss_collector")


# ─── Feed definitions ─────────────────────────────────────────────────────────

FEEDS: list[dict] = [
    # ── Google Alerts (Malaysia-focused, via Kem's account) ──────────────────
    {
        "name": "Google Alerts: Malaysia scam",
        "url": "https://www.google.com/alerts/feeds/02329075624815246977/3981748447557571059",
        "lang": "en",
        "country": "my",
        "keywords": [],
    },
    {
        "name": "Google Alerts: Malaysia scam call",
        "url": "https://www.google.com/alerts/feeds/02329075624815246977/2632013692841336179",
        "lang": "en",
        "country": "my",
        "keywords": [],
    },
    {
        "name": "Google Alerts: Malaysia phishing",
        "url": "https://www.google.com/alerts/feeds/02329075624815246977/7992337569018475671",
        "lang": "en",
        "country": "my",
        "keywords": [],
    },
    {
        "name": "Google Alerts: Malaysia bank fraud",
        "url": "https://www.google.com/alerts/feeds/02329075624815246977/7992337569018476492",
        "lang": "en",
        "country": "my",
        "keywords": [],
    },
    {
        "name": "Google Alerts: Malaysia OTP scam",
        "url": "https://www.google.com/alerts/feeds/02329075624815246977/1540671282108755169",
        "lang": "en",
        "country": "my",
        "keywords": [],
    },
    {
        "name": "Google Alerts: Malaysia investment fraud",
        "url": "https://www.google.com/alerts/feeds/02329075624815246977/1540671282108753333",
        "lang": "en",
        "country": "my",
        "keywords": [],
    },
    # ── Malaysian news RSS ───────────────────────────────────────────────────
    {
        "name": "Lowyat.NET",
        "url": "https://lowyat.net/feed/",
        "lang": "en",
        "country": "my",
        "keywords": ["scam", "fraud", "phishing", "investment", "online scam", "MCMC", "security", "breach", "data leak"],
    },
    {
        "name": "The Vocket",
        "url": "https://thevocket.com/feed/",
        "lang": "ms",
        "country": "my",
        "keywords": ["scam", "fraud", "tipu", "pelaburan", "phishing", "online"],
    },
    {
        "name": "Sinar Harian",
        "url": "https://www.sinarharian.com.my/rss",
        "lang": "ms",
        "country": "my",
        "keywords": ["scam", "fraud", "tipu", "pelaburan", "forex", "crypto", "phishing", "magnetic", "bonus"],
    },
    {
        "name": "Astro Awani",
        "url": "https://www.astroawani.com/rss",
        "lang": "ms",
        "country": "my",
        "keywords": ["scam", "fraud", "tipu", "pelaburan", "forex", "crypto", "phishing", "bank"],
    },
    {
        "name": "Free Malaysia Today",
        "url": "https://www.freemalaysiatoday.com/feed/",
        "lang": "en",
        "country": "my",
        "keywords": ["scam", "fraud", "cheat", "investment", "forex", "crypto", "phishing", "OTP"],
    },
    # ── Scam-specific feeds ─────────────────────────────────────────────────
    {
        "name": "Scambusters.org",
        "url": "https://scambusters.org/feed",
        "lang": "en",
        "country": "global",
        "keywords": ["scam", "fraud", "phishing", "smishing", "spam", "rip off"],
    },
]

# Additional fallback feeds
EXTRA_FEEDS = [
    "https://www.thesun.co.uk/feed/",
    "https://www.bbc.com/news/world-asia-33625350/revision你怎么?format=xml",
]

class RSSCollectorAgent:
    """
    Poll RSS/Atom feeds and push scam-relevant articles to queue.

    Filters by keyword list, extracts entities from article content
    via HTTP fetch of article links.
    """

    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/122.0.0.0 Safari/537.36",
        "Accept": "application/rss+xml, application/atom+xml, "
                  "application/xml, text/xml, */*",
        "Accept-Language": "en-US,en;q=0.9,ms;q=0.8",
    }

    SCAM_KEYWORDS = [
        "scam", "fraud", "cheat", "tipu", "pelaburan", "forex", "crypto",
        "phishing", "smishing", "vishing", "otp", "spam", "rip off",
        "ponzi", "pyramid", "hacked", "malicious", "fake bank",
        "investment scheme", "love scam", "job scam", " Macau scam",
    ]

    def __init__(self, max_articles_per_feed: int = 50, fetch_articles: bool = True):
        self.max_articles = max_articles_per_feed
        self.fetch_articles = fetch_articles
        self.queue = QueueHandler()
        self.db = Database()
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(20.0, connect=8.0),
            headers=self.HEADERS,
            follow_redirects=True,
        )
        self._scam_kw_re = re.compile(
            "|".join(re.escape(k) for k in self.SCAM_KEYWORDS),
            re.IGNORECASE,
        )
        log.info(f"RSSCollectorAgent initialized ({len(FEEDS)} feeds)")

    async def close(self):
        await self.client.aclose()

    @staticmethod
    def _hash(text: str) -> str:
        return stable_message_hash(text)

    def _is_scam_relevant(self, title: str, summary: str = "") -> bool:
        """Return True if text contains any scam keyword."""
        text = f"{title} {summary}".lower()
        return bool(self._scam_kw_re.search(text))

    async def _fetch_feed(self, feed: dict) -> list[dict]:
        """Parse a single RSS/Atom feed, return scam-relevant entries."""
        articles = []
        try:
            resp = await self.client.get(feed["url"], headers=self.HEADERS, timeout=15.0)
            if resp.status_code != 200:
                log.warning(f"[{feed['name']}] HTTP {resp.status_code}: {feed['url']}")
                return []
            resp.raise_for_status()

            parsed = feedparser.parse(resp.text)
            feed_title = parsed.feed.get("title", feed["name"]) if parsed.feed else feed["name"]

            cutoff = datetime.now(timezone.utc) - timedelta(days=7)  # last 7 days only

            for entry in parsed.entries[: self.max_articles]:
                title = entry.get("title", "")
                summary = entry.get("summary", "") or entry.get("description", "") or ""
                # Strip HTML tags from summary
                clean_summary = re.sub(r"<[^>]+>", " ", summary)
                clean_summary = re.sub(r"\s+", " ", clean_summary).strip()[:500]

                link = entry.get("link", "") or ""
                pub_ts = entry.get("published_parsed") or entry.get("updated_parsed")
                if pub_ts:
                    pub_dt = datetime(*pub_ts[:6], tzinfo=timezone.utc)
                else:
                    pub_dt = datetime.now(timezone.utc)

                if pub_dt < cutoff:
                    continue

                # Always include, let entity extraction decide
                articles.append({
                    "feed_name": feed["name"],
                    "feed_url": feed["url"],
                    "feed_lang": feed["lang"],
                    "country": feed["country"],
                    "title": title.strip(),
                    "summary": clean_summary,
                    "link": link,
                    "published": pub_dt.isoformat(),
                    "entry_id": entry.get("id", link),
                })

        except Exception as e:
            log.error(f"[{feed['name']}] Failed: {e}")

        return articles

    async def _fetch_article_content(self, url: str) -> str:
        """Fetch full article text from URL for entity extraction."""
        try:
            resp = await self.client.get(url, headers=self.HEADERS, timeout=15.0)
            if resp.status_code != 200:
                return ""
            resp.raise_for_status()

            from bs4 import BeautifulSoup
            soup = BeautifulSoup(resp.text, "html.parser")

            # Remove scripts, styles, nav, footer
            for tag in soup.find_all(["script", "style", "nav", "footer", "header", "aside"]):
                tag.decompose()

            # Try article body
            article = soup.find("article") or soup.find("div", class_=re.compile("article|content|body", re.I))
            if article:
                text = article.get_text(separator=" ", strip=True)
            else:
                text = soup.get_text(separator=" ", strip=True)

            # Collapse whitespace
            text = re.sub(r"\s+", " ", text).strip()
            return text[:3000]  # cap at 3000 chars

        except Exception:
            return ""

    async def run(self) -> dict:
        """Fetch all feeds, filter scam articles, push to queue."""
        log.info(f"═══ RSSCollectorAgent starting ({len(FEEDS)} feeds) ═══")

        all_articles = []
        feed_results = {}

        for feed in FEEDS:
            log.info(f"Fetching: {feed['name']}...")
            articles = await self._fetch_feed(feed)
            feed_results[feed["name"]] = len(articles)

            for art in articles:
                art["is_scam_keyword"] = self._is_scam_relevant(art["title"], art["summary"])

            all_articles.extend(articles)
            await asyncio.sleep(0.5)  # polite delay

        # Filter: scam-relevant only
        scam_articles = [a for a in all_articles if a["is_scam_keyword"]]
        log.info(f"  Total entries: {len(all_articles)} | Scam-relevant: {len(scam_articles)}")

        # Optionally fetch full article content
        queued = 0
        persisted = 0
        if self.fetch_articles and scam_articles:
            log.info(f"Fetching full article content for {len(scam_articles)} articles...")
            for art in scam_articles:
                if art["link"]:
                    content = await self._fetch_article_content(art["link"])
                    art["full_text"] = content
                    await asyncio.sleep(0.3)
                queued += 1

        # Push to queue
        for art in all_articles:  # push all, extractor filters
            text = f"{art['title']} {art.get('summary','')} {art.get('full_text','')}".strip()

            msg = RawMessage(
                platform="rss",
                channel=art["feed_name"],
                channel_id=art.get("entry_id", ""),
                sender_id=None,
                text=text[:5000],
                member_count=None,
                timestamp=art["published"],
                message_hash=self._hash(text),
                raw_json=json.dumps(art, ensure_ascii=False, default=str),
            )
            if self.db.upsert_scraped_message(msg):
                persisted += 1
            if self.queue.push_to_queue("raw_messages", msg.to_json()):
                queued += 1
            else:
                log.warning("Failed to queue RSS message %s", msg.message_hash)

        q_len = self.queue.get_queue_length("raw_messages")
        log.info(f"═══ Done: {len(all_articles)} articles queued. Queue depth: {q_len} ═══")

        return {
            "feeds_checked": len(FEEDS),
            "feed_results": feed_results,
            "total_articles": len(all_articles),
            "scam_relevant": len(scam_articles),
            "persisted": persisted,
            "queued": queued,
            "queue_depth": q_len,
        }


# ─── CLI ─────────────────────────────────────────────────────────────────────

async def _main():
    agent = RSSCollectorAgent(max_articles_per_feed=50, fetch_articles=True)
    try:
        result = await agent.run()
        return result
    finally:
        await agent.close()


if __name__ == "__main__":
    import json

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    )

    result = asyncio.run(_main())

    print("\n📊 RSS Collection Summary:")
    print(f"   Feeds checked: {result['feeds_checked']}")
    print(f"   Articles total: {result['total_articles']}")
    print(f"   Scam-relevant: {result['scam_relevant']}")
    print(f"   Queued: {result['queued']}")
    print(f"   Queue depth: {result['queue_depth']}")
    print()
    for name, count in result["feed_results"].items():
        print(f"   [{name}] {count} articles")
