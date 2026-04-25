# Fraud & Scam Monitoring MVP

**OpenClaw-based fraud intelligence platform** — scrapes Telegram + supported web sources, extracts entities, scores risk, and alerts via Telegram.

> **Core principle:** You win by entity correlation and campaign detection, not by scraping more channels.

---

## Architecture

```
Data Sources
    │
    ├─ Web (MySCAM.info, KenaScam.com)
    ├─ OpenSanctions
    ├─ Telegram ──────────────────────────┐
    └─ Facebook/TikTok (Phase 2)         │
                                         ▼
                              ┌──────────────────────┐
                              │   Redis Queue       │
                              │  raw_messages       │
                              └──────────┬───────────┘
                                         ▼
                    ┌─────────────────────────────────┐
                    │  FraudCollectorAgent            │
                    │  (canonical collection)         │
                    └──────────┬──────────────────────┘
                               │ extracted_entities
                               ▼
                    ┌─────────────────────────────────┐
                    │  FraudExtractorAgent            │
                    │  (entity extraction + dedup)    │
                    └──────────┬──────────────────────┘
                               │ scored_entities
                               ▼
                    ┌─────────────────────────────────┐
                    │  FraudScorerAgent               │
                    │  (5-step detection pipeline)   │
                    └──────────┬──────────────────────┘
                               │ campaigns (threshold)
                               ▼
                    ┌─────────────────────────────────┐
                    │  FraudAlerterAgent              │
                    │  (Telegram campaign alert)     │
                    └─────────────────────────────────┘
```

---

## Project Structure

```
fraud-mvp/
├── agents/
│   ├── collector.py      # Canonical collection + channel discovery
│   ├── rss_collector.py  # RSS/raw-message collector
│   ├── reddit_collector.py # Research-only Reddit intelligence
│   ├── extractor.py      # Entity extraction (Week 2)
│   ├── scorer.py         # 5-step detection pipeline (Week 3)
│   └── alerter.py        # Alert formatting + delivery (Week 4)
├── config/
│   ├── sources.yaml      # Seed sources + Telegram keywords
│   ├── keywords.yaml     # Scam keyword dictionary by category
│   └── scoring_rules.yaml # Scoring thresholds + rules
├── db/
│   ├── schema.sql        # SQLite schema
│   └── database.py       # DB wrapper
├── services/
│   ├── scraper/
│   │   ├── telegram_scraper.py
│   │   └── web_scraper.py
│   └── queue_handler.py   # Redis queue utilities
├── api/
│   └── main.py           # FastAPI endpoints (Week 4)
├── docker-compose.yaml
├── requirements.txt
└── README.md
```

---

## Setup

### 1. Install dependencies
```bash
cd /home/mssbai/Desktop/fraud-mvp
python3 -m venv .venv && source .venv/bin/activate
python3 -m pip install -r requirements.txt
```

### 2. Configure environment
```bash
cp .env.example .env
# Edit .env
# Required for API: API_ACCESS_TOKEN
# Required for live Telegram scraping: DEMO_MODE=false plus Telegram credentials
```

### 3. Start services
```bash
docker compose up -d redis
python3 -m agents.collector
```

---

## Supported Local Workflows

### Run the full daily pipeline
```bash
./fraud-mvp-daily-pipeline.sh
```

The scheduled daily pipeline is intentionally bounded:
- LLM enhancement is disabled by default for timer-driven runs
- SemakMule is isolated from the main critical path

Recommended operational flow with Reddit:

```bash
./fraud-mvp-reddit-sidecar.sh
./fraud-mvp-daily-pipeline.sh
```

Run the Reddit promotion job shortly before the main pipeline so qualified Reddit posts are already in `raw_messages` for extraction.

Run SemakMule as a sidecar job when needed:

```bash
./fraud-mvp-semakmule-sidecar.sh
```

or:

```bash
make semakmule
```

### Run pipeline stages manually
```bash
python3 -m agents.rss_collector
python3 -m agents.collector --web-only
python3 -m agents.collector --opensanctions-only
python3 -m agents.collector --telegram-only --skip-snowball
python3 -m agents.reddit_collector
./fraud-mvp-reddit-sidecar.sh
python3 -m agents.extractor
python3 -m agents.scorer
python3 -m agents.alerter
```

### Run the API
```bash
uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload
```

Important:
- `/collect/trigger`, `/extract/trigger`, and `/score/trigger` are manual-only status endpoints.
- They do not enqueue background jobs.
- Use the shell commands above or the daily pipeline script to execute work.
- `agents.reddit_collector` is research-first by default.
- Reddit only enters the main pipeline when you run `python3 -m agents.reddit_collector --promote-qualified` or `./fraud-mvp-reddit-sidecar.sh`.
- Promotion is gated to high-relevance posts with hard entities and writes explicit Reddit provenance into `raw_json`.
- the daily pipeline now runs replay/enrichment after extraction using `services.pipeline ingest`

### Run tests
```bash
python3 -m pytest tests
```

---

## Week 1 Checklist

