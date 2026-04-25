# FRAUD MVP — Project Blueprint
## Comprehensive Overview | 04/04/2026 | Kem + Bayang AI

---

## 1. WHAT IS FRAUD MVP?

A **fraud and scam intelligence platform** that continuously monitors Malaysian scam operations and delivers real-time alerts to Telegram.

**What it does:**
```
Scrapes 12+ sources 24/7  →  Extracts scam entities (phones, bank accounts, domains)
                              →  Clusters into campaigns
                              →  Verifies against PDRM Semakmule DB (288K+ records)
                              →  Sends structured alerts to Telegram
```

**Why it exists:**
- Scammers reuse phone numbers and bank accounts across victims
- No centralized, real-time public database for Malaysia
- Google Alerts and news sources are too slow and unstructured
- PDRM Semakmule exists but is a lookup tool, not an alert system

---

## 2. SYSTEM ARCHITECTURE

```
DAILY PIPELINE (7:00 AM MYT via systemd timer)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  ┌─────────────────────────────────────────────────────────────┐
  │  STEP 1: COLLECTION                                          │
  │                                                             │
  │  📰 RSS Feeds (12 sources)                                  │
  │     • Google Alerts (scam, phishing, OTP, investment fraud)   │
  │     • Malaysian news (Lowyat, Vocket, Free Malaysia Today)   │
  │     • Scambusters.org (US + global scam database)           │
  │                                                             │
  │  🌐 Web Scrapers                                            │
  │     • MyCERT Advisories (CyberSecurity Malaysia)             │
  │     • Consumer.org.my complaints                             │
  │     • PDRM Semakmule (stats + top-10 hot accounts)          │
  │                                                             │
  │  💬 Reddit (1,339 posts cached)                              │
  │     • r/MalaysianFinance, r/scams, r/CyberNews             │
  └─────────────────────────────────────────────────────────────┘
                            │
                            ▼
  ┌─────────────────────────────────────────────────────────────┐
  │  STEP 2: EXTRACTION                                         │
  │                                                             │
  │  LLM-powered entity extraction (Ollama Nemotron-Cascade 2)  │
  │     • Phone numbers (MY/SG/AU formats)                       │
  │     • Bank account numbers (MY bank prefix ID)               │
  │     • Domain names                                          │
  │     • URLs                                                  │
  │     • Email addresses                                        │
  │                                                             │
  │  Deduplication: Same entity from same source = skip         │
  └─────────────────────────────────────────────────────────────┘
                            │
                            ▼
  ┌─────────────────────────────────────────────────────────────┐
  │  STEP 3: SCORING                                            │
  │                                                             │
  │  5-stage campaign clustering                                 │
  │     1. Build entity graph (entity ↔ channel co-occurrence)  │
  │     2. Connected components (campaigns)                     │
  │     3. Reuse scoring (shared entities = higher risk)        │
  │     4. Cross-platform scoring (same entity across sources)  │
  │     5. Risk classification (low → critical)                 │
  │                                                             │
  │  Risk Levels:                                               │
  │     • CRITICAL: Score 90-100, entity reuse >20, banks+phones│
  │     • HIGH:     Score 70-89, reuse 10-20                   │
  │     • MEDIUM:   Score 40-69, reuse 5-10                    │
  │     • LOW:      Score 1-39, singletons or no reuse          │
  └─────────────────────────────────────────────────────────────┘
                            │
                            ▼
  ┌─────────────────────────────────────────────────────────────┐
  │  STEP 4: ALERTING                                           │
  │                                                             │
  │  Telegram alerts via Bot API                                 │
  │     • Entity breakdown (phones, banks, domains, URLs)        │
  │     • PDRM Semakmule verification status                     │
  │     • Bank identification (Maybank, CIMB, Public Bank...)     │
  │     • Phone carrier/country info                            │
  │     • Actionable advice per scam type                       │
  │     • Source channels listed                                │
  │                                                             │
  │  Deduplication: Same campaign = skip (alert_sent flag)      │
  └─────────────────────────────────────────────────────────────┘
```

