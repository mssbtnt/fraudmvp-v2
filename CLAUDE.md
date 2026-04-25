# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Fraud MVP** is a fraud intelligence platform targeting Malaysia and Southeast Asia. It scrapes Telegram and supported web sources, uses a gated Reddit promotion bridge for high-confidence Reddit posts, extracts entities (phone numbers, bank accounts, domains, URLs, emails), clusters them into campaigns via a multi-step scoring pipeline, and delivers alerts via Telegram.

**Core principle:** Entity correlation and campaign detection win — not volume of scraped channels.

---

## Running the Pipeline

```bash
# Full supported batch path
./fraud-mvp-daily-pipeline.sh

# Optional gated Reddit promotion
python3 -m agents.reddit_collector --promote-qualified

# Manual stage execution
python3 -m agents.rss_collector
python3 -m agents.collector --web-only
python3 -m agents.collector --opensanctions-only
python3 -m agents.collector --telegram-only --skip-snowball
python3 -m services.pipeline ingest
python3 -m agents.scorer
python3 -m agents.alerter

# API server (FastAPI, port 8000)
python3 -m uvicorn api.main:app --host 0.0.0.0 --port 8000

# Redis must be running first
docker compose up -d redis
```

**Demo mode** (default): runs without real Telegram credentials. Set `DEMO_MODE=false` in `.env` to enable live scraping.
For live Telegram scraping, the saved Telethon session must also be authorized. Refresh it manually with `python3 scripts/bootstrap_telegram_session.py` when needed.

---

## Data Sources

The collector pulls from three categories:

| Source | Platform | Reliability | Entities |
|--------|----------|-------------|---------|
| Web seed sources (MyCERT, consumer.org.my) | web | High | phone, domain, url, email |
| **OpenSanctions BNM Consumer Alert** | opensanctions | 0.95 | domain, url, telegram_channel, phone, company_name |
| **OpenSanctions SC Investor Alert** | opensanctions | 0.90 | domain, url, telegram_channel, phone, company_name |
| Telegram (keyword discovery + channel scraping) | telegram | Varies | All entity types |
| Reddit (gated promotion only) | reddit | Medium | phone, bank, url, email |

Both OpenSanctions lists are government-authoritative (Bank Negara Malaysia, Securities Commission Malaysia) and are fetched as NDJSON from `data.opensanctions.org` on every collector run. They are added to `config/sources.yaml` as `platform: opensanctions` entries and handled by `OpenSanctionsScraper`.

```
Data Sources (web, Telegram, gated Reddit promotion)
        ↓
raw_messages (Redis queue)
        ↓
FraudCollectorAgent / Reddit promotion  ← canonical raw-message persistence + queue publish
        ↓
extracted_entities (Redis queue)
        ↓
FraudExtractorAgent  ← regex entity extraction, scam type classification
        ↓
services.pipeline ingest  ← replay/enrichment from scraped_messages
        ↓
FraudScorerAgent  ← scoring + campaign creation
        ↓
alerts (Redis queue, threshold ≥60)
        ↓
FraudAlerterAgent  ← formats + delivers Telegram alerts and daily reports
```

### Scoring Pipeline (scorer.py)

1. **Entity Graph** — builds node/edge graph from DB (entities + entity_edges)
2. **Frequency Scoring** — entity count ≥3 → +40, ≥4 → +50
3. **Temporal Clustering** — cross-channel 24h → +30, cross-platform → +40
4. **Content Similarity** — keyword matching + optional LLM script similarity
5. **Scam Type Classification** — keyword, LLM, and cross-reference fallback
6. **Cross-Reference Scoring** — BNM/SC/SemakMule boosts
7. **Victim Signal Scoring** — financial loss, police report, community warning
8. **Relationship Scoring** — shared phone/domain/co-occurrence
9. **Trend Scoring** — spike/rising/increasing adjustments

### Key Files

| File | Role |
|------|------|
| `agents/collector.py` | Scrapes web + Telegram + OpenSanctions; discovers channels via keyword search and snowball pivot |
| `agents/reddit_collector.py` | Research-first Reddit runner with optional gated promotion into `scraped_messages` + `raw_messages` |
| `agents/extractor.py` | Extracts entities via regex; classifies scam type; deduplicates cross-type (phone≈bank by digit overlap) |
| `agents/scorer.py` | Scoring pipeline; clusters entities into campaigns; pushes alertable campaigns into `alerts` |
| `agents/alerter.py` | Imports from `services.alert_formatter`; handles Telegram delivery and daily-report state machine |
| `services/alert_formatter.py` | All alert formatting logic, Malaysian bank/phone reference data, Telegram API calls |
| `services/daily_report.py` | Daily report state machine for `alerts_found` / `no_recent_data` / `pipeline_failure` |
| `services/llm_similarity.py` | Ollama client for embeddings; `ScriptSimilarityScorer` + `KeywordExtractor` |
| `services/scraper/opensanctions_scraper.py` | Downloads + parses BNM + SC government alert lists from OpenSanctions (NDJSON); extracts domains, URLs, Telegram channels, phones, company names |
| `services/scraper/telegram_scraper.py` | Telethon-backed Telegram scraping; now fails fast without interactive prompts when the session is unauthorized |
| `db/database.py` | SQLite wrapper; `upsert_entity`, `add_entity_edge`, `upsert_campaign`, `get_edges_for_entities` (batch) |
| `config/sources.yaml` | Seed web sources (including OpenSanctions BNM + SC entries), Telegram discovery hubs, platform weights |
| `config/keywords.yaml` | Scam keywords by category (investment, job_task, aid_gov, urgency, phishing) with weights |
| `config/scoring_rules.yaml` | Frequency/temporal/similarity thresholds, risk tier cutoffs |

