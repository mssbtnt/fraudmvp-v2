# Fraud MVP — High-Level System Architecture

**Prepared for:** CTO  
**Date:** 2026-04-26  
**Version:** 1.0  
**Classification:** Internal — Engineering Review

---

## 1. Executive Summary

Fraud MVP is an automated fraud intelligence platform purpose-built for Malaysia and Southeast Asia. It continuously monitors web sources, government alert lists, Telegram channels, and Reddit to detect emerging scam campaigns before they reach victims. The system extracts fraud indicators (phone numbers, bank accounts, domains, URLs), clusters them into campaigns using a multi-signal scoring engine, and delivers real-time alerts via Telegram.

**Key Value Propositions:**
- **Proactive Detection:** Identifies scam campaigns from early signals (3+ related entities) before mass victimization
- **Government-Grade Data:** Integrates authoritative sources (Bank Negara Malaysia, Securities Commission, PDRM SemakMule)
- **Multi-Platform Coverage:** Monitors Telegram, web, Reddit, and OpenSanctions in a single pipeline
- **Automated Alerting:** Delivers scored, evidence-backed alerts with confidence ratings

**Current Scale (MVP):**
- ~18,800 lines of Python across 70+ files
- 9-step scoring pipeline with 20+ signal types
- SQLite database (PostgreSQL-ready)
- Docker containerized with profile-based orchestration
- FastAPI REST API with authentication and rate limiting

---

## 2. System Architecture Overview

