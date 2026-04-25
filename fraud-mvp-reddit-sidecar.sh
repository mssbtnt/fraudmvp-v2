#!/bin/bash
# fraud-mvp-reddit-sidecar.sh
# Runs Reddit promotion independently from the main scheduled pipeline so
# Playwright/login delays cannot block core collection, scoring, or alerting.

set -o pipefail

DATE=$(date +%Y%m%d)
LOG_DIR="$(dirname "$0")/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/reddit-sidecar-${DATE}.log"

log() {
    echo "$@" | tee -a "$LOG_FILE"
}

info() {
    log "  $1"
}

log "═══════════════════════════════════════════════════════"
log "  FRAUD MVP — Reddit Sidecar  $(date '+%Y-%m-%d %H:%M %Z')"
log "═══════════════════════════════════════════════════════"

cd "$(dirname "$0")"
if [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
elif [ -f "venv/bin/activate" ]; then
    source venv/bin/activate
else
    echo "No virtualenv found at .venv/ or venv/. Create one before running the Reddit sidecar." >&2
    exit 1
fi

export PYTHONPATH="$(pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"

CMD=("$PYTHON_BIN" -m agents.reddit_collector --promote-qualified)

if [ -n "${REDDIT_MIN_SCAM_RELEVANCE:-}" ]; then
    CMD+=(--min-scam-relevance "$REDDIT_MIN_SCAM_RELEVANCE")
fi

if [ -n "${REDDIT_MIN_TEXT_LENGTH:-}" ]; then
    CMD+=(--min-text-length "$REDDIT_MIN_TEXT_LENGTH")
fi

info "Running: $(printf '%q ' "${CMD[@]}")"
"${CMD[@]}" 2>&1 | tee -a "$LOG_FILE"
exitcode=${PIPESTATUS[0]}

if [ $exitcode -eq 0 ]; then
    info "✅ Reddit sidecar — succeeded"
else
    info "⚠️  Reddit sidecar — exited with code $exitcode"
fi

exit $exitcode
