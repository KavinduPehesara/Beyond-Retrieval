"""Tests for the ablation study.

The thing most worth guarding here is not arithmetic, it is the comparison
itself. ``with_verifier`` scores a subset of records and the other two
policies score all of them, so setting the first beside either of the others
would credit the verifier for the records it declined to answer. Several
tests below exist only to make that mistake fail loudly.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from slr.adapters.llm import cache_key
from slr.db import connect
from slr.eval import ablation

DB_PATH = Path("data/slr.db")
RUNS_DIR = Path("runs")

MODEL = "qwen2.5:7b-instruct"
PROMPT = "screen_v1"
RUN = "run-1"
REVIEW = "R"


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "t.db")
    c.execute(
        "INSERT INTO run (run_id, config_hash, model, prompt_version) VALUES (?, 'h', ?, ?)",
        (RUN, MODEL, PROMPT),
    )
    yield c
    c.close()


def _record(conn, work_id, label, *, decision, verified, note, proposed=None, confidence=0.8):
    """One screened record, plus the cached raw response behind it.

    ``proposed`` is what the model originally said. When the quote failed to
    verify, ``decision`` is "unverified" and only the cache still knows.
    """
    conn.execute(
        "INSERT INTO work (review, work_id, title, abstract, label_included) "
        "VALUES (?, ?, 'title', 'abstract', ?)",
        (REVIEW, work_id, label),
    )
    conn.execute(
        "INSERT INTO screening_decision (run_id, review, work_id, decision, confidence, "
        "evidence_span, span_verified, verify_note) VALUES (?, ?, ?, ?, ?, 'span', ?, ?)",
        (RUN, REVIEW, work_id, decision, confidence, verified, note),
    )
    payload = {
        "decision": proposed or (decision if decision in ("include", "exclude") else "include"),
        "confidence": confidence,
        "evidence_span": "span",
    }
    conn.execute(
        "INSERT INTO cached_response (cache_key, request_sha256, raw_response) VALUES (?, 'f', ?)",
        (cache_key(MODEL, PROMPT, REVIEW, work_id), json.dumps(payload)),
    )


# --------------------------------------------------------------------------
# Recovering what the model actually proposed
# --------------------------------------------------------------------------


def test_recovers_the_proposal_behind_an_unverified_decision(conn):
    """screen.py overwrites the decision with "unverified" when the quote
    fails, so the ablation would have nothing to score without the cache."""
    _record(conn, "w1", 1, decision="unverified", verified=0, note="not_found", proposed="include")

    recovered = ablation.recover_proposed_decisions(conn, RUN, REVIEW)
    assert recovered["w1"]["proposed"] == "include"
    assert recovered["w1"]["decision"] == "unverified"
    assert recovered["w1"]["span_verified"] is False
    assert recovered["w1"]["recovered"] is True


def test_a_verified_decision_needs_no_recovery(conn):
    """Verification rejects an answer, it never rewrites an accepted one, so
    a verified decision is already its own proposal."""
    _record(conn, "w1", 1, decision="include", verified=1, note="exact_after_normalisation")
    conn.execute("DELETE FROM cached_response")

    recovered = ablation.recover_proposed_decisions(conn, RUN, REVIEW)
    assert recovered["w1"]["proposed"] == "include"
    assert recovered["w1"]["recovered"] is True


def test_an_unrecoverable_record_is_reported_not_dropped(conn):
    """An ablation computed over a quietly smaller set of records than the
    headline figure is not a comparison. Missing records must surface."""
    _record(conn, "w1", 1, decision="unverified", verified=0, note="not_found", proposed="include")
    conn.execute("DELETE FROM cached_response")

    result = ablation.verifier_ablation(conn, RUN, REVIEW)
    assert result["n_unrecovered"] == 1
    assert "w1" in result["unrecovered_sample"]


def test_a_corrupt_cached_response_does_not_raise(conn):
    _record(conn, "w1", 1, decision="unverified", verified=0, note="not_found", proposed="include")
    conn.execute("UPDATE cached_response SET raw_response = 'not json'")

    recovered = ablation.recover_proposed_decisions(conn, RUN, REVIEW)
    assert recovered["w1"]["recovered"] is False
    assert recovered["w1"]["proposed"] is None


def test_unknown_run_id_raises(conn):
    with pytest.raises(ValueError, match="no run row"):
        ablation.recover_proposed_decisions(conn, "nope", REVIEW)


# --------------------------------------------------------------------------
# The comparison
# --------------------------------------------------------------------------


def _mixed_corpus(conn):
    """Four records: a verified include, a verified exclude, and two whose
    quotes failed -- one the model got right, one it got wrong."""
    _record(conn, "w1", 1, decision="include", verified=1, note="exact_after_normalisation")
    _record(conn, "w2", 0, decision="exclude", verified=1, note="exact_after_normalisation")
    _record(conn, "w3", 1, decision="unverified", verified=0, note="not_found", proposed="include")
    _record(conn, "w4", 1, decision="unverified", verified=0, note="not_found", proposed="exclude")


def test_only_the_shipped_policy_is_marked_incomparable(conn):
    _mixed_corpus(conn)
    policies = ablation.verifier_ablation(conn, RUN, REVIEW)["policies"]

    assert policies[ablation.POLICY_VERIFIED]["comparable"] is False
    assert policies[ablation.POLICY_RAW]["comparable"] is True
    assert policies[ablation.POLICY_REFERRALS_KEPT]["comparable"] is True


def test_the_shipped_policy_scores_only_verified_records(conn):
    _mixed_corpus(conn)
    policies = ablation.verifier_ablation(conn, RUN, REVIEW)["policies"]

    shipped = policies[ablation.POLICY_VERIFIED]
    assert shipped["n_predictions"] == 2, "only w1 and w2 verified"
    # w3 and w4 are referrals, not misses: they are not in the denominator.
    assert shipped["recall"] == pytest.approx(1.0)


def test_the_comparable_policies_score_every_record(conn):
    _mixed_corpus(conn)
    policies = ablation.verifier_ablation(conn, RUN, REVIEW)["policies"]

    assert policies[ablation.POLICY_RAW]["n_predictions"] == 4
    assert policies[ablation.POLICY_REFERRALS_KEPT]["n_predictions"] == 4
    # Trusting the model: w1 and w3 are caught, w4 is missed -> 2 of 3.
    assert policies[ablation.POLICY_RAW]["recall"] == pytest.approx(2 / 3)
    # Referring every unverified record to a human catches all three.
    assert policies[ablation.POLICY_REFERRALS_KEPT]["recall"] == pytest.approx(1.0)


def test_counts_what_trusting_the_model_would_mean(conn):
    """The number that makes the ablation an argument rather than a table:
    how many trusted decisions had no real quote, and how many of those were
    also wrong."""
    _mixed_corpus(conn)
    raw = ablation.verifier_ablation(conn, RUN, REVIEW)["policies"][ablation.POLICY_RAW]

    assert raw["n_unverifiable_trusted"] == 2, "w3 and w4"
    assert raw["n_unverifiable_wrong"] == 1, "only w4 was also factually wrong"


def test_the_gate_costs_reading(conn):
    """The verifier's price, stated in records a human must read."""
    _mixed_corpus(conn)
    policies = ablation.verifier_ablation(conn, RUN, REVIEW)["policies"]

    # Only the verified exclude (w2) is never read.
    assert policies[ablation.POLICY_REFERRALS_KEPT]["n_to_human"] == 3
    # Trusting the model, both proposed excludes are skipped.
    assert policies[ablation.POLICY_RAW]["n_to_human"] == 2