```
+-----------------------------------------------------------------------------+
|                           FRAUD MVP ARCHITECTURE                            |
|                    Fraud Intelligence Command Center                        |
+-----------------------------------------------------------------------------+

+-----------------------------------------------------------------------------+
|                              DATA SOURCES LAYER                               |
+-----------------------------------------------------------------------------+
|                                                                             |
|  +--------------+  +--------------+  +--------------+  +--------------+     |
|  |   MyCERT     |  | OpenSanctions|  |   Telegram   |  |    Reddit    |     |
|  |  Government  |  |   BNM + SC   |  |   Channels   |  |   Research   |     |
|  |   Advisories |  | Alert Lists  |  |  + Groups    |  |   + Promote  |     |
|  +------+-------+  +------+-------+  +------+-------+  +------+-------+     |
|         |                 |                 |                 |            |
|  Weight: 0.95      Weight: 0.95       Weight: 1.0       Weight: 0.5      |
|  Reliability: High  Reliability: High  Reliability: Var  Reliability: Med  |
|                                                                             |
|  Additional Sources: consumer.org.my, SemakMule (PDRM), RSS Feeds           |
|                                                                             |
+------------------------------+----------------------------------------------+
                               |
                               v
+-----------------------------------------------------------------------------+
|                           INGESTION LAYER                                   |
+-----------------------------------------------------------------------------+
|                                                                             |
|  +---------------------------------------------------------------+        |
|  |                    FraudCollectorAgent                         |        |
|  |                                                                |        |
|  |  +-------------+  +-------------+  +---------------------+  |        |
|  |  | WebScraper  |  |Telegram     |  | OpenSanctionsScraper  |  |        |
|  |  | (Playwright) |  |Scraper      |  | (BNM + SC NDJSON)    |  |        |
|  |  |             |  |(Telethon)   |  |                       |  |        |
|  |  +-------------+  +-------------+  +---------------------+  |        |
|  |                                                                |        |
|  |  Functions: Deduplication (text_hash), Queue Publishing,       |        |
|  |             Channel Discovery, Snowball Pivoting               |        |
|  +---------------------------------------------------------------+        |
|                                                                             |
|                         v raw_messages (Redis FIFO)                       |
|                                                                             |
+-----------------------------------------------------------------------------+
                               |
                               v
+-----------------------------------------------------------------------------+
|                         EXTRACTION LAYER                                    |
+-----------------------------------------------------------------------------+
|                                                                             |
|  +---------------------------------------------------------------+        |
|  |                    FraudExtractorAgent                         |        |
|  |                                                                |        |
|  |  Entity Extraction:        Regex-based pattern matching        |        |
|  |    * Phone numbers         Country-code aware validation       |        |
|  |    * Bank accounts         IBG prefix + length validation      |        |
|  |    * Domains / URLs        Suspicious TLD detection            |        |
|  |    * Email addresses       Domain reputation checking          |        |
|  |    * WhatsApp links        wa.me / wasap.my extraction       |        |
|  |    * QR codes              Visual + text detection             |        |
|  |                                                                |        |
|  |  Scam Classification:      3-tier fallback                       |        |
|  |    1. Keyword matching     (investment, job, phishing...)      |        |
|  |    2. LLM classification   (Ollama embeddings)                 |        |
|  |    3. Cross-reference      (BNM/SC/SemakMule)                |        |
|  |                                                                |        |
|  |  Cross-Type Deduplication: Phone ~ Bank by digit overlap         |        |
|  |                                                                |        |
|  +---------------------------------------------------------------+        |
|                                                                             |
|                    v extracted_entities (Redis FIFO)                        |
|                                                                             |
+-----------------------------------------------------------------------------+
                               |
                               v
+-----------------------------------------------------------------------------+
|                         ENRICHMENT LAYER                                    |
+-----------------------------------------------------------------------------+
|                                                                             |
|  +---------------------------------------------------------------+        |
|  |                 Pipeline Service (Replay/Ingest)               |        |
|  |                                                                |        |
|  |  * Replays scraped_messages for missed entities                |        |
|  |  * Enriches entity metadata (channel history, context)         |        |
|  |  * Backfills entity_edges for temporal analysis                |        |
|  |                                                                |        |
|  +---------------------------------------------------------------+        |
|                                                                             |
+-----------------------------------------------------------------------------+
                               |
                               v
+-----------------------------------------------------------------------------+
|                         SCORING LAYER (Core Engine)                         |
+-----------------------------------------------------------------------------+
|                                                                             |
|  +---------------------------------------------------------------+        |
|  |                    FraudScorerAgent                              |        |
|  |                                                                |        |
|  |  +--------------------------------------------------------+  |        |
|  |  |              9-Step Scoring Pipeline                     |  |        |
|  |  |                                                        |  |        |
|  |  |  Step 1: Entity Graph          Node/edge construction    |  |        |
|  |  |  Step 2: Frequency Scoring     Count thresholds (>=3)    |  |        |
|  |  |  Step 3: Temporal Clustering   Cross-channel 24h window  |  |        |
|  |  |  Step 4: Content Similarity    LLM script match >=80%    |  |        |
|  |  |  Step 5: Scam Type Classifier  3-tier classification     |  |        |
|  |  |  Step 6: Cross-Reference       BNM/SC/SemakMule boost      |  |        |
|  |  |  Step 7: Victim Signals        Financial loss, reports    |  |        |
|  |  |  Step 8: Relationships       Co-occurrence, shared phone |  |        |
|  |  |  Step 9: Trend Detection       Spike/rising detection    |  |        |
|  |  |                                                        |  |        |
|  |  |  Risk Thresholds:                                        |  |        |
|  |  |    * 0-39:   Log only                                    |  |        |
|  |  |    * 40-59:  Low priority alert                          |  |        |
|  |  |    * 60-79:  Medium priority alert                       |  |        |
|  |  |    * 80-94:  High priority alert                         |  |        |
|  |  |    * 95-100: Critical alert                              |  |        |
|  |  +--------------------------------------------------------+  |        |
|  |                                                                |        |
|  |  Output: Campaign clusters with scores, risk levels, evidence  |        |
|  +---------------------------------------------------------------+        |
|                                                                             |
|                      v alerts (Redis FIFO, threshold >=60)                  |
|                                                                             |
+-----------------------------------------------------------------------------+
                               |
                               v
+-----------------------------------------------------------------------------+
|                         ALERTING LAYER                                      |
+-----------------------------------------------------------------------------+
|                                                                             |
|  +---------------------------------------------------------------+        |
|  |                    FraudAlerterAgent                           |        |
|  |                                                                |        |
|  |  * Formats alerts with entity evidence and confidence scores   |        |
|  |  * Delivers via Telegram Bot API                               |        |
|  |  * Generates daily summary reports                             |        |
|  |  * Tracks delivery state in alert_log table                    |        |
|  |                                                                |        |
|  +---------------------------------------------------------------+        |
|                                                                             |
+-----------------------------------------------------------------------------+
                               |
                               v
+-----------------------------------------------------------------------------+
|                         CONSUMPTION LAYER                                   |
+-----------------------------------------------------------------------------+
|                                                                             |
|  +--------------+  +------------------------------------------+  |        |
|  |   Telegram   |  |           FastAPI REST API                 |  |        |
|  |    Alerts    |  |                                            |  |        |
|  |              |  |  Endpoints:                                |  |        |
|  |  Real-time   |  |  * GET  /health       - System health      |  |        |
|  |  delivery    |  |  * GET  /stats        - Pipeline metrics    |  |        |
|  |              |  |  * GET  /entities     - Entity listings    |  |        |
|  |  Daily       |  |  * GET  /campaigns    - Scored campaigns  |  |        |
|  |  summary     |  |  * GET  /alerts       - Alert history      |  |        |
|  |              |  |  * POST /collect/trigger - Collection      |  |        |
|  +--------------+  |  * POST /extract/trigger - Extraction      |  |        |
|                    |  * POST /score/trigger   - Scoring         |  |        |
|                    |                                            |  |        |
|                    |  Auth: API Key (X-API-Key header)        |  |        |
|                    |  Rate Limits: 60/min reads, 10/min writes  |  |        |
|                    |                                            |  |        |
|                    +--------------------------------------------+  |        |
|                                                                             |
|  +---------------------------------------------------------------+        |
|  |                    Static Dashboard (Frontend)                   |        |
|  |                                                                |        |
|  |  * Executive view:   KPIs, trends, alert summaries             |        |
|  |  * Intelligence:    Entity graphs, source breakdown              |        |
|  |  * Campaigns:        Scored clusters with drill-down            |        |
|  |  * Operations:       Pipeline status, queue depths               |        |
|  |  * Evidence:         Raw messages, entity provenance           |        |
|  |                                                                |        |
|  +---------------------------------------------------------------+        |
|                                                                             |
+-----------------------------------------------------------------------------+
```