- [x] Project structure scaffolded
- [x] `docker-compose.yaml` with Redis
- [x] `config/sources.yaml` — seed sources + Telegram keywords
- [x] `config/keywords.yaml` — scam keyword dictionary
- [x] `config/scoring_rules.yaml` — rule-based scoring config
- [x] `db/schema.sql` — SQLite schema (entities, edges, campaigns, sources)
- [x] `agents/collector.py` — OpenClaw-style collector agent
- [x] `services/scraper/telegram_scraper.py` — Telegram scraper (demo mode)
- [x] `services/scraper/web_scraper.py` — web scraper for seed sources
- [x] `services/queue_handler.py` — Redis queue utilities
- [x] `db/database.py` — SQLite wrapper
- [ ] Run `python -m agents.collector` and verify queue fills
- [ ] (With credentials) Switch `DEMO_MODE=false` and scrape live

---

## Demo Mode

The system runs fully in demo mode without any API credentials. It simulates:
- Telegram channel discovery (10 pre-seeded channels)
- Telegram message scraping (10 pre-seeded scam messages per channel)
- Web source scraping (demo entities from MySCAM.info/KenaScam.com)

To enable live scraping, set in `.env`:
```
DEMO_MODE=false
TELEGRAM_API_ID=123456
TELEGRAM_API_HASH=your_hash
API_ACCESS_TOKEN=replace_with_a_long_random_token
```

## Operations

Operational notes are documented in:
- [_docs/OPERATIONS_RUNBOOK.md](/home/mssbai/Desktop/fraud-mvp/_docs/OPERATIONS_RUNBOOK.md)

## Reddit Promotion

Reddit is not a default collection source for the daily batch path because it is noisier than Telegram or OpenSanctions. The supported bridge is a gated promotion mode:

```bash
./fraud-mvp-reddit-sidecar.sh
```

Only posts meeting the configured thresholds in [config/sources.yaml](/home/mssbai/Desktop/fraud-mvp/config/sources.yaml) are promoted. The default policy requires:
- high scam relevance
- sufficient content length
- at least one hard entity such as a phone, bank account, WhatsApp link, or suspicious URL

Promoted Reddit posts are persisted to `scraped_messages`, published to `raw_messages`, and tagged with explicit Reddit provenance so downstream extraction and scoring can inspect the source.

For unattended schedules, run Reddit as a separate sidecar timer shortly before the main pipeline. Do not keep it in `ExecStartPre=` for the main service, because Playwright/login delays can block core alert delivery.

The daily pipeline also replays recent persisted messages after extraction, which keeps derived tables aligned before scoring. You can tune the replay window with:

```bash
PIPELINE_REPLAY_SINCE=2026-04-14 PIPELINE_REPLAY_LIMIT=5000 ./fraud-mvp-daily-pipeline.sh
```

For unattended timer runs, the pipeline defaults to deterministic scoring without LLM enrichment. This prevents a slow or unhealthy model backend from blocking the entire `Type=oneshot` schedule. To opt in manually:

```bash
FRAUD_LLM_ENABLED=true FRAUD_LLM_TIMEOUT_SECONDS=20 ./fraud-mvp-daily-pipeline.sh
```

SemakMule verification is intentionally decoupled from the timed main pipeline. It can still persist and publish canonical raw messages, but it should run as a separate sidecar because the upstream endpoint is operationally unstable.

## Telegram Session Bootstrap

Live Telegram collection uses a saved Telethon user session. Background services are non-interactive, so if the session expires they cannot answer phone/code prompts. Refresh the session manually with:

```bash
python3 scripts/bootstrap_telegram_session.py
```

If the background pipeline reports that the Telegram session is not authorized, run that command once from a real terminal and then let the timer continue normally.

---

## Key Blueprints

| Document | Location |
|----------|----------|
| Implementation Plan | `/home/mssbai/Desktop/docs/fraud-mvp-implementation-plan.md` |
| MVP Blueprint | `openclaw_fraud_mvp_blueprint---1e44524e-31a3-4bd6-8c07-992f27c7987b.md` |
| Production Architecture | `openclaw_production_architecture---ecaf19f5-90bf-49b0-bb14-36ad6341451e.md` |
| Strategic Blueprint | `Scam_Detection_Strategy_Blueprint---dc2ac7a1-bc30-4cca-af07-1c0bbe124e95.pdf` |

---

## Metrics (2-Week Target)

| Metric | Target |
|--------|--------|
| Channels tracked | 50–150 |
| Entities collected | 500–2,000 |
| Campaigns detected | 10–30 |
| Alerts/day | 20–100 |
| End-to-end latency | < 10 min |
| Extraction accuracy | > 85% |
| False positive rate | < 25% |

---

## Fraud Funnel

| Layer | Platform | Role |
|-------|----------|------|
| Acquisition | Facebook, TikTok | Early scam narratives |
| **Core** | **Telegram** | Entity/script reuse |
| Conversion | WhatsApp | 1-to-1 execution (out of scope) |
| Signal | Reddit, X | Supplemental research only |

---

*Built with OpenClaw · GX10 · Nemotron-Cascade 2*
