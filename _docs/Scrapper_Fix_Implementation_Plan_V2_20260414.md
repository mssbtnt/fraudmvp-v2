# FraudMVP Scraper and Pipeline Fix Implementation Plan V2

Date: 2026-04-14
Owner: FraudMVP engineering
Scope: End-to-end collection, extraction, persistence, scoring, alerting, verification, and operational reliability
Supersedes: `_docs/Scrapper_Fix_Implementation_Plan_140426.md`

## 1. Executive Summary

The system currently has two partially overlapping execution models:

1. A queue-first batch pipeline that is actually wired end-to-end today through:
   - `fraud-mvp-daily-pipeline.sh`
   - `agents.rss_collector`
   - `services.scraper.web_scraper`
   - `services.scraper.semakmule_scraper`
   - `agents.extractor`
   - `agents.scorer`
   - `agents.alerter`
2. A DB-first reprocessing pipeline in `services.pipeline` that assumes `scraped_messages` is being populated and can be replayed through `services.ingestion.IngestionPipeline`.

The main problem is not one broken scraper. The main problem is architectural drift:

- the active batch path writes to Redis and then to `entities` and `entity_edges`
- the newer reprocessing path expects `scraped_messages`
- most active collectors do not persist to `scraped_messages`
- most historical entities have no `entity_edges`, so clustering quality is poor
- some docs and tests still describe an older intermediary queue flow that no longer matches the code

V2 fixes this by:

1. Declaring the queue-first batch pipeline as the canonical runtime path for now
2. Making persistence coherent by storing canonical raw messages in `scraped_messages`
3. Backfilling `entity_edges` and related derived tables from current data
4. Wiring Telegram and Reddit collection through real queue-producing collectors, not raw service modules
5. Hardening the batch pipeline for retries, observability, and operator safety
6. Updating tests and docs to match the actual runtime model
7. Fixing confirmed runtime and security defects before broader refactoring

## 2. Current State Assessment

### 2.1 Verified Current Runtime Flow

The current daily script runs:

- `agents.rss_collector`
- `services.scraper.web_scraper`
- `services.scraper.semakmule_scraper`
- `agents.extractor`
- `agents.scorer`
- `agents.alerter`

The current extraction path is:

1. collectors push JSON payloads to Redis `raw_messages`
2. extractor pops from `raw_messages`
3. extractor extracts entities from raw message text
4. extractor upserts `entities`
5. extractor creates `entity_edges`
6. scorer reads `entities` plus `entity_edges`
7. scorer writes `campaigns`
8. scorer pushes alert payloads to Redis `alerts`
9. alerter reads `alerts` and delivers or logs output

### 2.2 Verified Current DB State

Observed in `db/fraud_mvp.db`:

- `entities`: 2865
- `entity_edges`: 314
- `campaigns`: 1
- `scraped_messages`: 0
- `cross_references`: 1
- `victim_signals`: 0
- `entity_relationships`: 26
- `entity_mentions`: 107
- entities without edges: 2840

### 2.3 Confirmed Issues

The following issues are real and require action:

1. `scraped_messages` is empty, so `services.pipeline` and DB replay are effectively disconnected.
2. The batch shell pipeline omits Telegram collection even though Telegram is the main target source.
3. Reddit scraping is not integrated into the main extraction path.
4. Most entities have no `entity_edges`, which weakens or blocks channel-based clustering.
5. SemakMule reliability can interrupt collection quality.
6. API trigger endpoints are manual-only status endpoints, which is correct operationally, but this must stay explicit in docs and observability.
7. Tests and docs still refer to removed or outdated scorer queue behavior.
8. `agents.group_collector` currently calls a non-existent queue API and will fail at runtime.
9. `services.pipeline` has score and alert contract drift and is not operationally safe as a primary runner.
10. `db/database.py` schema constraints do not match `db/schema.sql`, which can reject valid extracted types.
11. Reddit credentials are hardcoded in source and must be removed immediately.
12. Some SemakMule queue payloads use empty `message_hash` values, weakening deduplication.

### 2.4 Important Clarifications

These points matter for correct remediation:

1. Empty `scraped_messages` does not by itself explain why the current shell pipeline fails to alert.
   The current scorer runs from `entities` and `entity_edges`, not from `scraped_messages`.
2. `services.scraper.telegram_scraper` is not a queue-producing collector entrypoint.
   The queue-producing Telegram orchestration is in `agents.collector`.
3. `services.scraper.reddit_scraper` currently writes JSON output to `data/` and does not feed the pipeline.
4. `ingestion.ingest_from_db()` reprocesses existing DB rows. It does not create `entity_edges` for new raw messages.
5. `entities_old` is only directly referenced by standalone migration scripts, not by normal `Database._ensure_schema()` startup logic.
6. `services.pipeline` should be treated as replay/admin tooling until its scorer and alerter contracts are fixed.