---

## 3. Component Deep Dive

### 3.1 Data Sources Layer

| Source | Platform | Reliability | Entities | Update Frequency |
|--------|----------|-------------|----------|------------------|
| **MyCERT** | Web | 0.95 | phone, domain, url, email | Daily |
| **OpenSanctions BNM** | Government | 0.95 | domain, url, phone, company | Daily |
| **OpenSanctions SC** | Government | 0.90 | domain, url, phone, company | Daily |
| **Telegram** | Social | Varies | All types | Real-time |
| **Reddit** | Social | 0.50 | phone, bank, url | Daily |
| **SemakMule** | Government | 0.95 | bank account | On-demand |
| **RSS Feeds** | Web | 0.80 | url, domain | Hourly |

**Source Strategy:**
- **Government sources** provide high-confidence ground truth (bank accounts, domains confirmed by BNM/SC/PDRM)
- **Telegram** offers real-time signals but requires filtering and validation
- **Reddit** is used for research and gated promotion only (medium confidence)
- **Cross-referencing** across sources dramatically boosts confidence scores

### 3.2 Collector Agent

**Responsibilities:**
1. Scrape seed web sources (MyCERT, consumer.org.my)
2. Download OpenSanctions NDJSON feeds (BNM + SC alert lists)
3. Discover Telegram channels via keyword search + snowball pivoting
4. Scrape discovered channels for messages
5. Deduplicate by content hash (`text_hash`)
6. Publish to `raw_messages` Redis queue

**Key Design Decisions:**
- **Playwright** for JavaScript-heavy sites (MyCERT)
- **Telethon** for Telegram API access with session persistence
- **NDJSON streaming** for OpenSanctions (memory-efficient)
- **Demo mode** for development (no real Telegram calls)

### 3.3 Extractor Agent

**Responsibilities:**
1. Pull raw messages from `raw_messages` queue
2. Extract entities using regex patterns tuned for Malaysian formats
3. Classify scam type (investment, job, phishing, romance, etc.)
4. Deduplicate cross-type entities (phone ~ bank by digit overlap)
5. Upsert entities and entity_edges to SQLite
6. Push to `extracted_entities` queue

**Entity Types Supported:**

