"""Tests for the metrics module.

Ranking metrics are checked against hand-computed cases; the operating-point
metrics against a small run whose every decision is known.
"""

from __future__ import annotations

import pandas as pd
import pytest

from slr.db import connect
from slr.eval import metrics
from slr.services.ingest import ingest_frame


# --------------------------------------------------------------------------
# Ranking metrics
# --------------------------------------------------------------------------


def _labels(pattern: str) -> tuple[list[str], dict[str, int]]:
    """'PNPNN' -> ranked ids and labels, P included, N excluded."""
    ids = [f"W{i}" for i in range(len(pattern))]
    return ids, {w: int(c == "P") for w, c in zip(ids, pattern)}


def test_ranking_metrics_by_hand():
    """P N P N N P N N N N: 3 included, 7 excluded, N = 10.

    95% of 3 -> ceil(2.85) = 3, all three needed; the third P is at rank 6.
    Read 6: TP 3, FP 3. Not read 4: TN 4, FN 0.
    TNR = 4 / 7; WSS = (4 + 0) / 10 - 0.05 = 0.35.
    """
    ids, labels = _labels("PNPNNPNNNN")
    m = metrics.ranking_metrics(ids, labels, recall_target=0.95)
    assert m.cutoff == 6
    assert m.recall_at_cutoff == 1.0
    assert m.tnr_at_recall == pytest.approx(4 / 7)
    assert m.wss_at_recall == pytest.approx(0.35)
    assert m.complete


def test_perfect_ranking_saves_everything():
    ids, labels = _labels("PP" + "N" * 18)
    m = metrics.ranking_metrics(ids, labels)
    assert m.cutoff == 2
    assert m.tnr_at_recall == 1.0


def test_worst_ranking_saves_nothing():
    ids, labels = _labels("N" * 18 + "PP")
    m = metrics.ranking_metrics(ids, labels)
    assert m.cutoff == 20
    assert m.tnr_at_recall == 0.0


def test_recall_target_rounding_is_exact():
    """0.95 * 20 is 19 exactly; floating point would make it 19.000000000000004."""
    ids, labels = _labels("P" * 19 + "N" * 5 + "P" + "N" * 5)
    m = metrics.ranking_metrics(ids, labels, recall_target=0.95)
    assert m.cutoff == 19
    assert m.recall_at_cutoff == pytest.approx(0.95)
    assert m.tnr_at_recall == 1.0


def test_partial_ranking_is_marked_incomplete():
    ids, labels = _labels("PNPNN")
    m = metrics.ranking_metrics(ids[:3], labels)
    assert not m.complete
    assert m.n_ranked == 3


def test_no_included_records_gives_no_ranking_figures():
    ids, labels = _labels("NNNN")
    m = metrics.ranking_metrics(ids, labels)
    assert m.tnr_at_recall is None and m.cutoff is None


@pytest.mark.parametrize("bad", [["W0", "W0"], ["W0", "unknown"]])
def test_invalid_rankings_are_rejected(bad):
    _, labels = _labels("PN")
    with pytest.raises(ValueError):
        metrics.ranking_metrics(bad, labels)


def test_decision_order_tiers():
    rows = [
        {"work_id": "ex_confident", "decision": "exclude", "confidence": 0.9, "span_verified": 1},
        {"work_id": "ex_unsure", "decision": "exclude", "confidence": 0.5, "span_verified": 1},
        {"work_id": "referred", "decision": "unverified", "confidence": 0.99, "span_verified": 0},
        {"work_id": "error", "decision": "error", "confidence": None, "span_verified": 0},
        {"work_id": "in_unsure", "decision": "include", "confidence": 0.6, "span_verified": 1},
        {"work_id": "in_confident", "decision": "include", "confidence": 0.95, "span_verified": 1},
    ]
    assert metrics.decision_order(rows) == [
        "in_confident",
        "in_unsure",
        "error",
        "referred",
        "ex_unsure",
        "ex_confident",
    ]


# --------------------------------------------------------------------------
# Operating-point metrics
# --------------------------------------------------------------------------


@pytest.fixture()
def conn(tmp_path):
    c = connect(tmp_path / "m.db")
    labels = [1, 1, 1, 0, 0, 0, 0, 0]
    ingest_frame(
        c,
        "Nelson_2002",
        pd.DataFrame(
            {
                "openalex_id": [f"W{i}" for i in range(8)],
                "title": [f"t{i}" for i in range(8)],
                "abstract": [f"a{i}" for i in range(8)],
                "label_included": labels,
            }
        ),
    )
    c.execute("INSERT INTO run (run_id, config_hash) VALUES ('r1', 'h'), ('r2', 'h')")
    yield c
    c.close()


def _decide(conn, run_id, work_id, decision, verified, confidence=0.8, cached=False):
    conn.execute(
        "INSERT INTO screening_decision (run_id, review, work_id, decision, confidence, "
        "span_verified, verify_note, from_cache, tokens_in, tokens_out) "
        "VALUES (?, 'Nelson_2002', ?, ?, ?, ?, 'n', ?, 1000, 100)",
        (run_id, work_id, decision, confidence, int(verified), int(cached)),
    )


