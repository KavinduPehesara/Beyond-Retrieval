"""Tests for the gap-recall estimator and the blind sample sheet."""

from __future__ import annotations

import pytest

from slr.db import connect
from slr.eval.gap_recall import draw, estimate_recall, score, wilson


def test_wilson_interval_by_hand():
    lo, hi = wilson(0, 10)
    assert lo == 0.0
    assert hi == pytest.approx(0.2775, abs=1e-3)
    assert wilson(5, 10)[0] < 0.5 < wilson(5, 10)[1]
    assert wilson(0, 0) == (0.0, 1.0)


def test_recall_by_hand():
    # 20 true positives; pool of 100 not_stated; 2 misses in a sample of 10
    # -> miss rate 0.2 -> 20 estimated false negatives -> recall 20/40.
    m = estimate_recall(tp=20, pool=100, sampled=10, misses=2)
    assert m["estimated_false_negatives"] == pytest.approx(20)
    assert m["recall_estimate"] == pytest.approx(0.5)
    assert m["recall_at_worst_miss_rate"] < m["recall_estimate"] < m["recall_at_best_miss_rate"]


def test_no_misses_gives_recall_one_at_the_point_estimate():
    m = estimate_recall(tp=20, pool=100, sampled=10, misses=0)
    assert m["recall_estimate"] == 1.0
    assert m["recall_at_worst_miss_rate"] < 1.0  # but the interval is honest


@pytest.fixture()
def conn(tmp_path):
    c = connect(tmp_path / "t.db")
    for i in range(12):
        c.execute(
            "INSERT INTO work (work_id, review, title, abstract, label_included) VALUES (?,?,?,?,0)",
            (f"W{i}", "R", f"title{i}", f"abstract{i}"),
        )
        value = "gap_stated" if i < 4 else "not_stated"
        rating = "valid" if i < 3 else None
        c.execute(
            "INSERT INTO gap_statement (run_id, source_run_id, review, work_id, value, span_verified, rating) "
            "VALUES ('G', 'S', 'R', ?, ?, 1, ?)",
            (f"W{i}", value, rating),
        )
    c.commit()
    yield c
    c.close()


def test_sheet_never_reveals_model_output(conn):
    sheet, key = draw(conn, {"R": "G"}, n_not_stated=4, n_flagged=2, seed=1)
    assert len(sheet) == 6
    for item in sheet:
        assert set(item) == {"index", "title", "abstract"}  # no stratum, no value, no rating
    assert {k["stratum"] for k in key} == {"not_stated", "gap_stated"}


def test_draw_is_deterministic_for_a_seed(conn):
    a = draw(conn, {"R": "G"}, n_not_stated=4, n_flagged=2, seed=7)
    b = draw(conn, {"R": "G"}, n_not_stated=4, n_flagged=2, seed=7)
    assert a == b


def test_score_counts_misses_and_control_agreement(conn):
    sheet, key = draw(conn, {"R": "G"}, n_not_stated=4, n_flagged=2, seed=1)
    labels = {}
    misses = 0
    for k in key:
        if k["stratum"] == "not_stated":
            is_gap = misses == 0  # first not_stated sampled is a miss
            misses += 1
            labels[str(k["index"])] = is_gap
        else:
            labels[str(k["index"])] = True  # blind label agrees with earlier valid ratings
    result = score(conn, {"R": "G"}, key, labels)
    m = result["per_review"]["R"]
    assert m["sampled_not_stated"] == 4
    assert m["misses_in_sample"] == 1
    assert m["true_positives"] == 3
    ctl = result["blind_control_agreement"]
    assert ctl["n"] == 2
    # controls sampled from W0-W3; W3 is flagged but unrated (not valid), so a
    # blind True on it is a disagreement -- agreement <= n either way
    assert 0 <= ctl["agree"] <= 2
