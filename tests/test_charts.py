"""Tests for the chart data layer.

Two kinds here. The first build a small synthetic database and assert the
shaping is right -- a recall curve that is monotonic and ends at 1.0, a
failure matrix whose shares sum to one, a histogram that bins the edges the
way a reader would expect. The second kind run against the real
``data/slr.db`` when it is present, and assert the charts reproduce figures
CLAUDE.md already records: if the confidence histogram disagrees with the
0.798/0.813 means, or the gap rate stops matching the recorded per-review
table, one of the two is wrong and the test says so.

The real-database tests skip rather than fail when the database or run
directories are absent, so a fresh clone (which has neither until ingest
runs) still passes the suite.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from slr.db import SCHEMA_VERSION, connect
from slr.eval import charts

DB_PATH = Path("data/slr.db")
RUNS_DIR = Path("runs")
EMBEDDINGS_DIR = Path("data/embeddings")


# --------------------------------------------------------------------------
# Synthetic fixtures
# --------------------------------------------------------------------------


@pytest.fixture
def conn(tmp_path) -> sqlite3.Connection:
    c = connect(tmp_path / "t.db")
    yield c
    c.close()


def _work(conn, review, work_id, label, *, year=2010, abstract="an abstract"):
    conn.execute(
        "INSERT INTO work (review, work_id, title, abstract, year, label_included) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (review, work_id, f"title {work_id}", abstract, year, label),
    )


def _run(conn, run_id):
    """screening_decision has a FK to run(run_id), so the run row comes first."""
    conn.execute(
        "INSERT OR IGNORE INTO run (run_id, config_hash, config_name, model, prompt_version) "
        "VALUES (?, ?, ?, ?, ?)",
        (run_id, "deadbeef", "test", "qwen2.5:7b-instruct", "screen_v1"),
    )


def _decision(conn, run_id, review, work_id, decision, confidence, verified, note, **kw):
    _run(conn, run_id)
    conn.execute(
        "INSERT INTO screening_decision (run_id, review, work_id, decision, confidence, "
        "evidence_span, span_verified, verify_note, from_cache, tokens_in, tokens_out, "
        "cost_usd, latency_ms) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            run_id,
            review,
            work_id,
            decision,
            confidence,
            "a span",
            verified,
            note,
            kw.get("from_cache", 0),
            kw.get("tokens_in", 100),
            kw.get("tokens_out", 20),
            kw.get("cost_usd", 0.0),
            kw.get("latency_ms", 1000),
        ),
    )


# --------------------------------------------------------------------------
# recall_curve
# --------------------------------------------------------------------------


def test_recall_curve_is_monotonic_and_reaches_one():
    labels = {f"w{i}": (1 if i in (2, 5, 9) else 0) for i in range(10)}
    ranked = [f"w{i}" for i in range(10)]
    curve = charts.recall_curve(ranked, labels)

    assert curve.n_included == 3
    assert curve.y[0] == 0.0
    assert curve.y[-1] == pytest.approx(1.0)
    assert all(b >= a for a, b in zip(curve.y, curve.y[1:])), "recall must never decrease"
    assert len(curve.x) == len(curve.y) == len(curve.random_baseline)


def test_recall_curve_perfect_ranking_rises_immediately():
    labels = {f"w{i}": (1 if i < 3 else 0) for i in range(100)}
    ranked = [f"w{i}" for i in range(100)]
    curve = charts.recall_curve(ranked, labels)
    # All three includes are in the first three records.
    assert curve.cutoff_95 == 3
    index = curve.x.index(3)
    assert curve.y[index] == pytest.approx(1.0)


def test_recall_curve_cutoff_matches_ranking_metrics():
    """The curve's 95% crossing is the same point the reported TNR uses.

    If these two ever diverge, the chart is telling a different story from
    the table beside it -- which is the one thing a results figure must not
    do.
    """
    from slr.eval.metrics import ranking_metrics

    labels = {f"w{i}": (1 if i % 7 == 0 else 0) for i in range(200)}
    ranked = sorted(labels, key=lambda w: (labels[w] == 0, w))
    curve = charts.recall_curve(ranked, labels)
    reported = ranking_metrics(ranked, labels, recall_target=0.95)
    assert curve.cutoff_95 == reported.cutoff


def test_recall_curve_keeps_every_include_when_downsampling():
    """Downsampling may drop flat stretches, never a step."""
    labels = {f"w{i:05d}": (1 if i % 500 == 0 else 0) for i in range(5000)}
    ranked = sorted(labels)
    curve = charts.recall_curve(ranked, labels, max_points=50)

    assert len(curve.x) < 400, "should have downsampled"
    include_positions = [i for i, w in enumerate(ranked, 1) if labels[w]]
    for position in include_positions:
        assert position in curve.x


def test_recall_curve_rejects_unknown_records():
    with pytest.raises(ValueError, match="not in the review"):
        charts.recall_curve(["ghost"], {"w1": 1})


def test_recall_curve_with_no_includes_is_flat_not_an_error():
    curve = charts.recall_curve(["w1", "w2"], {"w1": 0, "w2": 0})
    assert curve.n_included == 0
    assert curve.cutoff_95 is None


def test_screening_recall_curve_uses_decision_order(conn):
    for i in range(6):
        _work(conn, "R", f"w{i}", 1 if i in (0, 4) else 0)
    # w4 is a verified include with high confidence -> ranked first.
    _decision(conn, "run1", "R", "w4", "include", 0.9, 1, "exact_after_normalisation")
    _decision(conn, "run1", "R", "w0", "include", 0.5, 1, "exact_after_normalisation")
    for i in (1, 2, 3, 5):
        _decision(conn, "run1", "R", f"w{i}", "exclude", 0.8, 1, "exact_after_normalisation")

    curve = charts.screening_recall_curve(conn, "run1", "R")
    assert curve.n_included == 2
    # Both includes are ranked first, so recall hits 1.0 by position 2.
    assert curve.y[curve.x.index(2)] == pytest.approx(1.0)


# --------------------------------------------------------------------------
# verification / failures / confidence
# --------------------------------------------------------------------------


def test_verification_by_review_carries_prevalence_and_sorts_by_it(conn):
    for i in range(10):
        _work(conn, "LowPrev", f"a{i}", 1 if i == 0 else 0)
        _work(conn, "HighPrev", f"b{i}", 1 if i < 5 else 0)
    for i in range(10):
        _decision(conn, "r", "LowPrev", f"a{i}", "exclude", 0.8, 1, "ok")
        _decision(conn, "r", "HighPrev", f"b{i}", "exclude", 0.8, i % 2, "ok")

    rows = charts.verification_by_review(conn, {"LowPrev": "r", "HighPrev": "r"})
    assert [r["review"] for r in rows] == ["LowPrev", "HighPrev"]
    assert rows[0]["prevalence"] == pytest.approx(0.1)
    assert rows[0]["verification_rate"] == pytest.approx(1.0)
    assert rows[1]["verification_rate"] == pytest.approx(0.5)


def test_failure_matrix_counts_only_failures_and_normalises_rows(conn):
    for i in range(4):
        _work(conn, "R", f"w{i}", 0)
    _decision(conn, "r", "R", "w0", "include", 0.9, 1, "exact_after_normalisation")
    _decision(conn, "r", "R", "w1", "unverified", 0.8, 0, "not_found")
    _decision(conn, "r", "R", "w2", "unverified", 0.8, 0, "not_found")
    _decision(conn, "r", "R", "w3", "error", None, 0, "schema_validation_failed")

    matrix = charts.failure_type_matrix(conn, {"R": "r"})
    assert matrix["notes"][0] == "not_found", "dominant failure mode comes first"
    row = matrix["rows"][0]
    assert row["total_failures"] == 3, "the verified decision is not a failure"
    assert sum(row["shares"].values()) == pytest.approx(1.0)
    assert row["counts"]["schema_validation_failed"] == 1


def test_confidence_histogram_splits_by_verification(conn):
    for i in range(4):
        _work(conn, "R", f"w{i}", 0)
    _decision(conn, "r", "R", "w0", "include", 0.95, 1, "ok")
    _decision(conn, "r", "R", "w1", "include", 0.85, 1, "ok")
    _decision(conn, "r", "R", "w2", "unverified", 0.95, 0, "not_found")
    _decision(conn, "r", "R", "w3", "unverified", 0.05, 0, "not_found")

    hist = charts.confidence_histogram(conn, "r", bins=10)
    assert hist["n_verified"] == 2
    assert hist["n_unverified"] == 2
    assert hist["verified"][9] == 1 and hist["verified"][8] == 1
    assert hist["unverified"][9] == 1 and hist["unverified"][0] == 1
    assert hist["mean_verified"] == pytest.approx(0.90)
    assert hist["mean_unverified"] == pytest.approx(0.50)
    assert len(hist["bin_labels"]) == 10


def test_confidence_histogram_clamps_out_of_range_values(conn):
    """A provider returning 1.0 must land in the last bin, not off the end."""
    _work(conn, "R", "w0", 0)
    _decision(conn, "r", "R", "w0", "include", 1.0, 1, "ok")
    hist = charts.confidence_histogram(conn, "r", bins=10)
    assert hist["verified"][9] == 1
    assert sum(hist["verified"]) == 1


def test_override_outcomes_does_not_touch_ground_truth(conn):
    """Rule 4's boundary: this chart compares human with system, nothing else."""
    _work(conn, "R", "w0", 1)
    _work(conn, "R", "w1", 0)
    _decision(conn, "r", "R", "w0", "exclude", 0.8, 1, "ok")
    _decision(conn, "r", "R", "w1", "unverified", 0.8, 0, "not_found")
    conn.execute(
        "INSERT INTO human_decision (run_id, review, work_id, decision, rationale) "
        "VALUES (?, ?, ?, ?, ?)",
        ("r", "R", "w0", "include", "criteria met"),
    )
    conn.execute(
        "INSERT INTO human_decision (run_id, review, work_id, decision, rationale) "
        "VALUES (?, ?, ?, ?, ?)",
        ("r", "R", "w1", "unverified", "agree, refer"),
    )

    out = charts.override_outcomes(conn)
    assert out["n"] == 2
    assert out["changed"] == 1
    assert out["confirmed"] == 1
    assert out["disposed_referrals"] == 1
    assert "label_included" not in json.dumps(out)


