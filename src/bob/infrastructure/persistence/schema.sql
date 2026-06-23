-- Copyright (c) 2026 Vladimir Zoologov
-- SPDX-License-Identifier: BUSL-1.1
-- Bob persistence schema (SQLite + FTS5). Applied idempotently on init.

-- Episodic memory: the append-only timeline of lived experience.
CREATE TABLE IF NOT EXISTS episodic_log (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ts            TEXT    NOT NULL,            -- ISO-8601, timezone-aware
    event_type    TEXT    NOT NULL,
    content       TEXT    NOT NULL,
    mood_snapshot TEXT,                        -- mood at the moment (nullable)
    tags          TEXT    NOT NULL DEFAULT '', -- comma-separated labels
    -- BOB-021 consolidation: 1 once this episode has been folded into a digest
    -- (event_type='digest'). Non-destructive — the original row is kept, only
    -- flagged, so it is excluded from re-consolidation. Additive for fresh DBs;
    -- a guarded ALTER in initialize() migrates pre-existing DBs (defaults to 0).
    consolidated  INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_episodic_ts ON episodic_log (ts DESC);

-- FTS5 virtual table over episodic content — full-archive keyword recall (Fix A).
-- 'content'-less external-content index keyed back to episodic_log.id via rowid,
-- so the whole conversation is searchable even for turns never fact-extracted.
CREATE VIRTUAL TABLE IF NOT EXISTS episodic_fts USING fts5 (
    content,
    content='episodic_log',
    content_rowid='id'
);

-- Triggers keep the episodic FTS index in sync with the base table.
CREATE TRIGGER IF NOT EXISTS episodic_fts_ai AFTER INSERT ON episodic_log BEGIN
    INSERT INTO episodic_fts (rowid, content) VALUES (new.id, new.content);
END;

CREATE TRIGGER IF NOT EXISTS episodic_fts_ad AFTER DELETE ON episodic_log BEGIN
    INSERT INTO episodic_fts (episodic_fts, rowid, content) VALUES ('delete', old.id, old.content);
END;

CREATE TRIGGER IF NOT EXISTS episodic_fts_au AFTER UPDATE ON episodic_log BEGIN
    INSERT INTO episodic_fts (episodic_fts, rowid, content) VALUES ('delete', old.id, old.content);
    INSERT INTO episodic_fts (rowid, content) VALUES (new.id, new.content);
END;

-- Semantic memory: distilled, durable facts/beliefs.
CREATE TABLE IF NOT EXISTS semantic_memory (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    ts         TEXT    NOT NULL,
    category   TEXT    NOT NULL,
    content    TEXT    NOT NULL,
    confidence REAL    NOT NULL DEFAULT 1.0
);

CREATE INDEX IF NOT EXISTS idx_semantic_ts ON semantic_memory (ts DESC);

-- FTS5 virtual table over semantic content — P0 keyword recall (seam for vectors).
-- 'content'-less external-content index keyed back to semantic_memory.id via rowid.
CREATE VIRTUAL TABLE IF NOT EXISTS semantic_fts USING fts5 (
    content,
    content='semantic_memory',
    content_rowid='id'
);

-- Triggers keep the FTS index in sync with the base table.
CREATE TRIGGER IF NOT EXISTS semantic_fts_ai AFTER INSERT ON semantic_memory BEGIN
    INSERT INTO semantic_fts (rowid, content) VALUES (new.id, new.content);
END;

CREATE TRIGGER IF NOT EXISTS semantic_fts_ad AFTER DELETE ON semantic_memory BEGIN
    INSERT INTO semantic_fts (semantic_fts, rowid, content) VALUES ('delete', old.id, old.content);
END;

CREATE TRIGGER IF NOT EXISTS semantic_fts_au AFTER UPDATE ON semantic_memory BEGIN
    INSERT INTO semantic_fts (semantic_fts, rowid, content) VALUES ('delete', old.id, old.content);
    INSERT INTO semantic_fts (rowid, content) VALUES (new.id, new.content);
END;

-- Vector store (sqlite-vec): dense BGE-M3 embeddings (1024-dim) for semantic
-- search over memory. A vec0 virtual table whose rows map back to a source row
-- via (source, src_id): 'semantic' -> semantic_memory.id, 'episodic' ->
-- episodic_log.id. `source` is a partition key so KNN / existence checks stay
-- per-source-cheap. Created idempotently; populated by backfill + on-write embed
-- (the loadable sqlite-vec extension must be loaded on the connection first).
CREATE VIRTUAL TABLE IF NOT EXISTS memory_vec USING vec0 (
    source    TEXT partition key,  -- 'semantic' | 'episodic'
    src_id    INTEGER,             -- id in the source table this vector embeds
    embedding float[1024]          -- BGE-M3 dense vector
);

-- Current mood: a single-row snapshot (id = 1) holding a JSON blob.
CREATE TABLE IF NOT EXISTS mood_state (
    id    INTEGER PRIMARY KEY CHECK (id = 1),
    state TEXT NOT NULL,  -- JSON object
    ts    TEXT NOT NULL
);

-- Mood history: every mood snapshot, for drift/analysis.
CREATE TABLE IF NOT EXISTS mood_history (
    id    INTEGER PRIMARY KEY AUTOINCREMENT,
    state TEXT NOT NULL,  -- JSON object
    ts    TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_mood_history_ts ON mood_history (ts DESC);

-- Taste axes: learned preferences with conviction and experience counts.
CREATE TABLE IF NOT EXISTS taste_axes (
    axis             TEXT PRIMARY KEY,
    value            REAL    NOT NULL,
    conviction       REAL    NOT NULL DEFAULT 0.0,
    experience_count INTEGER NOT NULL DEFAULT 0
);

-- Relationship state with the user: a single-row JSON blob (id = 1).
CREATE TABLE IF NOT EXISTS relationship (
    id    INTEGER PRIMARY KEY CHECK (id = 1),
    state TEXT NOT NULL  -- JSON object (trust, familiarity, ...)
);

-- Generic key/value store (genesis_done flag, misc state).
CREATE TABLE IF NOT EXISTS kv (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- Per-persona proactivity state (drive engine). One row per persona_id so
-- Bobiverse replicas each keep their own reservoir/markers/flag. Round-tripped
-- by the SqliteProactivityStore adapter; mute_until is the optional timed-mute
-- expiry set by '/quiet 2h' (NULL = no timed mute).
CREATE TABLE IF NOT EXISTS proactivity_state (
    persona_id          TEXT    PRIMARY KEY,
    social_energy       REAL    NOT NULL,
    last_spoke_at       TEXT,                       -- ISO-8601, timezone-aware (nullable)
    last_user_msg_at    TEXT,                       -- ISO-8601, timezone-aware (nullable)
    proactivity_enabled INTEGER NOT NULL DEFAULT 1, -- 0/1 owner-mute flag
    mute_until          TEXT                        -- ISO-8601 timed-mute expiry (nullable)
);

-- Per-persona current fascination (BOB-020): the topic Bob is into right now,
-- its decaying intensity, and when it took hold. One row per persona_id so
-- Bobiverse replicas each keep their own. Round-tripped by SqliteFascinationStore;
-- a persona with no current fascination simply has no row.
CREATE TABLE IF NOT EXISTS fascination_state (
    persona_id TEXT PRIMARY KEY,
    topic      TEXT NOT NULL,
    intensity  REAL NOT NULL,
    created_at TEXT NOT NULL  -- ISO-8601, timezone-aware
);
