# Fraud MVP — Telegram Reporting Bot
## Project Blueprint v1.0 | 04/04/2026

---

## 1. OVERVIEW

**What:** A Telegram bot that lets users submit suspect phone numbers and bank accounts for instant verification against PDRM Semakmule (288K+ records), with a human-review queue for new/unverified submissions.

**Why:** Bridges the gap between fresh scam reports (people encountering scams today) and the official Semakmule database (which updates after victims file police reports — a lag of days/weeks). Turns your Telegram audience into a distributed reporting network.

**Goal:** Early warning on new scam numbers before they hit official databases.

---

## 2. NON-GOALS (Scope Boundaries)

- ❌ Auto-submitting reports to PDRM/Semakmule (only PDRM can add to their DB)
- ❌ Building a competing phone DB (Semakmule is the source of truth)
- ❌ Supporting every entity type (focus: phone numbers + bank accounts only)
- ❌ Real-time push notifications to all users (too complex for v1)
- ❌ Multi-language support beyond BM/EN
- ❌ Hosting a public API (admin-only REST endpoints)

---

## 3. USER EXPERIENCE

### 3.1 User Commands

| Command | Access | Description |
|---------|--------|-------------|
| `/start` | Public | Welcome message + quick stats |
| `/help` | Public | Full usage guide |
| `/report <phone>` | Public | Verify a phone number against Semakmule |
| `/report <phone> -r` | Public | Report a number as scam (triggers review) |
| `/report <bank>` | Public | Verify a bank account against Semakmule |
| `/report <bank> -r` | Public | Report a bank account as scam |
| `/stats` | Public | Show Semakmule database statistics |
| `/check` | Public | Re-check the last number you submitted |
| `/latest` | Public | Show 10 most reported numbers in system |
| `/submit` | Public | Multi-step: guided report submission |
| `/cancel` | Public | Cancel current conversation state |

**Examples:**
```
/report 01112345678
/report 0123456789 -r
/report 512802774281
/report 8881032092097 -r
```

### 3.2 Conversation Flow — `/report <phone>` (Verification)

```
USER                    BOT
  │
  ├─ /report 01112345678
  │
  │                      🔍 Checking PDRM Semakmule...
  │
  ├─                    ┌─ CASE A: FOUND IN SEMAKMULE ──────────────────┐
  │                    │                                                 │
  │                    │  🚨 SEMAKMULE VERIFIED SCAM NUMBER              │
  │                    │                                                 │
  │                    │  🇲🇾 +60 11-123 4567                           │
  │                    │  Network: Maxis/Hotlink                         │
  │                    │  Reports: 47 confirmed scam reports             │
  │                    │                                                 │
  │                    │  This number is linked to:                      │
  │                    │    • Investment fraud                            │
  │                    │    • Job scam operations                         │
  │                    │                                                 │
  │                    │  ─────────────────────────────────────          │
  │                    │  📋 Recommended action:                         │
  │                    │    • Block this number                          │
  │                    │    • Do NOT share personal details              │
  │                    │    • Report to PDRM if affected                │
  │                    │                                                 │
  │                    │  Saw this scam? Help protect others:          │
  │                    │    /report 01112345678 -r (confirm report)     │
  │                    └─────────────────────────────────────────────────┘
  │
  │                      ┌─ CASE B: NOT IN SEMAKMULE ────────────────────┐
  │                      │                                                 │
  │                      │  📝 NUMBER NOT IN PDRM DATABASE              │
  │                      │                                                 │
  │                      │  🇲🇾 +60 11-123 4567                           │
  │                      │  Network: Maxis/Hotlink                        │
  │                      │  Reports in Semakmule: 0                       │
  │                      │                                                 │
  │                      │  This number has NOT been confirmed as scam    │
  │                      │  by PDRM. It may be:                          │
  │                      │    • A new scam number (not yet reported)     │
  │                      │    • A legitimate number                       │
  │                      │    • Recently reported (pending processing)   │
  │                      │                                                 │
  │                      │  ─────────────────────────────────────          │
  │                      │  Did you receive a scam call/message?          │
  │                      │    /report 01112345678 -r  (submit report)    │
  │                      │                                                 │
  │                      │  Your report will be reviewed and may help     │
  │                      │  protect others from this number.              │
  │                      └─────────────────────────────────────────────────┘
```

