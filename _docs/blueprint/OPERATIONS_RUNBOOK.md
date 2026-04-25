# Fraud MVP Operations Runbook

## Supported Execution Model

This repository currently supports:

- manual stage execution via `python3 -m ...`
- batch execution via `./fraud-mvp-daily-pipeline.sh`
- API read access via FastAPI
- supplementary Reddit research via `python3 -m agents.reddit_collector`

This repository does not currently support:

- background job orchestration from the API
- automatic worker scheduling from `/collect/trigger`, `/extract/trigger`, or `/score/trigger`
- Reddit as a canonical pipeline source for extraction, scoring, or alerting

## Local Setup

```bash
cd /home/mssbai/Desktop/fraud-mvp
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
cp .env.example .env
```

Required `.env` values:

- `API_ACCESS_TOKEN`
- `REDIS_URL`
- `DATABASE_URL`

Required for live Telegram scraping:

- `DEMO_MODE=false`
- `TELEGRAM_API_ID`
- `TELEGRAM_API_HASH`
- `TELEGRAM_BOT_TOKEN` when applicable

Telegram session note:

- live Telegram scraping uses the saved Telethon user session at `/home/mssbai/Desktop/fraud-mvp/fraudmvp_user_session.session`
- background services are non-interactive and will not answer phone/code prompts
- if the session expires, refresh it manually with `python3 scripts/bootstrap_telegram_session.py`

Required for live alert delivery:

- `ALERT_BOT_TOKEN`
- `ALERT_CHAT_ID`

## Start Redis

```bash
docker compose up -d redis
```

## Run the Full Batch Pipeline

```bash
./fraud-mvp-daily-pipeline.sh
```

The script:

- auto-detects `.venv` first, then `venv`
- stops immediately if no virtualenv exists
- fails fast on preflight if the DB is not writable, Redis is unavailable, or required live Telegram env vars are missing
- runs replay/enrichment after extraction via `python3 -m services.pipeline ingest`
- continues through later stages even if an earlier stage fails
- writes daily logs under `logs/`

## Run Stages Manually

```bash
python3 -m agents.rss_collector
python3 -m agents.collector --web-only
python3 -m agents.collector --opensanctions-only
python3 -m agents.collector --telegram-only --skip-snowball
python3 -m services.scraper.semakmule_scraper
python3 -m agents.reddit_collector
python3 -m agents.extractor
python3 -m agents.scorer
python3 -m agents.alerter
```

Reddit notes:

- `agents.reddit_collector` defaults to research-only mode and writes local artifacts under `data/`
- `python3 -m agents.reddit_collector --promote-qualified` enables the gated bridge into `scraped_messages` and `raw_messages`
- promotion is restricted to high-relevance posts with hard entities based on `config/sources.yaml`
- promoted posts retain explicit Reddit provenance in `raw_json`
- Reddit is still not part of `fraud-mvp-daily-pipeline.sh`

Recommended cron flow:

1. Start Redis before both jobs.
2. Run Reddit promotion 5-15 minutes before the main pipeline.
3. Run `./fraud-mvp-daily-pipeline.sh` after Reddit promotion completes.

Example:

```cron
45 6 * * * cd /home/mssbai/Desktop/fraud-mvp && . .venv/bin/activate && python3 -m agents.reddit_collector --promote-qualified >> logs/reddit-cron.log 2>&1
0 7 * * * cd /home/mssbai/Desktop/fraud-mvp && . .venv/bin/activate && ./fraud-mvp-daily-pipeline.sh >> logs/pipeline-cron.log 2>&1
```

Replay tuning:

- `PIPELINE_REPLAY_SINCE` defaults to today
- `PIPELINE_REPLAY_LIMIT` defaults to `5000`
- `PIPELINE_REPLAY_PLATFORM` is optional if you want replay to focus on a single platform

## Schema Migrations

Run migrations only during controlled maintenance windows.

```bash
python3 scripts/migrate_schema_v2.py --dry-run
python3 scripts/migrate_schema_v2.py
python3 scripts/migrate_schema_v3.py --dry-run
python3 scripts/migrate_schema_v3.py
```

Operational rules:

- do not run `fraud-mvp-daily-pipeline.sh` while a schema migration is active
- migration scripts now create `db/fraud_mvp.db.migration.lock`
- runtime startup will fail fast if that lock file exists or if temporary tables such as `entities_old` are present
- use `python3 scripts/pipeline_baseline.py` before and after migrations to capture state

## Run the API

```bash
source .venv/bin/activate
uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload
```

Notes:

- `/health` is unauthenticated
- other endpoints require `X-API-Key: <API_ACCESS_TOKEN>`
- trigger endpoints are informational only and do not launch workers

## Basic Validation

```bash
python3 -m pytest tests
python3 -m compileall agents services api db tests
```

## Common Failure Modes

### API fails on startup

Check:

- `.env` exists
- `API_ACCESS_TOKEN` is set
- dependencies from `requirements.txt` are installed

### Queue depth stays at zero

Check:

- Redis is running
- `REDIS_URL` points to the correct instance
- the collector or scraper stage actually ran
- `scripts/pipeline_baseline.py` reports `queue_backend.mode` as `live`, not `no-op`

### Queue depth grows but campaigns do not appear

Check:

- extractor completed successfully
- scorer ran after extraction
- DB file path in `DATABASE_URL` is the same across stages

### Telegram collector logs an authorization error

Check:

- `.env` still has valid `TELEGRAM_API_ID` and `TELEGRAM_API_HASH`
- the saved session file exists
- the session is still authorized for the user account

Recovery:

```bash
source .venv/bin/activate
python3 scripts/bootstrap_telegram_session.py
```

### Telegram alerting does nothing

Check:

- `DEMO_MODE`
- `ALERT_BOT_TOKEN`
- `ALERT_CHAT_ID`

If credentials are missing, alerts are logged instead of sent.

## Recommended Operator Sequence

1. Start Redis.
2. Activate the virtualenv.
3. Run `python3 scripts/pipeline_baseline.py`.
4. Run tests after dependency changes.
5. Run the pipeline script or run stages manually in order.
6. Use the API for read access and status checks, not job orchestration.
