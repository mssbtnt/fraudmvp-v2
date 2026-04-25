-- Fraud MVP SQLite Schema v2 — Alert Intelligence Enhancement
-- Run with: sqlite3 db/fraud_mvp.db < db/schema.sql
-- Migration: python scripts/migrate_schema_v2.py

CREATE TABLE IF NOT EXISTS entities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    value TEXT NOT NULL,
    type TEXT NOT NULL CHECK(type IN (
        'phone', 'bank_account', 'domain', 'wallet', 'url', 'email', 'ip', 'company_name', 'facebook_url', 'facebook_page', 'telegram_url', 'telegram_channel', 'whatsapp_link', 'whatsapp_contact', 'app_url', 'instagram_url', 'twitter_url'
    )),
    first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    count INTEGER DEFAULT 1,
    campaign_id INTEGER,
    metadata TEXT,  -- JSON blob for extra data
    UNIQUE(value, type)
);

CREATE TABLE IF NOT EXISTS entity_edges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_id INTEGER NOT NULL,
    channel TEXT NOT NULL,
    platform TEXT NOT NULL DEFAULT 'telegram',
    channel_id TEXT,
    member_count INTEGER DEFAULT 0,
    message_hash TEXT,  -- dedup
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (entity_id) REFERENCES entities(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS campaigns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    score INTEGER NOT NULL,
    risk_level TEXT NOT NULL CHECK(risk_level IN (
        'low', 'medium', 'high', 'critical'
    )),
    campaign_type TEXT NOT NULL CHECK(campaign_type IN (
        'investment', 'job_task', 'aid_gov', 'phishing', 'unknown', 'loan_shark', 'romance', 'ecommerce', 'qr', 'macau'
    )),
    entity_ids TEXT NOT NULL,  -- JSON array of entity IDs
    channel_ids TEXT NOT NULL,  -- JSON array of channel identifiers
    keywords TEXT,  -- JSON array of matched keywords
    reason TEXT,
    script_sample TEXT,  -- Sample text for similarity matching
    first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    alert_sent BOOLEAN DEFAULT 0,
    alert_sent_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    url TEXT,
    platform TEXT NOT NULL DEFAULT 'web',
    type TEXT DEFAULT 'complaint_db',
    reliability_score REAL DEFAULT 0.5,
    tags TEXT,  -- JSON array
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_scraped TIMESTAMP,
    is_active BOOLEAN DEFAULT 1
);

CREATE TABLE IF NOT EXISTS scraped_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    platform TEXT NOT NULL,
    channel TEXT NOT NULL,
    channel_id TEXT,
    message_id TEXT,
    sender_id TEXT,
    text TEXT,
    text_hash TEXT UNIQUE,  -- dedup
    raw_json TEXT,  -- Full message JSON
    scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS alert_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id INTEGER,
    alert_level TEXT NOT NULL,
    message TEXT,
    sent_to TEXT,  -- Telegram chat ID or channel
    sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    status TEXT DEFAULT 'pending',
    response TEXT
);

-- ─── Phase 1: Cross-Reference Tables ────────────────────────────────────────

CREATE TABLE IF NOT EXISTS cross_references (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_id INTEGER NOT NULL,
    source_db TEXT NOT NULL,              -- 'bnm', 'sc', 'semakmule', 'internal'
    source_entity_name TEXT,              -- Name from the source listing
    match_confidence REAL DEFAULT 0.0,    -- 0.0-1.0
    listed_date TEXT,                     -- When entity was listed
    status TEXT DEFAULT 'confirmed',      -- confirmed, suspected, verified
    checked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (entity_id) REFERENCES entities(id)
);
CREATE INDEX IF NOT EXISTS idx_cross_ref_entity ON cross_references(entity_id);
CREATE INDEX IF NOT EXISTS idx_cross_ref_source ON cross_references(source_db);

-- ─── Phase 1: Victim Signal Tables ───────────────────────────────────────────

CREATE TABLE IF NOT EXISTS victim_signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id INTEGER,
    entity_id INTEGER,
    signal_type TEXT NOT NULL,             -- 'financial_loss', 'police_report', 'community_warning', 'emotional'
    pattern_matched TEXT,                  -- The regex pattern that matched
    extracted_text TEXT,                   -- The matching text snippet
    extracted_amount REAL,                 -- If monetary amount was extracted
    weight INTEGER DEFAULT 0,             -- Signal weight for scoring
    detected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (message_id) REFERENCES scraped_messages(id),
    FOREIGN KEY (entity_id) REFERENCES entities(id)
);
CREATE INDEX IF NOT EXISTS idx_victim_signal_entity ON victim_signals(entity_id);
CREATE INDEX IF NOT EXISTS idx_victim_signal_type ON victim_signals(signal_type);

