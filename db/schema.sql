-- Fraud MVP SQLite Schema
-- Run with: sqlite3 db/fraud_mvp.db < db/schema.sql

CREATE TABLE IF NOT EXISTS entities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    value TEXT NOT NULL,
    type TEXT NOT NULL CHECK(type IN (
        'phone', 'bank_account', 'domain', 'wallet', 'url', 'email', 'ip'
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
        'investment', 'job_task', 'aid_gov', 'phishing', 'unknown'
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

-- Indexes for fast lookups
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
CREATE INDEX IF NOT EXISTS idx_alert_log_campaign ON alert_log(campaign_id);

-- FTS5 for full-text search on messages
CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
    text,
    channel,
    content='scraped_messages',
    content_rowid='id'
);