---

## 3. DATA SOURCES

### 3.1 Google Alerts — 6 Feeds

| Alert | Query | Coverage |
|-------|-------|----------|
| 🇲🇾 Scam Malaysia | `malaysia scam` | General scam mentions |
| 🔐 Phishing | `malaysia phishing bank` | Phishing attacks |
| 🏦 Bank Fraud | `malaysia bank fraud otp` | OTP/banking fraud |
| 💰 Investment Fraud | `malaysia investment fraud` | Investment scams |
| 📱 Phone Scam | `malaysia scam call` | Phone/walk-in scams |
| 💼 Job Task Scam | `malaysia job task scam` | Job task scams |

### 3.2 Malaysian News — 5 Sources

| Source | Platform | URL |
|--------|----------|-----|
| Lowyat.NET | RSS | lowyat.net/feed |
| The Vocket | RSS | thevocket.com/feed |
| Free Malaysia Today | RSS | freemalaysiatoday.com/feed |
| Astro Awani | RSS | astroawani.com/feed |
| Sinar Harian | RSS | sinarharian.com.my/feed |

### 3.3 Government / Security

| Source | Type | Access |
|--------|------|--------|
| **PDRM Semakmule** | Scam DB (bank + phone) | Public API ✅ |
| MyCERT Advisories | Incident alerts | Web scraper ✅ |
| MyCERT Fraud Alerts | Fraud advisories | Web scraper ✅ |
| Consumer.org.my | Complaints | Web scraper ✅ |

### 3.4 Community / International

| Source | Type | Coverage |
|--------|------|----------|
| Scambusters.org | Scam database | RSS ✅ |
| Reddit (5 subreddits) | User reports | JSON API ✅ |

---

## 4. PDRM SEMAKMULE — Data Source

**The gold standard for Malaysian scam data.**

### What it has:
```
🏦 Bank Accounts:  288,239 verified scam accounts
📱 Phone Numbers:   227,125 verified scam numbers
🌐 Web:             https://semakmule.rmp.gov.my
```

### API Access:
```
Endpoint:  POST https://semakmule.rmp.gov.my/api/mule/get_search_data.php
Headers:   User-Agent, Content-Type: application/json
Body:      {"data": {"category": "bank", "bankAccount": "512802774281"}}
           {"data": {"category": "telefon", "telNo": "0112345678"}}

Response:  {"status": 1, "count": N, "table_data": [[account, report_count], ...]}
```

### Top Scam Accounts (as of 04 Apr 2026):

| Bank Account | Reports | 
|-------------|---------|
| 512802774281 | 47 |
| 17900052144 | 20 |
| 000 (demo/test) | 16 |
| 26700077605 | 15 |
| 1013041100083926 | 15 |
| 26444100022578 | 14 |
| 25810500018077 | 14 |
| 21220000087743 | 14 |

### How the Pipeline Uses It:

1. **Collection:** SemakMule scraper runs daily → fetches stats + top-10 hot accounts
2. **Verification:** Each extracted phone/bank is cross-checked against SemakMule
3. **Alerting:** Results embedded in Telegram alerts as `[PDRM VERIFIED — N reports 🚨]`

---

## 5. TELEGRAM ALERTS — Output

### Alert Template:

