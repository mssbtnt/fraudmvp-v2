# Fraud & Scam Monitoring MVP

**OpenClaw-based fraud intelligence platform** — scrapes Telegram + web sources, extracts entities, scores risk, and alerts via Telegram.

> **Core principle:** You win by entity correlation and campaign detection, not by scraping more channels.

---

## Architecture

```
Data Sources
    │
    ├─ Web (MySCAM.info, KenaScam.com)
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
                    │  (scraping + deduplication)     │
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
│   ├── collector.py      # Collection + channel discovery
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

## Setup (3 Steps)

### 1. Install dependencies
```bash
cd /home/mssbai/Desktop/fraud-mvp
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure environment
```bash
cp .env.example .env
# Edit .env — set DEMO_MODE=false and add Telegram credentials for live scraping
```

### 3. Start services
```bash
docker compose up -d redis
python -m agents.collector
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
```

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
| Signal | Reddit, X | Victim reports |

---

*Built with OpenClaw · GX10 · Nemotron-Cascade 2*
