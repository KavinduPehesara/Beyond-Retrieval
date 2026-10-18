"""Tests for the multi-model gap comparison.

The week-14 arms don't exist yet when these run, so every fixture here is a
synthetic run directory shaped exactly like a real ``gap_statements.jsonl``.
What's asserted is the arithmetic and the boundaries -- the real figures come
from real runs, as rule 2 requires.
"""

from __future__ import annotations

import json

import pytest

from slr.eval.gap_consensus import NOT_STATED, STATED, compare, load_arm, main


def _arm(tmp_path, name, rows):
    d = tmp_path / name
    d.mkdir()
    (d / "gap_statements.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rows), encoding="utf-8"
    )
    return d


def _row(work_id, value, review="R1", **kw):
    return {
        "work_id": work_id, "review": review, "value": value,
        "evidence_span": "further studies are needed" if value == STATED else None,
        "span_verified": value == STATED, "verify_note": value,
        "from_cache": False, "tokens_in": 800, "tokens_out": 50,
        "cost_usd": 0.0, "latency_ms": 10, "error": None, **kw,
    }


def test_load_arm_requires_a_gap_run_not_a_screening_run(tmp_path):
    (tmp_path / "screening").mkdir()
    (tmp_path / "screening" / "metrics.json").write_text("{}")
    with pytest.raises(FileNotFoundError, match="gap harness run directory"):
        load_arm(tmp_path / "screening")


def test_an_errored_record_is_a_missing_rating_not_a_third_category(tmp_path):
    """Same treatment inter-run agreement already gives unverified decisions:
    scoring an error as 'not_stated' would count a crash as a judgement."""
    d = _arm(tmp_path, "a", [_row("W1", None, error="schema_validation_failed")])
    assert load_arm(d)["R1\tW1"]["value"] is None


def test_the_two_combinations_move_in_opposite_directions(tmp_path):
    """`both` is an intersection and cannot flag more than the stingiest arm;
    `either` is a union and cannot flag fewer than the most generous."""
    a = load_arm(_arm(tmp_path, "a", [
        _row("W1", STATED), _row("W2", STATED), _row("W3", NOT_STATED), _row("W4", NOT_STATED)]))
    b = load_arm(_arm(tmp_path, "b", [
        _row("W1", STATED), _row("W2", NOT_STATED), _row("W3", STATED), _row("W4", NOT_STATED)]))

    r = compare({"model-a": a, "model-b": b})["per_review"][0]
    assert r["flagged_by_arm"] == {"model-a": 2, "model-b": 2}
    assert r["combined"]["both"] == 1     # only W1
    assert r["combined"]["either"] == 3   # W1, W2, W3
    assert r["combined"]["both"] <= min(r["flagged_by_arm"].values())
    assert r["combined"]["either"] >= max(r["flagged_by_arm"].values())
    assert r["n_unanimous"] == 2 and r["n_disagreed"] == 2


def test_perfect_agreement_scores_one_and_is_reported_per_review(tmp_path):
    rows = [_row("W1", STATED), _row("W2", NOT_STATED), _row("W3", NOT_STATED)]
    rows += [_row("W4", STATED, review="R2"), _row("W5", NOT_STATED, review="R2")]
    a = load_arm(_arm(tmp_path, "a", rows))
    b = load_arm(_arm(tmp_path, "b", rows))

    result = compare({"model-a": a, "model-b": b})
    assert [r["review"] for r in result["per_review"]] == ["R1", "R2"], "never pooled (rule 5)"
    for r in result["per_review"]:
        assert r["agreement_ac1"]["coefficient"] == pytest.approx(1.0)
        assert r["n_disagreed"] == 0


def test_a_record_only_one_arm_saw_is_not_a_disagreement(tmp_path):
    a = load_arm(_arm(tmp_path, "a", [_row("W1", STATED), _row("W2", STATED)]))
    b = load_arm(_arm(tmp_path, "b", [_row("W1", STATED)]))
    r = compare({"model-a": a, "model-b": b})["per_review"][0]
    assert r["n_records"] == 1          # the intersection, not the union
    assert r["n_disagreed"] == 0


def test_disagreements_are_listed_with_both_spans_for_a_human_to_read(tmp_path):
    """The disagreements are the whole point -- they are what a second rater
    buys. They have to come out of the artefact readable, not just counted."""
    a = load_arm(_arm(tmp_path, "a", [_row("W1", STATED)]))
    b = load_arm(_arm(tmp_path, "b", [_row("W1", NOT_STATED)]))
    r = compare({"model-a": a, "model-b": b})["per_review"][0]
    assert len(r["disagreements"]) == 1
    d = r["disagreements"][0]
    assert d["model-a"]["value"] == STATED
    assert d["model-a"]["span"] == "further studies are needed"
    assert d["model-b"]["value"] == NOT_STATED


def test_three_arms_work_and_both_needs_all_three(tmp_path):
    a = load_arm(_arm(tmp_path, "a", [_row("W1", STATED), _row("W2", STATED)]))
    b = load_arm(_arm(tmp_path, "b", [_row("W1", STATED), _row("W2", STATED)]))
    c = load_arm(_arm(tmp_path, "c", [_row("W1", STATED), _row("W2", NOT_STATED)]))
    r = compare({"a": a, "b": b, "c": c})["per_review"][0]
    assert r["combined"]["both"] == 1 and r["combined"]["either"] == 2
    assert "pabak" not in r  # two-rater only


def test_one_arm_is_refused(tmp_path):
    a = load_arm(_arm(tmp_path, "a", [_row("W1", STATED)]))
    with pytest.raises(ValueError, match="at least two arms"):
        compare({"only": a})


def test_the_report_says_agreement_is_not_correctness(tmp_path):
    """The caveat is part of the artefact, not something a reader is trusted to
    remember -- the same reason PolicyResult.comparable exists in the ablation."""
    a = load_arm(_arm(tmp_path, "a", [_row("W1", STATED)]))
    b = load_arm(_arm(tmp_path, "b", [_row("W1", STATED)]))
    note = compare({"a": a, "b": b})["note"]
    assert "not correctness" in note
    assert "correlate in their errors" in note


def test_cli_writes_a_run_directory(tmp_path, capsys):
    _arm(tmp_path, "run-a", [_row("W1", STATED), _row("W2", NOT_STATED)])
    _arm(tmp_path, "run-b", [_row("W1", STATED), _row("W2", STATED)])
    out = tmp_path / "out"
    code = main([
        "--runs", str(tmp_path), "--out", str(out),
        "--arm", "model-a=run-a", "--arm", "model-b=run-b",
    ])
    assert code == 0
    written = json.loads((out / "metrics.json").read_text(encoding="utf-8"))
    assert written["arms"] == ["model-a", "model-b"]
    assert written["per_review"][0]["n_disagreed"] == 1
    assert (out / "git_sha.txt").exists()      # rule 2: a figure traces to a commit
    assert "Gap discovery across models" in (out / "consensus.md").read_text(encoding="utf-8")


def test_cli_rejects_a_malformed_arm(tmp_path):
    assert main(["--runs", str(tmp_path), "--arm", "no-equals-sign", "--arm", "x=y"]) == 2
