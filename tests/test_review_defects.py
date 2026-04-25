from __future__ import annotations

import json
import importlib
import sys
import types
from contextlib import contextmanager

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

_fake_telethon = types.ModuleType("telethon")
_fake_telethon.TelegramClient = type("TelegramClient", (), {})
_fake_telethon.events = types.SimpleNamespace(NewMessage=lambda *args, **kwargs: None)
sys.modules.setdefault("telethon", _fake_telethon)

from agents.scorer import Campaign, EntityNode, FraudScorerAgent
from db.database import Database
from services.alert_builder import AlertBuilder, EntityNarrative
from services.cross_reference import CrossReferenceResult
from services.daily_report import DailyReportState, determine_daily_report_state
from services.entity_linker import EntityLinker
from services.pipeline import FraudMVPPipeline
from services.telegram_monitor import TelegramMonitor
from services.llm_enhancer import FraudLLMEnhancer
from services.scraper.semakmule_scraper import SemakMuleScraper
from services.victim_signal import VictimSignalDetector


class _NoopCrossRef:
    def check_entity(self, value: str, entity_type: str) -> CrossReferenceResult:
        return CrossReferenceResult(
            value=value,
            entity_type=entity_type,
            matched=False,
            confidence=0.0,
            sources=[],
            risk_boost=0,
        )


class _Relation:
    def __init__(self, source_id: int, target_id: int, relationship_type: str):
        self.source_id = source_id
        self.target_id = target_id
        self.relationship_type = relationship_type


class _StubEntityLinker:
    def get_related_entities(self, entity_id: int, max_depth: int = 1):
        if entity_id == 1:
            return [_Relation(1, 2, "shared_phone")]
        return []


class _ConnStub:
    def execute(self, *args, **kwargs):
        return self

    def fetchone(self):
        return None

    def commit(self):
        return None


class _DbStub:
    def __init__(self):
        self.saved_mentions = None

    @contextmanager
    def conn(self):
        yield _ConnStub()

    def upsert_campaign(self, **kwargs):
        return 1

    def stats(self):
        return {"campaigns": 1}


class _QueueStub:
    def __init__(self):
        self.pushed: list[tuple[str, str]] = []

    def push_to_queue(self, name: str, data: str):
        self.pushed.append((name, data))
        return True


class _TrendStub:
    def __init__(self):
        self.calls: list[tuple[str, dict[int, int]]] = []

    def record_mentions(self, day: str, entity_mentions: dict[int, int]):
        self.calls.append((day, entity_mentions))


def test_database_reset_derived_tables_works_on_fresh_db(tmp_path):
    db = Database(db_path=str(tmp_path / "fresh.db"))

    cleared = db.reset_derived_tables()

    assert cleared == {
        "cross_references": 0,
        "victim_signals": 0,
        "entity_relationships": 0,
        "entity_mentions": 0,
    }


def test_daily_report_partial_run_state_is_reachable():
    summary = {
        "collection": {
            "success": False,
            "required_sources": {
                "telegram": {"success": False, "messages": 0},
                "rss": {"success": True, "messages": 10},
            },
            "optional_sources": {},
            "scraped_messages_persisted": 10,
        },
        "extraction": {
            "success": True,
            "messages_processed": 10,
            "entities_extracted": 20,
        },
        "scoring": {
            "success": True,
            "campaigns_scored": 1,
            "alerts_triggered": 0,
        },
        "alerting": {
            "success": True,
            "alerts_sent": 0,
        },
    }

    state = determine_daily_report_state(summary, allow_partial_run_state=True)

    assert state == DailyReportState.PARTIAL_RUN_STALE_RESULTS


def test_alert_builder_uses_scoring_rules_thresholds_and_formats_related_entities(tmp_path):
    db = Database(db_path=str(tmp_path / "alert_builder.db"))
    first = db.upsert_entity("+60123456789", "phone")
    second = db.upsert_entity("123456789012", "bank_account")
    assert first != second

    builder = AlertBuilder(
        db=db,
        cross_ref=_NoopCrossRef(),
        entity_linker=_StubEntityLinker(),
    )

    assert builder._compute_risk_level(75) == "medium"
    assert builder._compute_risk_level(80) == "high"

    alert = builder.build_alert(
        entity_data={
            "entities": [
                {"value": "+60123456789", "type": "phone", "count": 2},
            ],
            "scam_type": "investment",
        },
        score=80,
    )
    chunks = builder.format_for_telegram(alert)

    assert any("Entities seen together:" in chunk for chunk in chunks)
    assert any("Shared Phone: 123456789012 (bank_account)" in chunk for chunk in chunks)


def test_victim_signal_llm_detection_builds_complete_signal_objects(monkeypatch):
    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps(
                {
                    "response": json.dumps(
                        {
                            "signals": [
                                {
                                    "type": "financial_loss",
                                    "text": "kena tipu RM500",
                                    "confidence": 1.0,
                                }
                            ],
                            "amount_mentioned": 500.0,
                        }
                    )
                }
            ).encode("utf-8")

    monkeypatch.setattr("urllib.request.urlopen", lambda *args, **kwargs: _Response())

    detector = VictimSignalDetector()
    result = detector.detect_signals_llm("kena tipu RM500")

    assert len(result.signals) == 1
    assert result.signals[0].pattern_matched == "llm_detection"
    assert result.signals[0].start_pos == 0
    assert result.signals[0].end_pos == len("kena tipu RM500")
    assert result.total_weight == detector.CATEGORY_CAPS["financial_loss"]