| Type | Description | Validation |
|------|-------------|------------|
| phone | Malaysian mobile/landline | Prefix + length check |
| bank_account | Malaysian bank accounts | IBG 4-digit prefix |
| domain | Domain names | Suspicious TLD check |
| url | Full URLs | Protocol + domain |
| email | Email addresses | Regex + domain check |
| whatsapp_link | wa.me / wasap.my links | Format validation |
| company_name | Business names | Cross-reference |
| telegram_channel | Telegram channel handles | @handle format |

### 3.4 Scorer Agent (Core Engine)

The scoring engine implements a **multi-signal Bayesian-like approach** where independent signals compound to produce a confidence score.

**Signal Weights (Configurable via YAML):**

| Signal | Base Weight | Max Boost | Description |
|--------|-------------|-----------|-------------|
| Entity Frequency | +40-65 | - | Count of related entities |
| Temporal Clustering | +30-45 | - | Cross-channel time proximity |
| Content Similarity | +22-35 | - | LLM script match percentage |
| Cross-Reference | +45-50 | - | BNM/SC/SemakMule match |
| Victim Signals | +5-50 | 50 | Financial loss, police reports |
| Relationships | +10-30 | - | Shared phone, co-occurrence |
| Trend | +10-20 | - | Spike/rising mention frequency |
| Combo Bonuses | +15-35 | - | Multi-signal combinations |

**Campaign Clustering:**
- BFS graph traversal from seed entities
- Temporal window: 24 hours
- Minimum cluster size: 3 entities + 2 channels
- Entity similarity threshold: 0.7

**Example Scoring Flow:**

```
Phone number 6012-345-6789 appears in:
  * Telegram channel A (2 messages, today)
  * Telegram channel B (1 message, today)
  * Reddit post (1 mention, today)
  * Matches BNM alert list (domain xyz-scam.com)

Score Calculation:
  Frequency (3+ entities):        +50
  Cross-platform (Telegram+Web):  +40
  Cross-reference (BNM match):    +50
  Scam type (investment):           +12
  Combo (phone + URL):            +15
  ---------------------------------------
  Total Score:                     167 -> Clamped to 100 (CRITICAL)
```

### 3.5 Alerter Agent

**Alert Delivery Flow:**

```
Daily Check
    |
    +---> Alerts Found (score >= 60)
    |         |
    |         +---> Send evidence-backed Telegram alert
    |         +---> Log to alert_log
    |
    +---> No Recent Data
    |         |
    |         +---> Send "No new threats" summary
    |
    +---> Pipeline Failure
              |
              +---> Send failure notification
```

### 3.6 FastAPI REST API

**Authentication:**
- Single API key via `X-API-Key` header or `?api_key=` query param
- `secrets.compare_digest()` prevents timing attacks
- Server fails fast if key not configured

**Rate Limiting:**
- Reads: 60 requests/minute per IP
- Writes: 10 requests/minute per IP
- Implemented via `slowapi` with Redis backend

**Endpoints:**

| Method | Path | Purpose | Rate Limit |
|--------|------|---------|------------|
| GET | `/health` | Health check | Unlimited |
| GET | `/stats` | Pipeline metrics | 60/min |
| GET | `/entities` | List entities | 60/min |
| GET | `/campaigns` | List campaigns | 60/min |
| GET | `/alerts` | Alert history | 60/min |
| GET | `/sources` | Data sources | 60/min |
| POST | `/collect/trigger` | Trigger collection | 10/min |
| POST | `/extract/trigger` | Trigger extraction | 10/min |
| POST | `/score/trigger` | Trigger scoring | 10/min |

### 3.7 Database Schema

**SQLite** (PostgreSQL-ready path)

```
entities                              entity_edges
+-------------+    +-------------+    +-----------------+
| id (PK)     |<---| entity_id   |    | id (PK)         |
| value       |    | channel     |    | campaign_id     |
| type        |    | platform    |    | entity_ids (JSON|
| count       |    | timestamp   |    | channel_ids(JSON|
| campaign_id |    | message_text|    | score           |
| metadata    |    | source_url  |    | risk_level      |
| first_seen  |    +-------------+    | campaign_type   |
| last_seen   |                       | keywords (JSON) |
+-------------+                       | alert_sent      |
                                      | first_seen      |
scraped_messages                      | last_seen       |
+-------------+                       +-----------------+
| id (PK)     |
| text_hash   |    alert_log
| text        |    +-----------------+
| platform    |    | id (PK)         |
| channel     |    | campaign_id(FK) |
| timestamp   |    | alert_type      |
| source_url  |    | score           |
| metadata    |    | sent_at         |
+-------------+    | status          |
                   | error_message   |
                   | metadata (JSON) |
                   +-----------------+
```

