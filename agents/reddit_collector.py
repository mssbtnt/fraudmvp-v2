"""
RedditCollectorAgent — supplementary Reddit intelligence runner.

Default mode is research-only.

An optional promotion mode can forward only high-confidence Reddit posts into
the canonical pipeline when they meet strict gating criteria.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))

from db.database import Database
from services.queue_handler import QueueHandler
from services.raw_message import RawMessage, stable_message_hash
from services.scraper.reddit_scraper import OUTPUT_PATH, RedditPost, RedditScraper

log = logging.getLogger("reddit_collector")

PROJECT_ROOT = Path(__file__).parent.parent
CONFIG_PATH = PROJECT_ROOT / "config" / "sources.yaml"
TRENDS_PATH = PROJECT_ROOT / "data" / "reddit_trends_summary.json"


class RedditCollectorAgent:
    """
    Run Reddit scraping in research-only mode or gated promotion mode.

    Promotion mode remains conservative by design. Only posts with strong scam
    relevance and extractable hard entities are forwarded to the main pipeline.
    """

    def __init__(
        self,
        promote_qualified: bool = False,
        min_scam_relevance: float | None = None,
        min_text_length: int | None = None,
        require_entity_types: list[str] | None = None,
    ) -> None:
        self.scraper = RedditScraper()
        self.db = Database()
        self.queue = QueueHandler()
        self.config = self._load_config()

        promotion_cfg = (
            self.config.get("collection", {})
            .get("reddit", {})
            .get("promotion", {})
        )
        self.promote_qualified = promote_qualified
        self.min_scam_relevance = (
            min_scam_relevance
            if min_scam_relevance is not None
            else float(promotion_cfg.get("min_scam_relevance", 0.67))
        )
        self.min_text_length = (
            min_text_length
            if min_text_length is not None
            else int(promotion_cfg.get("min_text_length", 120))
        )
        self.require_entity_types = require_entity_types or list(
            promotion_cfg.get(
                "require_entity_types",
                ["phones", "bank_accounts", "whatsapp_links", "urls"],
            )
        )

    @staticmethod
    def _load_config() -> dict:
        with open(CONFIG_PATH, encoding="utf-8") as handle:
            return yaml.safe_load(handle) or {}

    @staticmethod
    def _post_text(post: RedditPost) -> str:
        parts = [post.title.strip(), post.content.strip(), post.url.strip()]
        return "\n\n".join(part for part in parts if part)

    @staticmethod
    def _entity_counts(post: RedditPost) -> dict[str, int]:
        return {
            "phones": len(post.phones),
            "bank_accounts": len(post.bank_accounts),
            "whatsapp_links": len(post.whatsapp_links),
            "urls": len(post.urls),
        }

    def _promotion_reasons(self, post: RedditPost) -> list[str]:
        reasons: list[str] = []
        counts = self._entity_counts(post)

        if post.scam_relevance >= self.min_scam_relevance:
            reasons.append(f"scam_relevance>={self.min_scam_relevance}")
        if len(post.content.strip()) >= self.min_text_length:
            reasons.append(f"text_length>={self.min_text_length}")

        qualifying_entities = [
            entity_type
            for entity_type in self.require_entity_types
            if counts.get(entity_type, 0) > 0
        ]
        reasons.extend(f"has_{entity_type}" for entity_type in qualifying_entities)
        return reasons

    def qualifies_for_promotion(self, post: RedditPost) -> tuple[bool, list[str]]:
        reasons = self._promotion_reasons(post)
        has_relevance = any(reason.startswith("scam_relevance>=") for reason in reasons)
        has_text = any(reason.startswith("text_length>=") for reason in reasons)
        has_entity = any(reason.startswith("has_") for reason in reasons)
        return has_relevance and has_text and has_entity, reasons

    @staticmethod
    def _build_raw_message(post: RedditPost) -> RawMessage:
        text = RedditCollectorAgent._post_text(post)
        fallback_seed = f"reddit|r/malaysia|{post.url}|{post.search_query}"
        raw_payload = {
            "source_type": "reddit_promoted_post",
            "promotion_policy": "strict_gated_bridge_v1",
            "subreddit": "malaysia",
            "search_query": post.search_query,
            "title": post.title,
            "url": post.url,
            "content": post.content,
            "phones": post.phones,
            "bank_accounts": post.bank_accounts,
            "whatsapp_links": post.whatsapp_links,
            "urls": post.urls,
            "scam_relevance": post.scam_relevance,
            "timestamp": post.timestamp,
        }
        return RawMessage(
            platform="reddit",
            channel="r/malaysia",
            channel_id=post.search_query,
            sender_id=None,
            text=text,
            member_count=None,
            timestamp=post.timestamp,
            message_hash=stable_message_hash(text, fallback_seed=fallback_seed),
            raw_json=json.dumps(raw_payload, ensure_ascii=False),
            message_id=post.url,
        )

    def _write_report(self, report: dict) -> None:
        TRENDS_PATH.parent.mkdir(parents=True, exist_ok=True)
        TRENDS_PATH.write_text(
            json.dumps(report, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def run(self) -> dict:
        mode = "promotion" if self.promote_qualified else "research_only"
        log.info("Running Reddit collection in %s mode", mode)

        posts = self.scraper.run()
        trends = self.scraper.get_trends(posts)

        promoted = 0
        persisted = 0
        queued = 0
        skipped = 0
        promoted_samples: list[dict] = []

        if self.promote_qualified:
            for post in posts:
                qualifies, reasons = self.qualifies_for_promotion(post)
                if not qualifies:
                    skipped += 1
                    continue

                msg = self._build_raw_message(post)
                persisted_ok = self.db.upsert_scraped_message(msg)
                queued_ok = self.queue.push_to_queue("raw_messages", msg.to_json())

                if persisted_ok:
                    persisted += 1
                if queued_ok:
                    queued += 1
                else:
                    log.warning(
                        "Qualified Reddit post was persisted but not queued: %s",
                        msg.message_hash,
                    )

                promoted += 1
                if len(promoted_samples) < 10:
                    promoted_samples.append(
                        {
                            "title": post.title[:140],
                            "url": post.url,
                            "reasons": reasons,
                            "scam_relevance": post.scam_relevance,
                            "entity_counts": self._entity_counts(post),
                            "message_hash": msg.message_hash,
                        }
                    )

        report = {
            "mode": mode,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "posts_output_path": str(OUTPUT_PATH),
            "trends_output_path": str(TRENDS_PATH),
            "posts_scraped": len(posts),
            "trend_summary": trends,
            "promotion_policy": {
                "enabled": self.promote_qualified,
                "min_scam_relevance": self.min_scam_relevance,
                "min_text_length": self.min_text_length,
                "require_entity_types": self.require_entity_types,
            },
            "promotion_summary": {
                "qualified_promoted": promoted,
                "persisted": persisted,
                "queued": queued,
                "skipped": skipped,
                "queue_backend": self.queue.status(),
                "samples": promoted_samples,
            },
        }

        self._write_report(report)
        log.info(
            "Saved Reddit report to %s (%s posts, %s promoted)",
            TRENDS_PATH,
            len(posts),
            promoted,
        )
        return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m agents.reddit_collector",
        description="Run Reddit research collection with optional gated promotion.",
    )
    parser.add_argument(
        "--promote-qualified",
        action="store_true",
        help="Promote only high-confidence Reddit posts into scraped_messages/raw_messages.",
    )
    parser.add_argument(
        "--min-scam-relevance",
        type=float,
        default=None,
        help="Override the minimum scam relevance threshold for promotion.",
    )
    parser.add_argument(
        "--min-text-length",
        type=int,
        default=None,
        help="Override the minimum post content length for promotion.",
    )
    return parser


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    )
    args = build_parser().parse_args()
    agent = RedditCollectorAgent(
        promote_qualified=args.promote_qualified,
        min_scam_relevance=args.min_scam_relevance,
        min_text_length=args.min_text_length,
    )
    print(json.dumps(agent.run(), indent=2, ensure_ascii=False))