-- ─── Phase 3: Trend Detection Tables ────────────────────────────────────────

CREATE TABLE IF NOT EXISTS entity_mentions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_id INTEGER NOT NULL,
    date DATE NOT NULL,
    mention_count INTEGER DEFAULT 1,
    channel_count INTEGER DEFAULT 0,
    platforms TEXT DEFAULT '[]',           -- JSON array of platforms seen
    FOREIGN KEY (entity_id) REFERENCES entities(id),
    UNIQUE(entity_id, date)
);
CREATE INDEX IF NOT EXISTS idx_mentions_entity_date ON entity_mentions(entity_id, date);

-- ─── Phase 2: Campaign Clustering Tables ────────────────────────────────────

CREATE TABLE IF NOT EXISTS campaign_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id INTEGER NOT NULL,
    entity_id INTEGER NOT NULL,
    link_type TEXT NOT NULL,               -- 'co_occurrence', 'shared_phone', 'shared_domain', 'semantic', 'cross_reference'
    confidence REAL DEFAULT 1.0,           -- How confident the link is
    detected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (campaign_id) REFERENCES campaigns(id),
    FOREIGN KEY (entity_id) REFERENCES entities(id),
    UNIQUE(campaign_id, entity_id, link_type)
);
CREATE INDEX IF NOT EXISTS idx_campaign_links_campaign ON campaign_links(campaign_id);
CREATE INDEX IF NOT EXISTS idx_campaign_links_entity ON campaign_links(entity_id);

-- ─── Phase 3: Entity Relationship Graph ──────────────────────────────────────

CREATE TABLE IF NOT EXISTS entity_relationships (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_entity_id INTEGER NOT NULL,
    target_entity_id INTEGER NOT NULL,
    relationship_type TEXT NOT NULL,        -- 'co_occurs', 'shared_phone', 'shared_domain', 'same_campaign', 'registered_to'
    confidence REAL DEFAULT 1.0,
    evidence TEXT,                          -- JSON: message IDs, channels, dates
    first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    count INTEGER DEFAULT 1,
    FOREIGN KEY (source_entity_id) REFERENCES entities(id),
    FOREIGN KEY (target_entity_id) REFERENCES entities(id),
    UNIQUE(source_entity_id, target_entity_id, relationship_type)
);
CREATE INDEX IF NOT EXISTS idx_rel_source ON entity_relationships(source_entity_id);
CREATE INDEX IF NOT EXISTS idx_rel_target ON entity_relationships(target_entity_id);
CREATE INDEX IF NOT EXISTS idx_rel_type ON entity_relationships(relationship_type);

-- ─── Indexes for original tables ─────────────────────────────────────────────

CREATE INDEX IF NOT EXISTS idx_entities_campaign ON entities(campaign_id);
CREATE INDEX IF NOT EXISTS idx_entities_value ON entities(value);
CREATE INDEX IF NOT EXISTS idx_entities_type ON entities(type);
CREATE INDEX IF NOT EXISTS idx_entities_last_seen ON entities(last_seen);
CREATE INDEX IF NOT EXISTS idx_entity_edges_entity ON entity_edges(entity_id);
CREATE INDEX IF NOT EXISTS idx_entity_edges_channel ON entity_edges(channel);
CREATE INDEX IF NOT EXISTS idx_entity_edges_timestamp ON entity_edges(timestamp);
CREATE INDEX IF NOT EXISTS idx_campaigns_score ON campaigns(score);
CREATE INDEX IF NOT EXISTS idx_campaigns_risk ON campaigns(risk_level);
CREATE INDEX IF NOT EXISTS idx_campaigns_type ON campaigns(campaign_type);
CREATE INDEX IF NOT EXISTS idx_scraped_messages_hash ON scraped_messages(text_hash);
CREATE INDEX IF NOT EXISTS idx_scraped_messages_platform ON scraped_messages(platform);
CREATE INDEX IF NOT EXISTS idx_scraped_messages_channel ON scraped_messages(channel);
CREATE INDEX IF NOT EXISTS idx_alert_log_campaign ON alert_log(campaign_id);

-- ─── FTS5 for full-text search on messages ────────────────────────────────────

CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
    text,
    channel,
    content='scraped_messages',
    content_rowid='id'
);