def test_scorer_run_records_mentions_without_nodes_scope_error():
    scorer = FraudScorerAgent()
    scorer.db = _DbStub()
    scorer.queue = _QueueStub()
    scorer.trend_detector = _TrendStub()
    scorer.entity_linker = types.SimpleNamespace(link_from_campaigns=lambda campaigns: None)
    scorer.build_entity_graph = lambda: {
        1: EntityNode(
            id=1,
            value="+60123456789",
            type="phone",
            count=3,
            channels=["chan-a"],
            platforms=["telegram"],
            first_seen="2026-04-10T00:00:00+00:00",
            last_seen="2026-04-10T01:00:00+00:00",
        )
    }
    scorer.cluster_entities = lambda graph: [
        Campaign(
            entity_ids=[1],
            channel_ids=["chan-a"],
            score=80,
            risk_level="high",
            campaign_type="investment",
            keywords=["crypto"],
            reason="test",
            script_sample="test",
            first_seen="2026-04-10T00:00:00+00:00",
            last_seen="2026-04-10T01:00:00+00:00",
            entity_count=1,
            channel_count=1,
            cross_platform=False,
            entity_values=[{"type": "phone", "value": "+60123456789", "count": 3}],
        )
    ]

    result = scorer.run()

    assert result["alerts_triggered"] == 1
    assert scorer.trend_detector.calls
    assert scorer.trend_detector.calls[0][1] == {1: 3}


def test_queue_handler_recovers_after_transient_connection_failure(monkeypatch):
    fake_redis = types.ModuleType("redis")

    class _TransientConnectionError(Exception):
        pass

    class _TransientTimeoutError(Exception):
        pass

    class _Pool:
        @staticmethod
        def from_url(*args, **kwargs):
            return object()

    class _TransientClient:
        ping_calls = 0

        def __init__(self, connection_pool=None):
            self.connection_pool = connection_pool

        def ping(self):
            type(self).ping_calls += 1
            if type(self).ping_calls == 1:
                raise _TransientConnectionError("temporary failure")

    fake_redis.ConnectionError = _TransientConnectionError
    fake_redis.TimeoutError = _TransientTimeoutError
    fake_redis.ConnectionPool = _Pool
    fake_redis.Redis = _TransientClient
    fake_redis.RedisError = Exception

    monkeypatch.setitem(sys.modules, "redis", fake_redis)

    import services.queue_handler as queue_handler

    queue_handler = importlib.reload(queue_handler)
    first = queue_handler.QueueHandler()
    second = queue_handler.QueueHandler()

    assert first.client is None
    assert second.client is not None
    assert second.status()["available"] is True
    assert _TransientClient.ping_calls >= 2


def test_pipeline_load_config_merges_scoring_rules(tmp_path, monkeypatch):
    config_path = tmp_path / "pipeline.yaml"
    config_path.write_text(
        "pipeline:\n"
        "  ingest_batch_size: 25\n"
        "  run_interval_minutes: 30\n",
        encoding="utf-8",
    )

    class _PipelineDb:
        pass

    monkeypatch.setattr("services.pipeline.Database", _PipelineDb)

    pipeline = FraudMVPPipeline(config_path=str(config_path))

    assert pipeline.config["pipeline"]["ingest_batch_size"] == 25
    assert pipeline.config["trend"]["window_days"] == 30
    assert pipeline.config["entity_relationships"]["cross_reference_weight"] == 30


def test_telegram_monitor_builds_canonical_raw_message():
    monitor = TelegramMonitor.__new__(TelegramMonitor)

    raw_message = monitor._build_raw_message(
        {
            "message_id": 123,
            "text": "Hubungi saya di +60123456789",
            "date": "2026-04-15T12:34:56+00:00",
            "sender_id": 456,
            "sender_name": "Alice",
            "chat_id": -100987654321,
            "chat_title": "Fraud Watch",
            "chat_username": "fraud_watch",
            "platform": "telegram",
            "has_media": False,
        }
    )

    payload = json.loads(raw_message.raw_json)

    assert raw_message.platform == "telegram"
    assert raw_message.channel == "fraud_watch"
    assert raw_message.channel_id == "-100987654321"
    assert raw_message.sender_id == "456"
    assert raw_message.message_id == "123"
    assert raw_message.message_hash
    assert payload["chat_title"] == "Fraud Watch"