```
🔥 SCAM ALERT — Investment Fraud (CRITICAL)
📌 10 key entities flagged across 5 sources
 └─ 📱 4 phones └─ 🏦 4 bank accounts └─ 🌐 1 domain └─ 🔗 1 URL

📋 What we found:
 └─ 📱 🇲🇾 +6011-234 5678 (seen 13x) [PDRM VERIFIED — 47x 🚨]
 └─ 📱 🇲🇾 +6019-876 5432 (Maxis/Hotlink)
 └─ 🏦 6012 3456 789 (RHB Bank) [PDRM VERIFIED — 12x 🚨]
 └─ 🏦 1234 5678 9012 (Maybank) [PDRM VERIFIED — 8x 🚨]
 └─ 🌐 Scam domain: fake-bank.xyz
 └─ 🔗 https://fake-bank.xyz/login

🔑 Keywords: login, verify account, OTP

📍 Sources: MySCAM.info, Scam.com.my, Scamwatcher.com

📅 Detected: 2026-04-04

✅ Action: Block reported scam numbers / Verify bank account before transaction
```

### Phone Number Intelligence:

| Field | Example |
|-------|---------|
| E164 format | `+601112345678` |
| National format | `011-234 5678` |
| Country flag | 🇲🇾 Malaysia |
| Carrier | Maxis/Hotlink (from prefix) |
| Semakmule reports | `[PDRM VERIFIED — 47x 🚨]` |

### Bank Account Intelligence:

| Field | Example |
|-------|---------|
| Formatted | `5128 0277 4281` |
| Bank name | Maybank (from prefix `12`) |
| SWIFT code | MBBEMYKL |
| Semakmule reports | `[PDRM VERIFIED — 47x 🚨]` |

---

## 6. DATABASE SCHEMA

```
┌─────────────────────┐
│    entities         │  ← Unique scam entities (phones, banks, domains...)
├─────────────────────┤
│ id                  │
│ value               │  ← e.g. "60112345678"
│ type                │  ← phone, bank_account, domain, url, email
│ first_seen          │
│ last_seen           │
│ count               │  ← times seen across all sources
│ campaign_id         │  ← FK to campaigns (NULL = not assigned)
│ metadata            │  ← JSON blob
└─────────────────────┘
         │
         │ 1:N
         ▼
┌─────────────────────┐
│   entity_edges      │  ← Where each entity was found
├─────────────────────┤
│ id                  │
│ entity_id           │
│ channel             │  ← "r/Dota2Trade", "MyCERT Advisories"
│ platform            │  ← "telegram", "reddit", "web"
│ channel_id          │
│ member_count        │
│ message_hash        │  ← dedup
│ timestamp           │
└─────────────────────┘

┌─────────────────────┐
│    campaigns        │  ← Clustered scam campaigns
├─────────────────────┤
│ id                  │
│ score               │  ← 1-100
│ risk_level          │  ← low, medium, high, critical
│ campaign_type       │  ← investment, job_task, phishing, unknown
│ entity_ids          │  ← JSON array of entity FKs
│ channel_ids         │  ← JSON array of channel names
│ keywords            │  ← matched keywords
│ reason              │  ← why it was scored this way
│ script_sample       │  ← sample text for similarity matching
│ first_seen          │
│ last_seen           │
│ alert_sent          │  ← 0/1, dedup flag
│ alert_sent_at       │
└─────────────────────┘

┌─────────────────────┐
│     sources         │  ← Tracked data sources
├─────────────────────┤
│ id                  │
│ name                │
│ url                 │
│ platform            │
│ type                │
│ reliability_score   │
│ tags                │
│ is_active           │
└─────────────────────┘

┌─────────────────────┐
│  scraped_messages   │  ← Raw scraped content (deduped)
├─────────────────────┤
│ id                  │
│ platform            │
│ channel             │
│ text                │
│ text_hash           │  ← UNIQUE constraint = dedup
│ scraped_at          │
└─────────────────────┘

┌─────────────────────┐
│    alert_log        │  ← Telegram delivery audit trail
├─────────────────────┤
│ id                  │
│ campaign_id         │
│ alert_level         │
│ message             │
│ sent_to             │  ← Telegram chat ID
│ sent_at             │
│ status              │  ← delivered, failed
│ response            │  ← Telegram API response
└─────────────────────┘

┌─────────────────────┐
│  semakmule_cache    │  ← Bot-only: Semakmule lookup cache
├─────────────────────┤
│ entity_type         │
│ entity_value        │
│ result              │  ← JSON: {found, count}
│ checked_at          │
└─────────────────────┘

┌─────────────────────┐
│   bot_reports       │  ← Bot-only: user-submitted scam reports
├─────────────────────┤
│ id                  │
│ report_id           │  ← RPT-YYYYMMDD-NNNN
│ entity_type         │
│ entity_value        │
│ scam_type           │
│ description         │
│ user_id             │
│ submitted_at        │
│ status              │  ← pending, approved, rejected
│ reviewed_by         │
│ reviewed_at         │
│ semakmule_checked   │
└─────────────────────┘

┌─────────────────────┐
│ bot_conversations   │  ← Bot-only: multi-step conversation state
├─────────────────────┤
│ user_id             │
│ state               │
│ data                │  ← JSON blob
│ started_at          │
│ updated_at          │
└─────────────────────┘
```

