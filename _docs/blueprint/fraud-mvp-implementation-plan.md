# Fraud & Scam Monitoring MVP — Implementation Plan

**Generated:** 03/04/2026  
**Updated:** 03/04/2026 (v2 — incorporating Strategic Blueprint)  
**Target:** GX10 (aarch64, 128GB) · Ubuntu 24.04 · Nemotron-Cascade 2  
**Timeline:** 30 Days (Week-by-Week)

---

## Project Structure

```
/home/mssbai/Desktop/fraud-mvp/
├── agents/                    # OpenClaw agent definitions
│   ├── collector.py           # Snowball expansion collector
│   ├── extractor.py           # Entity + script extraction
│   ├── scorer.py              # 5-step detection pipeline
│   └── alerter.py             # Campaign alert formatter
├── config/
│   ├── sources.yaml           # Seed sources + platform priorities
│   ├── keywords.yaml           # Funnel keywords per platform
│   ├── scoring_rules.yaml     # Rule-based scoring + source weights
│   └── campaign_thresholds.yaml
├── db/
│   ├── schema.sql             # SQLite/PostgreSQL schema
│   └── migrations/
├── services/
│   ├── scraper/
│   │   ├── telegram.py        # Telegram core scraper
│   │   ├── facebook.py        # Phase 2 FB scraper
│   │   ├── tiktok.py          # Phase 2 TikTok scraper
│   │   └── web.py             # Seed source scraper (MySCAM.info)
│   ├── queue_handler.py        # Redis queue consumer/producer
│   ├── entity_graph.py         # Graph DB for entity relationships
│   └── telegram_bot.py        # Alert delivery
├── api/
│   └── main.py                 # FastAPI endpoints
├── tests/
├── docker-compose.yaml
└── README.md
```

---

## Core Principle

> **You win by entity correlation and campaign detection, not by scraping more channels or using bigger models.**

Cyber-fraud networks are **dynamic, not static** — they migrate, regenerate, and coordinate to evade static blocklists. The system must detect campaigns via entity reuse, script reuse, and temporal clustering.

---

## The Fraud Funnel Model

| Layer | Platform | Role | Priority |
|-------|----------|------|----------|
| **Acquisition** | Facebook, TikTok, IG | Lead generation, fake ads, early narratives | Phase 2 |
| **Operational Core** | Telegram | Group coordination, script reuse, entity reuse | Phase 1 |
| **Conversion** | WhatsApp | 1-to-1 execution (encrypted, hard to track) | Out of scope |
| **Signal** | Reddit, X | Victim reports, early warnings | Phase 3 |

**Source Weighting (scoring multiplier):**
| Platform | Weight |
|----------|--------|
| Telegram | 1.0 |
| Facebook | 0.7 |
| TikTok | 0.6 |
| Reddit/X | 0.5 |
| Web (seed sources) | 0.8 |

---

## Snowball Expansion Model

### Phase 1 — Seed
- Extract phone numbers and domains from complaint datasets (MySCAM.info, KenaScam.com)
- Populate initial entity store

### Phase 2 — Pivot
- Cross-reference entities across Telegram and Google
- Find channels connected to known entities

### Phase 3 — Snowball
- Automate discovery of new channels mentioning known entities
- **Target:** Expand 20 → 200 tracked channels in 7–14 days

---

## Targeted Channel Types (Keyword Triggers)

| Campaign Type | Keywords | Priority |
|---------------|----------|----------|
| **Investment Scams** | pelaburan, crypto signal, forex VIP, IPO private | HIGH |
| **Job/Task Scams** | kerja part time, task earning, like tiktok dapat duit | HIGH |
| **Aid/Government Impersonation** | bantuan kerajaan, RM500 bantuan, BKM bantuan | HIGH |
| **Phishing/Account Hijack** | OTP, login verify, account suspended | MEDIUM |

---

## 5-Step Detection Pipeline

### Step 1 — Entity Graph Construction
Map nodes (phone numbers, bank accounts, domains, wallets) to edges (channels, timestamps).
```
Node types: phone, bank_account, domain, wallet_address, url
Edge types: appears_in, shared_by, mentioned_alongside
```

### Step 2 — Frequency Scoring
High entity reuse = high fraud probability.

| Signal | Points |
|--------|--------|
| Entity count ≥ 3 | +40 |
| Each additional repeat | +10 |

### Step 3 — Temporal Clustering
Same entity appearing across multiple channels within 24 hours = active campaign.

| Signal | Points |
|--------|--------|
| Cross-channel spread in <24h | +30 |
| Cross-platform spread in <24h | +40 |

### Step 4 — Content Similarity (LLM)
Use local LLM to match scam scripts and narratives across messages.

| Signal | Points |
|--------|--------|
| Script/narrative similarity ≥ 80% | +20 |
| Keyword cluster match (funnel type) | +15 |

### Step 5 — Campaign Formation
If cluster score ≥ threshold → generate campaign alert automatically.

| Threshold | Action |
|-----------|--------|
| 40–59 | Low priority, log only |
| 60–79 | Medium priority, alert |
| ≥ 80 | High priority, immediate alert |

---

## Alert Format

```
🚨 CAMPAIGN ALERT

Risk Score: 75 (HIGH)

Type: Investment Scam
Platform: Telegram (1.0)
Entities: 5 shared across 3 channels

Entity Graph:
• Phone: +6012XXXX (appears in 4 channels)
• Domain: scam-site.com (appears in 3 channels)

Temporal Spread: 18 hours across 3 channels
Script Similarity: 87% match (Investment cluster)

Top Keywords: pelaburan, forex VIP, IPO private

Source Channels:
  - Channel A (1,200 members)
  - Channel B (800 members)
  - Channel C (3,400 members)

Time: 03/04/2026 09:30 MYT
```

