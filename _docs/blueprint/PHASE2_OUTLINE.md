# FraudMVP Phase 2 — Outline

**Proposed:** 13/04/2026  
**Status:** DRAFT — pending approval  
**Depends on:** Phase 1 (COMPLETE ✅)

---

## Current State (Phase 1 Recap)

| Component | Status | Details |
|-----------|--------|---------|
| DB Schema v2 | ✅ | 11 tables, 23 indexes, 2,864 entities |
| Cross-Reference Engine | ✅ | 3,277 known-bad entries (BNM + SC + Internal) |
| Victim Signal Detector | ✅ | 31 regex patterns, 5 categories, max +50 boost |
| Alert Builder | ✅ | Rich narratives, risk-level actions, Telegram chunking |
| Scorer (6-step) | ✅ | Frequency → Temporal → Content → Channel → CrossRef → VictimSignal |
| Alerter | ✅ | AlertBuilder with fallback |
| Data Cleanup | ✅ | 33 noise entries removed, BNM dates normalised |

### Gaps to Address in Phase 2

1. **Campaign clustering is naive** — same-entity overlap only, no co-occurrence graph
2. **Campaign types are limited** — only 5 canonical types (`investment`, `job_task`, `aid_gov`, `phishing`, `unknown`) with `loan_shark`, `romance`, `ecommerce`, `qr`, `macau` aliased to those 5
3. **No entity linking** — entities that appear together are not connected beyond campaign membership
4. **No trend detection** — `entity_mentions` table is empty, no spike/rise tracking
5. **No auto-naming** — campaigns get IDs but no human-readable names
6. **LLM enhancer exists but underutilised** — only `classify_scam_type()` and `analyze_message()`, not integrated into the scoring pipeline

---

## Phase 2 Components

### 2.1 Entity Linker — Co-occurrence Graph

**File:** `services/entity_linker.py`  
**Purpose:** Build a relationship graph between entities based on co-occurrence in messages, shared channels, and shared campaigns.

**What it does:**
- When a message mentions multiple entities (e.g., phone + bank account + WhatsApp link in the same message), record a `co_occurrence` relationship
- When the same phone number appears in both a Telegram group AND a WhatsApp message, record a `shared_channel` relationship  
- When a domain resolves to the same IP as a known-bad domain, record a `shared_infrastructure` relationship (future — requires DNS resolution)
- When two entities appear in the same campaign cluster, record a `same_campaign` relationship
- Write all relationships to `entity_relationships` table with confidence scores

**Relationship Types:**

| Type | Confidence | Evidence Source |
|------|-----------|----------------|
| `co_occurrence` | 0.6 | Same message mentions both entities |
| `shared_channel` | 0.7 | Same channel/platform, different messages |
| `shared_phone` | 0.9 | Phone linked in WhatsApp URL + standalone |
| `shared_domain` | 0.8 | Same domain serves multiple scam pages |
| `same_campaign` | 0.5 | Both in same campaign cluster |
| `cross_reference` | 1.0 | Both on same BNM/SC alert entry |

**DB Population:**
```python
class EntityLinker:
    def link_from_messages(self, messages: list[dict]) -> int:
        """Process scraped messages and create co-occurrence relationships."""
    
    def link_from_campaigns(self, campaigns: list[Campaign]) -> int:
        """Link entities within the same campaign cluster."""
    
    def link_from_cross_references(self, cross_refs: list[dict]) -> int:
        """Link entities that appear on the same BNM/SC alert entry."""
    
    def get_related_entities(self, entity_id: int, max_depth: int = 2) -> list[dict]:
        """BFS traversal of relationship graph, up to max_depth hops."""
    
    def compute_relationship_boost(self, entity_id: int) -> float:
        """Calculate score boost based on how entity connects to other bad entities."""
```

**Scoring Impact:** +10 to +30 based on `entity_relationships` config in `scoring_rules.yaml`

---

### 2.2 Scam Type Classifier — 3-Tier System

