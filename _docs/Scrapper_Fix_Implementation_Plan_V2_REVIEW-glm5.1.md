# FraudMVP V2 — Implementation Review

## Executive Summary

Phases 1–10 are structurally in place: canonical raw message contract, `scraped_messages` persistence, Telegram/Reddit collectors, daily pipeline, alert state machine, healthcheck, backfill scripts, schema migrations, and comprehensive tests. The architecture is sound and the V2 plan has been largely implemented.

There are however **6 confirmed runtime bugs**, **8 high-severity configuration inconsistencies**, and **7 structural issues** that need attention before production use.

---

## Confirmed Runtime Bugs

### Bug 1 — `AttributeError`: `CATEGORY_WEIGHTS` missing
**File:** `services/victim_signal.py:336`  
**Severity:** High

`CATEGORY_WEIGHTS` is referenced but only `CATEGORY_CAPS` exists. The LLM victim signal pass will crash with `AttributeError` on every detection.

---

### Bug 2 — `AttributeError`: `_format_related_entities` outside class
**File:** `services/alert_builder.py:520`  
**Severity:** High

`_format_related_entities` method body is defined outside the class (after the `if __name__` block). Calling `format_for_telegram()` → `_format_related_entities()` raises `AttributeError`.

---

### Bug 3 — `NameError`: `nodes` out of scope
**File:** `agents/scorer.py:843`  
**Severity:** High

`nodes` is referenced in `run()` but only defined inside `_score_cluster()`. Will crash with `NameError` when recording entity mentions.

---

### Bug 4 — `RuntimeError`: shared `httpx` client closed after first use
**File:** `services/scraper/web_scraper.py:221,287`  
**Severity:** High

`async with self.client as c:` closes the shared `httpx` client after the first call. Any subsequent call to `_scrape_mycert()` or `_scrape_consumer_org()` raises `RuntimeError: client closed`.

---

### Bug 5 — `raw_json` serialised with `str()` instead of `json.dumps()`
**File:** `agents/rss_collector.py:304`  
**Severity:** Medium

`raw_json=str(art)` uses Python's `str()` instead of `json.dumps()`. Downstream JSON parsing of `raw_json` will fail.

---

### Bug 6 — `PARTIAL_RUN_STALE_RESULTS` state is unreachable
**File:** `services/daily_report.py:107–108`  
**Severity:** Medium

The condition requires `scoring_failed=True` and scoring `success=True` simultaneously — a logical contradiction. This state can never be entered.

---

## Configuration Inconsistencies

### 1. Risk Threshold Mismatch *(Critical)*

Three different threshold maps coexist:

| Source | Low | Medium | High | Critical |
|--------|-----|--------|------|----------|
| `scoring_rules.yaml` | 40 | 60 | 80 | 95 |
| `alert_builder.py` | 30 | 50 | 70 | 90 |
| `pipeline.yaml` | — | 60 | — | — |

A campaign scoring 80 is classified as *High* by the scorer but *Critical* by the alert builder. Operators see alerts classified differently than the scorer intended. This was explicitly flagged in the V2 plan (Section 6, item 9) and remains unfixed.

**Fix:** Use `scoring_rules.yaml` as the single source of truth. `alert_builder.py` should read thresholds from config, not hardcode them.

---

### 2. Scam Type Mismatch

`keywords.yaml` defines 11 types (including `deposit_scam`, `tng_scam`). `scam_types.yaml` and the DB `CHECK` constraint define exactly 10 canonical types. Messages tagged `deposit_scam` or `tng_scam` from keywords will be rejected with a constraint violation.

**Fix:** Add `deposit_scam → job_task` and `tng_scam → qr` to `campaign_types.py`'s `CAMPAIGN_TYPE_ALIASES`, or update the DB `CHECK` constraint.

---

### 3. Duplicated Configuration

Entity relationship weights, cross-reference boosts, victim signal boosts, and platform weights are duplicated between `scoring_rules.yaml` and `pipeline.yaml`. If either is updated without the other, they silently diverge.

**Fix:** Remove duplicates from `pipeline.yaml` and have all services read from `scoring_rules.yaml`.

---

### 4. Ollama Model Mismatch

