"""Tests for ingest and the corpus tables.

Ingest is where the ground truth enters the system. A silent error here —
a label overwritten, a missing abstract stored as text, an index drifting out
of step with its table — corrupts every number computed afterwards.
"""

from __future__ import annotations

import pandas as pd
import pytest

from slr.db import SCHEMA_VERSION, connect, fts_integrity_ok
from slr.services.ingest import clean_text, clean_year, ingest_frame


def frame(**overrides):
    base = {
        "openalex_id": ["https://openalex.org/W1", "https://openalex.org/W2"],
        "doi": ["10.1/a", None],
        "title": ["Bayesian estimation in small samples", "Frequentist methods"],
        "abstract": ["We compare estimators at small n.", float("nan")],
        "publication_year": [2019.0, float("nan")],
        "label_included": [1, 0],
    }
    base.update(overrides)
    return pd.DataFrame(base)


@pytest.fixture()
def conn(tmp_path):
    c = connect(tmp_path / "test.db")
    yield c
    c.close()


def test_reingest_keeps_the_fts_index_consistent(conn):
    """INSERT OR REPLACE left orphaned index entries; an upsert must not."""
    for _ in range(3):
        ingest_frame(conn, "Smid_2020", frame())

    n_work = conn.execute("SELECT COUNT(*) FROM work").fetchone()[0]
    n_indexed = conn.execute("SELECT COUNT(*) FROM work_fts_docsize").fetchone()[0]
    assert n_work == 2
    assert n_indexed == 2
    assert fts_integrity_ok(conn)


def test_updated_text_is_searchable_and_old_text_is_not(conn):
    ingest_frame(conn, "Smid_2020", frame())
    ingest_frame(conn, "Smid_2020", frame(title=["Structural equation models", "Frequentist methods"]))

    def hits(term):
        return conn.execute(
            "SELECT COUNT(*) FROM work_fts WHERE work_fts MATCH ?", (term,)
        ).fetchone()[0]

    assert hits("structural") == 1
    assert hits("bayesian") == 0
    assert fts_integrity_ok(conn)


def test_missing_values_are_stored_as_null_not_as_text(conn):
    ingest_frame(conn, "Smid_2020", frame())
    row = conn.execute(
        "SELECT doi, abstract, year, language FROM work WHERE work_id = 'https://openalex.org/W2'"
    ).fetchone()
    assert row["doi"] is None
    assert row["abstract"] is None  # not "nan"
    assert row["year"] is None
    assert row["language"] is None  # not a guessed "en"


def test_float_year_is_parsed():
    assert clean_year(2019.0) == 2019
    assert clean_year("2019") == 2019
    assert clean_year(float("nan")) is None
    assert clean_year("unknown") is None


def test_clean_text_handles_pandas_missing_markers():
    assert clean_text(pd.NA) is None
    assert clean_text(None) is None
    assert clean_text("   ") is None
    assert clean_text(" text ") == "text"


def test_same_work_in_two_reviews_keeps_both_labels(conn):
    """A paper's label belongs to the review, not to the paper."""
    shared = frame(openalex_id=["W_SHARED", "W2"], label_included=[1, 0])
    other = frame(openalex_id=["W_SHARED", "W3"], label_included=[0, 1])
    ingest_frame(conn, "Radjenovic_2013", shared)
    ingest_frame(conn, "Smid_2020", other)

    labels = dict(
        conn.execute(
            "SELECT review, label_included FROM work WHERE work_id = 'W_SHARED'"
        ).fetchall()
    )
    assert labels == {"Radjenovic_2013": 1, "Smid_2020": 0}


def test_ingest_is_full_and_preserves_prevalence(conn):
    """No capping at ingest: stored prevalence is the review's prevalence."""
    n = 200
    big = pd.DataFrame(
        {
            "openalex_id": [f"W{i}" for i in range(n)],
            "title": [f"title {i}" for i in range(n)],
            "abstract": [f"abstract {i}" for i in range(n)],
            "label_included": [1 if i < 2 else 0 for i in range(n)],
        }
    )
    assert ingest_frame(conn, "Smid_2020", big) == n
    included = conn.execute("SELECT SUM(label_included) FROM work").fetchone()[0]
    assert included == 2


@pytest.mark.parametrize("bad", [float("nan"), 2, "yes"])
def test_invalid_labels_stop_the_ingest(conn, bad):
    with pytest.raises(ValueError):
        ingest_frame(conn, "Smid_2020", frame(label_included=[1, bad]))


def test_duplicate_record_with_conflicting_labels_is_rejected(conn):
    with pytest.raises(ValueError, match="different labels"):
        ingest_frame(conn, "Smid_2020", frame(openalex_id=["W1", "W1"], label_included=[1, 0]))


def test_old_schema_is_refused(tmp_path):
    import sqlite3

    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.execute("CREATE TABLE work (work_id TEXT PRIMARY KEY)")
    old.commit()
    old.close()
    with pytest.raises(RuntimeError, match=f"expects {SCHEMA_VERSION}"):
        connect(path)
