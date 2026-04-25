from __future__ import annotations

import json
import sys
import types
from pathlib import Path

_fake_redis = types.ModuleType("redis")
_fake_redis.ConnectionError = Exception
_fake_redis.ConnectionPool = type(
    "_FakeConnectionPool",
    (),
    {"from_url": staticmethod(lambda *args, **kwargs: object())},
)
_fake_redis.Redis = type("_FakeRedis", (), {"__init__": lambda self, connection_pool=None: None, "ping": lambda self: None})
_fake_redis.RedisError = Exception
sys.modules.setdefault("redis", _fake_redis)

from db.database import Database
from services.alert_formatter import format_alert
from services.campaign_types import campaign_type_label, normalize_campaign_type
from services.llm_enhancer import FraudLLMEnhancer
from services.llm_similarity import KeywordExtractor


def test_normalize_campaign_type_aliases():
    assert normalize_campaign_type("job_scam") == "job_task"
    assert normalize_campaign_type("deposit_scam") == "job_task"
    assert normalize_campaign_type("investment_scam") == "investment"
    assert normalize_campaign_type("qr_scam") == "qr"
    assert normalize_campaign_type("other") == "unknown"


def test_keyword_extractor_returns_canonical_category():
    extractor = KeywordExtractor()
    category, score = extractor.top_category("Jawatan kosong dan whatsapp link sekarang")
    assert category == "job_task"
    assert score > 0


def test_llm_enhancer_normalizes_parsed_response():
    enhancer = FraudLLMEnhancer()
    analysis = enhancer._parse_response(
        json.dumps(
            {
                "scam_type": "investment_scam",
                "risk_level": "high",
                "confidence": 0.9,
                "red_flags": ["guaranteed returns"],
                "reasoning": "test",
            }
        ),
        "test-model",
    )
    assert analysis.scam_type == "investment"


def test_database_upsert_campaign_normalizes_before_insert(tmp_path: Path):
    db = Database(db_path=str(tmp_path / "campaign_norm.db"))
    entity_id = db.upsert_entity("+60123456789", "phone")
    campaign_id = db.upsert_campaign(
        score=75,
        risk_level="high",
        campaign_type="job_scam",
        entity_ids=[entity_id],
        channel_ids=["chan-a"],
        keywords=["jawatan kosong"],
        reason="test",
    )
    with db.conn() as conn:
        row = conn.execute("SELECT campaign_type FROM campaigns WHERE id=?", (campaign_id,)).fetchone()
    assert row["campaign_type"] == "job_task"


def test_alert_formatter_uses_normalized_campaign_label():
    rendered = format_alert(
        {
            "risk_level": "high",
            "campaign_type": "investment_scam",
            "entity_ids": [],
            "channel_ids": [],
            "keywords": [],
            "entity_values": [],
            "reason": "test",
            "score": 80,
            "first_seen": "2026-04-10T00:00:00+00:00",
            "last_seen": "2026-04-10T01:00:00+00:00",
        }
    )
    assert "Investment Scam" in rendered
    assert campaign_type_label("investment_scam") == "Investment Scam"