## 3. Root Cause Model

### 3.1 Primary Root Cause

The primary root cause is split ownership of ingestion and persistence.

- Redis queues own live flow.
- SQLite `scraped_messages` is intended to own replay and derived enrichment.
- The codebase does not consistently persist the same message through both paths.

This produces the following bad outcomes:

- replay and backfill logic sees no source messages
- observability is misleading
- entity edges exist only for messages that happened to flow through extractor in the active queue path
- historical imported entities are mostly disconnected from channels and messages

### 3.2 Secondary Root Causes

1. Incomplete pipeline assembly
   - Telegram collection exists but is not in the daily script
   - Reddit scraping exists but is not pipeline-integrated

2. Persistence gap
   - most collectors push to Redis but do not persist canonical raw messages to `scraped_messages`

3. Historical data imported without provenance edges
   - BNM and SC entities were imported as standalone entities without equivalent message-level or edge-level backfill

4. Schema and contract drift
   - `db/database.py` and `db/schema.sql` do not allow the same entity and campaign types
   - `services.pipeline` score and alert behavior no longer matches downstream agent contracts

5. Documentation and test drift
   - runbooks and tests describe older queue contracts and removed scorer behavior

## 4. Target Operating Model

### 4.1 Canonical Runtime Model for V2

V2 adopts the queue-first batch pipeline as the official runtime model until a future deliberate migration to a DB-first orchestrator.

Official V2 flow:

1. collectors produce canonical raw message envelopes
2. each raw message is persisted to `scraped_messages`
3. each raw message is published to Redis `raw_messages`
4. extractor reads from Redis and writes:
   - `entities`
   - `entity_edges`
5. enrichment and backfill services derive:
   - `cross_references`
   - `victim_signals`
   - `entity_relationships`
   - `entity_mentions`
6. scorer reads from DB and forms campaigns
7. alerter reads from Redis `alerts` and logs delivery outcomes

### 4.2 Why This Model

This model is the lowest-risk path because:

- it aligns with the currently wired shell pipeline
- it minimizes invasive changes
- it preserves Redis-based stage decoupling
- it makes `scraped_messages` useful without rewriting the orchestrator
- it restores replay and auditability

### 4.3 Deferred Alternative

A future V3 may convert to a fully DB-first model using `services.pipeline` as the primary scheduler, but that is out of scope for this fix plan. V2 should first make one model coherent.

## 5. Design Principles

1. One canonical raw message envelope across all collectors
2. Every pipeline message must have durable provenance
3. No collector should bypass the canonical persistence path
4. Derived tables must be rebuildable from persisted raw data
5. Runtime and replay paths must be intentionally consistent
6. Manual API endpoints must remain explicitly non-orchestrating unless workers are actually attached
7. Backfills must be idempotent
8. Tests must validate real runtime contracts, not historical ones
9. Security and runtime hotfixes take precedence over phased cleanup

## 6. Required Functional Outcomes

V2 is complete only when all of the following are true:

1. Telegram collection is part of the daily batch flow through a real collector entrypoint.
2. Reddit collection is either:
   - fully integrated into the queue-first pipeline, or
   - explicitly excluded from the main pipeline with a documented reason.
3. Every accepted raw message is persisted into `scraped_messages`.
4. `services.pipeline ingest` can replay recent messages from `scraped_messages`.
5. Backfilled historical entities gain edges or are explicitly tagged as edge-less reference entities.
6. `entity_relationships` and `entity_mentions` can be rebuilt deterministically.
7. The pipeline handles transient collection failures without misleading success signals.
8. Tests and docs reflect the actual system flow.
9. No runtime path depends on stale schema constraints or incompatible pipeline contracts.

## 7. Implementation Plan

### Priority 0. Security and Runtime Hotfixes

Objective: Remove confirmed security exposure and unblock known failing runtime paths before phased implementation work.

Tasks:

1. Remove hardcoded Reddit fallback credentials and require env/session-based auth only.
2. Fix `agents.group_collector` queue publish to use the real queue API.
3. Fix `services.pipeline._run_score()` to consume the scorer's actual return contract.
4. Make `services.pipeline._run_alert()` explicitly report stub/manual behavior or call a real execution path, but not imply delivery.
5. Add a short operator note that `services.pipeline` is replay/admin only until its contract repairs are complete.

Files:

- update: `services/scraper/reddit_scraper.py`
- update: `agents/group_collector.py`
- update: `services/pipeline.py`
- update: docs

Acceptance criteria:

- no hardcoded credentials remain in source
- `agents.group_collector` can queue messages without `AttributeError`
- `services.pipeline` no longer misinterprets scorer results
- alert behavior is explicit and non-misleading

