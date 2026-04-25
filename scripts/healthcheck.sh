#!/bin/bash
# ──────────────────────────────────────────────────────────────────────────────
# FraudMVP Health Check
# Purpose: Monitor pipeline health and send Telegram alerts on failures.
# Schedule: Every 30 minutes via systemd user timer.
# Author: mssbai | Updated: 15/04/2026
# ──────────────────────────────────────────────────────────────────────────────

set -euo pipefail

# ── Configuration ────────────────────────────────────────────────────────────
PROJECT_ROOT="/home/mssbai/Desktop/fraud-mvp"
VENV_BIN="$PROJECT_ROOT/venv/bin"
PYTHON_BIN="$VENV_BIN/python3"
LOG_DIR="$PROJECT_ROOT/logs"
LOG_FILE="$LOG_DIR/pipeline.log"

# Load bot credentials from .env (avoid hardcoding tokens)
set -a
source "$PROJECT_ROOT/.env" 2>/dev/null || true
set +a

BOT_TOKEN="${ALERT_BOT_TOKEN:-}"
CHAT_ID="${ALERT_CHAT_ID:-7684441863}"
STALE_THRESHOLD_HOURS=6

# ── State ────────────────────────────────────────────────────────────────────
ERRORS=()          # Collect all errors; send ONE combined alert
WARNINGS=()        # Non-critical issues