**File:** `services/scam_classifier.py`  
**Config:** `config/scam_types.yaml`  
**Purpose:** Replace the current 5-type system with a proper 3-tier classification that supports the 10 DB campaign types.

**Current Problem:** The `campaign_types.py` has 10 types in the DB but only 5 canonical types. The aliases map `loan_shark → unknown`, `romance → unknown`, etc. This loses information.

**3-Tier Classification:**

| Tier | Method | When Used | Accuracy |
|------|--------|-----------|----------|
| **Tier 1: Keyword** | `KeywordExtractor` (regex + YAML patterns) | All messages | ~70% recall, ~90% precision |
| **Tier 2: LLM** | `FraudLLMEnhancer.classify_scam_type()` (Gemma 4) | When Tier 1 confidence < 80% or score ≥ 60 | ~85% recall, ~90% precision |
| **Tier 3: Cross-Reference** | `CrossReferenceEngine` entity match | When BNM/SC match found | ~95% precision (known entity type) |

**10 Canonical Campaign Types (expanded from 5):**

| Type | Label | Keywords (BM) | BNM/SC Source |
|------|-------|---------------|---------------|
| `investment` | Investment Scam | pelaburan, saham, dividen, ROI | ✅ SC list |
| `job_task` | Job / Task Scam | jawatan kosong, kerja sambilan, deposit | ✅ Community |
| `aid_gov` | Gov Aid Scam | bantuan, STR, e-kasih, PR1MA | ✅ BNM list |
| `phishing` | Phishing | link bank palsu, akaun, login | ✅ Community |
| `loan_shark` | Loan Shark / Ah Long | pinjaman, Ah Long, pemberi wang | ✅ BNM list |
| `romance` | Romance / Love Scam | love scam, sugar daddy, jodoh | ✅ Community |
| `ecommerce` | E-Commerce Scam | beli online, COD, penghantaran | ✅ Community |
| `qr` | QR Code Scam | scan QR, QR code, QR promosi | ✅ Community |
| `macau` | Macau Scam | macau scam, call center, telemarketer | ✅ PDRM |
| `unknown` | Unknown / Unclassified | — | — |

**New `campaign_types.py`:**
- Expand `CANONICAL_CAMPAIGN_TYPES` from 5 → 10
- Update `CAMPAIGN_TYPE_ALIASES` with comprehensive alias mappings
- Update `CAMPAIGN_TYPE_LABELS` for all 10 types
- Add `CAMPAIGN_TYPE_DESCRIPTIONS` for LLM prompt context
- Tier 1 → Tier 2 fallback chain

**Integration Point:** Scorer calls `ScamClassifier.classify(text, keywords, cross_ref_result)` → returns `(campaign_type, confidence, tier_used)`

---

### 2.3 Campaign Naming — Auto-Generate Human-Readable Names

**File:** `services/campaign_namer.py`  
**Purpose:** Generate memorable, searchable campaign names instead of campaign IDs.

**Naming Strategy:**

| Pattern | Example | When |
|---------|---------|------|
| `{type}-{entity}` | `investment-TradeviewCapital` | When a single prominent entity exists |
| `{type}-{phone_last4}` | `macau-5678` | When phone is the primary entity |
| `{type}-{domain}` | `phishing-maybank-my.com` | When domain is the primary entity |
| `{type}-cluster-{id}` | `unknown-cluster-47` | Fallback for multi-entity clusters |

**Implementation:**
```python
class CampaignNamer:
    def __init__(self, db: Database):
        self.db = db
    
    def name_campaign(self, campaign: Campaign, entities: list[EntityNode]) -> str:
        """Generate a human-readable campaign name."""
        # 1. Find the most prominent entity (highest count, cross-ref match, etc.)
        # 2. Apply naming pattern based on entity type
        # 3. Sanitise for filesystem/URL safety
        # 4. Check for name collision (append numeric suffix if needed)
        # 5. Store in campaign metadata
```