### Phase 0. Freeze and Baseline

Objective: Capture a reproducible baseline before changing data flow.

Tasks:

1. Snapshot current DB metrics and queue assumptions.
2. Export current counts for:
   - `entities`
   - `entity_edges`
   - `campaigns`
   - `scraped_messages`
   - `cross_references`
   - `victim_signals`
   - `entity_relationships`
   - `entity_mentions`
3. Save recent pipeline logs for comparison.
4. Add a simple baseline script under `scripts/` to print system health and table counts.

Files:

- new: `scripts/pipeline_baseline.py`
- docs: `_docs/`

Acceptance criteria:

- baseline report can be run locally with one command
- current state is captured before migration work starts

### Phase 1. Normalize the Canonical Raw Message Contract

Objective: Ensure all collectors emit one shared raw message schema.

Tasks:

1. Define a shared raw message envelope in one place.
2. Standardize fields:
   - `platform`
   - `channel`
   - `channel_id`
   - `message_id`
   - `sender_id`
   - `text`
   - `member_count`
   - `timestamp`
   - `message_hash`
   - `raw_json`
   - optional source metadata
3. Remove ad hoc collector-specific field drift where possible.
4. Add helper utilities for:
   - hash generation
   - safe serialization
   - validation
5. Replace collector-local `RawMessage` implementations with a single shared module.
6. Ensure every producer, including SemakMule top-10 payloads, emits a stable non-empty `message_hash`.

Recommended implementation:

- create a shared dataclass or schema module under `services/` or `agents/`
- update all queue-producing collectors to use it
- remove the duplicated `RawMessage` classes in `agents.collector`, `agents/rss_collector`, `agents/group_collector`, and `agents/reddit_collector`

Files:

- new: `services/raw_message.py`
- update: `agents/collector.py`
- update: `agents/rss_collector.py`
- update: `services/scraper/semakmule_scraper.py`
- update: `agents/group_collector.py`
- optional update: `agents/reddit_collector.py`

Acceptance criteria:

- every queue producer uses the same serializer
- every message has a stable `message_hash`
- invalid envelopes are rejected with logs, not silently accepted
- no collector maintains its own incompatible raw message class

### Phase 2. Persist Raw Messages Durably

Objective: Close the gap between queue-first runtime and DB-first replay by storing canonical raw messages in `scraped_messages`.

Tasks:

1. Add a single DB helper:
   - `upsert_scraped_message(...)`
2. Persist to `scraped_messages` before or at the same time as queue publish.
3. Use `INSERT OR IGNORE` or equivalent idempotent behavior on `text_hash`.
4. Track duplicate counts for observability.
5. Ensure `scraped_messages.scraped_at` is meaningful and source timestamps are preserved.

Design choice:

- persistence should happen at collection time, not extraction time
- extraction should remain focused on derived entity writes
- existing collector-local SQL writes should be replaced by one shared DB helper rather than expanded ad hoc

Why:

- replay should not depend on extractor having run
- failed extraction should not erase ingestion provenance

Files:

- update: `db/database.py`
- update: `agents/collector.py`
- update: `agents/rss_collector.py`
- update: `services/scraper/semakmule_scraper.py`
- update: `agents/group_collector.py`
- optional update: `agents/reddit_collector.py`

Acceptance criteria:

- running any collector increases both:
  - `raw_messages` queue depth
  - `scraped_messages` rows
- duplicate collector runs do not inflate `scraped_messages` uncontrollably
- `services.pipeline ingest` can replay newly collected messages
- collectors do not each embed their own `INSERT OR IGNORE` logic for `scraped_messages`

### Phase 3. Integrate Telegram Collection Correctly

Objective: Add Telegram into the daily pipeline through the real collector layer.

Tasks:

1. Do not invoke `services.scraper.telegram_scraper` directly from the shell pipeline.
2. Add `python3 -m agents.collector` as the Telegram-capable collection stage.
3. Reconcile overlap between:
   - existing RSS/web/SemakMule shell stages
   - the broader functionality already inside `agents.collector`
4. Decide one of two supported options:

Option A. Consolidated collection
- replace shell collection stages with `agents.collector` plus any supplemental collectors not already covered

Option B. Split collection
- keep individual RSS/web/SemakMule stages
- add a dedicated Telegram collector stage that uses `agents.collector` in a scoped mode

V2 recommendation:

Use Option B only if `agents.collector` is too broad or too slow operationally.
Otherwise consolidate collection in `agents.collector` and remove duplicated collection stages.

Required improvements:

1. add collector modes or flags such as:
   - `--telegram-only`
   - `--web-only`
   - `--opensanctions-only`
   - `--skip-snowball`
2. ensure demo mode behavior is explicit in logs
3. persist Telegram raw messages to `scraped_messages`

Files:

- update: `agents/collector.py`
- update: `fraud-mvp-daily-pipeline.sh`
- optional update: `Makefile`

Acceptance criteria:

- Telegram is part of the daily pipeline through a queue-producing collector
- operator can run Telegram collection independently
- collected Telegram messages appear in `scraped_messages`

### Phase 4. Integrate Reddit Intentionally

Objective: Either fully wire Reddit into extraction or explicitly isolate it as research-only.

Current state:

- `services/scraper/reddit_scraper.py` writes output files, not pipeline messages

Required decision:

1. Pipeline-integrated Reddit
   - convert Reddit results into canonical raw messages
   - persist to `scraped_messages`
   - publish to `raw_messages`

2. Non-pipeline Reddit
   - keep it as trend research only
   - remove it from the main implementation plan
   - document that it does not participate in entity extraction or scoring

V2 recommendation:

Integrate Reddit only if it can produce consistent raw messages and has acceptable runtime cost.
Otherwise classify it as supplemental offline intelligence and keep it out of the main batch path.

Security requirement:

- remove hardcoded fallback Reddit credentials from code
- require env-based credentials or session state only
- treat credential removal as Priority 0 work, not deferred cleanup

Files:

- update: `services/scraper/reddit_scraper.py`
- update: `agents/reddit_collector.py`
- update: `.env.example`
- update: docs

Acceptance criteria:

- no hardcoded live credentials remain in source
- Reddit is either fully wired into the main flow or explicitly documented as out of band

### Phase 5. Repair Historical Edge Coverage

Objective: Reduce the 2840 edge-less entities problem in a controlled, idempotent way.

Key distinction:

Not every entity must have a meaningful channel edge. Some entities are imported reference data, not message-native observations.

Therefore V2 must classify historical entities into:

1. message-backed entities
2. reference-import entities
3. unknown provenance entities

Tasks:

1. Reconcile schema constraints in `db/database.py` with `db/schema.sql` before any backfill or replay work.
2. Add provenance tagging in `entities.metadata` where missing.
3. Backfill `scraped_messages` and `entity_edges` only where a defensible source record exists.
4. For authoritative imports like BNM and SC:
   - create synthetic but explicit provenance records if using imported listings as source messages
   - mark them as `platform=opensanctions` or equivalent
5. Do not invent channel edges for entities with no source evidence.
6. Add a report that separates:
   - entities with zero edges by design
   - entities with zero edges due to broken ingestion

Recommended implementation:

- build a backfill script that replays authoritative imported datasets into canonical raw messages, then runs extractor or targeted edge generation

Files:

- new: `scripts/backfill_raw_messages.py`
- new: `scripts/backfill_entity_edges.py`
- update: `db/database.py`
- update: `services/ingestion.py`

Acceptance criteria:

- message-backed historical entities gain edges where source evidence exists
- edge-less reference entities are explicitly classified, not mixed with failures
- scoring quality improves measurably on rerun
- valid entity and campaign types are accepted consistently by both startup schema creation and migrated databases

### Phase 6. Rebuild Derived Tables from Canonical Source Data

Objective: Make all derived intelligence tables reconstructable from persisted source messages plus extracted entities.

Derived tables:

- `cross_references`
- `victim_signals`
- `entity_relationships`
- `entity_mentions`

Tasks:

1. Keep extraction responsible for `entities` and `entity_edges`.
2. Keep replay and enrichment responsible for:
   - co-occurrence links
   - victim signals
   - mention counting
   - cross-reference cache refresh
3. Make `services.pipeline ingest` explicitly a replay and enrichment tool, not a primary live-ingestion tool.
4. Repair score and alert step contracts before describing `services.pipeline` as safe for full-run usage.
5. Add CLI flags:
   - `--since`
   - `--platform`
   - `--limit`
   - `--dry-run`
6. Make replay idempotent where possible.

Files:

- update: `services/pipeline.py`
- update: `services/ingestion.py`
- update: `services/entity_linker.py`
- update: `services/trend_detector.py`

Acceptance criteria:

- replay from `scraped_messages` repopulates derived tables deterministically
- replay does not create duplicate edges
- replay outputs metrics for each derived subsystem
- full pipeline mode is either repaired end-to-end or clearly documented as unsupported

### Phase 7. Investigate and Neutralize `entities_old` Failures

Objective: Resolve the `entities_old` failure with evidence and prevent concurrent migration windows from breaking runtime operations.

Facts:

- `entities_old` rename logic exists in `scripts/migrate_schema_v2.py`
- normal startup `Database._ensure_schema()` does not rename `entities` to `entities_old`

Tasks:

1. search logs for exact `entities_old` error messages and timestamps
2. identify the command that produced them
3. verify whether migration scripts are ever run concurrently with the pipeline
4. treat concurrent migration as the primary suspected cause unless evidence shows otherwise
5. if concurrent migrations are happening:
   - stop automatic migration execution outside controlled maintenance
   - require explicit operator invocation
6. strengthen `Database._ensure_schema()` with:
   - schema version checks
   - logging of detected schema version
   - no implicit destructive migration behavior
7. document migration procedure and lock expectations

Optional hardening:

- add a lightweight startup verification that asserts required tables and columns exist
- fail fast with a clear message if schema is incompatible

Files:

- update: `db/database.py`
- update: `scripts/migrate_schema_v2.py`
- update: `scripts/migrate_schema_v3.py`
- update: `_docs/blueprint/OPERATIONS_RUNBOOK.md`

Acceptance criteria:

- root cause of `entities_old` is proven from logs or reproducible steps
- no normal pipeline execution path can enter migration rename windows
- schema mismatch failures become explicit and operator-friendly

### Phase 8. Harden Queue and Collector Reliability

Objective: Improve operational stability without hiding failures.

Tasks:

1. Make collector metrics explicit:
   - fetched
   - persisted
   - queued
   - duplicates
   - failed
2. Add retry behavior for transient network failures.
3. Add exponential backoff to SemakMule request failures.
4. Add collector stage timeouts and summary reporting.
5. Add preflight checks:
   - Redis reachable
   - DB writable
   - required env vars present for live Telegram mode
6. keep queue no-op fallback behavior visible in logs
7. add warnings when Redis is unavailable but a collector claims success
8. ensure all queued messages carry stable dedup keys, including SemakMule top-10 summaries

Files:

- update: `services/queue_handler.py`
- update: `services/scraper/semakmule_scraper.py`
- update: `fraud-mvp-daily-pipeline.sh`
- optional update: `Makefile`

Acceptance criteria:

- transient failures retry in a bounded way
- persistent failures surface clearly in the shell summary and logs
- operators can distinguish "no data found" from "collection failed"

### Phase 9. Correct the Daily Pipeline Script

Objective: Make the shell pipeline represent the actual supported execution model.

Tasks:

1. Choose one supported collection composition.
2. Remove or replace stages that do not feed the pipeline.
3. Add health checks before execution.
4. Add per-stage timing and row-count summaries.
5. Emit final summary with:
   - messages persisted
   - queue depth after collection
   - entities extracted
   - campaigns created
   - alerts sent
6. optionally add flags:
   - `--since`
   - `--skip-telegram`
   - `--skip-reddit`
   - `--skip-semakmule`
   - `--replay-only`

Recommended V2 shell stages:

1. preflight
2. collection
3. extraction
4. replay and enrichment
5. scoring
6. alerting
7. post-run metrics

Files:

- update: `fraud-mvp-daily-pipeline.sh`

Acceptance criteria:

- script stages correspond to real working modules
- final summary makes the system state obvious

### Phase 10. Update API and Operator Contract

Objective: Keep the API honest and useful.

Tasks:

1. Preserve manual-only semantics for trigger endpoints unless background workers are actually attached.
2. Expand `/stats` or add a new status endpoint with:
   - collector health summary
   - recent `scraped_messages` count
   - recent extraction count
   - recent campaign count
3. Add explicit "no recent data" indicators.
4. Do not make `/collect/trigger` appear to launch work if it does not.

Files:

- update: `api/main.py`

Acceptance criteria:

- API status reflects actual runtime model
- operators can tell whether the problem is no data, collector failure, extraction failure, or scoring failure

### Phase 11. Fix Tests and Documentation Drift

Objective: Make tests and docs match the code that actually runs.

Tasks:

1. remove or replace tests referring to removed scorer queue methods
2. add tests for:
   - collector persistence into `scraped_messages`
   - extractor idempotent edge creation
   - replay from `scraped_messages`
   - Telegram collector queue publish
   - SemakMule retry behavior
   - pipeline summary output
3. update docs:
   - README
   - runbook
   - CLAUDE.md
   - implementation plan docs

Files:

- update: `tests/test_phase2_data_integrity.py`
- new: `tests/test_scraped_message_persistence.py`
- new: `tests/test_pipeline_replay.py`
- new: `tests/test_pipeline_script_contract.py`
- update: `README.md`
- update: `_docs/blueprint/OPERATIONS_RUNBOOK.md`
- update: `CLAUDE.md`

Acceptance criteria:

- tests pass against the real runtime contract
- no docs claim that non-wired endpoints launch background jobs
- no docs claim scorer drains `extracted_entities` if it does not

## 8. Detailed File-by-File Work List

### `db/database.py`

Add:

- `upsert_scraped_message(...)`
- schema verification helper
- improved schema version logging
- entity and campaign constraint definitions aligned with `db/schema.sql`

Do not add:

- implicit destructive migrations on startup

### `agents/collector.py`

Add:

- canonical raw message builder usage
- DB persistence into `scraped_messages`
- optional collector mode flags
- better result summaries

### `agents/rss_collector.py`

Add:

- canonical raw message builder usage
- DB persistence into `scraped_messages`

### `services/scraper/semakmule_scraper.py`

Add:

- retry with bounded backoff
- canonical raw message persistence and publish
- explicit metrics

### `services/scraper/reddit_scraper.py`

Add or change:

- remove hardcoded credentials
- either convert results into canonical raw messages or document research-only role

### `agents/extractor.py`

Keep:

- `entities` and `entity_edges` ownership

Add:

- optional metric for number of source messages successfully extracted
- optional provenance usage from `scraped_messages`

### `services/ingestion.py`

Clarify role:

- replay and enrichment
- not primary edge creation path

Add:

- better logging and idempotent replay metrics

### `services/pipeline.py`

Add:

- CLI flags for replay windows
- explicit replay summary
- better naming around "ingest" versus "replay"
- repaired scorer return handling
- explicit alert-step contract

### `fraud-mvp-daily-pipeline.sh`

Change:

- stage composition
- preflight checks
- metrics summary

## 9. Execution Sequence

Recommended implementation order:

1. Priority 0 security and runtime hotfixes
2. Phase 0 baseline
3. Phase 1 canonical raw message contract
4. Phase 2 durable `scraped_messages` persistence
5. Phase 3 Telegram integration
6. Phase 4 Reddit integration decision
7. Phase 7 `entities_old` investigation and migration guardrails
8. Phase 5 schema reconciliation and historical edge repair
9. Phase 6 replay and enrichment rebuild
10. Phase 8 reliability hardening
11. Phase 9 pipeline script correction
12. Phase 10 API status improvements
13. Phase 11 tests and docs cleanup

Reason for this order:

- fix persistence before adding more sources
- fix runtime contract before backfills
- avoid building replay around empty `scraped_messages`
- avoid patching migrations before proving the failure mode

## 10. Acceptance Test Matrix

### 10.1 Collection

1. RSS collector run:
   - writes rows to `scraped_messages`
   - queues rows to `raw_messages`
2. Telegram collector run:
   - writes rows to `scraped_messages`
   - queues rows to `raw_messages`
3. SemakMule run:
   - retries bounded transient failures
   - persists queued messages

### 10.2 Extraction

1. extractor processes persisted queued messages
2. entities are upserted idempotently
3. entity edges are not duplicated for the same `message_hash`

### 10.3 Replay and Enrichment

1. `services.pipeline ingest --since <date>` replays recent rows from `scraped_messages`
2. derived tables populate deterministically
3. replay does not invent new source rows

### 10.4 Scoring and Alerting

1. scorer forms campaigns from real edge-backed entities
2. medium and above campaigns enqueue alerts
3. alerter logs or delivers correctly

### 10.5 Observability

1. pipeline final summary includes meaningful counts
2. API status shows recent data presence or absence
3. "no data" and "collection failure" are distinguishable

## 11. Metrics and SLOs

Track after V2:

1. `scraped_messages_last_24h`
2. `raw_messages_queued_last_run`
3. `extractor_messages_processed_last_run`
4. `entities_created_last_run`
5. `entity_edges_created_last_run`
6. `replay_messages_processed_last_run`
7. `campaigns_created_last_run`
8. `alerts_triggered_last_run`
9. `collector_failure_count_last_run`
10. `duplicate_raw_message_count_last_run`

Suggested minimum operational targets:

- `scraped_messages_last_24h > 0` on expected collection days
- extractor success rate above 95 percent of queued messages
- replay success rate above 99 percent for persisted rows
- pipeline step summaries always emitted, even on failure

## 12. Risk Register

### High Risk

1. Duplicating collection by running both consolidated and split collectors
   Mitigation: choose one collection topology and document it

2. Backfilling synthetic message provenance incorrectly
   Mitigation: explicitly label synthetic authoritative records and keep them separate from organic Telegram messages

3. Treating reference entities as ingestion failures because they have no channel edges
   Mitigation: add provenance classification

4. Hiding Redis outages behind no-op queue behavior
   Mitigation: add loud warnings and pipeline summaries

### Medium Risk

1. Reddit integration adds runtime cost without signal value
   Mitigation: make integration optional and measured

2. migration hardening addresses the wrong cause if `entities_old` logs are stale
   Mitigation: prove the failure source before code changes

## 13. Rollback Strategy

If a V2 change causes instability:

1. keep the old shell pipeline script as `.bak` during rollout
2. gate new collector persistence logic behind a config flag if needed
3. ship backfill scripts separately from runtime changes
4. do not combine schema changes, collector rewrites, and backfills in one deploy step

