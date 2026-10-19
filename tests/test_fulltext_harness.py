"""Tests for the full-text harness.

The harness exists so a full-text figure can be reported at all: rule 2 wants
a run directory with a config and a commit hash, and until this landed full
text could only be driven through the dashboard, which writes neither.

Europe PMC is never called here. ``resolve`` is patched, so these assert what
the harness records about each outcome, not what the network returns.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from slr.adapters.fulltext import FullText, Section
from slr.config import FULLTEXT_REVIEW, SUBSET, FullTextConfig
from slr.eval import fulltext_harness as H

PROSE = (
    "The primary outcome was all-cause mortality at 12 months. "
    "The pooled risk ratio was 0.84 (95% confidence interval 0.74 to 0.95). "
    "We used random-effects meta-analysis across 42 included studies. "
    "Participants were 1,284 adults aged 18 to 65 recruited from four centres. "
    "A limitation is that only English-language reports were eligible. "
) * 3


def _complete() -> FullText:
    return FullText(
        pmcid="PMC10248995", doi="10.1/a", title="A complete paper",
        abstract="A.", sections=[Section(title="Results", text=PROSE)],
    )


def _stub() -> FullText:
    return FullText(
        pmcid="PMC7508247", doi="10.2/b", title="A stub",
        abstract=None, sections=[Section(title="", text="Short stub.")],
    )


def _cfg(tmp_path, targets, **kw) -> FullTextConfig:
    return FullTextConfig(
        name="test", targets=targets, provider="mock", model="mock-1",
        db_path=tmp_path / "t.db", runs_dir=tmp_path / "runs",
        prompts_dir=Path("prompts"), ceiling_usd=1.0, **kw,
    )


def _run(tmp_path, mapping, **kw):
    def fake_resolve(target, *, client):
        return mapping[target]

    cfg = _cfg(tmp_path, list(mapping), **kw)
    with patch.object(H, "resolve", fake_resolve):
        run_dir = H.run(cfg)
    return run_dir, json.loads((run_dir / "metrics.json").read_text(encoding="utf-8"))


# --------------------------------------------------------------------------
# The boundary: live full-text records are not evaluation-corpus records
# --------------------------------------------------------------------------


def test_the_review_label_cannot_be_an_evaluation_review():
    """'_discover' keeps this boundary and so must this. A full-text row
    carrying a real review name could be mistaken for benchmark data."""
    assert FULLTEXT_REVIEW not in SUBSET
    with pytest.raises(ValueError, match="must not be an evaluation-corpus review"):
        FullTextConfig(name="bad", targets=["10.1/a"], review="Nelson_2002")


def test_targets_cannot_be_empty_or_blank():
    with pytest.raises(ValueError, match="at least one DOI or PMCID"):
        FullTextConfig(name="bad", targets=["   ", ""])


# --------------------------------------------------------------------------
# What the artefact has to record
# --------------------------------------------------------------------------


def test_a_run_writes_every_artefact_rule_2_asks_for(tmp_path):
    run_dir, metrics = _run(tmp_path, {"a": (_complete(), H.FULL, "open access")})
    written = {p.name for p in run_dir.iterdir()}
    assert written == {
        "config.yaml", "resolved_config.json", "metrics.json", "run.json",
        "git_sha.txt", "fulltext.jsonl",
    }
    assert (run_dir / "git_sha.txt").read_text(encoding="utf-8").strip()
    assert metrics["config_name"] == "test"
    assert metrics["review"] == FULLTEXT_REVIEW


def test_why_there_is_no_full_text_is_recorded_as_a_fact_not_a_failure(tmp_path):
    """paywalled / not_indexed / no_pmc are facts about Europe PMC's holdings.
    The 7 October note exists because conflating them with weak extraction
    misreads the system badly."""
    run_dir, metrics = _run(tmp_path, {
        "a": (_complete(), H.FULL, "open access"),
        "b": (_stub(), H.FRAGMENT, "flagged open access but only a stub was served"),
        "c": (None, H.PAYWALLED, "in Europe PMC, not open access"),
        "d": (None, H.NOT_INDEXED, "Europe PMC has no record"),
        "e": (None, H.LOOKUP_FAILED, "ConnectError: boom"),
    })
    assert metrics["availability"] == {
        H.FULL: 1, H.FRAGMENT: 1, H.PAYWALLED: 1, H.NOT_INDEXED: 1, H.LOOKUP_FAILED: 1
    }
    # usable_share counts only complete papers -- a fragment is not a usable one.
    assert metrics["usable_share"] == 0.2

    rows = {json.loads(line)["target"]: json.loads(line)
            for line in (run_dir / "fulltext.jsonl").read_text(encoding="utf-8").splitlines()}
    assert len(rows) == 5, "every target gets a row, including the ones with no text"
    assert rows["c"]["reason"] == "in Europe PMC, not open access"
    assert rows["c"]["fields"] == {}, "a paper with no text is not scored on fields"
    assert rows["e"]["availability"] == H.LOOKUP_FAILED


def test_how_much_of_the_paper_the_model_saw_is_recorded(tmp_path):
    """A field marked not_stated may be in the portion that was truncated
    away. The artefact has to let a reader tell those apart."""
    run_dir, metrics = _run(
        tmp_path, {"a": (_complete(), H.FULL, "open access")}, max_prompt_chars=200
    )
    row = json.loads((run_dir / "fulltext.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert row["truncated"] is True
    assert row["chars_shown"] <= 200
    assert row["chars_available"] > row["chars_shown"]
    assert 0 < row["share_shown"] < 1
    assert metrics["truncation"]["papers_truncated"] == 1
    assert metrics["truncation"]["max_prompt_chars"] == 200


def test_an_untruncated_paper_is_not_reported_as_truncated(tmp_path):
    _, metrics = _run(tmp_path, {"a": (_complete(), H.FULL, "open access")})
    assert metrics["truncation"]["papers_truncated"] == 0
    assert metrics["truncation"]["median_share_shown"] == 1.0


def test_every_field_gets_a_status_for_every_paper_read(tmp_path):
    _, metrics = _run(tmp_path, {
        "a": (_complete(), H.FULL, "open access"),
        "b": (_stub(), H.FRAGMENT, "stub"),
    })
    assert set(metrics["field_status"]) == set(H.FIELDS)
    for counts in metrics["field_status"].values():
        assert sum(counts.values()) == 2, "two papers were read, so two statuses per field"
        assert set(counts) <= {"verified", "not_stated", "unverified"}


def test_the_caveat_about_availability_is_in_the_artefact(tmp_path):
    """Written into metrics.json rather than left for a reader to remember --
    the same device as PolicyResult.comparable in the ablation."""
    _, metrics = _run(tmp_path, {"a": (None, H.PAYWALLED, "not open access")})
    assert "not extraction failures" in metrics["note"]
    assert "truncated away" in metrics["note"]


def test_max_records_caps_the_targets(tmp_path):
    _, metrics = _run(
        tmp_path,
        {"a": (_complete(), H.FULL, "ok"), "b": (_stub(), H.FRAGMENT, "stub")},
        max_records=1,
    )
    assert metrics["targets"] == 1


def test_resolve_treats_a_pmcid_as_a_pmcid_without_a_doi_lookup():
    """A target already naming a PMCID should not be sent through DOI lookup."""
    called = {"lookup": 0}

    def no_lookup(**kwargs):
        called["lookup"] += 1
        raise AssertionError("should not look up a PMCID by DOI")

    with patch.object(H, "find_availability", no_lookup), \
         patch.object(H, "fetch_full_text", lambda pmcid, client=None: _complete()):
        paper, outcome, _ = H.resolve("PMC10248995", client=None)
    assert called["lookup"] == 0
    assert outcome == H.FULL and paper is not None


def test_a_dirty_tree_is_refused_when_the_run_is_meant_to_be_reported(tmp_path):
    cfg = _cfg(tmp_path, ["a"])
    with patch.object(H, "git_state", lambda _d: ("abc123", True)):
        with pytest.raises(H.DirtyTree):
            H.run(cfg, require_clean=True)


def test_cli_reports_a_missing_config_rather_than_raising(tmp_path):
    assert H.main(["--config", str(tmp_path / "nope.yaml")]) == 2
