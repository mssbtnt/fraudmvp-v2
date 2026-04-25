# FraudMVP — System Flow Analysis & Plan Review

## System Flow

The repo contains **two distinct pipelines**, and this architectural split is the root of most confusion.

### Active Daily Path (Queue-First)

The shell script `fraud-mvp-daily-pipeline.sh:64` is the only wired end-to-end path today. It runs in sequence:

1. RSS collector
2. Web scraper
3. SemakMule scraper
4. Extractor
5. Scorer
6. Alerter

Collectors push raw JSON into Redis `raw_messages`. The extractor pops from that queue and writes to `entities` and `entity_edges` (`agents/extractor.py:500`, `agents/extractor.py:480`). The scorer then bypasses `scraped_messages` entirely and builds campaigns directly from `entities` + `entity_edges` (`agents/scorer.py:789`). Alerts are queued to `alerts` and delivered by the alerter (`agents/scorer.py:852`).

### Newer Service Path (DB-First)

`services.pipeline` reprocesses rows already in `scraped_messages` via `IngestionPipeline.ingest_from_db()` (`services/pipeline.py:171`, `services/ingestion.py:335`). This path is **effectively disconnected** because `scraped_messages` is empty.

### Current DB State

| Table | Count |
|-------|------:|
| `entities` | 2,865 |
| `entity_edges` | 314 |
| `scraped_messages` | 0 |
| `campaigns` | 1 |
| `entity_relationships` | 26 |
| `entity_mentions` | 107 |

2,840 of 2,865 entities currently have no edges, consistent with the plan's edge-gap observation.

---

## What the Plan Gets Right

The plan correctly identifies three real symptoms:

- `scraped_messages` is empty, breaking the DB-first ingestion/backfill path.
- Most entities have no `entity_edges`, crippling channel-based clustering since the scorer clusters on shared channels (`agents/scorer.py:789`).
- The shell pipeline does not include Telegram or Reddit collection today (`fraud-mvp-daily-pipeline.sh:66`).

The document is directionally useful. The problem is that several proposed fixes target the wrong components.

---

## Where the Plan Is Misaligned With the Code

**R1 — impact overstated.** Empty `scraped_messages` does not directly stop the current shell pipeline from producing alerts, because that path scores from `entities` and `entity_edges`, not from `scraped_messages` (`agents/extractor.py:483`, `agents/scorer.py:790`). What it breaks is the `services.pipeline` reprocessing path (`services/ingestion.py:339`).

**A1 — not implementable as written.** `services.scraper.telegram_scraper` is a library, not a runnable collector. It has no queue writes and no CLI that pushes messages into Redis (`services/scraper/telegram_scraper.py:90`). The module that actually orchestrates Telegram discovery and queue publishing is `agents.collector` (`agents/collector.py:463`, `agents/collector.py:581`).

**A2 — same issue as A1.** `services.scraper.reddit_scraper` scrapes Reddit and writes a JSON file under `data/`; it does not publish to `raw_messages` or insert into `scraped_messages` (`services/scraper/reddit_scraper.py:103`). Adding it to the shell script would not connect it to extraction/scoring. It also contains hardcoded fallback Reddit credentials — a separate security issue (`services/scraper/reddit_scraper.py:146`).

**A3 — wrong files.** Telegram and Reddit scrapers are not the queue producers in the current architecture. The queue-producing wrappers are `agents.collector`, `agents.rss_collector`, and `services.scraper.semakmule_scraper` (`agents/collector.py:581`, `services/scraper/semakmule_scraper.py:344`).

**C2 — incorrect.** `ingest_from_db()` does not create `entity_edges`; it only reads `scraped_messages` joined to existing edges (`services/ingestion.py:337`). Edge creation happens in the extractor via `write_to_db()` (`agents/extractor.py:480`). If new scraper data needs to create edges, the fix belongs in collection persistence and extractor flow — not `ingestion.py`.

**R4/B1–B3 — plausible but unproven.** The `RENAME TO entities_old` only exists in the standalone migration script `scripts/migrate_schema_v2.py:237`. `Database._ensure_schema()` does not do that rename; it only runs `CREATE TABLE IF NOT EXISTS` and sets `PRAGMA user_version = 1` (`db/database.py:54`). If `entities_old` errors are still occurring, the likely cause is concurrent or manual migration execution, not normal app startup. Proof is needed before patching.

**R7 — likely a false signal.** An empty `raw_messages` queue can simply mean the serial shell pipeline already drained it — collectors push, extractor immediately consumes. The API confirms the system is manual/script-driven, not continuously backgrounded (`api/main.py:321`).

### Additional Drift Noted

`tests/test_phase2_data_integrity.py:116` still expects `FraudScorerAgent._drain_extracted_queue()`, but that method no longer exists in `agents/scorer.py`. Parts of the test suite and documentation still describe an older intermediary design.

---

## Real Root Cause

The system does not have one broken pipeline. It has **two partially overlapping pipelines**:

- **Queue-first** — the only one actually wired end-to-end today.
- **DB-first** — added later, depends on `scraped_messages`, but almost no active collectors populate that table.

The implementation plan mixes symptoms from both models into a single fix list. The result is some valid observations alongside several fixes that would not change runtime behavior.

---

## Corrected Priority Order

**1. Choose a canonical ingestion model.**
If queue-first, keep the shell pipeline and make collectors or the extractor persist `scraped_messages` consistently. If DB-first, stop treating Redis as the primary source and switch orchestration to `services.pipeline`.

**2. Fix persistence before adding more scrapers.**
Telegram/Reddit sources only matter after they publish into the same canonical storage path. Adding `reddit_scraper.py` to the shell script as-is would mostly just produce a JSON file under `data/`.

**3. Backfill edges for legacy entities.**
Genuinely necessary — the scorer clusters by shared channels, and almost all current entities are edge-less.

**4. Then address robustness.**
SemakMule retry and health checks are worthwhile, but they are not the core blocker.