| File | Model |
|------|-------|
| `.env.example` | `nemotron-cascade-2:latest` |
| `pipeline.yaml` | `gemma4:31b` |
| `llm_similarity.py` (default) | `nemotron-cascade-2` |
| `llm_enhancer.py` (default) | `gemma4:31b-cloud` |

If LLM is enabled, the wrong model may be used depending on which service initiates the call.

---

### 5. Alert Threshold Gap

`pipeline.yaml` defines `score_threshold: 60` and `alert_threshold: 70`. Campaigns scoring 60–69 are created but never alerted — these accumulate as invisible "zombie campaigns."

---

### 6. Real Chat ID in `.env.example`

`ALERT_CHAT_ID=7684441863` is a real Telegram chat ID committed to a version-controlled template file.

---

## Architecture Issues

### 1. Schema Drift: `database.py` vs `schema.sql`

`database.py._ensure_schema()` creates 6 tables. `schema.sql` defines 11 tables. The 5 Phase 2 tables (`cross_references`, `victim_signals`, `entity_mentions`, `campaign_links`, `entity_relationships`) only exist if `schema.sql` was run manually. However, `database.py.reset_derived_tables()` references all 5 — it will fail with `OperationalError: no such table` on a fresh DB.

**Fix:** Add the 5 Phase 2 tables to `database.py._ensure_schema()`, or add a startup check that runs `schema.sql` if tables are missing.

---

### 2. Redis Permanent Failure Flag

`queue_handler.py:73` sets `_client_failed = True` globally when Redis connection fails. This flag is permanent for the process lifetime — even if Redis recovers, the queue handler stays in no-op mode.

**Fix:** Replace the global failure flag with `redis-py`'s built-in retry:

```python
from redis.backoff import ExponentialBackoff
from redis.retry import Retry
from redis.client import Redis

r = Redis(
    host='localhost',
    port=6379,
    retry=Retry(ExponentialBackoff(), 3),
    retry_on_error=[ConnectionError, TimeoutError],
)
```

---

### 3. Non-Canonical Message Formats

| Collector | Uses `RawMessage` | Pushes to Pipeline |
|-----------|:-----------------:|:------------------:|
| `collector.py` | ✅ Yes | ✅ Yes |
| `rss_collector.py` | ✅ Yes (buggy `raw_json`) | ✅ Yes |
| `group_collector.py` | ✅ Yes | ✅ Yes |
| `reddit_collector.py` | ✅ Yes | ✅ Yes |
| `semakmule_scraper.py` | ✅ Yes | ✅ Yes |
| `telegram_scraper.py` | ❌ Own `Message` class | ❌ No |
| `web_scraper.py` | ❌ Own `ScrapedEntity` class | ❌ No |
| `opensanctions_scraper.py` | ❌ Own `OpensanctionsEntity` class | ❌ No |
| `telegram_monitor.py` | ⚠️ Non-canonical dict | ✅ Yes (wrong format) |

`telegram_monitor.py` pushes non-canonical dicts directly to Redis `raw_messages`. Downstream extractors expecting `RawMessage` fields (`channel`, `channel_id`, `message_hash`, `raw_json`) receive `chat_title`, `chat_id`, etc. instead.

**Fix:** Convert `telegram_monitor.py` to produce `RawMessage` objects. Add a thin adapter layer in `collector.py` to transform `telegram_scraper.Message` and `web_scraper.ScrapeResult` into `RawMessage`.

---

### 4. SQLite Concurrency Risk

`docker-compose.yaml` mounts `./db:/app/db` as a shared volume between host and container. If the daily pipeline runs on the host while the API server writes inside the container, concurrent SQLite writes can corrupt the database. WAL mode mitigates this somewhat but is not sufficient for simultaneous writes from multiple processes.

---

### 5. No Dead-Letter Queue

`queue_handler.py` has no TTL on queue items and no dead-letter mechanism. If the extractor crashes mid-batch, those messages are lost from Redis. The `scraped_messages` persistence provides a recovery path, but there is no automated re-queuing.

---

### 6. API Rate Limiting Behind Proxy

