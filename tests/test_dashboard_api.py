from __future__ import annotations

import importlib
import sys
import types
from datetime import datetime, timezone
from pathlib import Path

from db.database import Database


class _QueueStub:
    def get_queue_length(self, queue_name: str) -> int:
        return {
            "raw_messages": 3,
            "extracted_entities": 2,
            "alerts": 1,
        }.get(queue_name, 0)

    def status(self) -> dict:
        return {
            "available": False,
            "redis_url": "redis://stub",
            "mode": "no-op",
            "error": "stubbed for unit test",
        }


def _load_api_main(monkeypatch):
    monkeypatch.setenv("API_ACCESS_TOKEN", "test-token")
    fake_slowapi = types.ModuleType("slowapi")

    class _Limiter:
        def __init__(self, *args, **kwargs):
            pass

        def limit(self, *args, **kwargs):
            def decorator(func):
                return func
            return decorator

    fake_slowapi.Limiter = _Limiter
    fake_slowapi._rate_limit_exceeded_handler = lambda *args, **kwargs: None
    fake_errors = types.ModuleType("slowapi.errors")
    fake_errors.RateLimitExceeded = type("RateLimitExceeded", (Exception,), {})
    fake_util = types.ModuleType("slowapi.util")
    fake_util.get_remote_address = lambda *args, **kwargs: "127.0.0.1"

    monkeypatch.setitem(sys.modules, "slowapi", fake_slowapi)
    monkeypatch.setitem(sys.modules, "slowapi.errors", fake_errors)
    monkeypatch.setitem(sys.modules, "slowapi.util", fake_util)
    if "api.main" in sys.modules:
        return importlib.reload(sys.modules["api.main"])
    return importlib.import_module("api.main")


def _seed_dashboard_db(db: Database) -> int:
    now = datetime.now(timezone.utc).isoformat()
    phone_id = db.upsert_entity("+60123456789", "phone")
    bank_id = db.upsert_entity("123456789012", "bank_account")
    domain_id = db.upsert_entity("fraud-example.com", "domain")

    db.add_entity_edge(phone_id, "telegram-alerts", message_hash="m1")
    db.add_entity_edge(bank_id, "telegram-alerts", message_hash="m2")
    db.add_entity_edge(domain_id, "reddit-malaysia", platform="reddit", message_hash="m3")

    with db.conn() as conn:
        conn.execute(
            """
            INSERT INTO scraped_messages
                (platform, channel, channel_id, message_id, sender_id, text, text_hash, raw_json, scraped_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("telegram", "telegram-alerts", "chan-1", "msg-1", "sender-1", "test", "hash-1", "{}", now),
        )
        conn.execute(
            """
            INSERT INTO cross_references (entity_id, source_db, source_entity_name, match_confidence, status, checked_at)
            VALUES (?, 'bnm', 'Test Listing', 0.95, 'confirmed', ?)
            """,
            (phone_id, now),
        )
        conn.execute(
            """
            INSERT INTO victim_signals (message_id, entity_id, signal_type, extracted_text, extracted_amount, detected_at)
            VALUES (1, ?, 'amount_mentioned', 'loss rm500', 500, ?)
            """,
            (phone_id, now),
        )
        conn.execute(
            """
            INSERT INTO entity_relationships
                (source_entity_id, target_entity_id, relationship_type, confidence, evidence, first_seen, last_seen, count)
            VALUES (?, ?, 'co_occurs', 0.9, '{}', ?, ?, 2)
            """,
            (phone_id, bank_id, now, now),
        )

    campaign_id = db.upsert_campaign(
        score=96,
        risk_level="critical",
        campaign_type="investment",
        entity_ids=[phone_id, bank_id, domain_id],
        channel_ids=["telegram-alerts", "reddit-malaysia"],
        keywords=["bank", "profit"],
        reason="cross-reference confirmed (+60); victim signals (+10)",
    )
    db.mark_alert_sent(campaign_id)
    db.log_alert(
        campaign_id=campaign_id,
        alert_level="critical",
        message="Critical investment campaign detected",
        sent_to="ops-room",
        status="delivered",
    )
    return campaign_id


def test_build_dashboard_summary_includes_management_sections(tmp_path: Path, monkeypatch):
    api_main = _load_api_main(monkeypatch)
    db = Database(db_path=str(tmp_path / "dashboard.db"))
    _seed_dashboard_db(db)

    summary = api_main._build_dashboard_summary(db, _QueueStub())

    assert summary["operations"]["messages_ingested_24h"] == 1
    assert summary["operations"]["entities_extracted_24h"] >= 3
    assert summary["operations"]["queue_depth"]["raw_messages"] == 3
    assert summary["intelligence"]["risk_distribution"][0]["label"] == "critical"
    assert summary["recent_campaigns"][0]["entity_count"] == 3
    assert summary["evidence"]["cross_reference_matches"] == 1
    assert summary["evidence"]["victim_signal_detections"] == 1
    assert summary["evidence"]["campaigns_with_supporting_evidence_pct"] == 100.0
    assert summary["recent_alerts"][0]["status"] == "delivered"


def test_build_campaign_drilldown_returns_evidence_context(tmp_path: Path, monkeypatch):
    api_main = _load_api_main(monkeypatch)
    db = Database(db_path=str(tmp_path / "dashboard-detail.db"))
    campaign_id = _seed_dashboard_db(db)

    detail = api_main._build_campaign_drilldown(db, campaign_id)

    assert detail is not None
    assert detail["id"] == campaign_id
    assert detail["metrics"]["entity_count"] == 3
    assert detail["metrics"]["cross_references"] == 1
    assert detail["metrics"]["victim_signals"] == 1
    assert detail["metrics"]["relationships"] >= 1
    assert detail["cross_references"][0]["source_db"] == "bnm"
    assert detail["recent_alert"]["status"] == "delivered"
