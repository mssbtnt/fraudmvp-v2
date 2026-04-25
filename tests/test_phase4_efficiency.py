from __future__ import annotations

import importlib
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
    ping_calls = 0

    def __init__(self, connection_pool=None):
        self.connection_pool = connection_pool

    def ping(self):
        type(self).ping_calls += 1


_fake_redis.ConnectionError = _FakeConnectionError
_fake_redis.ConnectionPool = _FakeConnectionPool
_fake_redis.Redis = _FakeRedisClient
_fake_redis.RedisError = Exception
sys.modules["redis"] = _fake_redis

from agents.extractor import FraudExtractorAgent
from agents.scorer import EntityNode, FraudScorerAgent
from db.database import Database


class _BatchQueue:
    def __init__(self):
        self.queues: dict[str, list[str]] = {}
        self.batch_pushes: list[tuple[str, list[str]]] = []

    def push_to_queue(self, name: str, data: str):
        self.queues.setdefault(name, []).insert(0, data)
        return True

    def push_to_queue_batch(self, name: str, items: list[str]):
        self.batch_pushes.append((name, list(items)))
        self.queues.setdefault(name, [])
        for item in items:
            self.queues[name].insert(0, item)
        return len(items)

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


class _SpyDB:
    def __init__(self):
        self.get_edges_for_entity_called = 0

    def get_recent_entities(self, limit=10000):
        return [
            {
                "id": 1,
                "value": "+60123456789",
                "type": "phone",
                "count": 2,
                "first_seen": "2026-04-10T00:00:00+00:00",
                "last_seen": "2026-04-10T01:00:00+00:00",
                "campaign_id": None,
            },
            {
                "id": 2,
                "value": "scam.xyz",
                "type": "domain",
                "count": 2,
                "first_seen": "2026-04-10T00:10:00+00:00",
                "last_seen": "2026-04-10T01:10:00+00:00",
                "campaign_id": None,
            },
        ]

    def get_edges_for_entities(self, entity_ids):
        return {
            1: [{"channel": "a", "platform": "telegram"}, {"channel": "b", "platform": "telegram"}],
            2: [{"channel": "b", "platform": "telegram"}],
        }

    def get_edges_for_entity(self, entity_id):
        self.get_edges_for_entity_called += 1
        raise AssertionError("build_entity_graph should use bulk edge loading")


def test_extractor_process_batch_uses_batch_queue_push(tmp_path: Path):
    db = Database(db_path=str(tmp_path / "extractor_batch.db"))
    queue = _BatchQueue()
    extractor = FraudExtractorAgent()
    extractor.db = db
    extractor.queue = queue
    extractor.keyword_extractor = _DummyKeywordExtractor()

    queue.push_to_queue(
        "raw_messages",
        json.dumps(
            {
                "platform": "telegram",
                "channel": "chan-a",
                "text": "Contact +60123456789 and visit https://scam.xyz",
                "message_hash": "msg-batch",
                "timestamp": "2026-04-10T00:00:00+00:00",
            }
        ),
    )

    result = extractor.process_batch(batch_size=1)

    assert result["messages_processed"] == 1
    assert result["entities_extracted"] >= 2
    assert len(queue.batch_pushes) == 1
    assert queue.batch_pushes[0][0] == "extracted_entities"
    assert len(queue.batch_pushes[0][1]) == result["entities_extracted"]


def test_scorer_build_entity_graph_uses_bulk_edge_loading():
    scorer = FraudScorerAgent()
    scorer.db = _SpyDB()
    graph = scorer.build_entity_graph()

    assert set(graph.keys()) == {1, 2}
    assert graph[1].channels == ["a", "b"] or graph[1].channels == ["b", "a"]
    assert graph[2].channels == ["b"]


def test_queue_handler_reuses_single_connected_client():
    queue_handler = importlib.import_module("services.queue_handler")
    queue_handler = importlib.reload(queue_handler)

    first = queue_handler.QueueHandler()
    second = queue_handler.QueueHandler()

    assert first.client is second.client
    assert _FakeRedisClient.ping_calls == 1