# --------------------------------------------------------------------------
# extraction / gap / corpus
# --------------------------------------------------------------------------


def _extraction(conn, run_id, review, work_id, field, verified, note):
    conn.execute(
        "INSERT INTO extraction (run_id, source_run_id, review, work_id, field_name, "
        "value, evidence_span, span_verified, verify_note) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (run_id, "src", review, work_id, field, "v", "s", verified, note),
    )


def test_extraction_coverage_reports_every_field_even_at_zero(conn):
    _work(conn, "R", "w0", 1)
    _extraction(conn, "e", "R", "w0", "study_design", 1, "ok")
    _extraction(conn, "e", "R", "w0", "country", 0, "not_stated")

    out = charts.extraction_coverage(conn, {"R": "e"})
    assert out["fields"] == list(charts.EXTRACTION_FIELDS)
    fields = out["rows"][0]["fields"]
    assert fields["study_design"]["share"] == pytest.approx(1.0)
    assert fields["country"]["share"] == pytest.approx(0.0)
    # Never extracted at all -> no share to report, rather than a false zero.
    assert fields["key_finding"]["n"] == 0
    assert fields["key_finding"]["share"] is None


def test_extraction_status_separates_not_stated_from_unverified(conn):
    _work(conn, "R", "w0", 1)
    _work(conn, "R", "w1", 1)
    _work(conn, "R", "w2", 1)
    _extraction(conn, "e", "R", "w0", "country", 1, "exact_after_normalisation")
    _extraction(conn, "e", "R", "w1", "country", 0, "not_stated")
    _extraction(conn, "e", "R", "w2", "country", 0, "not_found")

    rows = {r["field"]: r for r in charts.extraction_status(conn, "e", "R")}
    country = rows["country"]
    assert (country["verified"], country["not_stated"], country["unverified"]) == (1, 1, 1)
    assert country["n"] == 3


