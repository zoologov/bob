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
    confidence REAL    NOT NULL DEFAULT 1.0,
    -- BOB-021 dedup: when set, this fact was merged into the canonical fact with
    -- this id (a near-duplicate by embedding cosine, above a conservative
    -- threshold). Non-destructive — the row is kept with provenance (the canonical
    -- id), only excluded from recall so the duplicate never resurfaces. Additive
    -- for fresh DBs; a guarded ALTER in initialize() migrates pre-existing DBs
    -- (defaults to NULL, i.e. an active, un-superseded fact).
    superseded_by INTEGER
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
    mute_until          TEXT,                       -- ISO-8601 timed-mute expiry (nullable)
    pursuit_stopped     INTEGER NOT NULL DEFAULT 0  -- 0/1 goal-pursuit kill-switch (BOB-015)
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

-- Per-sender first impression (BOB-019): Bob's LIGHT first read on each person he
-- meets, keyed by sender_id so it works for owner / known / guest / bot alike. One
-- row per sender, written once on first contact (a save never moves first_seen or
-- the note), so a returning sender is recognised ("кажется, мы уже сталкивались").
-- This is per-PERSON data (about THEM), not owner-private memory — allowed even for
-- a guest. The deliberately minimal foundation for multi-party BOB-014, not it.
CREATE TABLE IF NOT EXISTS first_impression (
    sender_id     INTEGER PRIMARY KEY,
    first_seen_at TEXT NOT NULL,  -- ISO-8601, timezone-aware (when Bob first met them)
    note          TEXT NOT NULL   -- a short, grounded one-line impression
);

-- Per-sender relationship quality (BOB-014): how Bob STANDS with each person, on
-- four axes (trust / respect / warmth / compatibility), each bounded to [-1, 1].
-- Keyed by sender_id so it works for owner / known / guest / bot alike. Unlike the
-- formed-once first_impression, a relationship EVOLVES — a save UPSERTs the row with
-- the newer state after each turn (RelationshipTracker.apply_interaction). This is
-- per-PERSON data (about THEM), not owner-private memory — allowed even for a guest.
-- NB: named `person_relationship`, NOT `relationship` — the latter is the legacy
-- single-row owner-relationship JSON blob above (sqlite_repo), a different concept.
CREATE TABLE IF NOT EXISTS person_relationship (
    sender_id     INTEGER PRIMARY KEY,
    trust         REAL NOT NULL,
    respect       REAL NOT NULL,
    warmth        REAL NOT NULL,
    compatibility REAL NOT NULL
);

-- Conversation floor (BOB-025): who currently holds the "talking turn" in a thread,
-- so a label-less AMBIENT turn can be lifted to DIRECTED_TO_BOB while Bob holds the
-- floor (continuity). Keyed by the THREAD — (chat_id, thread_id) — since the floor is
-- a property of one running exchange, not of a person. thread_id is NOT NULL with a
-- sentinel (-1) standing for "no forum topic / main chat", because SQLite treats NULL
-- as distinct in a PRIMARY KEY (which would break the UPSERT); the adapter maps a
-- domain None to/from that sentinel. holder is the FloorHolder enum value
-- (bob/other/idle); holder_id is the OTHER person's id (nullable); since is a nullable
-- ISO-8601 stamp of when the holder was last confirmed; idle_streak is the silent-
-- ambient run. A thread never seen has no row (the store returns the default IDLE).
CREATE TABLE IF NOT EXISTS conversation_floor (
    chat_id     INTEGER NOT NULL,
    thread_id   INTEGER NOT NULL,             -- -1 sentinel = no topic / main chat
    holder      TEXT    NOT NULL,             -- FloorHolder value (bob/other/idle)
    holder_id   INTEGER,                      -- OTHER person's id (nullable)
    since        TEXT,                         -- ISO-8601 holder-confirmed stamp (nullable)
    idle_streak INTEGER NOT NULL DEFAULT 0,   -- silent-ambient run toward decay
    PRIMARY KEY (chat_id, thread_id)
);

-- Per-persona обида/sulk state (BOB-014 .2b): Bob's hurt affect, entered on a
-- SUSTAINED critical owner-drop, decaying to a GUARANTEED exit. One row per persona_id
-- so Bobiverse replicas each keep their own. Round-tripped by SqliteSulkStore; an
-- unseen persona simply has no row (the store returns the not-sulking default). This
-- carries NO memory and NO soul — only the affect state (anti-Exodus). `since` is a
-- nullable ISO-8601 entry stamp; `announced` is the one-shot GUPPI-announce flag.
CREATE TABLE IF NOT EXISTS sulk_state (
    persona_id TEXT    PRIMARY KEY,
    active     INTEGER NOT NULL DEFAULT 0,  -- 0/1 whether Bob is обижен
    intensity  REAL    NOT NULL DEFAULT 0,  -- [0,1] how hurt, decaying to exit
    low_streak INTEGER NOT NULL DEFAULT 0,  -- consecutive low/hostile observations
    since      TEXT,                        -- ISO-8601 entry stamp (nullable)
    announced  INTEGER NOT NULL DEFAULT 0   -- 0/1 one-shot GUPPI-announce flag
);

-- Goal Engine (BOB-015): Bob's goals + their tasks, per persona, so he keeps his
-- goals between sessions (autonomy stage B). One `goal` row per (persona_id, id);
-- `state`/`origin` are the string GoalState/GoalOrigin enum values. Round-tripped by
-- SqliteGoalStore into a domain GoalGraph; an unseen persona simply has no rows.
-- authz-before-autonomy lives above this table (the tick only advances APPROVED/
-- ACTIVE goals) — the store just persists the state the use-cases set.
CREATE TABLE IF NOT EXISTS goal (
    persona_id  TEXT NOT NULL,
    id          TEXT NOT NULL,
    title       TEXT NOT NULL,
    description TEXT NOT NULL,
    priority    INTEGER NOT NULL,
    criteria    TEXT NOT NULL,              -- textual completion criterion
    state       TEXT NOT NULL,              -- GoalState value (proposed/approved/…)
    origin      TEXT NOT NULL,              -- GoalOrigin value (owner/bob_proposed)
    created_at  TEXT NOT NULL,              -- ISO-8601, timezone-aware
    deadline    TEXT,                       -- ISO-8601, timezone-aware (nullable)
    PRIMARY KEY (persona_id, id)
);

-- One `task` row per (persona_id, id) — a unit of work of a goal. `deps` is a JSON
-- array of predecessor task ids (the topo-sort over readiness is built from it, so a
-- separate edge table is unnecessary at MVP scale); `needs_external_agency` (0/1) is
-- the stage-C gate flag — such a task is never executed autonomously, only proposed.
CREATE TABLE IF NOT EXISTS task (
    persona_id            TEXT NOT NULL,
    id                    TEXT NOT NULL,
    goal_id               TEXT NOT NULL,
    summary               TEXT NOT NULL,
    deps                  TEXT NOT NULL DEFAULT '[]',  -- JSON array of dep task ids
    state                 TEXT NOT NULL,               -- TaskState value
    needs_external_agency INTEGER NOT NULL DEFAULT 0,  -- 0/1 stage-C gate flag
    PRIMARY KEY (persona_id, id)
);

CREATE INDEX IF NOT EXISTS idx_task_goal ON task (persona_id, goal_id);
