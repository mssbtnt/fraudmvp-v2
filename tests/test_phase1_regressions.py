from __future__ import annotations

import sys
import types
from pathlib import Path

_fake_redis = types.ModuleType("redis")


class _FakeConnectionError(Exception):
    pass


class _FakeConnectionPool:
    @staticmethod
    def from_url(*args, **kwargs):
        return object()


class _FakeRedisClient:
    def __init__(self, connection_pool=None):
        self.connection_pool = connection_pool

    def ping(self):
        raise _FakeConnectionError("redis unavailable in unit test")


_fake_redis.ConnectionError = _FakeConnectionError
_fake_redis.ConnectionPool = _FakeConnectionPool
_fake_redis.Redis = _FakeRedisClient
_fake_redis.RedisError = Exception
sys.modules.setdefault("redis", _fake_redis)

from agents.scorer import EntityNode, FraudScorerAgent
from db.database import Database


class _StubKeywordExtractor:
    def extract(self, text: str):
        return {"investment": [("crypto", 30.0), ("profit", 20.0)]}


class _StubLLMEnhancer:
    def analyze_message(self, text: str, entities=None, keyword_score: int = 0):
        raise AssertionError("LLM should not be called for this regression test")


def test_score_cluster_no_unbound_campaign_type():
    agent = FraudScorerAgent()
    agent.keyword_extractor = _StubKeywordExtractor()
    agent.llm_enhancer = _StubLLMEnhancer()
    agent.channel_cfg = {"scam_language_detected": 20}
    agent.platform_weights = {"telegram": 1.0, "web": 0.8}
    agent.freq_cfg = {"entity_count_3": 40, "entity_count_4_plus": 50, "each_additional_repeat": 10}
    agent.temporal_cfg = {"cross_channel_same_platform_24h": 30, "cross_platform_24h": 40, "same_channel_48h": 15}
    agent.thresholds = {"low": 40, "medium": 60, "high": 80, "critical": 95}

    graph = {
        1: EntityNode(
            id=1,
            value="+60123456789",
            type="phone",
            count=3,
            channels=["telegram-alerts", "telegram-hub", "telegram-watch"],
            platforms=["telegram"],
            first_seen="2026-04-10T00:00:00+00:00",
            last_seen="2026-04-10T01:00:00+00:00",
        ),
        2: EntityNode(
            id=2,
            value="scam-site.xyz",
            type="domain",
            count=3,
            channels=["telegram-hub", "telegram-watch"],
            platforms=["telegram"],
            first_seen="2026-04-10T00:05:00+00:00",
            last_seen="2026-04-10T01:05:00+00:00",
        ),
    }

    campaign = agent._score_cluster({1, 2}, graph)

    assert campaign.score >= 40
    assert campaign.risk_level in {"low", "medium", "high", "critical"}
    assert campaign.campaign_type == "investment"


def test_get_cross_channel_count_executes_without_name_error(tmp_path: Path):
    db = Database(db_path=str(tmp_path / "phase1_count.db"))
    entity_id = db.upsert_entity("+60123456789", "phone")
    db.add_entity_edge(entity_id=entity_id, channel="a", message_hash="m1")
    db.add_entity_edge(entity_id=entity_id, channel="b", message_hash="m2")

    assert db.get_cross_channel_count(entity_id, hours=24) == 2


def test_upsert_source_updates_existing_row_without_unique_constraint(tmp_path: Path):
    db = Database(db_path=str(tmp_path / "phase1_sources.db"))

    first_id = db.upsert_source(
        name="My Source",
        platform="web",
        url="https://example.com/one",
        reliability_score=0.5,
        tags=["seed"],
    )
    second_id = db.upsert_source(
        name="My Source",
        platform="web",
        url="https://example.com/two",
        reliability_score=0.9,
        tags=["seed", "updated"],
    )

    assert first_id == second_id

    with db.conn() as conn:
        row = conn.execute("SELECT * FROM sources WHERE id = ?", (first_id,)).fetchone()
        count = conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0]

    assert count == 1
    assert row["url"] == "https://example.com/two"
    assert row["reliability_score"] == 0.9