---

## 4. Data Flow Diagram

```
Time -------------------------------------------------------------------->

T+0    Collector scrapes MyCERT -> finds domain "xyz-scam.com"
       |---> Deduplicated by text_hash
       |---> Stored in scraped_messages
       +---> Published to raw_messages queue

T+1    Extractor processes message
       |---> Extracts: domain "xyz-scam.com"
       |---> Extracts: phone "6012-345-6789"
       |---> Classifies: "investment scam"
       |---> Upserts entities table
       |---> Creates entity_edges (2 records)
       +---> Published to extracted_entities queue

T+2    Scorer runs (scheduled or triggered)
       |---> Builds entity graph from DB
       |---> Finds 3+ related entities (threshold)
       |---> Checks temporal clustering (24h window)
       |---> Cross-references BNM list (MATCH)
       |---> Calculates score: 85 (HIGH)
       |---> Creates campaign record
       |---> Sets alert_sent = 0
       +---> Published to alerts queue

T+3    Alerter processes alert
       |---> Formats evidence-backed message
       |---> Sends Telegram alert to ops channel
       |---> Updates alert_sent = 1
       +---> Logs to alert_log

T+24h  Daily report runs
       |---> Counts alerts sent in last 24h
       |---> Generates summary
       +---> Sends daily digest
```

---

## 5. Technology Stack

### 5.1 Core Framework

| Layer | Technology | Version | Purpose |
|-------|------------|---------|---------|
| Language | Python | 3.12 | Application logic |
| API Framework | FastAPI | 0.111.0 | REST API |
| Validation | Pydantic | 2.7.1 | Data models |
| Settings | pydantic-settings | 2.2.1 | Environment config |
| Server | Uvicorn | 0.29.0 | ASGI server |

### 5.2 Data and Storage

| Layer | Technology | Version | Purpose |
|-------|------------|---------|---------|
| Database | SQLite | 3.x | Primary storage (MVP) |
| Database Driver | psycopg2-binary | 2.9.9 | PostgreSQL-ready |
| Queue | Redis | 7.x | Inter-agent messaging |
| Queue Client | redis-py | 5.0.4 | Python Redis client |
| Config | YAML | - | Source/scoring rules |
| Env Config | python-dotenv | 1.0.1 | Environment variables |

### 5.3 Scraping and External APIs

| Layer | Technology | Version | Purpose |
|-------|------------|---------|---------|
| Web Scraping | Playwright | 1.44.0 | Browser automation |
| HTTP Client | httpx | 0.27.0 | Async HTTP requests |
| HTML Parsing | BeautifulSoup4 | 4.12.3 | DOM extraction |
| XML Parsing | lxml | 5.2.2 | XML/feed parsing |
| RSS Parsing | feedparser | 6.0.11 | RSS feed ingestion |
| Telegram API | Telethon | 1.35.0 | Telegram scraping |
| LLM | Ollama | - | Local embeddings |

### 5.4 Infrastructure

| Layer | Technology | Purpose |
|-------|------------|---------|
| Containerization | Docker | Application packaging |
| Orchestration | Docker Compose | Multi-service deployment |
| Scheduling | systemd timer | Daily pipeline execution |
| OS | Linux | Ubuntu/Debian |

### 5.5 Testing and Quality

| Layer | Technology | Version | Purpose |
|-------|------------|---------|---------|
| Testing | pytest | 8.2.1 | Test framework |
| Async Testing | pytest-asyncio | 0.23.6 | Async test support |
| Type Checking | mypy | 1.10.0 | Static type analysis |

---

## 6. Security Architecture

### 6.1 Threat Model

```
+----------------+----------------+----------------+
|    Public      |    Internal    |     Secure     |
|    Internet    |    Services    |     Storage    |
+----------------+----------------+----------------+
|                |                |                |
| Threats:       | Threats:       | Threats:       |
| * DDoS         | * API abuse    | * Data breach  |
| * Scraping     | * Credential   | * Unauthorized |
| * Injection    |   theft        |   access       |
|                | * Privilege    | * Backups      |
|                |   escalation   |                |
+----------------+----------------+----------------+
```