def _gap(conn, run_id, review, work_id, value, rating=None):
    conn.execute(
        "INSERT INTO gap_statement (run_id, source_run_id, review, work_id, value, "
        "evidence_span, span_verified, verify_note, rating) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (run_id, "src", review, work_id, value, "s", 1, "ok", rating),
    )


def test_gap_rate_and_precision(conn):
    for i in range(4):
        _work(conn, "R", f"w{i}", 1)
    _gap(conn, "g", "R", "w0", "gap_stated", "valid")
    _gap(conn, "g", "R", "w1", "gap_stated", "invalid")
    _gap(conn, "g", "R", "w2", "not_stated")
    _gap(conn, "g", "R", "w3", "not_stated")

    row = charts.gap_rate_by_review(conn, {"R": "g"})[0]
    assert row["gap_stated"] == 2
    assert row["gap_rate"] == pytest.approx(0.5)
    assert row["precision"] == pytest.approx(0.5)
    assert row["unrated"] == 0


def test_gap_precision_vs_recall_leaves_unmeasured_reviews_none(conn):
    """A review with no blind-labelled recall pass gets None, not a borrowed
    figure from another review."""
    _work(conn, "Smid_2020", "w0", 1)
    _gap(conn, "g", "Smid_2020", "w0", "gap_stated", "valid")
    row = charts.gap_precision_vs_recall(conn, {"Smid_2020": "g"})[0]
    assert row["precision"] == pytest.approx(1.0)
    assert row["recall_estimate"] is None
    assert row["recall_source"] is None