## 14. Deliverables

V2 should produce:

1. corrected shell pipeline
2. canonical raw message schema module
3. durable `scraped_messages` persistence path
4. Telegram collection integrated through a real collector
5. Reddit decision and security cleanup
6. historical edge backfill scripts
7. replay and enrichment CLI improvements
8. updated tests
9. updated docs and runbooks
10. post-fix verification report

## 15. Context and References

Primary repo references:

- `fraud-mvp-daily-pipeline.sh`
- `agents/collector.py`
- `agents/rss_collector.py`
- `agents/extractor.py`
- `agents/scorer.py`
- `agents/alerter.py`
- `services/pipeline.py`
- `services/ingestion.py`
- `services/queue_handler.py`
- `services/scraper/telegram_scraper.py`
- `services/scraper/reddit_scraper.py`
- `services/scraper/semakmule_scraper.py`
- `db/database.py`
- `_docs/blueprint/OPERATIONS_RUNBOOK.md`
- `CLAUDE.md`

Context7 note:

- FastAPI and redis-py library IDs were resolved to confirm the relevant official documentation targets for API and queue behavior.
- Deeper Context7 content queries timed out during this planning session, so this V2 plan is grounded primarily in the current codebase and local operational docs rather than extended external excerpts.

---

# New Proposed Daily-Report Alert Logic to Distinguishes
- no_alerts_but_data_processed
- no_recent_data
- pipeline_failure
- partial_run_stale_results

## Recommended Logic:

# FraudMVP — Daily Report State Machine

Use four mutually exclusive states for the daily report. This eliminates the current ambiguity where a no-alert message is emitted regardless of whether the pipeline actually had usable input.

---

## States

### 1. `alerts_found`

**Condition:** `alerts_sent > 0` or `alerts_triggered > 0`

**Behaviour:**
- Send campaign alerts as normal.
- Optional daily summary: date, fresh data processed, campaign count, alert count.

---

### 2. `no_alerts_but_data_processed`

**Condition:** Collection succeeded, recent data exists, extraction and scoring succeeded, `alerts_triggered == 0`.

**Thresholds:**
- `scraped_messages_last_24h > 0`
- `messages_processed > 0`
- `entities_extracted > 0`
- Scoring completed
- `alerts_triggered == 0`

**Message example:**

```
📊 FraudMVP Daily Report

📅 Date: 14/04/2026
✅ Status: Scan completed, no alert-level campaigns found

Sources were collected and processed successfully.
No campaigns crossed the configured alert threshold in this run.

Summary:
• Raw messages persisted: 148
• Messages extracted: 132
• Entities extracted: 417
• Campaigns scored: 6
• Alerts triggered: 0
```

---

### 3. `no_recent_data`

**Condition:** Pipeline ran, but there was not enough fresh input to make a trustworthy conclusion.

**Trigger:** Collector succeeded technically, but:
- `scraped_messages_last_24h == 0`, or
- All enabled collectors returned zero fresh messages.

**Message example:**

```
📊 FraudMVP Daily Report

📅 Date: 14/04/2026
⚠️ Status: No recent source data

The pipeline ran, but no fresh source messages were collected
in the expected time window.
This is not the same as "no scams detected".

Summary:
• Raw messages persisted: 0
• Enabled collectors: Telegram, RSS, SemakMule
• Recommendation: check collector health and source connectivity
```

---

### 4. `pipeline_failure`

**Condition:** One or more required stages failed, so the result is not trustworthy.

**Trigger:**
- Collection failed for required sources, or
- Extraction failed, or
- Scoring failed.

**Message example:**

```
📊 FraudMVP Daily Report

📅 Date: 14/04/2026
❌ Status: Pipeline failure

The pipeline did not complete successfully. Detection results
may be incomplete or stale.

Failed stages:
• Telegram collection
• Extraction

Recommendation:
• Inspect pipeline logs
• Rerun failed stages after fixing the issue
```

---

## Decision Order

Evaluate in this order so exactly one state is emitted per run:

| Priority | Condition | State |
|----------|-----------|-------|
| 1 | Required stage failed | `pipeline_failure` |
| 2 | `alerts_triggered > 0` | `alerts_found` |
| 3 | Fresh data processed successfully | `no_alerts_but_data_processed` |
| 4 | *(fallthrough)* | `no_recent_data` |

---

## Definitions

### "Fresh Data Processed" — all of the following must be true:

- `scraped_messages_last_24h > 0`
- `collector_failed_required == false`
- `extractor_failed == false`
- `scorer_failed == false`
- `messages_processed > 0`
- `entities_extracted > 0`

**Optional stricter variant:** require Telegram to have run successfully if it is configured as a required source.

### Required vs Optional Stages