### 6.2 Security Controls

| Control | Implementation | Status |
|---------|---------------|--------|
| API Authentication | API Key (X-API-Key) | Implemented |
| Timing Attack Prevention | `secrets.compare_digest()` | Implemented |
| Rate Limiting | `slowapi` (60/min read, 10/min write) | Implemented |
| Input Validation | Pydantic models | Implemented |
| SQL Injection Prevention | Parameterized queries | Implemented |
| CORS | Configurable origins | Default is wildcard |
| Secret Management | Environment variables | Implemented |
| Session File Security | Requires `.gitignore` audit | Needed |
| Audit Logging | `alert_log` + pipeline logs | Implemented |
| Dependency Scanning | Not implemented | Needed |

### 6.3 Data Classification

| Data Type | Sensitivity | Storage | Encryption |
|-----------|------------|---------|------------|
| Fraud entities (phone, bank) | Medium | SQLite | Filesystem-level |
| Telegram session files | High | Filesystem | Not encrypted |
| API keys / tokens | High | Environment | Not in code |
| Raw messages | Medium | SQLite | Filesystem-level |
| Scoring rules | Low | YAML files | None needed |

---

## 7. Deployment Architecture

### 7.1 Docker Compose Profiles

```
Profile: app (API + Frontend)
  fraud-mvp-app        -> FastAPI + static dashboard
  fraud-mvp-redis      -> Message queues
  Shared: config, db volumes

Profile: collector (Daily Pipeline)
  fraud-mvp-collector  -> agents.collector
  fraud-mvp-redis      -> Message queues
  Shared: config, db, logs volumes

Profile: scraper (Web + SemakMule)
  fraud-mvp-scraper    -> services.scraper.web_scraper
  fraud-mvp-semakmule  -> services.scraper.semakmule_scraper
  fraud-mvp-redis      -> Message queues
  Shared: config, db, logs volumes
```

### 7.2 Production Deployment Model

```
+---------------------------------------------------------------+
|                    HOST / VM / CLOUD INSTANCE                 |
|                                                               |
|  +---------------------------------------------------------+  |
|  |          systemd --user timer/service                     |  |
|  |     (triggers daily pipeline at 7:00 AM MYT)              |  |
|  +---------------------------------------------------------+  |
|                           |                                   |
|  +---------------------------------------------------------+  |
|  |          Docker Compose (profile-based)                 |  |
|  |                                                         |  |
|  |  +----------+  +----------+  +---------------------+   |  |
|  |  |  Redis   |  | FastAPI  |  |   Pipeline Agents   |   |  |
|  |  |Container |  |Container |  |                     |   |  |
|  |  |          |  |Port:8000 |  | * Collector         |   |  |
|  |  |* Queues  |  |          |  | * Extractor         |   |  |
|  |  |* Caching |  |* REST API|  | * Scorer             |   |  |
|  |  |          |  |* Dashboard| | * Alerter            |   |  |
|  |  +----------+  +----------+  +---------------------+   |  |
|  |                                                         |  |
|  |  Data Volumes:                                         |  |
|  |    ./db:/app/db        -> SQLite database              |  |
|  |    ./config:/app/config -> YAML configs (read-only)    |  |
|  |    ./logs:/app/logs     -> Application logs              |  |
|  |                                                         |  |
|  +---------------------------------------------------------+  |
|                                                               |
+---------------------------------------------------------------+
```

### 7.3 Scaling Path

**Phase 1: MVP (Current)**
- Single host, Docker Compose
- SQLite database
- Redis for queues
- Daily batch pipeline via systemd

**Phase 2: Scaling**
- PostgreSQL (psycopg2 already in requirements)
- Redis Cluster or managed Redis
- Separate scraper nodes (Playwright is resource-heavy)
- Celery or RQ for distributed task queue

**Phase 3: Enterprise**
- Kubernetes orchestration
- Horizontal pod autoscaling for API
- Dedicated scraping pools
- Read replicas for database
- CDN for dashboard assets

---

## 8. Operational Characteristics

### 8.1 Daily Pipeline Schedule

