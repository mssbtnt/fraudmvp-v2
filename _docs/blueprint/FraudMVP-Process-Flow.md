# FraudMVP System Process Flow

**Project:** FraudMVP (AI-Powered Fraud Detection Platform)
**Version:** 1.0
**Classification:** Internal — Confidential

## 1. System Overview
FraudMVP is designed to detect coordinated scam campaigns targeting Malaysians in real-time. Unlike traditional reactive blacklists, FraudMVP proactively monitors scammer hubs (Telegram, Web, Social Media) to identify patterns and link entities before victims are impacted.

---

## 2. The 4-Step Detection Pipeline

The system operates as a continuous linear pipeline with a feedback loop for scoring.

### Step 1: Collect (The Ingestion Layer)
The system monitors high-risk sources to gather raw data.
- **Sources:** 
    - Telegram broadcast channels (Real-time monitoring)
    - Scam reporting websites (KenaScam, MyScamInfo)
    - RSS feeds and Reddit scam threads
    - SemakMule displayed data
- **Action:** Scrapers pull raw messages and metadata.
- **Output:** Raw text pushed to a processing queue (Redis).

### Step 2: Extract (The Entity Layer)
Raw text is processed to identify actionable intelligence using AI.
- **AI Extraction:** LLMs and Regex extract:
    - **Phone Numbers:** Validated against Malaysian telco prefixes.
    - **Bank Accounts:** Matched against 4-digit IBG prefixes.
    - **URLs:** Identified and classified (e.g., phishing, fake investment).
- **Classification:** The scam type is identified (e.g., Job Scam, Investment Fraud, Phishing).
- **Output:** Structured entities linked to the original source.

### Step 3: Score (The Intelligence Layer)
A 5-step scoring mechanism determines if a set of entities constitutes a "Campaign."

| Stage | Metric | Logic | Points |
| :--- | :--- | :--- | :--- |
| 1 | **Entity Graph** | Link shared phone/bank accounts across different channels. | Base |
| 2 | **Frequency** | 3 or more unique entities appearing in one post/channel. | +40 pts |
| 3 | **Temporal Clustering** | Same entities appearing across different channels within 24h. | +30 pts |
| 4 | **Content Similarity** | Matching "scripts" or persuasive templates (LLM analysis). | +20 pts |
| 5 | **Campaign Formation** | Total Score $\ge$ 60 $\rightarrow$ Trigger Alert. | **Threshold** |

### Step 4: Alert (The Delivery Layer)
High-confidence detections are pushed to operational teams.
- **Risk Tiers:**
    - **Low (40-59):** Logged for observation.
    - **Medium (60-79):** Standard alert to fraud ops.
    - **High (80-94):** Priority alert + API notification.
    - **Critical (95+):** Immediate escalation.
- **Delivery:** Formatted alerts sent via `@fraudmvpalert_bot` and REST API.

---

## 3. Technical Architecture Summary

- **Infrastructure:** ASUS GX10 (NVIDIA GPU, 128GB RAM) — Local-first processing.
- **AI Core:** Ollama (Local LLMs for script analysis and entity extraction).
- **Storage:** SQLite (MVP) $\rightarrow$ PostgreSQL (Production).
- **Latency:** End-to-end detection to alert in **< 10 minutes**.

## 4. Process Flow Diagram (Conceptual)

`[Sources]` $\rightarrow$ `[Scrapers]` $\rightarrow$ `[Raw Queue]` $\rightarrow$ `[AI Extractor]` $\rightarrow$ `[Entity Graph]` $\rightarrow$ `[Scoring Engine]` $\rightarrow$ `[Alert Bot/API]`