def test_review_metrics_by_hand(conn):
    """Truth: W0-W2 included, W3-W7 excluded. Seven records screened.

    W0 include ok        -> TP
    W1 exclude ok        -> FN (verified exclude of an included record)
    W2 unverified        -> referral; included, reaches a human
    W3 include ok        -> FP
    W4 exclude ok        -> TN
    W5 exclude ok        -> TN
    W6 error             -> referral
    """
    for work_id, decision, verified in [
        ("W0", "include", True),
        ("W1", "exclude", True),
        ("W2", "unverified", False),
        ("W3", "include", True),
        ("W4", "exclude", True),
        ("W5", "exclude", True),
        ("W6", "error", False),
    ]:
        _decide(conn, "r1", work_id, decision, verified)

    m = metrics.review_metrics(
        conn, "r1", "Nelson_2002", usd_per_1m_input=0.15, usd_per_1m_output=0.60
    )
    assert (m.n_records, m.n_included_truth, m.n_screened) == (8, 3, 7)
    assert m.prevalence == pytest.approx(3 / 8)
    assert (m.true_positives, m.false_negatives, m.false_positives, m.true_negatives) == (1, 1, 1, 2)
    assert m.recall_verified == pytest.approx(0.5)
    assert m.verification_rate == pytest.approx(5 / 7)
    # To a human: W0, W2, W3, W6. Included among them: W0, W2 -> 2 of 3.
    assert m.n_to_human == 4
    assert m.recall_with_referrals == pytest.approx(2 / 3)
    assert m.work_saved == pytest.approx(3 / 7)
    assert m.agreement_pabak == pytest.approx(2 * (3 / 5) - 1)
    assert m.agreement_ac1 is not None
    assert m.ranking["complete"] is False
    assert m.cost_usd_at_config_prices == pytest.approx(7 * (1000 * 0.15 + 100 * 0.60) / 1e6)


def test_cost_at_config_prices_ignores_cache_state(conn):
    """A cached rerun must report the same cost figure as the live run."""
    _decide(conn, "r1", "W0", "include", True, cached=False)
    _decide(conn, "r2", "W0", "include", True, cached=True)
    a = metrics.review_metrics(conn, "r1", "Nelson_2002", usd_per_1m_input=1.0)
    b = metrics.review_metrics(conn, "r2", "Nelson_2002", usd_per_1m_input=1.0)
    assert a.as_dict() == b.as_dict()


def test_inter_run_agreement(conn):
    for run_id in ("r1", "r2"):
        _decide(conn, run_id, "W0", "include", True)
        _decide(conn, run_id, "W1", "exclude", True)
    _decide(conn, "r1", "W2", "include", True)
    _decide(conn, "r2", "W2", "unverified", False)  # missing, not disagreement
    result = metrics.inter_run_agreement(conn, ["r1", "r2"], "Nelson_2002")
    assert result.coefficient == pytest.approx(1.0)
    assert result.n_units_paired == 2


def test_verification_failures_order_is_stable(conn):
    _decide(conn, "r1", "W0", "unverified", False)
    conn.execute("UPDATE screening_decision SET verify_note = 'b_note' WHERE work_id = 'W0'")
    _decide(conn, "r1", "W1", "unverified", False)
    conn.execute("UPDATE screening_decision SET verify_note = 'a_note' WHERE work_id = 'W1'")
    assert list(metrics.verification_failures(conn, "r1")) == ["a_note", "b_note"]


def test_override_accuracy_joins_human_decisions_with_ground_truth(conn):
    """W0-W2 are truth-included, W3+ truth-excluded (fixture labels above).

    A disposed referral (W2) and a corrected verified decision (W3) both
    show up, each carrying whether the human's call matched the label --
    the one join in the codebase allowed to compare a human decision with
    ground truth, kept out of slr.services.override on purpose.
    """
    _decide(conn, "r1", "W2", "unverified", False)  # referral, disposed by a human
    _decide(conn, "r1", "W3", "include", True)  # model wrong; verified anyway
    conn.execute(
        "INSERT INTO human_decision (run_id, review, work_id, decision, rationale) VALUES "
        "('r1', 'Nelson_2002', 'W2', 'include', 'clear RCT on reread'), "
        "('r1', 'Nelson_2002', 'W3', 'exclude', 'model verified a real but misleading quote')"
    )
    records = metrics.override_accuracy(conn, "r1", "Nelson_2002")
    by_id = {r.work_id: r for r in records}

    assert by_id["W2"].model_decision == "unverified"
    assert by_id["W2"].human_decision == "include"
    assert by_id["W2"].matches_truth is True  # W2 is truth-included

    assert by_id["W3"].model_decision == "include"
    assert by_id["W3"].model_verified is True
    assert by_id["W3"].human_decision == "exclude"
    assert by_id["W3"].matches_truth is True  # W3 is truth-excluded; override was correct
