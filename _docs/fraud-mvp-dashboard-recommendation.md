# FraudMVP — Management Dashboard Recommendation

The dashboard should not be a generic database viewer. That shows activity, not value. It needs to answer three questions fast:

1. Is the system alive and operating reliably?
2. What fraud intelligence is it producing?
3. Why should we trust the output?

The best first version is a simple dashboard in `frontend/` with four sections.

---

## What to Show

### 1. Operations Overview

*Proves reliability and efficiency.*

| Metric | Purpose |
|--------|---------|
| Last successful pipeline run | Confirms the system is running |
| Next scheduled run | Shows continuity |
| Fresh data status (last 24h) | Confirms live input |
| Queue depth | Shows backlog health |
| Messages ingested (24h) | Throughput |
| Entities extracted (24h) | Throughput |
| Campaigns formed (24h) | Detection activity |
| Alerts sent (24h) | Output volume |

Management can see the system is running continuously, see throughput rather than just existence, and assess pipeline efficiency and operational stability.

---

### 2. Intelligence Overview

*Proves the system detects fraud patterns rather than collecting noise.*

- Campaigns by risk level
- Campaign trend over time
- Scam-type distribution
- Top active campaigns
- Top reused entities
- Most active channels/platforms

This shows that the system turns raw messages into structured intelligence, demonstrates clustering and prioritisation, and lets management see where risk is concentrated.

---

### 3. Evidence & Confidence Overview

*Proves the output is explainable and credible.*

- Cross-reference matches count
- Victim signal detections count
- Entity relationship count
- Linked-entity depth (average entities per campaign)
- Alert reasons breakdown
- Percentage of campaigns with supporting evidence

Management needs to know alerts are not random. This section shows intelligence beyond rule matches and makes the system defensible to non-technical stakeholders.

---

### 4. Campaign Drilldown

*The "show me an example" area.*

For each recent campaign, display:

- Score and risk level
- Campaign type
- First seen / last seen
- Entity count and channel count
- Top entities
- Reason summary
- Whether alerted
- Supporting cross-reference / victim-signal markers

This turns abstract metrics into concrete cases and gives management something to inspect without reading raw DB rows.

---

## What to Avoid in V1

Do not lead with:

- Raw `scraped_messages`
- Full entity tables
- Redis internals
- Long lists of low-level logs
- Too many charts

These are useful for operators, not management. They dilute the message.

---

## Intelligence Signals Worth Showcasing

The most management-worthy signals in the current system are:

- Campaign formation from many entities and channels
- Prioritisation by risk level
- Cross-reference confirmation from BNM, SC, and SemakMule
- Victim-signal detection
- Trend detection
- Recent alert output
- System freshness

That combination demonstrates both **efficiency** (volume processed, freshness, run stability) and **intelligence** (structured detection, prioritisation, evidence-backed output).

---

## Build Plan

Build in this order to keep scope controlled:

1. **`frontend/` scaffold** — A lightweight static app or small React/Vite app.
2. **Operations Overview page first** — Use existing `/stats`, `/status`, `/campaigns`, `/alerts`, `/entities` endpoints.
3. **Add backend summary endpoints only if needed** — The current API is close, but chart-ready management cards may need small aggregate endpoints rather than pulling large lists into the browser.
4. **Intelligence Overview and drilldown pages** — Recent campaigns and alerts with evidence summaries.
5. **Polish last** — Good layout, clear labels, no admin-panel clutter. Only after the data model is right.

---

## Suggested Pages

| Page | Content |
|------|---------|
| Executive Dashboard | Operations and intelligence overview combined |
| Campaigns | Risk distribution, trends, top active campaigns |
| Alerts | Recent alerts with reason and provenance |
| Evidence & Quality | Cross-references, victim signals, entity-linking depth |

---

## Technical Direction

- Create `frontend/` and read from existing FastAPI endpoints first.
- Only add narrow backend summary routes if current endpoints are too list-oriented for the dashboard's needs.
- Do not create a second data access path directly into SQLite from the frontend.

This keeps the implementation low-risk and avoids duplicating the data access layer.

---

## Implementation Checklist

- [ ] Create `frontend/` scaffold reading from existing FastAPI endpoints
- [ ] Build Operations Overview (pipeline freshness, queue health, alert throughput)
- [ ] Build Intelligence Overview (campaigns by risk, scam-type distribution, top entities, evidence summaries)
- [ ] Build Evidence & Quality view (source coverage, cross-references, victim signals, entity-linking depth)
- [ ] Add Campaign/Alert drilldown (reasons, timestamps, entity counts, channel counts, provenance)
- [ ] Extend API with summary endpoints if needed to avoid over-fetching
- [ ] Validate against current DB contents; confirm fast load, clean degradation when Redis or recent data is absent, no pipeline interference

---

Use this setup.

  The important distinction is:

  - The FastAPI server requires API_ACCESS_TOKEN to
    start.
  - The dashboard page at /dashboard no longer asks you
    to type that token in the browser.
  - Other API routes like /stats, /entities, /
    campaigns, /alerts still require that token if you
    call them directly.

  1. Create .env
  From the repo root:

  cp .env.example .env

  Open .env and set at least these values:

  DEMO_MODE=true
  API_ACCESS_TOKEN=your_long_random_token_here
  DATABASE_URL=sqlite:///./db/fraud_mvp.db
  CORS_ORIGINS=*

  For API_ACCESS_TOKEN, use any long random string.
  Example:

  API_ACCESS_TOKEN=fraud-mvp-local-2026-very-long-random-
  string-12345

  If you want to generate one in shell:

  openssl rand -hex 32

  Then paste the output into .env as the value of
  API_ACCESS_TOKEN.

  2. Install dependencies
  If you have not created the virtualenv yet:

  make install

  This creates .venv and installs requirements.txt.

  3. Start Redis
  The app can still show dashboard data without Redis,
  but queue health will degrade to no-op mode. If you
  want the full normal setup:

  make redis

  4. Start the API
  Run:

  make api

  That starts:

  uvicorn api.main:app --host 0.0.0.0 --port 8000
  --reload

  If startup fails, the first thing to check is
  whether .env exists and contains API_ACCESS_TOKEN.

  5. Open the dashboard
  In your browser:

  http://localhost:8000/dashboard

  That page should load directly with no API-key prompt.

  6. If the dashboard still looks empty
  Check the summary endpoint directly in the browser:

  http://localhost:8000/dashboard_api/summary

  Expected result: JSON with sections like:

  - operations
  - intelligence
  - evidence
  - recent_campaigns
  - recent_alerts

  If that URL works, the backend is fine and a hard
  refresh of /dashboard should fix the UI cache.

  7. What token to use
  Use the exact token you put in .env under:

  API_ACCESS_TOKEN=...

  That token is only needed for protected API endpoints,
  for example:

  curl -H "X-API-Key: YOUR_TOKEN"
  http://localhost:8000/stats

  You do not need to enter it on the dashboard page
  anymore.

  Minimal working setup
  If you only want the dashboard up quickly, this is
  enough:

  1. cp .env.example .env
  2. Set API_ACCESS_TOKEN in .env
  3. Leave DEMO_MODE=true
  4. make install
  5. make api
  6. Open http://localhost:8000/dashboard

  If you want, I can do one more pass and add a short
  “How to Run Dashboard” section into README.md so this
  is documented in the repo itself.