`api/main.py` uses `get_remote_address` for rate limiting. Behind a reverse proxy, all traffic appears to originate from one IP. The app should use `X-Forwarded-For` in production.

---

### 7. FastAPI Missing Lifespan

The FastAPI app does not use a lifespan context manager. Per FastAPI documentation, startup/shutdown logic (DB connection pools, Redis connections, cross-reference engine loading) should use an `@asynccontextmanager`-decorated lifespan function rather than module-level globals created at import time.

---

## Daily Report State Machine

`daily_report.py` implements the state machine from the V2 plan. The four primary states are correct and match the spec. `determine_daily_report_state()` evaluates in this order:

1. `pipeline_failure` — if any required stage failed
2. `alerts_found` — if `alerts_triggered > 0`
3. `no_alerts_but_data_processed` — if fresh data was processed successfully
4. `no_recent_data` — fallthrough

The ordering is logically sound. The `PARTIAL_RUN_STALE_RESULTS` fifth state is implemented but unreachable due to its contradictory condition (Bug 6 above).

---

## Test Coverage Assessment

### Covered

- Import verification (14 modules)
- DB schema verification (11 tables, 16 columns, entity/campaign types)
- Data quality (garbage IDs, clone noise, BNM dates, type distribution)
- Service verification (cross-reference, victim signals, scam classifier, entity linker, campaign namer, trend detector, campaign types)
- Integration tests (scorer init, alerter init, campaign dataclass, pipeline classify→name, cross-ref→alert)
- Edge cases (empty, `None`, long, unicode, special characters)
- Performance benchmarks (5 checks)
- Phase 3 ingestion tests

### Missing

- `scraped_messages` persistence (V2 plan Phase 2 acceptance criteria)
- Pipeline replay from `scraped_messages`
- Daily report state machine
- `alert_builder.py._format_related_entities` (the broken method — Bug 2)
- `telegram_monitor.py` non-canonical message format
- `web_scraper.py` client-closing bug (Bug 4)
- `victim_signal.py` LLM pass / `CATEGORY_WEIGHTS` (Bug 1)
- `scorer.py` `nodes` `NameError` (Bug 3)

---

## Recommendations

### P0 — Fix Before Next Pipeline Run

1. **`victim_signal.py:336`** — Define `CATEGORY_WEIGHTS` or change the reference to `CATEGORY_CAPS`.
2. **`alert_builder.py:520`** — Move `_format_related_entities` back inside the class.
3. **`scorer.py:843`** — Replace `nodes` reference with an entity count lookup from DB.
4. **`web_scraper.py`** — Remove `async with self.client as c:` and use `self.client` directly.
5. **`.env.example`** — Remove the real `ALERT_CHAT_ID` value.

### P1 — Fix This Sprint

6. **Unify risk thresholds** — Make `alert_builder.py` read from `scoring_rules.yaml`.
7. **`rss_collector.py:304`** — Change `str(art)` to `json.dumps(art)`.
8. **Scam type aliases** — Add `deposit_scam → job_task` and `tng_scam → qr` to `CAMPAIGN_TYPE_ALIASES`.
9. **`database.py._ensure_schema()`** — Add the 5 Phase 2 tables.
10. **`telegram_monitor.py`** — Convert to produce canonical `RawMessage`.

### P2 — Fix Next Sprint

11. **`queue_handler.py`** — Add `redis-py` `Retry(ExponentialBackoff())`.
12. **`pipeline.yaml`** — Remove duplicated config; read from `scoring_rules.yaml`.
13. **`daily_report.py`** — Make `PARTIAL_RUN_STALE_RESULTS` reachable or remove it.
14. **Test coverage** — Add tests for persistence, replay, alert builder, and daily report state machine.
15. **`.dockerignore`** — Exclude `.venv/`, `db/`, `logs/`.

### P3 — Technical Debt

16. Add FastAPI lifespan for startup/shutdown (cross-ref engine loading, DB pool).
17. Consider PostgreSQL if concurrent writes become a requirement.
18. Fix `_normalise_domain` in `cross_reference.py` — use `startswith("www.")` not `replace`.
19. Fix Myanmar flag emoji in `alert_formatter.py`.
20. Unify Ollama model references across all services.