def test_prevalence_and_year_histogram(conn):
    _work(conn, "R", "w0", 1, year=2001)
    _work(conn, "R", "w1", 0, year=2001)
    _work(conn, "R", "w2", 0, year=2005)

    prevalence = charts.prevalence_by_review(conn)[0]
    assert prevalence["n"] == 3 and prevalence["included"] == 1
    assert prevalence["prevalence"] == pytest.approx(1 / 3)

    years = charts.year_histogram(conn, "R")
    assert years["years"] == [2001, 2005]
    assert years["counts"] == [2, 1]
    assert years["included"] == [1, 0]
    assert years["span"] == (2001, 2005)


def test_prevalence_excludes_discovered_records(conn):
    """Discover's records are outside the evaluation corpus by construction,
    and must not appear in a corpus chart."""
    _work(conn, "R", "w0", 1)
    _work(conn, "_discover", "openalex:1", 0)
    reviews = [r["review"] for r in charts.prevalence_by_review(conn)]
    assert reviews == ["R"]


def test_metadata_coverage_flags_what_cannot_be_charted(conn):
    _work(conn, "R", "w0", 1)
    rows = {r["column"]: r for r in charts.metadata_coverage(conn)}
    assert rows["country"]["filled"] == 0
    assert rows["country"]["chartable"] is False


# --------------------------------------------------------------------------
# performance
# --------------------------------------------------------------------------


def test_latency_summary_ignores_cache_hits(conn):
    for i in range(3):
        _work(conn, "R", f"w{i}", 0)
    _decision(conn, "r", "R", "w0", "exclude", 0.8, 1, "ok", latency_ms=1000)
    _decision(conn, "r", "R", "w1", "exclude", 0.8, 1, "ok", latency_ms=3000)
    _decision(conn, "r", "R", "w2", "exclude", 0.8, 1, "ok", latency_ms=1, from_cache=1)

    out = charts.latency_summary(conn, "r")
    assert out["n"] == 2, "the cache hit is excluded"
    assert out["mean_ms"] == pytest.approx(2000.0)