---

## 7. INFRASTRUCTURE

### 7.1 Docker Services

```yaml
services:
  redis:
    image: redis:7-alpine
    ports: "6379:6379"
    restart: unless-stopped

  app:
    build: ./Dockerfile
    ports: "8000:8000"
    environment:
      - REDIS_URL=redis://fraud-mvp-redis:6379
    profiles: [app]

  collector:
    build: ./Dockerfile
    command: python -m agents.collector
    profiles: [collector]

  scraper:
    build: ./Dockerfile
    command: python -m services.scraper.web_scraper
    profiles: [scraper]

  semakmule:
    build: ./Dockerfile
    command: python -m services.scraper.semakmule_scraper
    profiles: [scraper]

  fraud-bot:
    build: ./Dockerfile
    command: python -m agents.reporter_bot.bot
    profiles: [bot]
```

### 7.2 Cron / Scheduler

```
Daily: 7:00 AM MYT (23:00 UTC)
Systemd: fraud-mvp-daily.timer
Script:  fraud-mvp-daily-pipeline.sh
Log:     logs/pipeline.log
```

### 7.3 Environment Variables

```bash
# Core
REDIS_URL=redis://localhost:6379
DATABASE_URL=sqlite:///./db/fraud_mvp.db
OLLAMA_BASE_URL=http://127.0.0.1:11434
LOG_LEVEL=INFO

# Telegram
ALERT_BOT_TOKEN=8394214447:AAE...      # Alert delivery bot
TELEGRAM_BOT_TOKEN=8694119385:AAG...   # bayangx10files_bot (reporting bot)
ALERT_CHAT_ID=7684441863                # Kem's Telegram ID
ADMIN_CHAT_ID=7684441863

# Bot
BOT_TOKEN=8694119385:AAG...              # bayangx10files_bot
BOT_RATE_LIMIT_REQUESTS=20
BOT_RATE_LIMIT_SUBMISSIONS=5
BOT_CACHE_TTL_SECONDS=3600

# Demo/Safety
DEMO_MODE=false
API_ACCESS_TOKEN=Yb...                 # Auto-generated
```

---

## 8. API ENDPOINTS (FastAPI)

| Endpoint | Auth | Rate Limit | Description |
|----------|------|------------|-------------|
| `GET /health` | None | Unlimited | Health check |
| `GET /stats` | API Key | 60/min | System statistics |
| `GET /entities` | API Key | 60/min | List tracked entities |
| `GET /campaigns` | API Key | 60/min | List scam campaigns |
| `GET /alerts` | API Key | 60/min | List sent alerts |
| `GET /sources` | API Key | 60/min | List data sources |
| `POST /collect/trigger` | API Key | 10/min | Trigger collection |
| `POST /extract/trigger` | API Key | 10/min | Trigger extraction |
| `POST /score/trigger` | API Key | 10/min | Trigger scoring |

**Auth:** `X-API-Key: <token>` header (or `?api_key=<token>` query param)