# ── Helper: Send Telegram Alert ───────────────────────────────────────────────
send_telegram_alert() {
    local body="$1"

    if [[ -z "$BOT_TOKEN" || -z "$CHAT_ID" ]]; then
        echo "⚠️  No ALERT_BOT_TOKEN/ALERT_CHAT_ID — logging only"
        echo "$body"
        return
    fi

    local message="🚨 *FraudMVP Health Alert* 🚨

$body"

    # Use proper JSON payload to avoid Markdown parsing errors
    local payload
    payload=$(printf '%s' "$message" | python3 -c "
import sys, json
text = sys.stdin.read()
print(json.dumps({'chat_id': '$CHAT_ID', 'text': text, 'parse_mode': 'Markdown'}))
")

    local http_code
    http_code=$(curl -s -o /dev/null -w "%{http_code}" \
        -X POST "https://api.telegram.org/bot${BOT_TOKEN}/sendMessage" \
        -H "Content-Type: application/json" \
        -d "$payload")

    if [[ "$http_code" != "200" ]]; then
        echo "❌ Telegram delivery failed (HTTP $http_code)"
    else
        echo "✅ Health alert sent to Telegram"
    fi
}

# ── Helper: Log ───────────────────────────────────────────────────────────────
log_ok()   { echo "✅ $1"; }
log_warn() { echo "⚠️  $1"; WARNINGS+=("$1"); }
log_fail() { echo "❌ $1"; ERRORS+=("$1"); }

# ── Check 1: Redis ────────────────────────────────────────────────────────────
# Redis runs natively on host port 6379 (not Docker). Use Python since
# redis-cli is not installed on this host.
check_redis() {
    local redis_info
    redis_info=$($PYTHON_BIN -c "
import redis, sys
try:
    r = redis.Redis(host='localhost', port=6379, socket_timeout=5)
    assert r.ping(), 'ping failed'
    info = r.info('server')
    v = info.get('redis_version', '?')
    keys = r.dbsize()
    print(f'v{v} keys={keys}')
except Exception as e:
    print(f'ERROR: {e}', file=sys.stderr)
    sys.exit(1)
" 2>&1)

    if [[ $? -eq 0 && "$redis_info" != *"ERROR"* ]]; then
        log_ok "Redis: Online ($redis_info)"
    else
        log_fail "Redis: DOWN — pipeline cannot pass data between steps ($redis_info)"
    fi
}

# ── Check 2: SQLite Database ──────────────────────────────────────────────────
check_database() {
    local db_path="$PROJECT_ROOT/db/fraud_mvp.db"

    if [[ ! -f "$db_path" ]]; then
        log_fail "Database: File not found at $db_path"
        return
    fi

    # Check connectivity + integrity
    local result
    result=$($PYTHON_BIN -c "
import sqlite3, sys
conn = sqlite3.connect('$db_path')
conn.row_factory = None
try:
    # Quick integrity check (first 100 rows only for speed)
    tables = conn.execute(\"SELECT COUNT(*) FROM sqlite_master WHERE type='table'\").fetchone()
    msgs = conn.execute('SELECT COUNT(*) FROM scraped_messages').fetchone()
    ents = conn.execute('SELECT COUNT(*) FROM entities').fetchone()
    camps = conn.execute('SELECT COUNT(*) FROM campaigns').fetchone()
    print(f'tables={tables[0]} msgs={msgs[0]} ents={ents[0]} camps={camps[0]}')
except Exception as e:
    print(f'ERROR: {e}', file=sys.stderr)
    sys.exit(1)
finally:
    conn.close()
" 2>&1)

    if [[ $? -eq 0 && "$result" != *"ERROR"* ]]; then
        log_ok "Database: Accessible ($result)"
    else
        log_fail "Database: Connection failed — $result"
    fi
}

# ── Check 3: Pipeline Agents ─────────────────────────────────────────────────
check_agents() {
    for agent in extractor scorer alerter; do
        if $PYTHON_BIN -c "
import sys
sys.path.insert(0, '$PROJECT_ROOT')
import agents.${agent}
" 2>/dev/null; then
            log_ok "Agent $agent: Ready"
        else
            log_fail "Agent $agent: Failed to import — check for syntax/module errors"
        fi
    done
}

# ── Check 4: Pipeline Freshness ───────────────────────────────────────────────
# Check if the pipeline log has been updated recently.
# If the 3-hour systemd timer is working, the log should never be >6h stale.
check_freshness() {
    if [[ ! -f "$LOG_FILE" ]]; then
        log_fail "Pipeline: Log file not found at $LOG_FILE"
        return
    fi

    # Use pure bash: compare log file mod time against a reference file
    # Create a temp file aged STALE_THRESHOLD_HOURS ago
    local stale_ref
    stale_ref=$(mktemp)
    # Set modification time to STALE_THRESHOLD_HOURS ago
    local stale_seconds=$((STALE_THRESHOLD_HOURS * 3600))
    touch -d "$STALE_THRESHOLD_HOURS hours ago" "$stale_ref" 2>/dev/null || {
        # Fallback for systems where touch -d isn't available
        local now
        now=$(date +%s)
        local target=$((now - stale_seconds))
        touch -t "$(date -d "@$target" '+%Y%m%d%H%M.%S')" "$stale_ref" 2>/dev/null
    }

    if [[ "$LOG_FILE" -ot "$stale_ref" ]]; then
        # Log is older than threshold
        local last_mod
        last_mod=$(stat -c '%y' "$LOG_FILE" 2>/dev/null | cut -d'.' -f1)
        local hours_ago
        hours_ago=$(( ( $(date +%s) - $(stat -c %Y "$LOG_FILE") ) / 3600 ))
        log_fail "Pipeline: Stale — last run at $last_mod (${hours_ago}h ago, threshold=${STALE_THRESHOLD_HOURS}h)"
    else
        local hours_ago
        hours_ago=$(( ( $(date +%s) - $(stat -c %Y "$LOG_FILE") ) / 3600 ))
        log_ok "Pipeline: Fresh — last run ${hours_ago}h ago"
    fi

    rm -f "$stale_ref"
}

# ── Check 5: Systemd Timer Active ─────────────────────────────────────────────
# Verify the 3-hour pipeline timer is actually enabled and scheduled.
check_timer() {
    local timer_name="fraud-mvp-daily.timer"

    if ! systemctl --user is-enabled "$timer_name" &>/dev/null; then
        log_fail "Timer: $timer_name is NOT enabled — pipeline won't run automatically"
        return
    fi

    if ! systemctl --user is-active "$timer_name" &>/dev/null; then
        log_warn "Timer: $timer_name enabled but NOT active"
        return
    fi

    local next_run
    next_run=$(systemctl --user show "$timer_name" -p NextElapseUSecRealtime --value 2>/dev/null || echo "unknown")
    local last_result
    last_result=$(systemctl --user show "fraud-mvp-daily.service" -p Result --value 2>/dev/null || echo "unknown")

    if [[ "$last_result" == "success" ]]; then
        log_ok "Timer: Active (3h cycle), last run: success"
    elif [[ "$last_result" == "failure" ]]; then
        log_warn "Timer: Active but last run FAILED — check journalctl --user -u fraud-mvp-daily"
    else
        log_ok "Timer: Active (3h cycle)"
    fi
}

# ── Check 6: Data Flow Health ─────────────────────────────────────────────────
# Check if scraped_messages has any recent data (the root cause of "no alerts").
check_data_flow() {
    local result
    result=$($PYTHON_BIN -c "
import sqlite3
conn = sqlite3.connect('$PROJECT_ROOT/db/fraud_mvp.db')
recent = conn.execute(\"SELECT COUNT(*) FROM scraped_messages WHERE scraped_at >= datetime('now', '-24 hours')\").fetchone()[0]
total = conn.execute('SELECT COUNT(*) FROM scraped_messages').fetchone()[0]
edges = conn.execute('SELECT COUNT(*) FROM entity_edges').fetchone()[0]
print(f'total={total} recent_24h={recent} edges={edges}')
conn.close()
" 2>&1)

    if [[ $? -eq 0 ]]; then
        local recent_24h
        recent_24h=$(echo "$result" | grep -oP 'recent_24h=\K[0-9]+')
        if [[ "${recent_24h:-0}" -eq 0 ]]; then
            log_warn "Data: No scraped messages in last 24h — scrapers may not be running"
        else
            log_ok "Data: $result"
        fi
    else
        log_warn "Data: Could not query scraped_messages — $result"
    fi
}

# ══ Main ─────────────────────────────────────────────────────────────────════
echo "══════════════════════════════════════════════════"
echo "  FraudMVP Health Check — $(date '+%d/%m/%Y %H:%M')"
echo "══════════════════════════════════════════════════"
echo ""

check_redis
check_database
check_agents
check_freshness
check_timer
check_data_flow

echo ""
echo "──────────────────────────────────────────────────"

# ── Send combined alert if any errors ──────────────────────────────────────────
if [[ ${#ERRORS[@]} -gt 0 ]]; then
    echo ""
    echo "🚨 ${#ERRORS[@]} error(s) detected:"
    for err in "${ERRORS[@]}"; do
        echo "  • $err"
    done

    # Build combined alert message
    combined=""
    for err in "${ERRORS[@]}"; do
        combined+="• $err\n"
    done
    send_telegram_alert "$combined"
fi

if [[ ${#WARNINGS[@]} -gt 0 ]]; then
    echo ""
    echo "⚠️  ${#WARNINGS[@]} warning(s):"
    for warn in "${WARNINGS[@]}"; do
        echo "  • $warn"
    done
    # Warnings don't trigger Telegram alerts (non-critical)
fi

if [[ ${#ERRORS[@]} -eq 0 && ${#WARNINGS[@]} -eq 0 ]]; then
    echo "✅ All systems healthy"
fi

echo "──────────────────────────────────────────────────"