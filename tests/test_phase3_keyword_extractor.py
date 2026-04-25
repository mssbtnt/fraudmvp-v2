from __future__ import annotations

import sys
import types

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

from services.llm_similarity import KeywordExtractor


def test_keyword_extractor_uses_real_yaml_phrases():
    extractor = KeywordExtractor()

    matches = extractor.extract("Jawatan kosong, whatsapp link sekarang. Kerja sambilan mudah.")
    assert "job_task" in matches
    terms = {kw for kw, _ in matches["job_task"]}
    assert "jawatan kosong" in terms
    assert "whatsapp link" in terms
    assert extractor.keyword_score("Jawatan kosong, whatsapp link sekarang.") > 0


def test_keyword_extractor_applies_regex_patterns():
    extractor = KeywordExtractor()

    matches = extractor.extract("Hubungi kami di https://wa.me/60123456789 dan layari promo.xyz sekarang.")
    flat = {kw for kws in matches.values() for kw, _ in kws}
    assert "regex:whatsapp_link" in flat
    assert "regex:suspicious_tld" in flat


def test_keyword_extractor_applies_exclusion_penalties():
    extractor = KeywordExtractor()

    risky_score = extractor.keyword_score("jawatan kosong whatsapp link")
    safer_score = extractor.keyword_score("jawatan kosong whatsapp link kerja tetap kwsp socso gaji bulanan")

    assert risky_score > safer_score


def test_keyword_extractor_top_category_for_aid_gov_text():
    extractor = KeywordExtractor()

    category, score = extractor.top_category("Bantuan kerajaan BKM RM500 untuk anda. Sila daftar sekarang.")
    assert category == "aid_gov"
    assert score > 0
