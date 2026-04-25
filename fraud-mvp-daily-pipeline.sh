#!/bin/bash
# fraud-mvp-daily-pipeline.sh
# Runs the supported batch pipeline:
# preflight → collect → extract → replay/enrich → score → alert → postflight
# Schedule: 7:00 AM MYT daily (23:00 UTC)
# Each step is isolated — one failure does NOT stop the pipeline.
# Exit code = number of failed steps (0 = all succeeded).

set -o pipefail  # Catch errors in pipes too

DATE=$(date +%Y%m%d)
LOG_DIR="$(dirname "$0")/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/${DATE}.log"

log() {
    echo "$@" | tee -a "$LOG_FILE"
}

info() {
    log "  $1"
}

run_step() {
    local name="$1"; shift
    local exitcode
    local cmd_display

    echo "" | tee -a "$LOG_FILE"
    log "━━━ $name ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    cmd_display=$(printf '%q ' "$@")
    info "Running: $cmd_display"
    "$@" 2>&1 | tee -a "$LOG_FILE"
    exitcode=${PIPESTATUS[0]}

    if [ $exitcode -eq 0 ]; then
        info "✅ $name — succeeded"
    else
        info "⚠️  $name — exited with code $exitcode (continuing pipeline)"
    fi

    return $exitcode
}

summary_metric() {
    local label="$1"; shift
    log "  ${label}: $*"
}

db_count() {
    local sql="$1"
    "$PYTHON_BIN" - <<PY
import sqlite3
conn = sqlite3.connect('db/fraud_mvp.db')
cur = conn.cursor()
print(cur.execute("""$sql""").fetchone()[0])
conn.close()
PY
}

run_preflight_check() {
    local name="$1"; shift
    local exitcode
    local cmd_display

    info "Preflight: $name"
    cmd_display=$(printf '%q ' "$@")
    info "Command: $cmd_display"
    "$@" 2>&1 | tee -a "$LOG_FILE"
    exitcode=${PIPESTATUS[0]}
    if [ $exitcode -ne 0 ]; then
        info "❌ Preflight failed: $name"
        exit 1
    fi
}

# ── Header ───────────────────────────────────────────────────────────────────

log "═══════════════════════════════════════════════════════"
log "  FRAUD MVP — Daily Pipeline  $(date '+%Y-%m-%d %H:%M %Z')"
log "═══════════════════════════════════════════════════════"