def test_latency_summary_on_an_all_cached_run_is_empty_not_an_error(conn):
    _work(conn, "R", "w0", 0)
    _decision(conn, "r", "R", "w0", "exclude", 0.8, 1, "ok", from_cache=1)
    assert charts.latency_summary(conn, "r")["n"] == 0


def test_cache_savings(conn):
    for i in range(4):
        _work(conn, "R", f"w{i}", 0)
    _decision(conn, "r", "R", "w0", "exclude", 0.8, 1, "ok", latency_ms=2000)
    for i in (1, 2, 3):
        _decision(conn, "r", "R", f"w{i}", "exclude", 0.8, 1, "ok", from_cache=1, latency_ms=0)

    out = charts.cache_savings(conn, "r")
    assert out["live_calls"] == 1
    assert out["cached_calls"] == 3
    assert out["cache_hit_rate"] == pytest.approx(0.75)
    # Three cache hits at the 2s live mean.
    assert out["hours_saved"] == pytest.approx(6000 / 1000 / 3600)


# --------------------------------------------------------------------------
# Against the real database -- do the charts reproduce recorded figures?
# --------------------------------------------------------------------------

real_db = pytest.mark.skipif(
    not DB_PATH.exists(), reason="no local data/slr.db; run ingest first"
)


@pytest.fixture(scope="module")
def real():
    if not DB_PATH.exists():
        pytest.skip("no local data/slr.db")
    c = connect(DB_PATH)
    yield c
    c.close()


@real_db
def test_real_prevalence_matches_the_recorded_corpus_table(real):
    """The six reviews, their record counts and inclusion rates, exactly as
    CLAUDE.md's corpus table states them."""
    expected = {
        "Radjenovic_2013": (5935, 48),
        "Smid_2020": (2627, 27),
        "van_der_Waal_2022": (1970, 33),
        "Menon_2022": (975, 74),
        "van_der_Valk_2021": (725, 89),
        "Nelson_2002": (366, 80),
    }
    rows = {r["review"]: r for r in charts.prevalence_by_review(real)}
    for review, (n, included) in expected.items():
        if review not in rows:
            pytest.skip(f"{review} not ingested locally")
        assert (rows[review]["n"], rows[review]["included"]) == (n, included), review
    if len(rows) == 6:
        assert sum(r["n"] for r in rows.values()) == 12598
        assert sum(r["included"] for r in rows.values()) == 351


@real_db
def test_real_confidence_is_not_calibrated(real):
    """The recorded finding: the model is as confident when it invents a
    quote as when it copies one. If this test ever fails, the finding has
    changed and the report's claim needs rewriting -- it is not a flaky
    test.
    """
    rows = real.execute(
        "SELECT span_verified, AVG(confidence) AS mean, COUNT(*) AS n "
        "FROM screening_decision WHERE confidence IS NOT NULL GROUP BY span_verified"
    ).fetchall()
    means = {bool(r["span_verified"]): r["mean"] for r in rows}
    if len(means) < 2:
        pytest.skip("need both verified and unverified decisions")
    gap = means[True] - means[False]
    assert abs(gap) < 0.10, (
        f"confidence gap is now {gap:.3f}; CLAUDE.md records 0.015. "
        "A large gap would mean confidence HAS become informative -- a real "
        "finding, but one that contradicts the recorded result."
    )