def test_a_decision_cannot_exist_without_ground_truth_to_score_it_against(conn):
    """The ablation filters decisions to records present in `work`, but it
    never has to: the schema's foreign key makes an orphan decision
    impossible in the first place. Asserting that here means the filter is
    belt-and-braces rather than load-bearing, and that a future schema change
    which drops the constraint fails this test rather than silently letting
    unlabelled records into a confusion matrix.
    """
    import sqlite3

    _mixed_corpus(conn)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO screening_decision (run_id, review, work_id, decision, confidence, "
            "evidence_span, span_verified, verify_note) VALUES (?, ?, 'ghost', 'include', 0.9, "
            "'s', 1, 'ok')",
            (RUN, REVIEW),
        )
    assert ablation.verifier_ablation(conn, RUN, REVIEW)["n_records"] == 4


# --------------------------------------------------------------------------
# Stage ablations over recorded run directories
# --------------------------------------------------------------------------


def _write_run(runs_dir, name, per_review):
    d = runs_dir / name
    d.mkdir(parents=True)
    (d / "metrics.json").write_text(
        json.dumps({"mode": "screen", "per_review": per_review}), encoding="utf-8"
    )


def test_stage_ablation_computes_deltas_against_the_first_stage(tmp_path):
    _write_run(tmp_path, "a", [{"review": "R", "prevalence": 0.01, "ranking": {"tnr_at_recall": 0.5}}])
    _write_run(tmp_path, "b", [{"review": "R", "prevalence": 0.01, "ranking": {"tnr_at_recall": 0.7}}])

    out = ablation.stage_ablation(tmp_path, {"bm25": "a", "dense": "b"})
    row = out["rows"][0]
    assert out["baseline"] == "bm25"
    assert row["stages"] == {"bm25": 0.5, "dense": 0.7}
    assert row["deltas"]["dense"] == pytest.approx(0.2)
    assert row["deltas"]["bm25"] == pytest.approx(0.0)


def test_stage_ablation_names_a_missing_run_rather_than_skipping_it(tmp_path):
    _write_run(tmp_path, "a", [{"review": "R", "prevalence": 0.01, "ranking": {"tnr_at_recall": 0.5}}])
    out = ablation.stage_ablation(tmp_path, {"bm25": "a", "dense": "does-not-exist"})
    assert out["missing_runs"] == ["dense"]