cd "$(dirname "$0")"
if [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
elif [ -f "venv/bin/activate" ]; then
    source venv/bin/activate
else
    echo "No virtualenv found at .venv/ or venv/. Create one before running the pipeline." >&2
    exit 1
fi
export PYTHONPATH="$(pwd)"

PYTHON_BIN="${PYTHON_BIN:-python3}"
BASELINE_SCRIPT="scripts/pipeline_baseline.py"
PIPELINE_REPLAY_SINCE="${PIPELINE_REPLAY_SINCE:-$(date +%F)}"
PIPELINE_REPLAY_LIMIT="${PIPELINE_REPLAY_LIMIT:-5000}"
PIPELINE_REPLAY_PLATFORM="${PIPELINE_REPLAY_PLATFORM:-}"
FRAUDMVP_SEND_ALERTS_FOUND_SUMMARY="${FRAUDMVP_SEND_ALERTS_FOUND_SUMMARY:-false}"
FRAUD_LLM_ENABLED="${FRAUD_LLM_ENABLED:-false}"
FRAUD_LLM_TIMEOUT_SECONDS="${FRAUD_LLM_TIMEOUT_SECONDS:-20}"
FRAUD_LLM_MAX_FAILURES="${FRAUD_LLM_MAX_FAILURES:-2}"

FAILED=0
RSS_OK=0
WEB_OK=0
OPENSANCTIONS_OK=0
TELEGRAM_OK=0
EXTRACTION_OK=0
REPLAY_OK=0
SCORING_OK=0

# ── Preflight ───────────────────────────────────────────────────────────────

run_step "Preflight: Baseline" \
    "$PYTHON_BIN" "$BASELINE_SCRIPT" || ((FAILED++))

run_preflight_check "Database writable" \
    "$PYTHON_BIN" -c "from db.database import Database; db=Database(); print({'stats': db.stats()})"

run_preflight_check "Redis reachable" \
    "$PYTHON_BIN" -c "from services.queue_handler import QueueHandler; q=QueueHandler(); status=q.status(); print(status); raise SystemExit(0 if status['available'] else 1)"

if [ "${DEMO_MODE:-true}" != "true" ]; then
    run_preflight_check "Live Telegram env" \
        "$PYTHON_BIN" -c "import os; missing=[k for k in ['TELEGRAM_API_ID','TELEGRAM_API_HASH'] if not os.getenv(k)]; print({'missing': missing}); raise SystemExit(0 if not missing else 1)"
fi

START_SCRAPED_MESSAGES=$(db_count "SELECT COUNT(*) FROM scraped_messages")
START_ENTITIES=$(db_count "SELECT COUNT(*) FROM entities")
START_CAMPAIGNS=$(db_count "SELECT COUNT(*) FROM campaigns")
START_ALERT_LOG=$(db_count "SELECT COUNT(*) FROM alert_log")

# ── Step 1: Collection ──────────────────────────────────────────────────────

if run_step "Step 1: RSS Feeds" \
    "$PYTHON_BIN" -m agents.rss_collector; then
    RSS_OK=1
else
    ((FAILED++))
fi

if run_step "Step 1b: Web Seed Collector" \
    "$PYTHON_BIN" -m agents.collector --web-only; then
    WEB_OK=1
else
    ((FAILED++))
fi

if run_step "Step 1c: OpenSanctions Collector" \
    "$PYTHON_BIN" -m agents.collector --opensanctions-only; then
    OPENSANCTIONS_OK=1
else
    ((FAILED++))
fi

if run_step "Step 1d: Telegram Collector" \
    "$PYTHON_BIN" -m agents.collector --telegram-only --skip-snowball; then
    TELEGRAM_OK=1
else
    ((FAILED++))
fi

END_COLLECTION_SCRAPED_MESSAGES=$(db_count "SELECT COUNT(*) FROM scraped_messages")
SCRAPED_MESSAGES_PERSISTED=$((END_COLLECTION_SCRAPED_MESSAGES - START_SCRAPED_MESSAGES))
if [ $SCRAPED_MESSAGES_PERSISTED -lt 0 ]; then
    SCRAPED_MESSAGES_PERSISTED=0
fi
COLLECTION_OK=$(( RSS_OK && WEB_OK && OPENSANCTIONS_OK && TELEGRAM_OK ))

# ── Step 2: Extraction ───────────────────────────────────────────────────────

if run_step "Step 2: Extraction" \
    "$PYTHON_BIN" -m agents.extractor; then
    EXTRACTION_OK=1
else
    ((FAILED++))
fi

END_EXTRACTION_ENTITIES=$(db_count "SELECT COUNT(*) FROM entities")
ENTITIES_EXTRACTED=$((END_EXTRACTION_ENTITIES - START_ENTITIES))
if [ $ENTITIES_EXTRACTED -lt 0 ]; then
    ENTITIES_EXTRACTED=0
fi
MESSAGES_PROCESSED=$SCRAPED_MESSAGES_PERSISTED

# ── Step 3: Replay + Enrichment ─────────────────────────────────────────────

REPLAY_CMD=(
    "$PYTHON_BIN" -m services.pipeline ingest
    --since "$PIPELINE_REPLAY_SINCE"
    --limit "$PIPELINE_REPLAY_LIMIT"
)

if [ -n "$PIPELINE_REPLAY_PLATFORM" ]; then
    REPLAY_CMD+=(--platform "$PIPELINE_REPLAY_PLATFORM")
fi

if run_step "Step 3: Replay + Enrichment" \
    "${REPLAY_CMD[@]}"; then
    REPLAY_OK=1
else
    ((FAILED++))
fi

# ── Step 4: Scoring ─────────────────────────────────────────────────────────

if run_step "Step 4: Scoring" \
    "$PYTHON_BIN" -m agents.scorer; then
    SCORING_OK=1
else
    ((FAILED++))
fi

END_SCORING_CAMPAIGNS=$(db_count "SELECT COUNT(*) FROM campaigns")
CAMPAIGNS_SCORED=$((END_SCORING_CAMPAIGNS - START_CAMPAIGNS))
if [ $CAMPAIGNS_SCORED -lt 0 ]; then
    CAMPAIGNS_SCORED=0
fi
ALERTS_TRIGGERED=$(db_count "SELECT COUNT(*) FROM campaigns WHERE alert_sent=0")
if [ $ALERTS_TRIGGERED -lt 0 ]; then
    ALERTS_TRIGGERED=0
fi

# ── Step 5: Alerting ─────────────────────────────────────────────────────────

export FRAUDMVP_COLLECTION_SUCCESS="$COLLECTION_OK"
export FRAUDMVP_RSS_SUCCESS="$RSS_OK"
export FRAUDMVP_WEB_SUCCESS="$WEB_OK"
export FRAUDMVP_OPENSANCTIONS_SUCCESS="$OPENSANCTIONS_OK"
export FRAUDMVP_TELEGRAM_SUCCESS="$TELEGRAM_OK"
export FRAUDMVP_SEMAKMULE_SUCCESS=true
export FRAUDMVP_REDDIT_ENABLED=false
export FRAUDMVP_REDDIT_SUCCESS=false
export FRAUDMVP_RSS_MESSAGES=0
export FRAUDMVP_WEB_MESSAGES=0
export FRAUDMVP_OPENSANCTIONS_MESSAGES=0
export FRAUDMVP_TELEGRAM_MESSAGES=0
export FRAUDMVP_SEMAKMULE_MESSAGES=0
export FRAUDMVP_REDDIT_MESSAGES=0
export FRAUDMVP_SCRAPED_MESSAGES_PERSISTED="$SCRAPED_MESSAGES_PERSISTED"
export FRAUDMVP_EXTRACTION_SUCCESS="$EXTRACTION_OK"
export FRAUDMVP_MESSAGES_PROCESSED="$MESSAGES_PROCESSED"
export FRAUDMVP_ENTITIES_EXTRACTED="$ENTITIES_EXTRACTED"
export FRAUDMVP_SCORING_SUCCESS="$SCORING_OK"
export FRAUDMVP_CAMPAIGNS_SCORED="$CAMPAIGNS_SCORED"
export FRAUDMVP_ALERTS_TRIGGERED="$ALERTS_TRIGGERED"
export FRAUDMVP_SEND_ALERTS_FOUND_SUMMARY="$FRAUDMVP_SEND_ALERTS_FOUND_SUMMARY"

run_step "Step 5: Alerting" \
    "$PYTHON_BIN" -m agents.alerter || ((FAILED++))

END_ALERT_LOG=$(db_count "SELECT COUNT(*) FROM alert_log")
ALERTS_SENT_DELTA=$((END_ALERT_LOG - START_ALERT_LOG))
if [ $ALERTS_SENT_DELTA -lt 0 ]; then
    ALERTS_SENT_DELTA=0
fi

# ── Postflight ──────────────────────────────────────────────────────────────

run_step "Postflight: Baseline" \
    "$PYTHON_BIN" "$BASELINE_SCRIPT" || ((FAILED++))

# ── Footer ──────────────────────────────────────────────────────────────────

echo "" | tee -a "$LOG_FILE"
summary_metric "Log file" "$LOG_FILE"
summary_metric "Replay since" "$PIPELINE_REPLAY_SINCE"
summary_metric "Replay limit" "$PIPELINE_REPLAY_LIMIT"
summary_metric "Scraped messages persisted" "$SCRAPED_MESSAGES_PERSISTED"
summary_metric "Entities extracted" "$ENTITIES_EXTRACTED"
summary_metric "Campaigns scored" "$CAMPAIGNS_SCORED"
summary_metric "Alerts sent" "$ALERTS_SENT_DELTA"
if [ -n "$PIPELINE_REPLAY_PLATFORM" ]; then
    summary_metric "Replay platform" "$PIPELINE_REPLAY_PLATFORM"
fi
if [ $FAILED -eq 0 ]; then
    log "✅ Pipeline complete — $(date '+%Y-%m-%d %H:%M %Z')"
else
    log "⚠️  Pipeline complete with $FAILED step(s) failed — $(date '+%Y-%m-%d %H:%M %Z')"
fi

exit $FAILED
