"""SQLite schema and connection.

Six tables, and an FTS5 index over title and abstract. No server process, so
the whole artefact is one folder a marker can reproduce a result from.

Two design points worth stating, because they are what RQ1 rests on:

* ``work.label_included`` is ground truth. It is written by the ingest
  service and read by ``slr.eval.metrics``. Nothing in ``slr.services.screen``
  or in any prompt may touch it.
* ``screening_decision.span_verified`` is the column the trust argument lives
  or dies on. It is set by the verifier, never by the model.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- The corpus. One row per bibliographic record.
CREATE TABLE IF NOT EXISTS work (
    work_id         TEXT PRIMARY KEY,
    review          TEXT NOT NULL,          -- which SYNERGY review it came from
    doi             TEXT,
    title           TEXT,
    abstract        TEXT,
    year            INTEGER,
    venue           TEXT,
    publisher       TEXT,
    country         TEXT,
    language        TEXT,
    label_included  INTEGER                 -- GROUND TRUTH. Never in a prompt.
);
CREATE INDEX IF NOT EXISTS idx_work_review ON work(review);

-- Full-text index over title and abstract. This is the lexical baseline.
CREATE VIRTUAL TABLE IF NOT EXISTS work_fts USING fts5(
    title,
    abstract,
    content='work',
    content_rowid='rowid',
    tokenize='porter unicode61'
);

-- One row per run of the pipeline.
CREATE TABLE IF NOT EXISTS run (
    run_id          TEXT PRIMARY KEY,
    config_hash     TEXT NOT NULL,
    config_name     TEXT,
    git_sha         TEXT,
    provider        TEXT,
    model           TEXT,
    prompt_version  TEXT,
    temperature     REAL,
    started_at      TEXT,
    finished_at     TEXT,
    total_cost_usd  REAL DEFAULT 0.0
);

-- One row per AI screening decision.
CREATE TABLE IF NOT EXISTS screening_decision (
    run_id          TEXT NOT NULL,
    work_id         TEXT NOT NULL,
    decision        TEXT,                   -- include | exclude | unverified | error
    confidence      REAL,
    evidence_span   TEXT,
    span_verified   INTEGER NOT NULL,       -- 0/1. Set by the verifier only.
    verify_note     TEXT,
    from_cache      INTEGER DEFAULT 0,
    tokens_in       INTEGER DEFAULT 0,
    tokens_out      INTEGER DEFAULT 0,
    cost_usd        REAL DEFAULT 0.0,
    latency_ms      INTEGER DEFAULT 0,
    created_at      TEXT,
    PRIMARY KEY (run_id, work_id),
    FOREIGN KEY (run_id) REFERENCES run(run_id),
    FOREIGN KEY (work_id) REFERENCES work(work_id)
);
CREATE INDEX IF NOT EXISTS idx_decision_run ON screening_decision(run_id);

-- Human decisions, kept separate so agreement and override rate can be
-- computed against the AI row rather than overwriting it.
CREATE TABLE IF NOT EXISTS human_decision (
    run_id          TEXT NOT NULL,
    work_id         TEXT NOT NULL,
    decision        TEXT NOT NULL,
    rationale       TEXT,
    created_at      TEXT,
    PRIMARY KEY (run_id, work_id)
);

-- Response cache. This table is what keeps the project inside its budget.
CREATE TABLE IF NOT EXISTS cached_response (
    cache_key       TEXT PRIMARY KEY,       -- hash(model, prompt_version, work_id)
    raw_response    TEXT NOT NULL,
    tokens_in       INTEGER DEFAULT 0,
    tokens_out      INTEGER DEFAULT 0,
    created_at      TEXT
);

-- Populated in week 11, for the included subset only.
CREATE TABLE IF NOT EXISTS gap_statement (
    work_id         TEXT NOT NULL,
    sentence        TEXT NOT NULL,
    category        TEXT,
    cluster_id      INTEGER,
    created_at      TEXT
);
"""

# Keep the FTS index in step with the work table.
TRIGGERS = """
CREATE TRIGGER IF NOT EXISTS work_ai AFTER INSERT ON work BEGIN
    INSERT INTO work_fts(rowid, title, abstract)
    VALUES (new.rowid, new.title, new.abstract);
END;

CREATE TRIGGER IF NOT EXISTS work_ad AFTER DELETE ON work BEGIN
    INSERT INTO work_fts(work_fts, rowid, title, abstract)
    VALUES ('delete', old.rowid, old.title, old.abstract);
END;

CREATE TRIGGER IF NOT EXISTS work_au AFTER UPDATE ON work BEGIN
    INSERT INTO work_fts(work_fts, rowid, title, abstract)
    VALUES ('delete', old.rowid, old.title, old.abstract);
    INSERT INTO work_fts(rowid, title, abstract)
    VALUES (new.rowid, new.title, new.abstract);
END;
"""


def connect(db_path: str | Path) -> sqlite3.Connection:
    """Open the database, creating it and the schema if absent."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    conn.executescript(TRIGGERS)
    conn.commit()
    return conn


def reset(db_path: str | Path) -> None:
    """Drop and recreate. Used by tests; not called by the pipeline."""
    db_path = Path(db_path)
    if db_path.exists():
        db_path.unlink()
    connect(db_path).close()
