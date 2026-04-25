#!/bin/bash
# fraud-mvp-semakmule-sidecar.sh
# Runs SemakMule independently from the main scheduled pipeline so
# external TLS/endpoint instability cannot block core collection/scoring.

set -o pipefail

DATE=$(date +%Y%m%d)
LOG_DIR="$(dirname "$0")/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/semakmule-${DATE}.log"

log() {
    echo "$@" | tee -a "$LOG_FILE"
}

info() {
    log "  $1"
}

log "═══════════════════════════════════════════════════════"
log "  FRAUD MVP — SemakMule Sidecar  $(date '+%Y-%m-%d %H:%M %Z')"
log "═══════════════════════════════════════════════════════"

cd "$(dirname "$0")"
if [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
elif [ -f "venv/bin/activate" ]; then
    source venv/bin/activate
else
    echo "No virtualenv found at .venv/ or venv/. Create one before running the SemakMule sidecar." >&2
    exit 1
fi

export PYTHONPATH="$(pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
SEMAKMULE_VERIFY_RECENT_ENTITIES="${SEMAKMULE_VERIFY_RECENT_ENTITIES:-true}"
SEMAKMULE_VERIFY_LIMIT="${SEMAKMULE_VERIFY_LIMIT:-100}"
SEMAKMULE_MAX_RETRIES="${SEMAKMULE_MAX_RETRIES:-2}"
SEMAKMULE_HTTP_TIMEOUT_SECONDS="${SEMAKMULE_HTTP_TIMEOUT_SECONDS:-8}"
SEMAKMULE_CURL_TIMEOUT_SECONDS="${SEMAKMULE_CURL_TIMEOUT_SECONDS:-8}"

info "Running: $PYTHON_BIN -m services.scraper.semakmule_scraper"
"$PYTHON_BIN" -m services.scraper.semakmule_scraper 2>&1 | tee -a "$LOG_FILE"
exitcode=${PIPESTATUS[0]}

if [ $exitcode -eq 0 ]; then
    info "✅ SemakMule sidecar — succeeded"
else
    info "⚠️  SemakMule sidecar — exited with code $exitcode"
fi

exit $exitcode
