"""
RedditScraper — supplementary source for scam trend intelligence.

Scrapes r/malaysia using Playwright (Firefox) with keyword search.
This source is intentionally research-only:
- it writes local artifacts under data/
- it does not write pipeline raw messages
- it does not participate in extraction, scoring, or alerting

Use it for:
- emerging scam pattern detection
- scam type trend analysis
- contextual intelligence from community discussion
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import yaml

log = logging.getLogger("reddit_scraper")

PROJECT_ROOT = Path(__file__).parent.parent.parent
CONFIG_PATH = PROJECT_ROOT / "config" / "sources.yaml"
DATA_DIR = PROJECT_ROOT / "data"
SESSION_PATH = DATA_DIR / "reddit_session.json"
OUTPUT_PATH = DATA_DIR / "reddit_malaysia_scams.json"

# Regex patterns for entity extraction
PHONE_RE = re.compile(r"(?:\+?6?01[0-9]\s*[-]?\s*[0-9]{3,4}\s*[-]?\s*[0-9]{4})", re.IGNORECASE)
BANK_RE = re.compile(r"\b(\d{10,16})\b")
WA_RE = re.compile(r"(?:wa\.me/|whatsapp\.com/send\?phone=|wasap\.my/)(\d+)", re.IGNORECASE)
URL_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)

# Scam keyword patterns for relevance scoring
SCAM_KEYWORDS = [
    "scam", "penipu", "tipu", "fraud", "phishing", "macau scam", "ah long",
    "skim cepat kaya", "pelaburan haram", "loan shark", "romance scam",
    "job scam", "e-commerce scam", "tng scam", "duitnow scam",
]


@dataclass
class RedditPost:
    """A scraped Reddit post with scam relevance data."""
    title: str
    url: str
    search_query: str
    content: str
    phones: list[str] = field(default_factory=list)
    bank_accounts: list[str] = field(default_factory=list)
    whatsapp_links: list[str] = field(default_factory=list)
    urls: list[str] = field(default_factory=list)
    scam_relevance: float = 0.0
    timestamp: str = ""


class RedditScraper:
    """
    Reddit scraper for r/malaysia scam trend intelligence.
    
    Uses Playwright with Firefox to search and extract posts.
    Logs in as a real user for full content access.
    """

    def __init__(self):
        self.config = self._load_config()
        self.reddit_config = self.config.get("collection", {}).get("reddit", {})
        self.search_queries = self.reddit_config.get("search_queries", SCAM_KEYWORDS)
        self.max_posts = self.reddit_config.get("max_posts_per_query", 10)
        self.use_old_reddit = self.reddit_config.get("use_old_reddit", True)

    def _load_config(self) -> dict:
        """Load sources.yaml configuration."""
        try:
            with open(CONFIG_PATH) as f:
                return yaml.safe_load(f) or {}
        except Exception as e:
            log.warning(f"Could not load config: {e}")
            return {}

    def _score_scam_relevance(self, text: str) -> float:
        """Score how scam-relevant a post is (0.0 - 1.0)."""
        text_lower = text.lower()
        hits = sum(1 for kw in SCAM_KEYWORDS if kw in text_lower)
        return min(hits / 3.0, 1.0)  # 3+ keyword hits = max relevance

    def _extract_entities(self, text: str) -> dict:
        """Extract entities from text."""
        return {
            "phones": list(set(PHONE_RE.findall(text)))[:5],
            "bank_accounts": [b for b in list(set(BANK_RE.findall(text))) if len(b) >= 10][:3],
            "whatsapp_links": list(set(WA_RE.findall(text))),
            "urls": [u for u in URL_RE.findall(text) if "reddit.com" not in u and "wikipedia.org" not in u][:5],
        }

    def run(self) -> list[RedditPost]:
        """Synchronous wrapper for the research-only scraper entrypoint."""
        return asyncio.run(self.scrape())

    async def scrape(self) -> list[RedditPost]:
        """
        Main scrape method. Searches r/malaysia for scam-related posts
        and extracts content + entities.
        """
        from playwright.async_api import async_playwright

        all_posts: list[RedditPost] = []
        seen_urls: set[str] = set()

        async with async_playwright() as p:
            browser = await p.firefox.launch(headless=True)

            # Try to load saved session
            context = None
            if SESSION_PATH.exists():
                log.info(f"Loading saved Reddit session from {SESSION_PATH}")
                try:
                    context = await browser.new_context(storage_state=str(SESSION_PATH))
                except Exception as e:
                    log.warning(f"Session load failed: {e}")
                    context = None

            if not context:
                context = await browser.new_context(viewport={"width": 1280, "height": 720})

            page = await context.new_page()

            # Check if logged in
            await page.goto("https://www.reddit.com/r/malaysia/", timeout=60000)
            await page.wait_for_timeout(3000)

            logged_in = await page.evaluate("""
                () => {
                    const userMenu = document.querySelector('[data-testid="user-dropdown"], .HeaderProfile');
                    const loginLink = document.querySelector('a[href*="/login"]');
                    return !!userMenu || !loginLink;
                }
            """)

            if not logged_in:
                log.info("Not logged in — attempting Reddit authentication")
                # Load credentials from env
                reddit_email = os.getenv("REDDIT_EMAIL")
                reddit_password = os.getenv("REDDIT_PASSWORD")

                if not reddit_email or not reddit_password:
                    log.warning(
                        "Reddit credentials not configured; continuing without login"
                    )
                else:
                    await page.goto("https://www.reddit.com/login/", timeout=60000)
                    await page.wait_for_timeout(3000)

                    try:
                        username_input = page.locator('input[name="username"], input#loginUsername, input[type="text"]').first
                        password_input = page.locator('input[name="password"], input#loginPassword, input[type="password"]').first

                        await username_input.fill(reddit_email)
                        await password_input.fill(reddit_password)

                        login_btn = page.locator('button[type="submit"], button:has-text("Log In"), button:has-text("Sign in")').first
                        await login_btn.click()
                        await page.wait_for_timeout(8000)

                        await context.storage_state(path=str(SESSION_PATH))
                        log.info("Reddit login successful — session saved")
                    except Exception as e:
                        log.error(f"Reddit login failed: {e}")
            else:
                log.info("Reddit session restored (already logged in)")

            # Search for each keyword
            for query in self.search_queries:
                log.info(f"Searching r/malaysia for: '{query}'")
                search_url = f"https://www.reddit.com/r/malaysia/search/?q={query}&sort=new&restrict_sr=on&t=year"

                try:
                    await page.goto(search_url, timeout=60000)
                    await page.wait_for_timeout(5000)

                    # Scroll to load more
                    for _ in range(3):
                        await page.evaluate("window.scrollBy(0, 1500)")
                        await page.wait_for_timeout(2000)

                    # Extract post links
                    posts_raw = await page.evaluate("""
                        () => {
                            const results = [];
                            const selectors = [
                                'a[href*="/r/malaysia/comments/"]',
                                'div[data-testid="post-container"] a',
                                'search-telemetry-tracker a',
                            ];
                            const seen = new Set();
                            for (const sel of selectors) {
                                document.querySelectorAll(sel).forEach(el => {
                                    const href = el.href || el.getAttribute('href') || '';
                                    const title = el.textContent?.trim() || '';
                                    if (href.includes('/comments/') && !seen.has(href) && title.length > 5) {
                                        seen.add(href);
                                        results.push({ title: title.substring(0, 200), url: href });
                                    }
                                });
                            }
                            return results;
                        }
                    """)

                    # Fallback: extract from HTML
                    if not posts_raw:
                        content = await page.content()
                        post_pattern = re.compile(r'href="(https://www\.reddit\.com/r/malaysia/comments/[^"]+)"', re.IGNORECASE)
                        raw_links = list(set(post_pattern.findall(content)))[:self.max_posts]
                        posts_raw = [{"title": "Unknown", "url": link} for link in raw_links]

                    # Visit each post and extract content
                    for i, post in enumerate(posts_raw[:self.max_posts]):
                        url = post.get("url", "")
                        title = post.get("title", "Unknown")

                        if url in seen_urls:
                            continue
                        seen_urls.add(url)

                        # Use old.reddit.com for easier scraping
                        old_url = url.replace("www.reddit.com", "old.reddit.com")

                        try:
                            await page.goto(old_url, timeout=30000)
                            await page.wait_for_timeout(2000)

                            content = await page.evaluate("""
                                () => {
                                    const postBody = document.querySelector('.expando .md');
                                    const bodyText = postBody ? postBody.innerText : '';
                                    const comments = document.querySelectorAll('.comment .md');
                                    let commentTexts = [];
                                    comments.forEach((c, i) => { if (i < 10) commentTexts.push(c.innerText); });
                                    return { body: bodyText, comments: commentTexts.join('\\n') };
                                }
                            """) or {}

                            full_text = f"{content.get('body', '')}\n{content.get('comments', '')}"
                            page_title = await page.evaluate("""
                                () => {
                                    const t = document.querySelector('a.title');
                                    return t ? t.textContent.trim() : document.title;
                                }
                            """) or title

                            entities = self._extract_entities(full_text)
                            relevance = self._score_scam_relevance(full_text + " " + page_title)

                            reddit_post = RedditPost(
                                title=page_title[:150],
                                url=url,
                                search_query=query,
                                content=full_text[:2000],
                                phones=entities["phones"],
                                bank_accounts=entities["bank_accounts"],
                                whatsapp_links=entities["whatsapp_links"],
                                urls=entities["urls"],
                                scam_relevance=relevance,
                                timestamp=datetime.now(timezone.utc).isoformat(),
                            )
                            all_posts.append(reddit_post)

                            log.info(f"  [{query}] {page_title[:50]}... relevance={relevance:.2f}")

                        except Exception as e:
                            log.warning(f"  Error scraping post: {e}")
                            continue

                except Exception as e:
                    log.error(f"Error searching for '{query}': {e}")
                    continue

            await browser.close()

        # Save results
        OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
            json.dump([self._post_to_dict(p) for p in all_posts], f, ensure_ascii=False, indent=2)

        log.info(f"Saved {len(all_posts)} posts to {OUTPUT_PATH}")
        return all_posts

    def _post_to_dict(self, post: RedditPost) -> dict:
        """Convert RedditPost to dict for serialization."""
        return {
            "title": post.title,
            "url": post.url,
            "search_query": post.search_query,
            "phones": post.phones,
            "bank_accounts": post.bank_accounts,
            "whatsapp_links": post.whatsapp_links,
            "urls": post.urls,
            "scam_relevance": post.scam_relevance,
            "content_preview": post.content[:500],
            "content_length": len(post.content),
            "timestamp": post.timestamp,
        }

    def get_trends(self, posts: list[RedditPost]) -> dict:
        """Analyze scam trends from scraped posts."""
        total = len(posts)
        high_relevance = [p for p in posts if p.scam_relevance >= 0.5]
        with_entities = [p for p in posts if p.phones or p.bank_accounts or p.whatsapp_links]

        # Count by query
        query_counts = {}
        for p in posts:
            q = p.search_query
            query_counts[q] = query_counts.get(q, 0) + 1

        # Top scam types mentioned
        scam_type_counts = {}
        for p in posts:
            text = (p.title + " " + p.content).lower()
            for kw in SCAM_KEYWORDS:
                if kw in text:
                    scam_type_counts[kw] = scam_type_counts.get(kw, 0) + 1

        return {
            "total_posts": total,
            "high_relevance_posts": len(high_relevance),
            "posts_with_entities": len(with_entities),
            "query_distribution": query_counts,
            "top_scam_keywords": dict(sorted(scam_type_counts.items(), key=lambda x: x[1], reverse=True)[:10]),
            "entity_summary": {
                "total_phones": sum(len(p.phones) for p in posts),
                "total_bank_accounts": sum(len(p.bank_accounts) for p in posts),
                "total_whatsapp_links": sum(len(p.whatsapp_links) for p in posts),
                "total_suspicious_urls": sum(len(p.urls) for p in posts),
            },
        }


if __name__ == "__main__":
    scraper = RedditScraper()
    posts = scraper.run()
    trends = scraper.get_trends(posts)
    print(f"\nTrends: {json.dumps(trends, indent=2)}")