| Time (MYT) | Step | Duration |
|------------|------|----------|
| 07:00 | Preflight checks (DB, Redis, Telegram) | 1 min |
| 07:01 | RSS collection | 3 min |
| 07:05 | Web seed collection | 3 min |
| 07:08 | OpenSanctions collection | 2 min |
| 07:10 | Telegram collection | 5 min |
| 07:15 | Entity extraction | 5 min |
| 07:20 | Replay + enrichment | 5 min |
| 07:25 | Scoring | 5 min |
| 07:30 | Alerting | 5 min |
| 07:35 | Postflight + daily report | 5 min |
| 07:40 | **Complete** | **~40 min total** |

### 8.2 Failure Handling

| Component | Failure Mode | Behavior | Recovery |
|-----------|-------------|----------|----------|
| Redis | Connection lost | Graceful degradation (no-op mode) | Auto-reconnect |
| Telegram | Session unauthorized | Skip Telegram, continue pipeline | Manual refresh |
| Web source | Timeout / 404 | Log error, continue with other sources | Retries on next run |
| Scorer | LLM timeout | Skip LLM step, continue with rules | Fallback to keywords |
| SQLite | Lock conflict | Wait/retry (WAL mode recommended) | Transaction rollback |
| API | Rate limit exceeded | 429 response | Client retry with backoff |

### 8.3 Monitoring and Observability

| Metric | Source | Alert Threshold |
|--------|--------|----------------|
| Pipeline success/failure | Log file | Failure > 2 consecutive days |
| Entities extracted daily | DB query | Drop > 50% from baseline |
| Campaigns scored | DB query | Zero campaigns for 3+ days |
| API requests/min | FastAPI logs | Spike > 10x baseline |
| Redis queue depth | Redis INFO | > 10,000 messages |
| Telegram delivery rate | alert_log | Failure rate > 10% |

### 8.4 Backup and Recovery

| Asset | Backup Strategy | Recovery Time |
|-------|----------------|---------------|
| SQLite database | Daily filesystem snapshot | < 1 hour |
| Redis data | Redis RDB snapshots | < 30 minutes |
| Config files | Git version control | Instant |
| Telegram sessions | Manual re-auth required | 15 minutes |

---

## 9. Integration Points

### 9.1 External APIs

| Service | Protocol | Auth | Purpose |
|---------|----------|------|---------|
| Telegram Bot API | HTTPS + MTProto | Bot token | Alert delivery |
| Telegram MTProto | TCP | API ID + Hash | Channel scraping |
| OpenSanctions | HTTPS | None | NDJSON feed download |
| MyCERT | HTTPS | None | Web scraping |
| SemakMule | HTTPS | None | Bank account verification |
| Reddit | HTTPS | OAuth (optional) | Research scraping |
| Ollama | HTTP (local) | None | LLM embeddings |

### 9.2 Internal APIs

| Service | Protocol | Consumer | Purpose |
|---------|----------|----------|---------|
| FastAPI REST | HTTP | Dashboard, external tools | Data access |
| Redis queues | TCP | All agents | Async messaging |
| SQLite | File | All agents | Persistent storage |

### 9.3 Future Integrations (Roadmap)

| Service | Purpose | Priority |
|---------|---------|----------|
| Slack Webhooks | Alternative alert channel | Medium |
| PagerDuty | Critical alert escalation | Medium |
| ElasticSearch | Full-text search on messages | Low |
| Grafana | Metrics visualization | Low |
| VirusTotal | URL/domain reputation | Medium |
| Have I Been Pwned | Credential breach checks | Low |

---

## 10. Cost Analysis (MVP)

### 10.1 Infrastructure Costs (Monthly)

| Component | Spec | Cost (USD) | Notes |
|-----------|------|------------|-------|
| VPS / Cloud VM | 4 vCPU, 8GB RAM | $20-40 | Single host sufficient for MVP |
| Redis | Self-hosted | $0 | Included in VM |
| SQLite | Self-hosted | $0 | Included in VM |
| Telegram API | Standard | $0 | Free tier |
| OpenSanctions | Public data | $0 | Free |
| Domain / SSL | Basic | $10/year | Let's Encrypt (free) |
| **Total** | | **~$25-45/month** | |

### 10.2 Scaling Costs (Projected)

