from __future__ import annotations

import asyncio
import json
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

from agents.extractor import FraudExtractorAgent
from agents.scorer import FraudScorerAgent
from db.database import Database
from services.scraper.semakmule_scraper import MuleAccount, SemakMuleScraper


class _MemoryQueue:
    def __init__(self):
        self.queues: dict[str, list[str]] = {}

    def push_to_queue(self, name: str, data: str):
        self.queues.setdefault(name, []).insert(0, data)
        return True

    def pop_from_queue(self, name: str, timeout: int = 0):
        items = self.queues.get(name, [])
        if not items:
            return None
        return items.pop()

    def get_queue_length(self, name: str):
        return len(self.queues.get(name, []))


class _DummyKeywordExtractor:
    def extract(self, text: str):
        return {}

    def top_category(self, text: str):
        return ("unknown", 0.0)


class _StubLLMEnhancer:
    def analyze_message(self, text: str, entities=None, keyword_score: int = 0):
        raise AssertionError("LLM should not be invoked in this test")


class _TestSemakMule(SemakMuleScraper):
    def __init__(self, db: Database, queue: _MemoryQueue):
        self.client = None
        self.queue = queue
        self.db = db

    async def close(self):
        return None

    async def verify_entity(self, entity_type: str, value: str):
        if value.endswith("6789"):
            return MuleAccount(
                category="telefon" if entity_type == "phone" else "bank",
                value=value,
                report_count=3,
                scraped_at="2026-04-10T00:00:00+00:00",
            )
        return None


def test_add_entity_edge_is_idempotent_by_message_hash(tmp_path: Path):
    db = Database(db_path=str(tmp_path / "edges.db"))
    entity_id = db.upsert_entity("+60123456789", "phone")

    first = db.add_entity_edge(
        entity_id=entity_id,
        channel="chan-a",
        platform="telegram",
        message_hash="same-msg",
    )
    second = db.add_entity_edge(
        entity_id=entity_id,
        channel="chan-a",
        platform="telegram",
        message_hash="same-msg",
    )

    assert first == second
    with db.conn() as conn:
        count = conn.execute("SELECT COUNT(*) FROM entity_edges").fetchone()[0]
    assert count == 1


def test_extractor_reprocessing_same_message_does_not_add_duplicate_edges(tmp_path: Path):
    db = Database(db_path=str(tmp_path / "scorer.db"))
    queue = _MemoryQueue()

    extractor = FraudExtractorAgent()
    extractor.db = db
    extractor.queue = queue
    extractor.keyword_extractor = _DummyKeywordExtractor()

    raw_message = json.dumps(
        {
            "platform": "telegram",
            "channel": "chan-a",
            "text": "WhatsApp saya +60123456789",
            "message_hash": "msg-1",
            "timestamp": "2026-04-10T00:00:00+00:00",
        }
    )
    count, entities = extractor.process_message(raw_message)
    assert count == 1
    with db.conn() as conn:
        before = conn.execute("SELECT COUNT(*) FROM entity_edges").fetchone()[0]

    count_again, entities_again = extractor.process_message(raw_message)
    assert count_again == 1

    with db.conn() as conn:
        after = conn.execute("SELECT COUNT(*) FROM entity_edges").fetchone()[0]

    assert before == 1
    assert after == 1


def test_semakmule_verifies_from_db_without_consuming_extracted_queue(tmp_path: Path):
    db = Database(db_path=str(tmp_path / "semakmule.db"))
    queue = _MemoryQueue()

    entity_id = db.upsert_entity(
        "+60123456789",
        "phone",
        {"platform": "telegram", "channel": "chan-a"},
    )
    queue.push_to_queue("extracted_entities", json.dumps({"entity_id": entity_id}))

    scraper = _TestSemakMule(db, queue)
    result = asyncio.run(scraper.process_entities())

    assert result["checked"] == 1
    assert result["confirmed"] == 1
    assert queue.get_queue_length("extracted_entities") == 1
    assert queue.get_queue_length("raw_messages") == 1

    row = db.get_entity_by_value("+60123456789", "phone")
    metadata = json.loads(row["metadata"])
    assert metadata["semakmule_verified"] is True
    assert metadata["semakmule_report_count"] == 3


def test_semakmule_skips_recently_checked_entities(tmp_path: Path):
    db = Database(db_path=str(tmp_path / "semakmule_skip.db"))
    queue = _MemoryQueue()
    db.upsert_entity(
        "+60111116789",
        "phone",
        {
            "platform": "telegram",
            "channel": "chan-a",
            "semakmule_checked_at": "2999-01-01T00:00:00+00:00",
        },
    )

    scraper = _TestSemakMule(db, queue)
    result = asyncio.run(scraper.process_entities())

    assert result["checked"] == 0
    assert result["confirmed"] == 0
    assert queue.get_queue_length("raw_messages") == 0