---

## 9. REPORTING BOT — Telegram Bot

**Bot:** [@bayangx10files_bot](https://t.me/bayangx10files_bot)
**Purpose:** Let users submit and verify suspect phone numbers and bank accounts

### Commands:

| Command | Description |
|---------|-------------|
| `/start` | Welcome + quick stats |
| `/help` | Full usage guide |
| `/report <phone/bank>` | Verify against PDRM Semakmule |
| `/report <phone/bank> -r` | Report as scam (triggers admin review) |
| `/submit` | Multi-step guided report submission |
| `/stats` | Semakmule database statistics |
| `/check` | Re-check last submitted number |
| `/latest` | 10 most reported numbers |
| `/cancel` | Cancel current conversation |

### Admin Commands:

| Command | Description |
|---------|-------------|
| `/pending` | List pending reports |
| `/approve <id>` | Approve + forward to PDRM |
| `/reject <id>` | Dismiss report |
| `/ban <user_id>` | Ban user |

### Bot Status:
```
Phase 1:  ✅ Blueprint created
Phase 2:  ⏳ Pending implementation
Phase 3:  ⏳ Pending implementation
```

---

## 10. PRODUCTION FIXES APPLIED

All critical/high issues from production audit have been fixed:

| Phase | Issues Fixed |
|-------|-------------|
| **Phase 1** | Dockerfile created, Docker Compose updated, Redis networking fixed |
| **Phase 2** | API authentication (X-API-Key), rate limiting (slowapi) |
| **Phase 3** | Semakmule N+1 → parallel async (9x faster), Redis connection pooling, campaign_id index |
| **Phase 4** | datetime.utcnow() deprecated fixes (9 files), pipeline error handling, schema migrations, dead channel cleanup, demo mode defaults |

### Performance Improvements:
```
Semakmule lookup:  15s → 1.6s (10 accounts, parallel async)
Redis pooling:     New connections per call → shared ConnectionPool(max=20)
DB scan:           Full table scan on campaign_id → index scan
```

---

## 11. PROJECT FILES

```
fraud-mvp/
├── agents/
│   ├── __init__.py
│   ├── collector.py          # Orchestrates all collectors
│   ├── rss_collector.py      # RSS feed scraper (12 feeds)
│   ├── reddit_collector.py    # Reddit JSON API scraper
│   ├── extractor.py           # LLM-powered entity extraction
│   ├── scorer.py             # Campaign clustering + scoring
│   ├── alerter.py            # Telegram alert formatter + sender
│   └── reporter_bot/         # [PLANNED] Telegram reporting bot
│       ├── bot.py
│       ├── conversation.py
│       ├── services/
│       │   ├── semakmule.py
│       │   ├── phone.py
│       │   ├── bank.py
│       │   └── submission.py
│       ├── models/
│       └── admin/
│
├── services/
│   ├── queue_handler.py       # Redis queue (LPUSH/RPOP FIFO)
│   ├── llm_similarity.py      # Ollama similarity scorer (not yet wired)
│   └── scraper/
│       ├── web_scraper.py     # MyCERT, Consumer.org.my
│       ├── telegram_scraper.py # Telegram (Telethon-based)
│       ├── reddit_scraper.py  # Reddit (PRAW-based)
│       └── semakmule_scraper.py # PDRM Semakmule API
│
├── api/
│   └── main.py               # FastAPI REST API
│
├── db/
│   ├── database.py            # SQLite wrapper (all tables)
│   ├── schema.sql             # Schema definition
│   └── fraud_mvp.db          # SQLite database
│
├── config/
│   ├── sources.yaml           # Data source definitions
│   └── keywords.yaml          # Scam keyword list
│
├── logs/
│   └── pipeline.log           # Daily pipeline logs
│
├── fraud-mvp-daily-pipeline.sh  # Cron entry point script
├── docker-compose.yaml          # Multi-service Docker config
├── Dockerfile                   # Python 3.12 container image
├── requirements.txt             # Python dependencies
├── .env                         # Environment variables
├── .env.docker                  # Docker-specific overrides
├── .dockerignore                # Build context exclusions
└── fraud-bot-blueprint-v1.md   # Bot implementation blueprint
```

---

## 12. CURRENT STATUS

```
┌────────────────────────────────────────────────────────┐
│  FRAUD MVP — STATUS SUMMARY                            │
│  Updated: 04/04/2026                                  │
├────────────────────────────────────────────────────────┤
│                                                        │
│  🔄 DAILY PIPELINE         ✅ OPERATIONAL              │
│     • Collector        ✅ 12 sources, RSS + web        │
│     • Extractor        ✅ LLM entity extraction        │
│     • Scorer           ✅ 5-stage campaign clustering  │
│     • Alerter          ✅ Telegram delivery            │
│                                                        │
│  📊 DATA                      ✅ ACCUMULATING          │
│     • Entities         3,150+ tracked                  │
│     • Campaigns        21 detected (all risk levels)  │
│     • Sources          13 active                        │
│     • Reddit posts     1,339 cached                     │
│                                                        │
│  🔍 PDRM SEMAKMULE         ✅ INTEGRATED               │
│     • Bank accounts     288,239 verified               │
│     • Phone numbers     227,125 verified               │
│     • Top-10 scraping  ✅ Daily                         │
│     • Entity verify     ✅ Embedded in alerts           │
│                                                        │
│  ⏰ DAILY SCHEDULE         ✅ CONFIGURED                │
│     • Timer:           fraud-mvp-daily.timer           │
│     • Schedule:        7:00 AM MYT daily (23:00 UTC)    │
│     • Next run:        Tomorrow 07:00 MYT              │
│                                                        │
│  🌐 API                     ✅ RUNNING                  │
│     • Auth:            X-API-Key required             │
│     • Rate limits:     60/min reads, 10/min writes    │
│     • Endpoints:       9 total                         │
│                                                        │
│  🤖 TELEGRAM BOT           📋 BLUEPRINT READY          │
│     • Bot:             @bayangx10files_bot             │
│     • Phase 1-3:       Awaiting verification          │
│                                                        │
│  🐳 DOCKER                 ✅ BUILDABLE                  │
│     • Image:           fraud-mvp:latest               │
│     • Services:        redis, app, collector, scraper  │
│                                                        │
└────────────────────────────────────────────────────────┘
```

---

## 13. WHAT'S NEXT

### Immediate (Pre-Production)
- [ ] Verify Fraud Bot Blueprint with Kem
- [ ] Implement Fraud Bot Phase 1 (Semakmule lookup only)
- [ ] Implement Fraud Bot Phase 2 (User submissions + admin review)
- [ ] Implement Fraud Bot Phase 3 (Integration + polish)
- [ ] Wire Ollama LLM similarity into scorer pipeline

### Future Roadmap
- [ ] Reddit real-time monitoring (not just cached posts)
- [ ] Telegram bot user-facing channel (public bot group)
- [ ] Approved bot reports → auto-forward to PDRM CCID
- [ ] Web dashboard (FastAPI admin panel)
- [ ] Email alerting (SMTP)
- [ ] Bulk PDRM report export

---

## 14. CREDITS

| | |
|--|--|
| **Project Lead** | Kem |
| **AI Assistant** | Bayang (OpenClaw) |
| **Framework** | Python 3.12, FastAPI, Redis, SQLite |
| **LLM** | Ollama (Nemotron-Cascade 2, local) |
| **Data** | PDRM CCID Semakmule, MyCERT, Google Alerts |
| **Bot** | python-telegram-bot v21 |
| **Host** | ASUS Ascent GX10 (GB10 Grace Blackwell, 128GB) |

---

*Fraud MVP Blueprint — v1.0 — 04/04/2026*