| Phase | Users | Messages/Day | Infra Cost | Notes |
|-------|-------|-------------|------------|-------|
| MVP | 1-5 | 1,000 | $25-45 | Current |
| Growth | 10-20 | 10,000 | $100-200 | PostgreSQL, separate scraper |
| Enterprise | 50+ | 100,000 | $500-1,000 | K8s, multiple scrapers, Redis cluster |

### 10.3 Development Velocity

| Metric | Value |
|--------|-------|
| Total development time | ~4 weeks (iterative) |
| Lines of code | ~18,800 |
| Test files | 12 |
| Configuration files | 7 YAML files |
| Agents | 5 (collector, extractor, scorer, alerter, reddit) |
| Services | 15+ shared modules |

---

## 11. Decision Log

| Decision | Rationale | Trade-off |
|----------|-----------|-----------|
| SQLite over PostgreSQL | Simpler MVP, zero-config setup | Limited concurrency, no horizontal scaling |
| Local Ollama over OpenAI | Zero API costs, data privacy | Requires GPU, model maintenance |
| Redis queues over RabbitMQ | Simpler ops, Python-native | Less enterprise features |
| Bash pipeline over Airflow | Faster to build, easier to debug | Less scheduling flexibility |
| Single API file over routers | Faster initial development | Maintainability risk at scale |
| Playwright over Scrapy | JavaScript-heavy sites | Higher resource usage |
| Telethon over Bot API for scraping | Access to channel history | Session management complexity |
| YAML configs over database configs | Git-tracked, code reviewable | Requires restart to apply |

---

## 12. Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Telegram API changes break scraping | Medium | High | Abstraction layer, fallback to demo mode |
| Government sources block scraping | Low | High | Respect robots.txt, rate limiting, mirror sources |
| SQLite concurrency issues | Medium | Medium | WAL mode, plan PostgreSQL migration |
| LLM unavailability | Medium | Medium | Keyword-only fallback, circuit breaker |
| False positive alerts | Medium | Medium | Threshold tuning, human-in-the-loop review |
| Data volume exceeds single-host capacity | Medium | Medium | Phase 2 scaling path defined |
| Security breach (API key leak) | Low | Critical | Key rotation process, audit logging |
| Playwright memory exhaustion | Medium | Medium | Resource limits, separate containers |

---

## 13. Roadmap and Next Steps

### Q2 2026 (Immediate)
- [ ] Fix packaging (`pyproject.toml`, remove `sys.path.insert`)
- [ ] Add CI/CD pipeline (GitHub Actions)
- [ ] Split API into routers for maintainability
- [ ] Add proper pytest test suite
- [ ] Enable SQLite WAL mode

### Q3 2026 (Growth)
- [ ] Migrate to PostgreSQL
- [ ] Add Alembic schema migrations
- [ ] Implement API versioning (`/v1/`)
- [ ] Add background task endpoints
- [ ] Circuit breaker for LLM calls
- [ ] Slack webhook integration

### Q4 2026 (Scale)
- [ ] Kubernetes deployment manifests
- [ ] Horizontal scaling for scrapers
- [ ] Redis Cluster or managed Redis
- [ ] Read replicas for database
- [ ] Advanced analytics (trend forecasting)
- [ ] Multi-region deployment

---

## 14. Conclusion

Fraud MVP represents a **production-ready, domain-specific intelligence platform** with strong architectural foundations. The 9-step scoring engine, multi-source aggregation, and Malaysian market focus provide significant competitive advantage over generic fraud detection tools.

**Key Strengths for CTO:**
1. **Proven Pipeline:** Daily automated operation with failure isolation
2. **Authoritative Data:** Government-grade source integration (BNM, SC, PDRM)
3. **Extensible Design:** Configuration-driven scoring, pluggable agents
4. **Clear Scaling Path:** SQLite to PostgreSQL, Docker Compose to Kubernetes
5. **Cost-Efficient:** ~$25-45/month MVP, local LLM eliminates API costs

**Recommended Immediate Actions:**
1. Approve Q2 technical debt reduction (packaging, tests, CI/CD)
2. Allocate resources for PostgreSQL migration (Q3)
3. Establish security review process for Telegram session management
4. Define SLA targets for alert delivery latency

---

*Architecture document prepared by Engineering for CTO review.*  
*For technical details, see `CLAUDE.md` and `_docs/fraud-mvp-comprehensive-assessment-2026-04-26.md`.*