### 3.3 Conversation Flow — `/report <phone> -r` (Submission)

```
USER                    BOT
  │
  ├─ /report 01112345678 -r
  │
  │                      📝 SUBMIT SCAM REPORT

  │                      Please describe what happened:
  │                      (e.g. "Received WhatsApp message asking for
  │                       OTP for investment scheme")
  │
  ├─ [user types description]
  │
  │                      ┌─ VALID SUBMISSION ─────────────────────────────┐
  │                      │                                                  │
  │                      │  ✅ Report submitted successfully!               │
  │                      │                                                  │
  │                      │  Report ID: #RPT-20260404-0042                   │
  │                      │  Number: 🇲🇾 +60 11-123 4567                    │
  │                      │  Submitted: 04/04/2026 17:55 MYT                 │
  │                      │  Status: Under review                            │
  │                      │                                                  │
  │                      │  Thank you for helping protect the community.   │
  │                      │  We will update you once reviewed.              │
  │                      └──────────────────────────────────────────────────┘
  │
  │                      [Admin notified: 1 pending report]
```

### 3.4 Conversation Flow — Guided `/submit` (Multi-Step)

```
USER                    BOT
  │
  ├─ /submit
  │
  │                      📋 SCAM REPORT — STEP 1/4

  │                      What type of scam was it?
  │                      1️⃣ Phone/WhatsApp call
  │                      2️⃣ SMS
  │                      3️⃣ Bank transfer / Investment
  │                      4️⃣ Online purchase
  │                      5️⃣ Job offer
  │                      6️⃣ Government aid / e-Wallet
  │                      7️⃣ Other
  │
  ├─ 3
  │
  │                      📋 SCAM REPORT — STEP 2/4

  │                      Enter the suspect's phone number
  │                      (e.g. 01112345678 or +601112345678)
  │
  ├─ 01112345678
  │
  │                      📋 SCAM REPORT — STEP 3/4

  │                      🇲🇾 +60 11-123 4567 (Maxis/Hotlink)
  │                      Network: Maxis/Hotlink

  │                      Enter suspect's bank account (if known)
  │                      (Press /skip to skip)
  │
  ├─ 512802774281
  │
  │                      📋 SCAM REPORT — STEP 4/4

  │                      🏦 5128 0277 4281 (Maybank)
  │                      Bank: Maybank

  │                      Briefly describe what happened:
  │
  ├─ [description]
  │
  │                      ✅ Report submitted!
  │                      Report ID: #RPT-20260404-0043
  │                      Status: Under review
```

---

## 4. ARCHITECTURE

### 4.1 System Context

```
                    ┌──────────────────┐
                    │  TELEGRAM SERVERS │
                    └────────┬─────────┘
                             │ Bot API (Long Polling)
                             ▼
                    ┌──────────────────┐
                    │  Telegram Bot     │
                    │  (python-telegram │
                    │   -bot v21+)     │
                    └────────┬─────────┘
                             │ save to DB
                    ┌────────▼─────────┐
                    │  SQLite DB        │
                    │  fraud_bot.db    │
                    └────────┬─────────┘
                             │
         ┌───────────────────┼────────────────────┐
         │                   │                    │
         ▼                   ▼                    ▼
  ┌────────────┐   ┌────────────────┐   ┌─────────────┐
  │ Semakmule  │   │ Admin Panel    │   │ Alert Queue │
  │ API        │   │ (future)       │   │ (future)    │
  └────────────┘   └────────────────┘   └─────────────┘
```

### 4.2 Tech Stack

| Component | Technology | Justification |
|-----------|-----------|---------------|
| Bot framework | `python-telegram-bot v21+` (CallbackQueryHandler, ConversationHandler) | Official Python Telegram Bot library with async support |
| Database | SQLite (`fraud_bot.db`) | Shared with existing Fraud MVP via DB module |
| Semakmule API | `httpx` async | Already in codebase, TLS 1.0 fix applied |
| Phone parsing | `phonenumbers` | Already installed |
| Bank ID | Custom prefix map | Already in `agents/alerter.py` |
| Admin notification | Telegram message directly to admin chat ID | Simple, no extra infra |
| Deployment | Docker (`fraud-bot` service) | Shares `Dockerfile` with fraud-mvp |
| Config | `.env` + `config/bot.yaml` | Token, admin IDs, feature flags |