---

## 30-Day Implementation Timeline

### Week 1 — Foundation & Snowball Collection

| Day | Task | Deliverable |
|-----|------|-------------|
| 1–2 | Project scaffolding, Docker Compose, folder structure | `fraud-mvp/` base |
| 3–4 | Seed source scraper (MySCAM.info, KenaScam.com) | Initial entity DB |
| 5–6 | Telegram scraper — keyword-triggered channel discovery | Telegram collector v1 |
| 7 | Snowball loop: entity → Google/Telegram pivot | Collection pipeline |

**Agents Built:** `collector.py`

---

### Week 2 — Entity Extraction + Content Similarity

| Day | Task | Deliverable |
|-----|------|-------------|
| 8–9 | Phone, bank account, URL regex + LLM extraction | `agents/extractor.py` |
| 10–11 | Script/narrative extraction for similarity matching | LLM similarity module |
| 12–13 | Entity deduplication + graph edge builder | `services/entity_graph.py` |
| 14 | Integration test — extraction accuracy >85% | Live extraction demo |

**Agents Built:** `extractor.py`

---

### Week 3 — 5-Step Detection Pipeline

| Day | Task | Deliverable |
|-----|------|-------------|
| 15–16 | Entity graph DB setup (SQLite → Redis for fast lookup) | Graph construction |
| 17–18 | Frequency scoring + temporal clustering engine | `agents/scorer.py` v1 |
| 19–20 | Content similarity via LLM (80% threshold) | Scorer v2 |
| 21 | Threshold tuning + campaign formation logic | Scoring accuracy report |

**Agents Built:** `scorer.py`

---

### Week 4 — Alerting, API & Integration

| Day | Task | Deliverable |
|-----|------|-------------|
| 22–23 | Telegram campaign alert formatting + delivery | `agents/alerter.py` |
| 24–25 | FastAPI endpoints (`/alerts`, `/entities`, `/campaigns`, `/health`) | `api/main.py` |
| 26–27 | End-to-end pipeline test with real data | Full flow demo |
| 28–29 | Docker Compose, health checks, Prometheus metrics | Monitoring setup |
| 30 | Documentation + README + KPI validation | MVP shipped |

**Agents Built:** `alerter.py`

---

## Phase Rollout (Platform Expansion)

| Phase | Platforms | Timeline | Target Channels |
|-------|-----------|----------|-----------------|
| **Phase 1** | Telegram Core | Days 1–30 | 50–150 |
| **Phase 2** | Facebook + TikTok | Post-MVP | 150–300 |
| **Phase 3** | Reddit + X | Post-MVP | Signal enrichment |

---

## Technical Decisions

| Component | Choice | Rationale |
|-----------|--------|-----------|
| Database | SQLite (MVP) + Redis (graph cache) | Zero setup, fast lookups |
| Queue | Redis pub/sub | Simple, single-node |
| Scraper | Python + Telethon (TG) + Playwright (web) | Headless for JS sites |
| Graph DB | SQLite + Redis (adjacency) | Lightweight graph representation |
| LLM | Nemotron-Cascade 2 (local) | Privacy, no API cost |
| API | FastAPI | Lightweight, auto-docs |
| Container | Docker Compose | Single-node simplicity |

---

## Dependencies (Python Packages)

```
ollama
telethon              # Telegram scraping
playwright            # Web scraping
redis                 # Queue + graph cache
psycopg2              # PostgreSQL (future)
fastapi               # API
uvicorn               # ASGI server
pydantic              # Data validation
python-dotenv         # Config
pytest                # Tests
httpx                 # Async HTTP
beautifulsoup4        # HTML parsing
networkx              # Entity graph (optional)
```

---

## Security Controls

- [ ] Tool allowlist: HTTP GET, scraper, DB write only
- [ ] Docker isolation per agent
- [ ] No system file access from agents
- [ ] Prompt injection input filtering
- [ ] Human-in-the-loop: alerts delivered, not auto-blocked
- [ ] JWT for API (future RBAC)

---

## KPIs

| Metric | Target |
|--------|--------|
| Channels tracked | 50–150 (2-week window) |
| Entities collected | 500–2,000 |
| Campaigns detected | 10–30 |
| Alerts per day | 20–100 |
| End-to-end latency | < 10 min |
| Extraction accuracy | > 85% |
| False positive rate | < 25% |
| Uptime | > 95% |

---

## Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| OSINT noise (20–40%) | Source weighting prevents noise explosion |
| Model hallucination | Output validation layer before DB write |
| Hardware constraints (GX10) | SQLite + Redis, avoid heavy ML |
| Prompt injection | Input sanitization + allowlist |
| Entity graph explosion | Temporal windows + deduplication |

---

## Post-MVP Roadmap

1. **Campaign clustering** — cross-reference entities across platforms
2. **Facebook + TikTok scrapers** — acquisition layer detection
3. **ML-based scoring** — upgrade from rule-based
4. **Reddit/X integration** — victim report signal layer
5. **Grafana dashboard** — real-time visualization
6. **Multi-node scaling** — Kafka + Kubernetes
7. **FIaaS commercialization** — banks, telcos, government

---

*Plan v2 ready. Which week should we start building?*