**DB Change:** Add `name` column to `campaigns` table.

---

### 2.4 Trend Detector — Mention Spike Detection

**File:** `services/trend_detector.py`  
**Purpose:** Detect when an entity or campaign type is spiking in mentions, indicating an active or growing scam wave.

**What it does:**
- Populate `entity_mentions` table daily with per-entity mention counts
- Compute 7-day EMA (Exponential Moving Average) for each entity
- Compare current day's count to EMA to detect spikes:
  - **Spike**: current > EMA × 3 → +20 boost
  - **Rising**: current > EMA × 2 → +15 boost
  - **Increasing**: current > EMA × 1.5 → +10 boost
- Track at both entity level AND campaign type level

**DB Population:**
```python
class TrendDetector:
    def record_mentions(self, date: str, entity_mentions: dict[int, int]) -> int:
        """Record daily mention counts for entities."""
    
    def detect_trends(self, entity_id: int = None, campaign_type: str = None) -> list[TrendResult]:
        """Detect spikes, rises, and increases for entities or campaign types."""
    
    def get_ema(self, entity_id: int, days: int = 30) -> float:
        """Get Exponential Moving Average for an entity."""
```

**Scoring Impact:** Uses `trend` section in `scoring_rules.yaml` (+10 to +20 boost)

**Architecture:** Trend detection runs as a **post-processing step** after scoring, not inline. The scorer checks `trend_detector.detect_trends()` and applies boosts.

---

### 2.5 LLM-Enhanced Victim Signal Detection

**File:** `services/victim_signal.py` (enhanced)  
**Purpose:** Add an LLM-based detection layer on top of the existing regex patterns to catch creative spellings, mixed-language phrases, and context-dependent signals.

**Approach:**

| Layer | Method | When Used | Recall |
|-------|--------|-----------|--------|
| **Regex (existing)** | Pattern matching | All messages | ~60% recall |
| **LLM (new)** | Gemma 4 analysis | When regex score > 0 OR keywords match | ~85% recall |

**LLM Prompt Strategy:**
```
Analyse this Malaysian scam-related message for victim signals.
Look for: financial loss admissions, police reports, monetary amounts, 
emotional distress, community warnings.

Consider: Malay slang (kena tipu, dah kena), English mix (scam, fraud), 
creative spellings (sc4m, $cam), indirect references.

Return JSON: {"signals": [{"type": "financial_loss", "text": "...", "confidence": 0.9}]}
```

**Integration:**
- Regex runs first (fast, cheap)
- If regex finds ANY signal, skip LLM (already detected)
- If regex finds NOTHING but the message is suspicious (keyword match ≥ 1), run LLM
- LLM results are merged with regex results (deduplicated)

**Cost:** ~0.01 MYR/message for LLM calls (Gemma 4 via Ollama, local)

---

### 2.6 Pipeline Integration — Updated Scorer Flow

The scorer will be updated from 6 steps to 9 steps:

```
Step 1: Entity Graph Construction (existing)
Step 2: Frequency Scoring (existing)
Step 3: Temporal Clustering (existing)
Step 4: Content Similarity + Keyword Extraction (existing)
Step 5: Scam Type Classification (NEW — 3-tier)
Step 6: Cross-Reference Scoring (Phase 1)
Step 7: Victim Signal Scoring (Phase 1, enhanced with LLM)
Step 8: Entity Relationship Scoring (NEW)
Step 9: Trend Scoring (NEW — spike/rise detection)

Final: Platform Weight × Cap 100 → Risk Level → Alert
```

**Campaign Output (enhanced):**
```python
@dataclass
class Campaign:
    # ... existing fields ...
    name: str = ""                          # NEW: auto-generated name
    scam_type_tier: str = ""                # NEW: "keyword" | "llm" | "cross_ref"
    scam_type_confidence: float = 0.0       # NEW: 0.0-1.0
    relationship_boost: float = 0.0          # NEW: entity relationship boost
    trend_status: str = ""                  # NEW: "spike" | "rising" | "increasing" | "stable"
```