| Stage | Classification |
|-------|---------------|
| Collection | Required |
| Extraction | Required |
| Scoring | Required |
| Reddit | Optional |
| SemakMule supplemental | Optional |

**Implications:**
- If Reddit fails but Telegram/RSS/extraction/scoring succeed → do **not** emit `pipeline_failure`.
- If Telegram is a required source and its collector fails → emit `pipeline_failure` (or `partial_run_stale_results` if using the extended model below).

---

## Optional: Fifth State — `partial_run_stale_results`

Add this if you want finer-grained failure reporting rather than treating every source problem as a hard failure.

**Condition:**
- Pipeline technically completed.
- One or more non-optional sources failed or were skipped.
- Scoring ran, but results are incomplete.

**Message example:**

```
⚠️ Status: Partial run completed

Scoring completed, but one or more required sources were unavailable.
Results may under-report active campaigns.
```

---

## Implementation

Build a daily report builder that consumes a single run summary dict:

```python
{
    "collection": {
        "success": True,
        "required_sources": {
            "telegram": {"success": True, "messages": 72},
            "rss":      {"success": True, "messages": 41},
        },
        "optional_sources": {
            "reddit":   {"success": False, "messages": 0},
        },
        "scraped_messages_persisted": 113,
    },
    "extraction": {
        "success": True,
        "messages_processed": 102,
        "entities_extracted": 355,
    },
    "scoring": {
        "success": True,
        "campaigns_scored": 5,
        "alerts_triggered": 0,
    },
    "alerting": {
        "success": True,
        "alerts_sent": 0,
    },
}
```

Derive status from this summary dict rather than checking only whether the alerts queue was empty.

---

## Expected Outcome

After this change, a no-alert report should only be emitted when the system genuinely processed fresh data and found nothing above threshold. It should no longer be the default fallback for cases where the pipeline had no usable inputs.


---

How the Every-3-Hour Alert Works

It's a systemd user timer — not crontab.

┌─────────────────────────┐
│  fraud-mvp-daily.timer   │  ← Schedules the run
│  (systemd user timer)    │
└───────────┬─────────────┘
            │ triggers
            ▼
┌─────────────────────────┐
│  fraud-mvp-daily.service │  ← Runs the pipeline
│  (systemd user service)  │
│  Type=oneshot            │
└───────────┬─────────────┘
            │ executes
            ▼
┌──────────────────────────────┐
│  fraud-mvp-daily-pipeline.sh │  ← Shell script
│  Step 1: Collect (RSS,Web,SemakMule)
│  Step 2: Extract             │
│  Step 3: Score               │
│  Step 4: Alert (Telegram)    │
└──────────────────────────────┘

Schedule Logic

| Directive                 | Value                  | Meaning                                             |
| ------------------------- | ---------------------- | --------------------------------------------------- |
| OnCalendar=*-*-* 00:00:00 | Midnight daily         | First run always at 12AM MYT                        |
| OnUnitActiveSec=3h        | 3 hours after last run | Subsequent runs: 3AM, 6AM, 9AM, 12PM, 3PM, 6PM, 9PM |
| Persistent=true           | Catch up missed runs   | If machine was off at 12AM, it runs on boot         |
| RandomizedDelaySec=60     | ±60s jitter            | Prevents exact-second stampede                      |

What It Does Every 3 Hours

12AM → Collect (RSS + Web + SemakMule) → Extract → Score → Alert
 3AM → Collect → Extract → Score → Alert
 6AM → Collect → Extract → Score → Alert
 9AM → Collect → Extract → Score → Alert
12PM → Collect → Extract → Score → Alert
 3PM → Collect → Extract → Score → Alert
 6PM → Collect → Extract → Score → Alert
 9PM → Collect → Extract → Score → Alert

Current Status

|            |                                            |
| ---------- | ------------------------------------------ |
| Timer      | ✅ Active, enabled, running since Apr 10    |
| Next run   | 12:00:20 AM (in ~12 min)                   |
| Last run   | 9:07:44 PM (2h 39min ago)                  |
| No crontab | Confirmed — the scheduling is 100% systemd |

Key Difference vs Crontab

|             | systemd timer                        | crontab                |
| ----------- | ------------------------------------ | ---------------------- |
| Location    | ~/.config/systemd/user/              | crontab -l             |
| Logs        | journalctl --user -u fraud-mvp-daily | /var/log/syslog        |
| Persistence | Survives reboots (Persistent=true)   | Depends on cron daemon |
| Management  | systemctl --user start/stop/status   | crontab -e             |
| User scope  | User-level (no root needed)          | System-level           |

---

# TELEGRAM TELETHON SESSION LOGIN
cd /home/mssbai/Desktop/fraud-mvp
source venv/bin/activate
python3 scripts/bootstrap_telegram_session.py