def test_llm_enhancer_disables_after_repeated_failures(monkeypatch):
    monkeypatch.setattr("services.llm_enhancer.LLM_ENABLED", True)
    monkeypatch.setattr("services.llm_enhancer.LLM_MAX_FAILURES", 2)
    monkeypatch.setattr("services.llm_enhancer.LLM_TIMEOUT_SECONDS", 1.0)

    enhancer = FraudLLMEnhancer(model="gemma4:test")
    monkeypatch.setattr(
        enhancer,
        "_generate",
        lambda prompt, model: "" if model == "gemma4:test" else "not-json",
    )

    first = enhancer.analyze_message("suspicious message")
    second = enhancer.analyze_message("suspicious message")
    third = enhancer.analyze_message("suspicious message")

    assert first.confidence == 0.0
    assert second.confidence == 0.0
    assert enhancer.enabled is False
    assert third.model_used == "disabled"
    enhancer.close()


def test_scorer_skips_llm_boost_when_enhancer_disabled():
    scorer = FraudScorerAgent()
    scorer.llm_enhancer.enabled = False
    scorer.scam_classifier.llm_enhancer = scorer.llm_enhancer
    scorer.channel_cfg = {"scam_language_detected": 20}
    scorer.platform_weights = {"telegram": 1.0}
    scorer.freq_cfg = {"entity_count_3": 40, "entity_count_4_plus": 50, "each_additional_repeat": 10}
    scorer.temporal_cfg = {"cross_channel_same_platform_24h": 30, "cross_platform_24h": 40, "same_channel_48h": 15}
    scorer.thresholds = {"low": 40, "medium": 60, "high": 80, "critical": 95}
    scorer.cross_ref_cfg = {}
    scorer.victim_detector = VictimSignalDetector()
    scorer.cross_ref = types.SimpleNamespace(check_entity=lambda value, entity_type: types.SimpleNamespace(matched=False))
    scorer.entity_linker = types.SimpleNamespace(compute_relationship_boost=lambda entity_id: 0.0)
    scorer.trend_detector = types.SimpleNamespace(detect_trends=lambda entity_id=None: [])

    graph = {
        1: EntityNode(
            id=1,
            value="+60123456789",
            type="phone",
            count=3,
            channels=["telegram-a", "telegram-b", "telegram-c"],
            platforms=["telegram"],
            first_seen="2026-04-10T00:00:00+00:00",
            last_seen="2026-04-10T01:00:00+00:00",
        ),
        2: EntityNode(
            id=2,
            value="scam-site.xyz",
            type="domain",
            count=3,
            channels=["telegram-a", "telegram-b", "telegram-c"],
            platforms=["telegram"],
            first_seen="2026-04-10T00:05:00+00:00",
            last_seen="2026-04-10T01:05:00+00:00",
        ),
    }

    campaign = scorer._score_cluster({1, 2}, graph)

    assert "LLM boost" not in campaign.reason


def test_semakmule_can_skip_entity_verification_when_disabled(tmp_path):
    class _SkipSemakMule(SemakMuleScraper):
        ENABLE_ENTITY_VERIFICATION = False

        def __init__(self, db: Database):
            self.client = None
            self.queue = types.SimpleNamespace(get_queue_length=lambda name: 0)
            self.db = db

        async def close(self):
            return None

    db = Database(db_path=str(tmp_path / "skip_semakmule.db"))
    db.upsert_entity("+60123456789", "phone")

    scraper = _SkipSemakMule(db)
    result = __import__("asyncio").run(scraper.process_entities())

    assert result["checked"] == 0
    assert result["confirmed"] == 0


def test_entity_linker_skips_same_campaign_fanout_for_large_campaign(monkeypatch):
    linker = EntityLinker.__new__(EntityLinker)
    linker.db = None
    linker.config = {}
    linker.rel_config = {}
    linker.min_confidence = 0.5
    linker.same_campaign_max_entities = 4
    linker.same_campaign_max_pairs = 6

    upsert_calls: list[tuple[int, int]] = []
    monkeypatch.setattr(
        linker,
        "_upsert_relationship",
        lambda source_id, target_id, rel_type, confidence, evidence, additional_count=1: upsert_calls.append((source_id, target_id)) or 1,
    )

    created = linker.link_from_campaigns(
        [{"id": 99, "entity_ids": [1, 2, 3, 4, 5], "campaign_type": "investment"}]
    )

    assert created == 0
    assert upsert_calls == []


def test_entity_linker_links_same_campaign_pairs_within_limits(monkeypatch):
    linker = EntityLinker.__new__(EntityLinker)
    linker.db = None
    linker.config = {}
    linker.rel_config = {}
    linker.min_confidence = 0.5
    linker.same_campaign_max_entities = 10
    linker.same_campaign_max_pairs = 10

    upsert_calls: list[tuple[int, int, str]] = []

    def _record_call(source_id, target_id, rel_type, confidence, evidence, additional_count=1):
        upsert_calls.append((source_id, target_id, rel_type))
        return 1

    monkeypatch.setattr(linker, "_upsert_relationship", _record_call)

    created = linker.link_from_campaigns(
        [{"id": 7, "entity_ids": [3, 1, 2, 2], "campaign_type": "investment"}]
    )

    assert created == 3
    assert upsert_calls == [
        (1, 2, "same_campaign"),
        (1, 3, "same_campaign"),
        (2, 3, "same_campaign"),
    ]
