# FraudMVP Phase 3 — Outline

**Proposed:** 13/04/2026
**Status:** APPROVED — in development
**Depends on:** Phase 1 (✅) + Phase 2 (✅)

---

## Current State Analysis

### What Works
- 9-step scorer pipeline compiles and runs
- All 7 services + 2 agents import correctly
- 120/120 verification tests pass
- Cross-reference: 3,277 entries (BNM + SC + Internal)
- Scam classifier: 10 types, all tests pass
- Campaign namer: generates clean names
- Entity linker: shared_domain links work

### Critical Gaps (Phase 3 Must-Fix)
1. **Entity Linker disconnected** — `link_from_messages()` never called. The extractor writes entities to DB but doesn't create co-occurrence relationships.
2. **Trend detector has no data** — `entity_mentions` table is empty. EMA returns 0 for everything.
3. **Cross-reference cache empty** — `cross_references` table has 0 rows (in-memory index works but cache isn't persisted).
4. **Campaign clustering naive** — uses shared-edge grouping only, no relationship awareness.
5. **Alert builder doesn't use EntityLinker** — related entities not shown in alerts.
6. **No daily pipeline runner** — scorer/alerter are one-shot, no scheduling.
7. **LLM victim signals deferred** — from Phase 2, not yet implemented.

---

## Phase 3 Components

### 3.1 Message Ingestion Pipeline
**File:** `services/ingestion.py` (~15KB)
**Purpose:** Wire the extractor output to EntityLinker and TrendDetector.

Flow:
```
Raw Message → Extractor → entities + edges
  → EntityLinker.link_from_messages()  [co-occurrence]
  → TrendDetector.record_mentions()    [daily counts]
  → Queue for scorer
```

### 3.2 Entity Mentions Backfill
**File:** `scripts/backfill_mentions.py` (~8KB)
**Purpose:** Populate entity_mentions from historical entity_edges data.

Aggregates existing edge timestamps by entity_id + date to create historical daily counts.

### 3.3 Enhanced Campaign Clustering
**Modified:** `agents/scorer.py`
**Purpose:** Use entity_relationships as additional clustering signal.

- After initial edge-based clustering, check entity_relationships for cross-cluster links
- Merge clusters that share high-confidence relationships (≥0.8)
- Weight clustering by relationship type: cross_reference > shared_phone > co_occurrence > same_campaign

### 3.4 Alert Builder + Entity Linker Integration
**Modified:** `services/alert_builder.py`
**Purpose:** Show co-occurring and related entities in alerts.

- Query EntityLinker.get_related_entities() for each entity
- Display related entities with relationship type and confidence
- Show "Entities seen together" section in alerts

### 3.5 LLM-Enhanced Victim Signal Detection
**Modified:** `services/victim_signal.py`
**Purpose:** Add Gemma 4 second pass when regex finds nothing.

- If regex score = 0 but keyword_score ≥ 1, run LLM analysis
- Use Ollama Gemma 4 for detection
- Merge LLM results with regex (deduplicated)
- Graceful fallback if Ollama unavailable

### 3.6 Daily Pipeline Runner
**File:** `services/pipeline.py` (~12KB)
**Config:** `config/pipeline.yaml` (~2KB)
**Purpose:** Orchestrate daily pipeline: ingest → score → alert → trend update.

Scheduled via cron or manual run. Steps:
1. Ingest new messages (from Redis queue)
2. Run entity linking on new entities
3. Run trend detection (daily mention update)
4. Run scorer on new entity clusters
5. Run alerter on high-risk campaigns
6. Update cross-reference cache
7. Log pipeline summary

### 3.7 Campaign Deduplication
**Modified:** `agents/scorer.py`
**Purpose:** Prevent duplicate campaigns for the same entity cluster.

- Before creating a new campaign, check if entities overlap ≥70% with an existing campaign
- If so, update existing campaign (merge entities, update score)
- If not, create new campaign

---

## Implementation Order

| # | Component | Priority | Est. Time | Dependencies |
|---|-----------|:--------:|:---------:|-------------|
| 1 | Ingestion Pipeline | HIGH | 2-3h | Extractor, EntityLinker, TrendDetector |
| 2 | Backfill Mentions | HIGH | 1-2h | entity_edges data |
| 3 | Enhanced Clustering | HIGH | 2-3h | EntityLinker |
| 4 | Alert + Entity Linker | MEDIUM | 1-2h | EntityLinker |
| 5 | LLM Victim Signals | MEDIUM | 1-2h | Ollama |
| 6 | Daily Pipeline | HIGH | 2-3h | All above |
| 7 | Campaign Dedup | MEDIUM | 1-2h | Scorer |

**Total:** 10-17 hours

---

## DB Schema Changes

None — all tables already exist from Phase 1.

---

## Files to Create

| File | Size Est. | Purpose |
|------|:---------:|---------|
| `services/ingestion.py` | ~15 KB | Message ingestion pipeline |
| `scripts/backfill_mentions.py` | ~8 KB | Historical mentions backfill |
| `services/pipeline.py` | ~12 KB | Daily pipeline runner |
| `config/pipeline.yaml` | ~2 KB | Pipeline configuration |

## Files to Modify

| File | Changes |
|------|---------|
| `agents/scorer.py` | Enhanced clustering + campaign dedup |
| `services/alert_builder.py` | Entity linker integration |
| `services/victim_signal.py` | LLM-enhanced detection |