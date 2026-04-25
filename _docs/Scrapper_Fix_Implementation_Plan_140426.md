# FraudMVP Implementation Plan — Full Pipeline Fix

## Root Cause Analysis

| # | Issue | Impact | Severity |
|---|-------|--------|----------|
| R1 | `scraped_messages` table is empty (0 rows) | No new data → no alerts | 🔴 Critical |
| R2 | Telegram scraper not in pipeline script | Primary data source missing | 🔴 Critical |
| R3 | Reddit scraper not in pipeline script | Supplementary data source missing | 🟠 High |
| R4 | `entities_old` error still occurring (12:05 today) | All extractor writes fail during pipeline runs | 🔴 Critical |
| R5 | 2,839/2,840 entities have no `entity_edges` (`channels=[]`) | Clustering needs shared channels → 0 clusters | 🔴 Critical |
| R6 | Pipeline fails 3/8 runs (SemakMule timeout) | Intermittent data gaps | 🟡 Medium |
| R7 | `raw_messages` Redis queue always empty | Extractor has nothing to process | 🟠 High |

---

## Execution Plan

### Phase A — Fix Data Flow *(Critical)*

| Step | Task | File/Location | Details |
|------|------|---------------|---------|
| A1 | Add Telegram scraper to pipeline | `fraud-mvp-daily-pipeline.sh` | Add `python3 -m services.scraper.telegram_scraper` with proper env |
| A2 | Add Reddit scraper to pipeline | `fraud-mvp-daily-pipeline.sh` | Add `python3 -m services.scraper.reddit_scraper` with Playwright |
| A3 | Verify scrapers push to Redis queue | `telegram_scraper.py`, `reddit_scraper.py` | Ensure messages go to `raw_messages` queue → `scraped_messages` DB |
| A4 | Verify extractor drains from queue | `agents/extractor.py` | Confirm it pops from `raw_messages` and writes to DB |

### Phase B — Fix `entities_old` Error *(Critical)*

| Step | Task | File/Location | Details |
|------|------|---------------|---------|
| B1 | Reproduce & diagnose `entities_old` error | `db/database.py` | Race condition: migration script runs `ALTER TABLE entities RENAME TO entities_old` then copies; pipeline fails if it runs during this window |
| B2 | Add defensive schema check | `db/database.py _ensure_schema()` | Add `PRAGMA user_version` check — skip migration if already at v2 |
| B3 | Add DB lock/retry logic | `db/database.py` | Use `PRAGMA busy_timeout` (already 5000ms) + retry on "no such table" errors |

### Phase C — Fix Entity Edges *(Critical)*

| Step | Task | File/Location | Details |
|------|------|---------------|---------|
| C1 | Re-ingest BNM/SC entities with edge creation | New script or `ingestion.py` | 2,864 entities exist but have no edges; re-ingest to create `entity_edges` from existing data |
| C2 | Ensure new scraper data creates edges | `ingestion.py` | When scraped messages arrive, `ingest_from_db` must create `entity_edges` correctly |

### Phase D — Pipeline Robustness

| Step | Task | File/Location | Details |
|------|------|---------------|---------|
| D1 | Add SemakMule timeout retry | `semakmule_scraper.py` | Retry with exponential backoff instead of crash |
| D2 | Add health check to pipeline | `fraud-mvp-daily-pipeline.sh` | Check DB + Redis + API connectivity before running |
| D3 | Add `--since` flag to pipeline | `pipeline.py` | Allow manual re-ingestion with date range |
| D4 | Fix systemd timer failures | `fraud-mvp-daily.service` | Add `Restart=on-failure` + `RestartSec=30s` |

### Phase E — Monitoring & Verification

| Step | Task | File/Location | Details |
|------|------|---------------|---------|
| E1 | End-to-end pipeline test with sample data | New test script | Push test message to Redis → extract → link → score → alert |
| E2 | Add pipeline metrics logging | `pipeline.py` | Log: `messages_scraped`, `entities_extracted`, `campaigns_scored`, `alerts_sent` |
| E3 | Add "no data" alert to daily report | `alerter.py` | If `scraped_messages = 0` for last 24h, flag as warning |

---

## Execution Order

```
A1–A2 → A3–A4 → B1–B3 → C1–C2 → D1–D4 → E1–E3
```

- **A1–A4** — Fix data flow (most critical; nothing works without data in the pipeline)
- **B1–B3** — Fix `entities_old` extractor errors
- **C1–C2** — Fix entity edge creation to unblock clustering
- **D1–D4** — Harden pipeline reliability and scheduler
- **E1–E3** — Verify end-to-end and add observability