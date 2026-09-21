"""Tests for the random and lexical baselines.

A baseline that silently degrades is worse than no baseline: every later
improvement is measured against it.
"""

from __future__ import annotations

import pandas as pd
import pytest

from slr.db import connect
from slr.services import retrieve
from slr.services.ingest import ingest_frame

RECORDS = [
    ("W1", "Bayesian estimation in small samples", "Bias of Bayesian estimators at n below fifty.", 1),
    ("W2", "Frequentist methods", "Maximum likelihood under misspecification.", 0),
    ("W3", "Structural equation models", "Bayesian structural equation modelling, small samples.", 1),
    ("W4", "Unrelated topic", "Soil moisture in arid regions.", 0),
]


def _conn(tmp_path, name, order):
    c = connect(tmp_path / name)
    rows = [RECORDS[i] for i in order]
    ingest_frame(
        c,
        "Smid_2020",
        pd.DataFrame(
            {
                "openalex_id": [r[0] for r in rows],
                "title": [r[1] for r in rows],
                "abstract": [r[2] for r in rows],
                "label_included": [r[3] for r in rows],
            }
        ),
    )
    return c


@pytest.fixture()
def conn(tmp_path):
    c = _conn(tmp_path, "t.db", [0, 1, 2, 3])
    yield c
    c.close()


@pytest.mark.parametrize(
    "query",
    [
        "Bayesian estimation, small samples.",
        "bias/variance of Bayesian estimators?",
        "NOT Bayesian NEAR samples",  # FTS5 operators as plain words
        '"unbalanced quote (Bayesian',
    ],
)
def test_punctuation_in_query_still_ranks(conn, query):
    """Previously a comma made FTS5 throw, and the ranking fell back to table order."""
    ranked = retrieve.lexical_rank(conn, query, "Smid_2020")
    assert ranked[0]["score"] is not None
    assert {r["work_id"] for r in ranked[:2]} == {"W1", "W3"}


def test_lexical_rank_returns_the_full_review(conn):
    ranked = retrieve.lexical_rank(conn, "Bayesian", "Smid_2020")
    assert sorted(r["work_id"] for r in ranked) == ["W1", "W2", "W3", "W4"]
    assert ranked[-1]["score"] is None


def test_query_with_no_usable_terms_returns_unranked_review(conn):
    ranked = retrieve.lexical_rank(conn, "a, b; ?", "Smid_2020")
    assert [r["work_id"] for r in ranked] == ["W1", "W2", "W3", "W4"]


@pytest.mark.parametrize("strategy", ("random", "bm25"))
def test_rows_handed_to_screening_carry_no_ground_truth(conn, strategy):
    """Rule 4: label_included is read by the metrics module and nothing else.

    dense/hybrid/rerank get the same check in test_dense_retrieve.py, against
    dense_retrieve.py's functions directly with a fake embedder — going
    through retrieve.rank() here would load the real SPECTER2/MiniLM models,
    which this suite deliberately never does.
    """
    rows = retrieve.rank(conn, strategy, "Smid_2020", seed=1, query="Bayesian")
    assert rows
    for row in rows:
        assert "label_included" not in row.keys()


# --------------------------------------------------------------------------
# Corpus independence — the defect found 21 September 2026
# --------------------------------------------------------------------------


def _conn_with_second_review(tmp_path, name):
    """Smid_2020 exactly as above, plus a large unrelated review.

    The second review is deliberately full of the same vocabulary the query
    uses. That is what shifts IDF: terms that are rare in Smid_2020 alone
    become common once these are indexed too.
    """
    c = _conn(tmp_path, name, [0, 1, 2, 3])
    ingest_frame(
        c,
        "Nelson_2002",
        pd.DataFrame(
            {
                "openalex_id": [f"N{i}" for i in range(200)],
                "title": [f"Bayesian estimation in trials {i}" for i in range(200)],
                "abstract": [
                    "Bayesian estimation of treatment effects in small samples." for _ in range(200)
                ],
                "label_included": [0] * 200,
            }
        ),
    )
    return c


@pytest.mark.parametrize(
    "query",
    [
        "Bayesian estimation small samples",
        "Bayesian structural equation modelling",
    ],
)
def test_bm25_is_unaffected_by_other_reviews_in_the_database(tmp_path, query):
    """A review's ranking must not depend on what else has been ingested.

    ``bm25()`` derives IDF from the whole index it is called on. Querying the
    shared ``work_fts`` and filtering by review afterwards made a review's
    scores move whenever another review was added — observed for real between
    the week 8 and week 9 baseline runs (Smid_2020 TNR@95 0.568 -> 0.618),
    with an identical ``corpus_sha256`` in both metrics files.

    Scores, not just order: an ordering can survive an IDF shift by luck.
    """
    alone = _conn(tmp_path, "alone.db", [0, 1, 2, 3])
    with_other = _conn_with_second_review(tmp_path, "with_other.db")

    def signature(conn):
        return [
            (r["work_id"], None if r["score"] is None else round(r["score"], 10))
            for r in retrieve.lexical_rank(conn, query, "Smid_2020")
        ]

    assert signature(alone) == signature(with_other)
    alone.close()
    with_other.close()


def test_bm25_scope_does_not_leak_records_from_other_reviews(tmp_path):
    """The per-review index must hold that review and nothing else."""
    conn = _conn_with_second_review(tmp_path, "scoped.db")
    ranked = retrieve.lexical_rank(conn, "Bayesian estimation", "Smid_2020")
    assert sorted(r["work_id"] for r in ranked) == ["W1", "W2", "W3", "W4"]
    assert all(r["review"] == "Smid_2020" for r in ranked)
    conn.close()


def test_bm25_leaves_no_temporary_table_behind(tmp_path):
    """The temp index is scaffolding; it must not outlive the call."""
    conn = _conn_with_second_review(tmp_path, "temp.db")
    retrieve.lexical_rank(conn, "Bayesian estimation", "Smid_2020")
    leftover = conn.execute(
        "SELECT name FROM temp.sqlite_master WHERE name LIKE 'review_fts%'"
    ).fetchall()
    assert leftover == []
    conn.close()


def test_random_rank_is_independent_of_insertion_order(tmp_path):
    a = _conn(tmp_path, "a.db", [0, 1, 2, 3])
    b = _conn(tmp_path, "b.db", [3, 1, 0, 2])
    order_a = [r["work_id"] for r in retrieve.random_rank(a, "Smid_2020", seed=7)]
    order_b = [r["work_id"] for r in retrieve.random_rank(b, "Smid_2020", seed=7)]
    assert order_a == order_b


def test_unknown_strategy_is_rejected(conn):
    with pytest.raises(ValueError):
        retrieve.rank(conn, "not-a-real-strategy", "Smid_2020", seed=1)


def test_new_strategies_are_registered():
    assert set(retrieve.STRATEGIES) == {"random", "bm25", "dense", "hybrid", "rerank"}
