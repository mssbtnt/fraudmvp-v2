# Fraud MVP Comprehensive Code Review and Safe Implementation Plan

Date: 2026-04-10

## Scope

This review focuses on:

- runtime correctness
- data integrity across the queue and DB pipeline
- operational safety
- detection quality
- efficiency and maintainability

The goal is to improve the system without changing its intended behavior or introducing risky architectural churn.

## Current System Summary

The current system is a Python fraud-monitoring backend built around:

- source ingestion from web, Telegram, RSS, OpenSanctions, and SemakMule
- Redis queues for pipeline stage handoff
- SQLite for entity, edge, campaign, and alert persistence
- FastAPI for read-only operational APIs
- Telegram-based alert delivery

Primary flow:

1. collectors push `raw_messages`
2. extractor parses entities and writes them to DB
3. scorer builds campaign clusters and queues alerts
4. alerter formats and delivers campaign alerts

## Review Findings

### Critical

1. Scorer can fail at runtime due to uninitialized `campaign_type`.

Evidence:
- [agents/scorer.py](/home/mssbai/Desktop/fraud-mvp/agents/scorer.py#L385)
- [agents/scorer.py](/home/mssbai/Desktop/fraud-mvp/agents/scorer.py#L406)

Problem:
- `_score_cluster()` assigns `scam_type = campaign_type` before `campaign_type` exists.
- Any scoring path that reaches this branch can raise and disrupt campaign formation.

Impact:
- campaign scoring instability
- missed alerts
- hidden failures if exceptions are swallowed upstream

Recommendation:
- initialize `campaign_type = "unknown"` before LLM logic
- keep the LLM override optional and side-effect free
- add a unit test covering a suspicious cluster with and without LLM availability

2. Keyword scoring is effectively disconnected from the actual keyword config.

Evidence:
- [services/llm_similarity.py](/home/mssbai/Desktop/fraud-mvp/services/llm_similarity.py#L162)
- [config/keywords.yaml](/home/mssbai/Desktop/fraud-mvp/config/keywords.yaml#L7)

Problem:
- `KeywordExtractor` expects `categories.*.keywords`
- `config/keywords.yaml` uses top-level groups like `primary`, `secondary`, `slang`, `community_flags`, `regex_patterns`, `scam_types`
- as written, `_keyword_map` will stay empty

Impact:
- near-zero keyword contribution to scoring
- weak campaign classification
- reduced effectiveness of extractor/scorer despite having a rich keyword file

Recommendation:
- define and document a single canonical keyword schema
- update loader logic to support the current YAML format
- add tests that assert real keyword hits from the checked-in config

3. Entity edges are inserted twice for the same extracted item.

Evidence:
- extractor writes edges immediately: [agents/extractor.py](/home/mssbai/Desktop/fraud-mvp/agents/extractor.py#L275)
- scorer drains `extracted_entities` and writes edges again: [agents/scorer.py](/home/mssbai/Desktop/fraud-mvp/agents/scorer.py#L147)

Problem:
- the extractor writes entity edges during DB persistence
- the scorer then replays the queue and adds another edge for the same entity/message

Impact:
- inflated graph density
- distorted frequency and channel spread signals
- higher false positives and misleading campaign scores

Recommendation:
- choose one source of truth for edge persistence
- safest option: extractor persists entities and edges, scorer only reads DB
- if queue replay is needed, add idempotency constraints keyed by `entity_id + message_hash + channel`

### High

4. Database helper contains a latent `NameError`.

Evidence:
- [db/database.py](/home/mssbai/Desktop/fraud-mvp/db/database.py#L297)

Problem:
- `get_cross_channel_count()` uses `timedelta` without importing it

Impact:
- method fails when called
- future scoring or analytics work may break unexpectedly

Recommendation:
- import `timedelta`
- add a small DB helper test suite for all public database methods

5. `upsert_source()` uses `ON CONFLICT(name)` without a unique constraint.

Evidence:
- table definition: [db/database.py](/home/mssbai/Desktop/fraud-mvp/db/database.py#L104)
- conflict statement: [db/database.py](/home/mssbai/Desktop/fraud-mvp/db/database.py#L378)

Problem:
- SQLite requires a unique or primary key constraint for `ON CONFLICT(name)`

Impact:
- source tracking path is broken when exercised
- ingestion metadata becomes unreliable

Recommendation:
- add `UNIQUE(name)` if that matches business semantics
- otherwise use a read-then-update pattern or key on `(name, platform, url)`
- add a migration path rather than rebuilding the table ad hoc

6. `rss_collector` depends on `feedparser`, but it is missing from dependencies.

Evidence:
- import: [agents/rss_collector.py](/home/mssbai/Desktop/fraud-mvp/agents/rss_collector.py#L17)
- requirements: [requirements.txt](/home/mssbai/Desktop/fraud-mvp/requirements.txt#L1)

Impact:
- batch pipeline can fail at Step 1 on a clean environment

Recommendation:
- add `feedparser` to `requirements.txt`
- add a smoke test that imports every scheduled entrypoint

7. Docker and shell entrypoints are inconsistent with the local runtime assumptions.

Evidence:
- shell script expects `venv/bin/activate`: [fraud-mvp-daily-pipeline.sh](/home/mssbai/Desktop/fraud-mvp/fraud-mvp-daily-pipeline.sh#L50)
- Dockerfile creates `/app/venv` and uses `python`: [Dockerfile](/home/mssbai/Desktop/fraud-mvp/Dockerfile#L34)
- compose uses container `python`: [docker-compose.yaml](/home/mssbai/Desktop/fraud-mvp/docker-compose.yaml#L60)

Problem:
- local script assumes `venv/`, not `.venv/` or `/app/venv`
- environment activation expectations are not standardized

Impact:
- operational drift
- avoidable deployment failures

Recommendation:
- standardize on one virtualenv path for host docs and scripts
- add a bootstrap or Makefile target instead of relying on implicit shell state

### Medium

8. Telegram live scraping path appears fragile and partially incorrect.

Evidence:
- bot-token startup for scraping client: [services/scraper/telegram_scraper.py](/home/mssbai/Desktop/fraud-mvp/services/scraper/telegram_scraper.py#L85)
- participant count extraction via `full.full_user_`: [services/scraper/telegram_scraper.py](/home/mssbai/Desktop/fraud-mvp/services/scraper/telegram_scraper.py#L95)
- demo username typo with embedded space: [services/scraper/telegram_scraper.py](/home/mssbai/Desktop/fraud-mvp/services/scraper/telegram_scraper.py#L217)

Problem:
- bot-auth and user-session usage are mixed
- participant-count attribute looks suspicious for `GetFullChannelRequest`
- demo data includes an invalid username shape

Impact:
- live Telegram scraping may behave differently from demo expectations
- metadata quality may be poor even when scraping succeeds

Recommendation:
- separate bot-mode and user-session code paths clearly
- validate `ChannelFull` parsing against Telethon objects
- clean demo fixtures so tests reflect valid data

9. Source weights are inconsistent across config and code.

Evidence:
- config uses `web_seed`: [config/scoring_rules.yaml](/home/mssbai/Desktop/fraud-mvp/config/scoring_rules.yaml#L29)
- scorer fallback assumes `web`: [agents/scorer.py](/home/mssbai/Desktop/fraud-mvp/agents/scorer.py#L377)

Impact:
- some platform weighting will silently fall back to defaults

Recommendation:
- normalize allowed platform keys in one place
- validate config on startup

10. API trigger endpoints do not actually trigger work.

Evidence:
- [api/main.py](/home/mssbai/Desktop/fraud-mvp/api/main.py#L321)

Impact:
- operational ambiguity
- users may think jobs are enqueued when nothing happens

Recommendation:
- rename them to status/hint endpoints or wire them to a real job runner
- document clearly until real orchestration is added

11. `SemakMuleScraper` consumes `extracted_entities`, which conflicts with scorer ownership.

Evidence:
- [services/scraper/semakmule_scraper.py](/home/mssbai/Desktop/fraud-mvp/services/scraper/semakmule_scraper.py#L268)
- scorer also consumes same queue: [agents/scorer.py](/home/mssbai/Desktop/fraud-mvp/agents/scorer.py#L147)

Problem:
- two consumers can race on the same queue

Impact:
- nondeterministic processing
- missing scorer edges or missed SemakMule verification

Recommendation:
- stop sharing one queue across two independent consumers
- move SemakMule verification to a post-extraction DB read phase or separate verification queue

### Low

12. `python -m compileall` passes, but that only proves syntax, not behavior.

Evidence:
- local validation on 2026-04-10 succeeded with `python3 -m compileall agents services api db`

Meaning:
- syntax is mostly valid
- runtime and integration bugs remain

13. Some RSS/demo fixtures are low quality and should not be treated as production truth.

Evidence:
- malformed extra feed URL: [agents/rss_collector.py](/home/mssbai/Desktop/fraud-mvp/agents/rss_collector.py#L132)
- multiple placeholder/demo-oriented entries across scrapers

Impact:
- noisy test behavior
- lower confidence in source realism

Recommendation:
- distinguish `fixture/demo/test` assets from production seeds

## Safe Implementation Strategy

### Principle

Make the pipeline more reliable before making it more sophisticated.

Priority order:

1. correctness and idempotency
2. queue ownership and data integrity
3. config normalization
4. observability and tests
5. scoring quality and efficiency improvements

### Phase 1: Stabilize Runtime Correctness

Changes:

- fix uninitialized `campaign_type` in scorer
- import `timedelta` in database helper
- add missing dependencies such as `feedparser`
- repair `upsert_source()` semantics and supporting schema
- clean obviously invalid demo fixtures

Safety rails:

- no changes to queue names yet
- no changes to API shape
- no scoring-threshold changes in this phase

Verification:

- import smoke test for all entrypoints
- unit tests for scorer happy path
- unit tests for DB helpers

### Phase 2: Restore Data Integrity and Queue Ownership

Changes:

- remove duplicate edge insertion path
- define one owner for `extracted_entities`
- move SemakMule verification off the scorer’s queue path
- add idempotency checks on edges and message handling

Recommended direction:

- extractor writes entities and edges
- scorer reads only from DB plus optional campaign queue
- SemakMule verifies via DB query or dedicated verification queue

Safety rails:

- preserve existing persisted schema as much as possible
- introduce DB constraints only with explicit migration steps
- add metrics before and after the change to compare entity-edge counts

Verification:

- replay a fixed fixture set through the pipeline
- confirm edge counts do not increase on repeated runs
- confirm campaign counts remain stable or improve explainably

### Phase 3: Normalize Config and Detection Logic

Changes:

- make `keywords.yaml` match the loader or vice versa
- add config validation on startup
- normalize platform/source names
- ensure scoring uses real keyword weights

Enhancements:

- support exclusions from `keywords.yaml`
- support regex pattern scoring from config
- support scam-type mapping directly from checked-in config instead of duplicating category logic in code

Safety rails:

- keep existing thresholds initially
- log both old and new scores in shadow mode before switching fully

Verification:

- fixture-based keyword tests
- compare score deltas on a representative message corpus

### Phase 4: Improve Efficiency Without Risky Re-architecture

Changes:

- reduce repeated DB connection churn where safe
- batch more reads during scoring
- cache parsed config and static metadata
- avoid duplicate queue writes

Potential improvements:

- bulk edge fetches are already present; extend this pattern to campaign assembly
- add DB uniqueness/index support for hot lookup paths
- separate I/O-heavy verifiers from latency-sensitive scoring

Safety rails:

- no premature async rewrites
- no switch away from SQLite until scale justifies it

Verification:

- measure queue drain rate
- measure end-to-end batch time
- compare DB file growth and row counts before and after

### Phase 5: Operational Hardening

Changes:

- standardize environment/bootstrap workflow
- document one supported execution mode for local and Docker
- make API trigger endpoints honest or actually operative
- add structured logging and run summaries

Verification:

- one documented local runbook
- one documented Docker runbook
- one daily batch smoke run

## Recommended Work Breakdown

### Track A: Must Fix First

- scorer runtime bug
- keyword loader mismatch
- duplicate edge insertion
- queue ownership conflict with SemakMule
- missing `feedparser`
- broken `upsert_source()` conflict path

### Track B: Safe Quality Improvements

- platform/config normalization
- Telegram scraper cleanup
- better source metadata persistence
- stricter idempotency around message hashes
- improved tests around extractor false positives

### Track C: Nice to Have After Stabilization

- real orchestration behind API triggers
- richer campaign explainability
- shadow-mode score comparison
- migration path to Postgres if throughput requires it

## Proposed Deliverables

### Deliverable 1: Stability Patch Set

- minimal code changes to remove runtime failures
- dependency fixes
- queue-consumer ownership correction
- tests for the fixed regressions

### Deliverable 2: Detection Logic Alignment

- working keyword pipeline
- normalized config schema
- documented scoring inputs and thresholds

### Deliverable 3: Operational Hardening

- runbooks
- bootstrap commands
- clear entrypoint behavior
- API contract cleanup

## Test Plan

The implementation should include the following test layers:

- unit tests for extractor entity normalization and filtering
- unit tests for scorer cluster scoring and campaign type assignment
- unit tests for DB upsert and edge idempotency
- smoke tests that import and instantiate all scheduled entrypoints
- fixture-based end-to-end replay test:
  - queue sample `raw_messages`
  - run extractor
  - run scorer
  - assert entities, edges, campaigns, and alerts are deterministic

## Non-Goals for the First Hardening Pass

- replacing SQLite
- rewriting the pipeline into a distributed job system
- adding heavy ML dependencies beyond current Ollama integration
- changing business thresholds without measured evidence

## Recommended Sequence

1. Fix hard runtime bugs and missing dependencies.
2. Remove edge duplication and queue-consumer conflicts.
3. Make keyword/config scoring actually functional.
4. Add tests and observability around the corrected behavior.
5. Only then tune scoring and efficiency.

## Success Criteria

The hardening work should be considered successful when:

- repeated runs do not duplicate entity edges
- scorer runs without runtime exceptions
- keyword config contributes measurable score
- SemakMule verification no longer races the scorer
- batch pipeline starts cleanly in a fresh environment
- API and operational docs match actual system behavior

## Notes

This plan intentionally favors small, reversible fixes over large redesigns. The current system already has a workable architecture; the main problem is integration drift. Tightening ownership, config contracts, and idempotency will improve both effectiveness and efficiency without destabilizing the pipeline.
