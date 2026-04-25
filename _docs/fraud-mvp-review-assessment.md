# FraudMVP V2 — Implementation Review Assessment

The review is directionally useful, but it mixes three different classes of findings: real runtime defects that should be fixed immediately, valid architectural risks that are not all production blockers, and a few stale or already-resolved claims.

The review's strongest value is in the runtime bug list. Its weaker parts are the configuration section and the missing coverage section, where at least some claims are outdated.

---

## Confirmed Issues

These findings are real based on the current code:

**`victim_signal.py:336`** — `VictimSignalDetector` will raise `AttributeError` because it references `CATEGORY_WEIGHTS`, but only `CATEGORY_CAPS` exists.
Status: fixed. The LLM path now uses `CATEGORY_CAPS` and constructs complete `VictimSignal` objects.

**`alert_builder.py:318`, `520`** — `AlertBuilder._format_related_entities` is defined after the `if __name__ == "__main__"` block instead of inside the class. `format_for_telegram()` will fail when it calls it.
Status: fixed. The helper now lives on the class and is covered by regression test.

**`scorer.py:841`** — `FraudScorerAgent.run()` references `nodes` outside its scope when recording mentions. Real `NameError` risk.
Status: fixed. Mention counts now derive from `campaign.entity_values` plus the graph built in `run()`.

**`web_scraper.py:221`, `287`** — `WebScraper` incorrectly uses `async with self.client as c:` on a shared client, closing it after the first call.
Status: fixed. The scraper now reuses the shared `httpx.AsyncClient` directly and keeps lifecycle management in `close()`.

**`rss_collector.py:313`** — RSS collector persists `raw_json` using `str(art)` instead of proper JSON serialisation.
Status: fixed. The collector now uses `json.dumps(..., ensure_ascii=False, default=str)`.

**`daily_report.py:107`** — The `PARTIAL_RUN_STALE_RESULTS` branch is logically unreachable.
Status: fixed. The partial-run state now activates when required collection sources fail but extraction and scoring still succeed.

**`scoring_rules.yaml:61` vs `alert_builder.py:106`** — Risk threshold drift is real. Scorer uses `60/80/95` from config; alert builder hardcodes `50/70/90`.
Status: fixed. `AlertBuilder` now loads thresholds from `config/scoring_rules.yaml`.

**`database.py:77` vs `database.py:482`** — Schema drift on fresh DB creation: `_ensure_schema()` only creates core tables, but `reset_derived_tables()` assumes derived tables already exist.
Status: fixed. `_ensure_schema()` now creates the derived V2 tables and indexes needed by replay/reset paths.

---

## Overstated or Stale Findings

These parts of the original review need correction or removal:

**`deposit_scam` alias gap is already fixed.** `deposit_scam → job_task` exists in `services/campaign_types.py:44`. The review only partially checked this area.

**"Daily report state machine tests are missing" is false.** Dedicated coverage already exists in `tests/test_daily_report.py:1`. What is actually missing is coverage for the broken `PARTIAL_RUN_STALE_RESULTS` branch specifically.

**`services.pipeline` alerter clarification is already implemented.** `_run_alert()` explicitly notes the alerter is not executed there (`services/pipeline.py:289`).

**`pipeline.yaml` alert threshold gap is not a confirmed runtime bug.** The scorer queues alerts by `risk_level in ("medium", "high", "critical")` (`agents/scorer.py:852`); `pipeline.yaml`'s `alert_threshold` appears unused in the current path. This is still config drift, but "zombie campaigns" is not proven.

**`telegram_monitor.py` format issue is a secondary integration defect.** It is real if that service is active, but it is not on the canonical daily runtime path. It should not be grouped with the top blockers.

---

## Valid Risks — Lower Priority Than the Review Suggests

These are worth fixing but are not in the same class as the crashing bugs above:

**`queue_handler.py:35`** — Redis permanent no-op mode via `_client_failed` is a real resilience flaw.

**`api/main.py:68`** — Rate limiting behind a reverse proxy is a deployment hardening issue, not a core implementation failure.

**`api/main.py:101`** — Missing FastAPI lifespan handling is technical debt, relevant only if startup resources need orderly teardown.

**`.env.example`** — Real `ALERT_CHAT_ID` value is a hygiene issue and should be removed, but is not in the same severity band as the crashing bugs.

---

## What the Review Missed

**Working tree vs clean baseline.** The workspace has many uncommitted additions and edits. This review should be treated as a review of the current working tree, not a stable baseline.

**`scraped_messages` persistence is already wired in multiple collectors** — `agents/collector.py:635`, `agents/group_collector.py:147`, `agents/reddit_collector.py:181`, `services/scraper/semakmule_scraper.py:112`. The review should have distinguished "implemented but insufficiently tested" from "missing".

**Phase 11 closure is not assessed.** The original note states phases 0–11 were implemented, but the review does not audit Phase 11 specifically. It is not a complete plan-completion audit.

---

## Revised Priority Order

### P0 — Fix Before Next Pipeline Run

1. Completed in current branch:
   `victim_signal.py`, `alert_builder.py`, `scorer.py`, `web_scraper.py`,
   `rss_collector.py`, `daily_report.py`, and `database.py`

### P1 — Cleanup

8. `queue_handler.py:35` — Replace `_client_failed` flag with `redis-py` `Retry(ExponentialBackoff())`
   Status: fixed. `QueueHandler` now uses redis-py retry configuration and no longer permanently disables Redis for the process after one failed connection attempt.
9. `.env.example` — Remove real `ALERT_CHAT_ID` value
   Status: fixed.
10. `pipeline.yaml` — Remove duplicated config; consolidate into `scoring_rules.yaml`
   Status: fixed. `services.pipeline` now merges shared settings from `scoring_rules.yaml`, and `pipeline.yaml` only carries pipeline-runner settings.
11. `telegram_monitor.py` — Canonicalise to produce `RawMessage` objects
   Status: fixed. The monitor now builds canonical `RawMessage` envelopes, persists them to `scraped_messages`, and publishes the canonical JSON payload.

---

## Validation

Verified in code and fixed in the current branch:

- `PYTHONPATH=. pytest -q tests/test_daily_report.py tests/test_review_defects.py`
- `PYTHONPATH=. pytest -q tests/test_phase1_regressions.py tests/test_phase2_data_integrity.py tests/test_phase4_efficiency.py`

Both test runs passed.

### Report Corrections Needed

- Remove the `deposit_scam` alias gap claim — already fixed
- Remove the "daily report state machine tests missing" claim — tests exist; reword to "missing coverage for the unreachable `PARTIAL_RUN_STALE_RESULTS` branch"
- Downgrade `pipeline.yaml` `alert_threshold` from confirmed runtime bug to stale/unused config drift