### 4.3 Directory Structure

```
fraud-mvp/
├── agents/
│   └── reporter_bot/
│       ├── __init__.py
│       ├── bot.py              # Bot initialization, command handlers
│       ├── conversation.py      # Multi-step conversation handlers
│       ├── services/
│       │   ├── __init__.py
│       │   ├── semakmule.py    # Semakmule verification service
│       │   ├── phone.py        # Phone parsing + carrier lookup
│       │   ├── bank.py         # Bank identification
│       │   └── submission.py   # Report submission to DB
│       ├── models/
│       │   ├── __init__.py
│       │   ├── report.py       # Report dataclass
│       │   └── user.py         # User tracking
│       ├── admin/
│       │   ├── __init__.py
│       │   └── notifier.py     # Admin notification service
│       └── config.py           # Bot-specific config
├── config/
│   └── bot_config.yaml         # Bot behavior settings (limits, etc.)
├── db/
│   ├── database.py             # Extended with bot tables
│   └── schema_bot.sql          # New tables for bot
├── .env                        # BOT_TOKEN, ADMIN_CHAT_ID, etc.
└── docker-compose.yaml          # Add fraud-bot service
```

---

## 5. DATABASE SCHEMA

### 5.1 New Tables

```sql
-- User submissions (not yet in Semakmule)
CREATE TABLE bot_reports (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    report_id      TEXT UNIQUE NOT NULL,   -- human-readable: RPT-YYYYMMDD-NNNN

    -- Entity reported
    entity_type    TEXT NOT NULL CHECK(entity_type IN ('phone', 'bank_account')),
    entity_value   TEXT NOT NULL,          -- normalized: 01112345678

    -- Classification
    scam_type      TEXT,                   -- investment, job_task, phishing, etc.

    -- Context
    description    TEXT,                   -- user description of what happened
    user_id        TEXT,                  -- Telegram user ID (anonymized)
    username       TEXT,                   -- Telegram username (optional)

    -- Source
    source         TEXT DEFAULT 'telegram',
    submitted_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    -- Triage
    status         TEXT DEFAULT 'pending'
                  CHECK(status IN ('pending', 'approved', 'rejected', 'forwarded')),
    reviewed_by    TEXT,
    reviewed_at    TIMESTAMP,
    review_notes   TEXT,

    -- Semakmule state
    semakmule_checked  BOOLEAN DEFAULT 0,
    semakmule_result    TEXT,              -- JSON of Semakmule response
    semakmule_checked_at TIMESTAMP
);

CREATE INDEX idx_bot_reports_entity    ON bot_reports(entity_type, entity_value);
CREATE INDEX idx_bot_reports_status   ON bot_reports(status);
CREATE INDEX idx_bot_reports_submitted ON bot_reports(submitted_at DESC);

-- User conversation state (for multi-step flows)
CREATE TABLE bot_conversations (
    user_id        TEXT PRIMARY KEY,
    state          TEXT,                   -- 'SUBMIT_STEP_1', 'SUBMIT_STEP_2', etc.
    data           TEXT,                   -- JSON blob of partial submission
    started_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Semakmule lookup cache (avoid repeated API calls for same number)
CREATE TABLE semakmule_cache (
    entity_type  TEXT NOT NULL,
    entity_value TEXT NOT NULL,
    result       TEXT NOT NULL,           -- JSON: {found, count, bank_name, etc.}
    checked_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(entity_type, entity_value)
);

CREATE INDEX idx_cache_checked ON semakmule_cache(checked_at);
```

### 5.2 Extension to Existing `campaigns` Table

```sql
-- Add source for bot-reported campaigns (new column)
ALTER TABLE campaigns ADD COLUMN source TEXT DEFAULT 'telegram_bot';
```

---

## 6. BOT COMMANDS — DETAILED SPEC

### 6.1 `/start`
- Send welcome message
- Show quick stats: "PDRM Semakmule: 288,239 bank accounts, 227,125 phone numbers"
- Show inline keyboard: [🔍 Check a number] [📝 Report a scam] [📊 Stats]

### 6.2 `/help`
- Full usage guide
- How to report a number
- What happens to your report
- Privacy note (Telegram user ID stored for admin contact only)