---

## Implementation Order

| # | Component | Est. Time | Dependencies | Priority |
|---|-----------|:----------:|--------------|:--------:|
| 1 | Scam Type Classifier | 2-3h | None (expand existing `campaign_types.py`) | HIGH |
| 2 | Campaign Namer | 1-2h | Scam Type Classifier | HIGH |
| 3 | Entity Linker | 3-4h | DB schema (already has `entity_relationships` table) | HIGH |
| 4 | Trend Detector | 2-3h | `entity_mentions` table (already exists) | MEDIUM |
| 5 | LLM-Enhanced Victim Signals | 2-3h | Existing `victim_signal.py` + Ollama | MEDIUM |
| 6 | Scorer Integration (9-step) | 2-3h | All above components | HIGH |
| 7 | End-to-End Testing | 1-2h | All above | HIGH |

**Total estimated:** 13-20 hours

---

## DB Schema Changes

### `campaigns` table — add columns

```sql
ALTER TABLE campaigns ADD COLUMN name TEXT DEFAULT '';
ALTER TABLE campaigns ADD COLUMN scam_type_tier TEXT DEFAULT 'keyword';
ALTER TABLE campaigns ADD COLUMN scam_type_confidence REAL DEFAULT 0.0;
ALTER TABLE campaigns ADD COLUMN relationship_boost REAL DEFAULT 0.0;
ALTER TABLE campaigns ADD COLUMN trend_status TEXT DEFAULT 'stable';
```

### New migration script: `scripts/migrate_schema_v3.py`

- Adds 5 columns to `campaigns`
- Updates `campaign_type` CHECK constraint from 5 → 10 canonical types
- Verifies all existing data

---

## Files to Create

| File | Size Est. | Purpose |
|------|:---------:|---------|
| `services/scam_classifier.py` | ~8 KB | 3-tier scam type classification |
| `services/entity_linker.py` | ~12 KB | Co-occurrence graph builder |
| `services/campaign_namer.py` | ~6 KB | Auto-generate campaign names |
| `services/trend_detector.py` | ~8 KB | Spike/rise/increase detection |
| `config/scam_types.yaml` | ~4 KB | 10-type definitions, aliases, LLM prompts |
| `scripts/migrate_schema_v3.py` | ~12 KB | DB migration v2 → v3 |

## Files to Modify

| File | Changes |
|------|---------|
| `services/campaign_types.py` | Expand canonical types 5→10, update aliases/labels |
| `services/victim_signal.py` | Add LLM-enhanced detection layer |
| `agents/scorer.py` | Add Steps 5,8,9 (scam type, relationships, trends) + Campaign fields |
| `agents/alerter.py` | Include campaign name, scam type tier, trend status in alerts |
| `services/alert_builder.py` | New sections: campaign name, trend indicator |
| `config/scoring_rules.yaml` | Verify new scoring sections are used |

---

## Testing Plan

| Test | What | Tool |
|------|------|------|
| Scam classifier unit | Each tier produces correct type | `pytest` |
| Entity linker integration | Co-occurrence from real messages | `pytest` |
| Campaign naming | No collisions, sanitised names | `pytest` |
| Trend detector | Spike/rise/increase from mention data | `pytest` |
| LLM victim signals | Creative spellings detected | Manual + `pytest` |
| 9-step scorer | All boosts applied correctly | `pytest` |
| End-to-end | Message → Score → Alert → Telegram | Manual |

---

## Out of Scope (Phase 3)

- **Live pipeline testing** with real Telegram channels (requires running scraper)
- **SemakMule integration** (site still DOWN)
- **OpenSanctions integration** (requires API key)
- **Dashboard / Web UI**
- **Rate limiting / Quota management** for LLM calls
- **Historical backfill** of `entity_mentions` (no historical data yet)

---

*Phase 2 outline — pending approval from mssbai*