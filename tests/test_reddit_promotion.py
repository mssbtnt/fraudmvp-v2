from __future__ import annotations

import json

from agents.reddit_collector import RedditCollectorAgent
from services.scraper.reddit_scraper import RedditPost


def build_agent() -> RedditCollectorAgent:
    return RedditCollectorAgent(
        promote_qualified=True,
        min_scam_relevance=0.67,
        min_text_length=120,
    )


def test_reddit_post_qualifies_for_promotion_when_relevance_and_entities_are_present():
    agent = build_agent()
    post = RedditPost(
        title="Victim reports phishing bank scam",
        url="https://www.reddit.com/r/malaysia/comments/example1",
        search_query="phishing",
        content=(
            "I was contacted on WhatsApp and told to transfer money to "
            "123456789012. The scammer used +60123456789 and sent me to "
            "https://fake-bank-login.example to verify my account."
        ),
        phones=["+60123456789"],
        bank_accounts=["123456789012"],
        whatsapp_links=["60123456789"],
        urls=["https://fake-bank-login.example"],
        scam_relevance=0.95,
        timestamp="2026-04-15T00:00:00+00:00",
    )

    qualifies, reasons = agent.qualifies_for_promotion(post)

    assert qualifies is True
    assert "scam_relevance>=0.67" in reasons
    assert any(reason.startswith("has_") for reason in reasons)


def test_reddit_post_does_not_qualify_without_hard_entities():
    agent = build_agent()
    post = RedditPost(
        title="General scam discussion",
        url="https://www.reddit.com/r/malaysia/comments/example2",
        search_query="scam",
        content=(
            "People are discussing a suspicious platform, but no phone number, "
            "bank account, WhatsApp link, or external URL was included in this post."
        ),
        phones=[],
        bank_accounts=[],
        whatsapp_links=[],
        urls=[],
        scam_relevance=0.99,
        timestamp="2026-04-15T00:00:00+00:00",
    )

    qualifies, reasons = agent.qualifies_for_promotion(post)

    assert qualifies is False
    assert "scam_relevance>=0.67" in reasons
    assert not any(reason.startswith("has_") for reason in reasons)


def test_promoted_reddit_raw_message_carries_explicit_provenance():
    post = RedditPost(
        title="Victim reports phishing bank scam",
        url="https://www.reddit.com/r/malaysia/comments/example3",
        search_query="phishing",
        content=(
            "Victim lost money to a phishing flow using +60123456789 and "
            "https://fake-bank-login.example with bank account 123456789012."
        ),
        phones=["+60123456789"],
        bank_accounts=["123456789012"],
        whatsapp_links=[],
        urls=["https://fake-bank-login.example"],
        scam_relevance=0.90,
        timestamp="2026-04-15T00:00:00+00:00",
    )

    raw = RedditCollectorAgent._build_raw_message(post)
    payload = json.loads(raw.raw_json)

    assert raw.platform == "reddit"
    assert raw.channel == "r/malaysia"
    assert payload["source_type"] == "reddit_promoted_post"
    assert payload["promotion_policy"] == "strict_gated_bridge_v1"
    assert payload["url"] == post.url