### 6.3 `/report <value> [-r]`

**Without `-r`:** Lookup only
1. Parse input → detect phone vs bank account
2. Normalize: phone → `01112345678`, bank → `512802774281`
3. Check `semakmule_cache` table first (cache TTL: 1 hour)
4. If miss → call Semakmule API → cache result
5. Return formatted result to user

**With `-r`:** Lookup + submission
1. Perform lookup (above)
2. Save to `bot_reports` table
3. Notify admin (if admin chat ID configured)
4. Return confirmation with Report ID

### 6.4 `/submit`
- Multi-step ConversationHandler
- Steps: scam_type → entity_value → bank_account (optional) → description
- Each step has 5-minute timeout → auto-cancel with `/cancel`
- On completion: save to `bot_reports`, notify admin

### 6.5 `/stats`
- Fetch from Semakmule scraper's cached stats (show: "As of 04 Apr 2026")
- Show: total bank accounts, total phones, top 3 reported numbers this week
- Cache: refresh every 6 hours

### 6.6 `/check`
- Re-check last number the user submitted
- Useful after filing a police report (user wants to see if it's now in Semakmule)

### 6.7 `/latest`
- Show 10 most submitted numbers in bot system (pending + approved)
- Filter: approved only (don't reveal pending investigations)
- Group by entity type

### 6.8 `/cancel`
- Clear user's conversation state from `bot_conversations`
- Send: "Conversation cancelled. Start fresh with /submit or /report"

---

## 7. ADMIN FEATURES

### 7.1 Admin Notification (v1 — Simple)

When a user submits a report with `-r`:
```
📨 NEW SCAM REPORT

ID:      #RPT-20260404-0043
Type:    Phone
Number:  🇲🇾 +60 11-123 4567
Bank:    🏦 5128 0277 4281 (Maybank)
Scam:    Investment fraud
From:    @username (TG: 7684441863)
Time:    04/04/2026 17:55 MYT

Description:
"WhatsApp message asking me to invest in crypto platform..."

───────────────
/approve 0043   → Forward to PDRM
/reject 0043    → Dismiss
/flag 0043      → Mark as priority
```

### 7.2 Admin Commands

| Command | Who | Description |
|---------|-----|-------------|
| `/admin` | Admin only | Show admin dashboard |
| `/pending` | Admin only | List pending reports |
| `/approve <id>` | Admin only | Mark as approved/forwarded |
| `/reject <id>` | Admin only | Dismiss report |
| `/stats` | Admin only | Bot usage statistics |
| `/ban <user_id>` | Admin only | Ban user from submitting |
| `/broadcast <msg>` | Admin only | Broadcast to all bot users (future) |

### 7.3 Admin Dashboard (future, not v1)
- Web panel at `/admin` (protected, same FastAPI)
- Shows: pending queue, submission trends, top reported numbers
- Actions: approve/reject/flag

---

## 8. ANTI-ABUSE & SAFETY

### 8.1 Rate Limiting

| Action | Limit | Window | Response |
|--------|-------|--------|----------|
| `/report` (check) | 20 | per user / minute | "Slow down! Try again in X seconds." |
| `/report -r` (submit) | 5 | per user / hour | "You've submitted too many reports. Please wait." |
| `/submit` | 3 | per user / hour | Same |
| Any command | 60 | per user / minute | Global rate limit |

### 8.2 Input Validation

- Phone numbers: Must pass `phonenumbers` validation. Reject if < 7 digits or invalid format.
- Bank accounts: Must be 8-16 digits. Reject implausible patterns (Steam UIDs, timestamps).
- Description: Max 500 characters. HTML/special chars stripped.
- Scam type: Must match predefined list (no free text for type).

### 8.3 Abuse Patterns

| Pattern | Mitigation |
|---------|-----------|
| User submits 50 reports in 1 hour | Rate limit + flag for review |
| User reports legitimate numbers as prank | Admin review required; repeated = ban |
| Bot used for harassment | Admin can ban by user_id |
| Spam/mass reporting | Require confirmation step for submissions |
| Self-reporting own number | Allowed (user may want to check) |

### 8.4 Privacy

- Telegram user ID stored (for admin contact on urgent reports)
- Username stored if available (optional)
- Phone numbers stored in normalized form (digits only)
- Reports NOT shared publicly
- Admin can export CSV (for PDRM forwarding)

---

## 9. INTEGRATION WITH FRAUD MVP

### 9.1 Shared Components

| Component | Shared with Fraud MVP | How |
|-----------|----------------------|-----|
| `db/database.py` | ✅ | Extended with bot tables via schema_bot.sql |
| `SemakMuleScraper` | ✅ | Used via `services/scraper/semakmule_scraper.py` |
| `phonenumbers` lib | ✅ | Already installed |
| Bank ID map | ✅ | Copied from `agents/alerter.py` |
| Redis | ✅ | QueueHandler already shared |
| `.env` config | ✅ | Add `BOT_TOKEN`, `ADMIN_CHAT_ID` |

### 9.2 New Data Flow

```
Telegram Bot → bot_reports table
                    │
                    ├── [v1] Admin reviews → forwards to PDRM manually
                    │
                    └── [future] Approved reports → campaigns table
                                    → triggers scam alert pipeline
```

### 9.3 Future: Bot Reports → Alert Pipeline

After admin approves a report:
1. Insert entity into `entities` table with `source = 'telegram_bot'`
2. Insert edge into `entity_edges` with `platform = 'telegram_bot'`
3. Push to `extracted_entities` queue
4. Normal pipeline: scorer → campaign detection → alerter
5. Original reporter gets Telegram alert when campaign formed

This is **v2 scope** — not in initial build.

---

## 10. CONFIGURATION

### 10.1 `.env` additions

```bash
# Telegram Bot
BOT_TOKEN=your_telegram_bot_token_here
ADMIN_CHAT_ID=7684441863                    # Your Telegram chat ID

# Bot behavior
BOT_RATE_LIMIT_REQUESTS=20                  # per minute
BOT_RATE_LIMIT_SUBMISSIONS=5               # per hour
BOT_CACHE_TTL_SECONDS=3600                  # Semakmule cache (1 hour)
BOT_CONVERSATION_TIMEOUT=300               # 5 minute timeout per step

# Optional
BOT_ALLOW_ANONYMOUS=true                   # Allow reports without Telegram ID
BOT_NOTIFY_NEW_REPORTS=true                # Notify admin on new submission
```

### 10.2 `config/bot_config.yaml`

```yaml
bot:
  name: "FraudCheck Bot"
  description: "Verify scam numbers against PDRM Semakmule + community reports"

scam_types:
  - id: "phone_whatsapp"
    label: "Phone/WhatsApp call"
    emoji: "📞"
  - id: "sms"
    label: "SMS"
    emoji: "💬"
  - id: "investment"
    label: "Investment fraud"
    emoji: "📈"
  - id: "job_task"
    label: "Job task scam"
    emoji: "💼"
  - id: "online_purchase"
    label: "Online purchase scam"
    emoji: "🛒"
  - id: "aid_gov"
    label: "Government aid / e-Wallet scam"
    emoji: "💰"
  - id: "phishing"
    label: "Phishing / Account hijack"
    emoji: "🎣"
  - id: "other"
    label: "Other"
    emoji: "❓"

admin:
  notify_on_submit: true
  notify_on_approve: false
  forward_channel_id: ""   # Future: auto-forward approved to channel
```

---

## 11. IMPLEMENTATION PHASES

### Phase 1: Core Bot MVP
**Goal:** Single Telegram bot that verifies numbers against Semakmule only. No review queue yet.

| # | Task | Effort |
|---|------|--------|
| 1 | Create `agents/reporter_bot/` directory structure | 15 min |
| 2 | Extend `db/database.py` with bot tables + schema_bot.sql | 30 min |
| 3 | Write `semakmule.py` service (cached lookup) | 30 min |
| 4 | Write `phone.py` and `bank.py` services (reuse from alerter) | 15 min |
| 5 | Write `bot.py` — command handlers (`/start`, `/help`, `/stats`, `/report`) | 2 hr |
| 6 | Add Semakmule cache table + caching logic | 30 min |
| 7 | Add `BOT_TOKEN`, `ADMIN_CHAT_ID` to `.env` | 5 min |
| 8 | Test end-to-end with real Telegram bot | 1 hr |
| 9 | Add `fraud-bot` service to `docker-compose.yaml` | 15 min |

**Phase 1 deliverable:** A Telegram bot that anyone can message `/report 01112345678` and get an instant Semakmule verification result.

---

### Phase 2: Report Submission + Review Queue
**Goal:** Users can submit reports, admin gets notified.

| # | Task | Effort |
|---|------|--------|
| 1 | Write `conversation.py` — multi-step ConversationHandler for `/submit` | 2 hr |
| 2 | Write `submission.py` — save report to `bot_reports` | 30 min |
| 3 | Write `admin/notifier.py` — Telegram message to admin on new submission | 30 min |
| 4 | Implement rate limiting (per-user, per-command) | 1 hr |
| 5 | Add input validation (phone format, bank length, description sanitization) | 1 hr |
| 6 | Add `/pending`, `/approve`, `/reject` admin commands | 1 hr |
| 7 | Write `models/report.py` dataclass | 15 min |
| 8 | Add conversation state table (`bot_conversations`) | 15 min |
| 9 | End-to-end test: user submits → admin approves | 1 hr |

**Phase 2 deliverable:** Users can submit scam reports via bot. Admin receives notification with approve/reject actions.

---

### Phase 3: Polish + Integration
**Goal:** Connect bot reports to Fraud MVP pipeline.

| # | Task | Effort |
|---|------|--------|
| 1 | Add `/latest` — show 10 most reported numbers | 30 min |
| 2 | Add `/check` — re-check last submitted number | 15 min |
| 3 | Auto-update Semakmule stats every 6 hours | 30 min |
| 4 | Export approved reports as CSV (for PDRM forwarding) | 30 min |
| 5 | Add `source='telegram_bot'` to approved campaigns | 30 min |
| 6 | Add ban/unban command for admins | 30 min |
| 7 | Docker build + deploy verification | 1 hr |
| 8 | Write user-facing `/help` and onboarding | 30 min |
| 9 | Write admin guide | 30 min |

---

## 12. ESTIMATED EFFORT

| Phase | Tasks | Time |
|-------|-------|------|
| Phase 1 | 9 tasks | ~6 hours |
| Phase 2 | 9 tasks | ~9 hours |
| Phase 3 | 9 tasks | ~5.5 hours |
| **Total** | **27 tasks** | **~20.5 hours** |

**Recommended pacing:** Phase 1 in one session, Phase 2 in one session, Phase 3 in a follow-up.

---

## 13. TEST PLAN

### Phase 1 Tests
1. Bot starts without errors → `python -m agents.reporter_bot.bot`
2. `/start` → welcome message + stats
3. `/report 01112345678` → "not found" response
4. `/report 512802774281` → "PDRM VERIFIED — 51 reports" response
5. `/report invalid` → "Invalid format" error
6. `/stats` → shows cached Semakmule stats
7. Rate limit: 21st `/report` in 1 minute → "slow down" message
8. Admin notification fires when bot token + admin ID configured

### Phase 2 Tests
1. `/report 01112345678 -r` → shows lookup + "submit?" prompt
2. `/submit` → 4-step flow completes → report saved in DB
3. Admin receives Telegram notification within 5 seconds of submission
4. `/pending` → shows submitted report
5. `/approve <id>` → report marked approved
6. `/reject <id>` → report marked rejected
7. Rate limit: 6th submission in 1 hour → blocked
8. User submits with description containing HTML → sanitized

### Phase 3 Tests
1. `/latest` → shows 10 approved numbers
2. `/check` → re-checks last submitted number
3. CSV export → valid CSV with correct columns
4. Approved report appears in Fraud MVP campaigns table
5. Docker compose up → bot starts successfully

---

## 14. OPEN QUESTIONS (for Kem to verify)

1. **Admin identity:** Who is the admin? Just you (Kem), or multiple people?
2. **Bot ownership:** Who creates the Telegram bot? (Need @BotFather token)
3. **PDRM forwarding:** What do you want the approved report CSV to look like? Single file per report or bulk weekly export?
4. **Channel posting:** Should approved/rejected reports be posted to a private Telegram channel (e.g. for your team)?
5. **Bot name:** What should the bot be called? (e.g. "FraudCheck Bot", "ScamShield MY")
6. **Onboarding:** Start with just you as admin, or invite-only beta with a user list?

---

*Blueprint v1.0 — 04/04/2026 — Verify before implementation*