@real_db
def test_real_charts_run_on_every_review_with_a_run(real):
    """Smoke test with teeth: every chart, every review that has a run, and
    nothing raises or returns a malformed shape."""
    if not RUNS_DIR.exists():
        pytest.skip("no local runs/ directory")
    from slr.api.runs_index import (
        latest_extract_run,
        latest_gap_run,
        list_reviews_with_screen_runs,
    )

    screen_runs = list_reviews_with_screen_runs(RUNS_DIR)
    if not screen_runs:
        pytest.skip("no screening runs recorded locally")

    verification = charts.verification_by_review(real, screen_runs)
    assert verification, "at least one review should have a verification rate"
    for row in verification:
        assert 0.0 <= row["verification_rate"] <= 1.0
        assert row["prevalence"] is not None, "rule 5: prevalence travels with the figure"

    matrix = charts.failure_type_matrix(real, screen_runs)
    for row in matrix["rows"]:
        assert sum(row["shares"].values()) == pytest.approx(1.0)

    for review, run_id in screen_runs.items():
        hist = charts.confidence_histogram(real, run_id, review)
        assert len(hist["verified"]) == len(hist["unverified"]) == charts.CONFIDENCE_BINS
        curve = charts.screening_recall_curve(real, run_id, review)
        assert all(b >= a for a, b in zip(curve.y, curve.y[1:])), review
        if curve.n_included:
            assert curve.y[-1] == pytest.approx(1.0), review

        extract_run = latest_extract_run(RUNS_DIR, review)
        if extract_run:
            for row in charts.extraction_status(real, extract_run, review):
                assert row["verified"] + row["not_stated"] + row["unverified"] == row["n"]
        gap_run = latest_gap_run(RUNS_DIR, review)
        if gap_run:
            for row in charts.gap_rate_by_review(real, {review: gap_run}):
                assert 0.0 <= row["gap_rate"] <= 1.0

    scatter = charts.verification_vs_recall(real, RUNS_DIR)
    assert len({p["review"] for p in scatter}) == len(scatter), "one point per review"


@real_db
def test_real_gap_rate_matches_the_recorded_per_review_table(real):
    """CLAUDE.md's week 11 table, recomputed from the tables."""
    if not RUNS_DIR.exists():
        pytest.skip("no local runs/ directory")
    from slr.api.runs_index import latest_gap_run

    expected = {  # review: (records, gap_stated)
        "Radjenovic_2013": (132, 5),
        "Smid_2020": (10, 1),
        "van_der_Waal_2022": (82, 17),
        "Menon_2022": (69, 36),
        "van_der_Valk_2021": (11, 3),
        "Nelson_2002": (114, 12),
    }
    checked = 0
    for review, (records, stated) in expected.items():
        run_id = latest_gap_run(RUNS_DIR, review)
        if not run_id:
            continue
        rows = charts.gap_rate_by_review(real, {review: run_id})
        if not rows:
            continue
        assert (rows[0]["n_records"], rows[0]["gap_stated"]) == (records, stated), review
        checked += 1
    if not checked:
        pytest.skip("no gap runs recorded locally")


@real_db
def test_real_semantic_map_projects_or_says_why_not(real):
    reviews = [r["review"] for r in charts.prevalence_by_review(real)]
    if not reviews:
        pytest.skip("no reviews ingested")
    any_available = False
    for review in reviews:
        out = charts.semantic_map(real, review, EMBEDDINGS_DIR, max_points=300)
        if not out["available"]:
            assert out["reason"], "an unavailable map must say why"
            continue
        any_available = True
        assert out["n_plotted"] <= 300
        assert len(out["points"]) == out["n_plotted"]
        assert 0.0 <= out["variance_explained"] <= 1.0
        # Every included record survives downsampling.
        n_included = sum(1 for p in out["points"] if p["included"])
        total_included = real.execute(
            "SELECT SUM(label_included) AS s FROM work WHERE review = ?", (review,)
        ).fetchone()["s"]
        assert n_included == total_included, review
    if not any_available:
        pytest.skip("no cached SPECTER2 embeddings locally")


@real_db
def test_schema_version_is_what_the_charts_were_written_against(real):
    assert SCHEMA_VERSION >= 4
