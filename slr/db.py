"""SQLite schema and connection.

Six tables, and an FTS5 index over title and abstract. No server process, so
the whole artefact is one folder a marker can reproduce a result from.

Three design points worth stating, because they are what RQ1 rests on:

* ``work.label_included`` is ground truth. It is written by the ingest
  service and read by ``slr.eval.metrics``. Nothing in ``slr.services.screen``
  or in any prompt may touch it.
* ``screening_decision.span_verified`` is the column the trust argument lives
  or dies on. It is set by the verifier, never by the model.
* A record is identified by ``(review, work_id)``, not by ``work_id`` alone.
  The same OpenAlex work can appear in more than one SYNERGY review, and its
  label belongs to the review, not to the paper.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

# Bump whenever the schema changes shape. An older database is refused rather
# than silently half-migrated: it is regenerated from SYNERGY by ingest.
SCHEMA_VERSION = 4

SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- The corpus. One row per bibliographic record per review.
CREATE TABLE IF NOT EXISTS work (
    review          TEXT NOT NULL,          -- which SYNERGY review it came from
    work_id         TEXT NOT NULL,
    doi             TEXT,
    title           TEXT,
    abstract        TEXT,
    year            INTEGER,
    venue           TEXT,
    publisher       TEXT,
    country         TEXT,
    language        TEXT,                   -- NULL until detection exists
    label_included  INTEGER NOT NULL,       -- GROUND TRUTH. Never in a prompt.
    PRIMARY KEY (review, work_id)
);

-- Published eligibility criteria per review, stored by ingest with where the
-- text came from. A review without a row here is screened under draft
-- criteria, and every metrics file says so.
CREATE TABLE IF NOT EXISTS review_criteria (
    review          TEXT PRIMARY KEY,
    criteria        TEXT NOT NULL,
    source          TEXT NOT NULL,
    sha256          TEXT NOT NULL
);

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
    review          TEXT NOT NULL,
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
    PRIMARY KEY (run_id, review, work_id),
    FOREIGN KEY (run_id) REFERENCES run(run_id),
    FOREIGN KEY (review, work_id) REFERENCES work(review, work_id)
);
CREATE INDEX IF NOT EXISTS idx_decision_run ON screening_decision(run_id);

-- Human decisions, kept separate so agreement and override rate can be
-- computed against the AI row rather than overwriting it.
CREATE TABLE IF NOT EXISTS human_decision (
    run_id          TEXT NOT NULL,
    review          TEXT NOT NULL,
    work_id         TEXT NOT NULL,
    decision        TEXT NOT NULL,
    rationale       TEXT,
    created_at      TEXT,
    PRIMARY KEY (run_id, review, work_id)
);

-- Response cache. This table is what keeps the project inside its budget.
CREATE TABLE IF NOT EXISTS cached_response (
    cache_key       TEXT PRIMARY KEY,       -- hash(model, prompt_version, review, work_id)
    request_sha256  TEXT NOT NULL,          -- hash of the exact request sent
    raw_response    TEXT NOT NULL,
    tokens_in       INTEGER DEFAULT 0,
    tokens_out      INTEGER DEFAULT 0,
    created_at      TEXT
);

-- Populated in week 11, for the included subset only.
CREATE TABLE IF NOT EXISTS gap_statement (
    review          TEXT NOT NULL,
    work_id         TEXT NOT NULL,
    sentence        TEXT NOT NULL,
    category        TEXT,
    cluster_id      INTEGER,
    created_at      TEXT
);

-- Structured data extraction over verified-include records from a prior
-- screening run. One row per (run, record, field) — mirrors screening's
-- ask -> validate shape -> verify quote discipline, just per field instead
-- of per decision. span_verified is set by the verifier, never the model,
-- same as screening_decision.span_verified.
CREATE TABLE IF NOT EXISTS extraction (
    run_id          TEXT NOT NULL,          -- the extraction run
    source_run_id   TEXT NOT NULL,          -- the screening run it reads from
    review          TEXT NOT NULL,
    work_id         TEXT NOT NULL,
    field_name      TEXT NOT NULL,
    value           TEXT,
    evidence_span   TEXT,
    span_verified   INTEGER NOT NULL,       -- 0/1. Set by the verifier only.
    verify_note     TEXT,                   -- includes "not_stated"
    created_at      TEXT,
    PRIMARY KEY (run_id, review, work_id, field_name)
);
CREATE INDEX IF NOT EXISTS idx_extraction_run ON extraction(run_id);
"""

# Keep the FTS index in step with the work table.
#
# Ingest must write with an UPSERT (INSERT ... ON CONFLICT DO UPDATE), never
# INSERT OR REPLACE: REPLACE deletes the old row without firing the delete
# trigger (unless recursive_triggers is on), which leaves orphaned entries in
# the index and changes BM25 scores every time ingest is re-run.
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
    _check_schema_version(conn, db_path)
    conn.executescript(SCHEMA)
    conn.executescript(TRIGGERS)
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    conn.commit()
    return conn


def _check_schema_version(conn: sqlite3.Connection, db_path: Path) -> None:
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    n_tables = conn.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table'"
    ).fetchone()[0]
    if n_tables and version != SCHEMA_VERSION:
        conn.close()
        raise RuntimeError(
            f"{db_path} has schema version {version}; this code expects "
            f"{SCHEMA_VERSION}. Delete the file and re-run ingest — the corpus "
            f"is regenerated from SYNERGY. Cached responses in it are lost."
        )


def fts_integrity_ok(conn: sqlite3.Connection) -> bool:
    """True when the FTS index matches the work table exactly."""
    try:
        conn.execute("INSERT INTO work_fts(work_fts, rank) VALUES ('integrity-check', 1)")
    except sqlite3.DatabaseError:
        return False
    return True


def reset(db_path: str | Path) -> None:
    """Drop and recreate. Used by tests; not called by the pipeline."""
    db_path = Path(db_path)
    if db_path.exists():
        db_path.unlink()
    connect(db_path).close()