---

## Database Schema

SQLite at `db/fraud_mvp.db`. Key tables:
- **entities** — `(value, type)` unique; `count`, `campaign_id`, `metadata` JSON
- **entity_edges** — `(entity_id, channel, platform, timestamp)`; records every appearance
- **campaigns** — `entity_ids` + `channel_ids` as JSON arrays; `score`, `risk_level`, `alert_sent`
- **scraped_messages** — deduped by `text_hash`
- **alert_log** — delivery status per campaign

The `Database._ensure_schema()` method runs `CREATE TABLE IF NOT EXISTS` on every instantiation, making it idempotent and self-migrating.

---

## Data Flow Conventions

- Queues use **LPUSH + RPOP** (FIFO). Queue names: `raw_messages`, `extracted_entities`, `alerts`
- `ExtractedEntity.to_json()` embeds `entity_id` (set by extractor after upsert) so the scorer avoids re-looking up entities
- `scorer._drain_extracted_queue()` trusts the `entity_id` in the queue message — no `get_entity_by_value()` lookup needed
- `alerter` always reloads campaign + entity data from DB in `process_alert()` for authoritative state
- API trigger endpoints are informational only; background execution is managed by a `systemd --user` timer/service

---

## Malaysian Market Reference Data

- **Bank identification**: IBG 4-digit prefix lookup (`BANK_CODE_PREFIXES` in extractor, `MALAYSIAN_BANKS` in formatter) + length-based fallback
- **Phone carriers**: 2-digit prefix lookup (`MALAYSIAN_MOBILE_PREFIXES`) — simplified to "Malaysian mobile" since number portability means any prefix can be any telco
- **Phone risk tiers**: country code → risk level (critical: Myanmar 95, Cambodia 855, Laos 856; high: West Africa, Caribbean NANP lookalikes; medium: India, Russia, Eastern Europe)
- **Suspicious TLDs**: `.xyz, .top, .club, .online, .site, .click, .link, .work, .loan, .download, .stream, .cfd, .gq, .ml, .tk, .pw`
- **Complaint sources**: `consumer.org.my`, GASO — entities here are *victim-posted*; `_is_complaint_source()` filters out legitimate org emails/URLs

---

## Environment Variables

Key variables in `.env` (see `.env.example` for full list):

| Variable | Default | Notes |
|----------|---------|-------|
| `DEMO_MODE` | `true` | Set `false` for live Telegram scraping |
| `REDIS_URL` | `redis://localhost:6379` | |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Local LLM for embeddings |
| `OLLAMA_MODEL` | `nemotron-cascade-2:latest` | |
| `ALERT_BOT_TOKEN` | — | Telegram bot for alert delivery |
| `ALERT_CHAT_ID` | — | Target Telegram chat |
| `API_ACCESS_TOKEN` | — | Required for API endpoints; server fails fast if missing |
| `REDDIT_EMAIL` / `REDDIT_PASSWORD` | — | Optional for Reddit research/promoted scraping |

---

## API

FastAPI on port 8000. All endpoints except `/health` require `X-API-Key` header or `?api_key=` query param.

Key endpoints:
- `GET /stats` — counts, queue depth, queue backend status, recent activity, freshness
- `GET /status` — operator-focused runtime status
- `GET /entities?type=&limit=` — list entities with channels (uses batch `get_edges_for_entities`)
- `GET /campaigns?risk=&limit=` — list campaigns
- `POST /collect/trigger`, `/extract/trigger`, `/score/trigger` — manual-only informational endpoints (rate limited 10/min)

Rate limits: 60/min reads, 10/min writes per IP. CORS origins configurable via `CORS_ORIGINS` env var.

---

## Important Patterns

- **Redis graceful degradation**: `QueueHandler` catches `ConnectionError` and falls back to no-op mode — pipeline won't crash if Redis is down
- **DB context manager**: always use `with db.conn() as conn:` for automatic commit/rollback
- **Extractor cross-type dedup**: strip non-digits and compare; phone vs bank accounts sharing the same 9-12 digit string are de-duplicated (bank wins)
- **Scorer campaign dedup**: `visited` set on outer loop tracks globally assigned entities across BFS runs; inner BFS uses a separate per-cluster `visited` set initialized from seed entity
- **`_to_dict()` in collector**: checks `__dataclass_fields__` first (dataclasses), then `to_dict()`, then `__dict__`, then `dict` — in that priority order