def test_variant_ablation_collects_verification_rates(tmp_path):
    _write_run(tmp_path, "v1", [{"review": "R", "verification_rate": 0.52, "recall_verified": 0.9}])
    _write_run(tmp_path, "v2", [{"review": "R", "verification_rate": 0.13, "recall_verified": 0.4}])

    out = ablation.verification_ablation_from_runs(tmp_path, {"screen_v1": "v1", "screen_v2": "v2"})
    variants = out["rows"][0]["variants"]
    assert variants["screen_v1"]["verification_rate"] == 0.52
    assert variants["screen_v2"]["verification_rate"] == 0.13


def test_the_table_keeps_the_incomparable_policy_in_its_own_section(conn):
    """A reader scanning the first table must not find the subset-scored
    figure sitting in it."""
    _mixed_corpus(conn)
    table = ablation.format_verifier_table([ablation.verifier_ablation(conn, RUN, REVIEW)])

    comparison, _, reference = table.partition("## Shipped system, for reference")
    assert "Recall, trusting the model" in comparison
    assert "verified decisions only" in reference
    assert "not** comparable" in reference


# --------------------------------------------------------------------------
# Against the real database
# --------------------------------------------------------------------------

real_db = pytest.mark.skipif(not DB_PATH.exists(), reason="no local data/slr.db")


@pytest.fixture(scope="module")
def real():
    if not DB_PATH.exists():
        pytest.skip("no local data/slr.db")
    c = connect(DB_PATH)
    yield c
    c.close()


@real_db
def test_every_decision_is_recoverable_on_the_real_corpus(real):
    """The ablation is only honest if it covers the same records the
    headline figures do. If the response cache is ever wiped again, this
    fails rather than the ablation quietly shrinking."""
    if not RUNS_DIR.exists():
        pytest.skip("no local runs/")
    from slr.api.runs_index import list_reviews_with_screen_runs

    runs = list_reviews_with_screen_runs(RUNS_DIR)
    if not runs:
        pytest.skip("no screening runs")

    for review, run_id in runs.items():
        result = ablation.verifier_ablation(real, run_id, review)
        assert result["n_unrecovered"] == 0, (
            f"{review}: {result['n_unrecovered']} decisions could not be recovered "
            f"from the response cache, so the ablation covers fewer records than "
            f"the reported figures"
        )


@real_db
def test_the_gate_never_loses_recall_against_trusting_the_model(real):
    """The recorded finding: referring unverified decisions to a human
    catches included papers the model would otherwise have dropped. If this
    ever reverses, the verifier's case changes and the report needs
    rewriting -- it is not a flaky test."""
    if not RUNS_DIR.exists():
        pytest.skip("no local runs/")
    from slr.api.runs_index import list_reviews_with_screen_runs

    runs = list_reviews_with_screen_runs(RUNS_DIR)
    if not runs:
        pytest.skip("no screening runs")

    for review, run_id in runs.items():
        policies = ablation.verifier_ablation(real, run_id, review)["policies"]
        raw = policies[ablation.POLICY_RAW]["recall"]
        gate = policies[ablation.POLICY_REFERRALS_KEPT]["recall"]
        if raw is None or gate is None:
            continue
        assert gate >= raw, f"{review}: gate {gate:.3f} below trust {raw:.3f}"


@real_db
def test_the_retrieval_ablation_reproduces_the_recorded_week_9_figures(real):
    """The corrected post-BM25-fix numbers CLAUDE.md records."""
    if not RUNS_DIR.exists():
        pytest.skip("no local runs/")
    from slr.eval.ablation_harness import RETRIEVAL_STAGES

    out = ablation.stage_ablation(RUNS_DIR, RETRIEVAL_STAGES)
    if out["missing_runs"]:
        pytest.skip(f"missing run dirs: {out['missing_runs']}")

    expected = {
        "Smid_2020": {"bm25": 0.520, "dense": 0.696, "hybrid": 0.757, "rerank": 0.757},
        "Nelson_2002": {"bm25": 0.038, "dense": 0.178, "hybrid": 0.094, "rerank": 0.094},
        "van_der_Valk_2021": {"bm25": 0.049, "dense": 0.181, "hybrid": 0.068, "rerank": 0.068},
    }
    rows = {r["review"]: r for r in out["rows"]}
    for review, stages in expected.items():
        if review not in rows:
            continue
        for stage, value in stages.items():
            actual = rows[review]["stages"].get(stage)
            assert actual == pytest.approx(value, abs=0.002), f"{review}/{stage}"


@real_db
def test_rerank_is_still_identical_to_hybrid(real):
    """Recorded as a real finding, not a bug: every review's 95%-recall
    cutoff falls past the 200-record reranking window, so reordering inside
    that window cannot move the figure."""
    if not RUNS_DIR.exists():
        pytest.skip("no local runs/")
    from slr.eval.ablation_harness import RETRIEVAL_STAGES

    out = ablation.stage_ablation(RUNS_DIR, RETRIEVAL_STAGES)
    if out["missing_runs"]:
        pytest.skip(f"missing run dirs: {out['missing_runs']}")
    for row in out["rows"]:
        hybrid, rerank = row["stages"].get("hybrid"), row["stages"].get("rerank")
        if hybrid is None or rerank is None:
            continue
        assert hybrid == pytest.approx(rerank), row["review"]
