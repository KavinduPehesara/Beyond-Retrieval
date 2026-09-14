"""Tests for the harness, including the weeks 7–8 exit test.

Exit test (proposal, Table 5): a stored configuration reproduces an identical
metrics file. These tests run the real harness end to end with the mock
provider over a synthetic corpus: no network, no key, no cost.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from slr.config import load_config
from slr.db import connect
from slr.eval import harness, report_tables
from slr.services.ingest import ingest_frame

REPO = Path(__file__).resolve().parent.parent
REVIEW = "Nelson_2002"
N_RECORDS = 60
N_INCLUDED = 13


def _corpus() -> pd.DataFrame:
    rows = []
    for i in range(N_RECORDS):
        included = i < N_INCLUDED
        topic = (
            "screening accuracy against a reference standard in the target population"
            if included
            else "an unrelated outcome measured in a different population"
        )
        rows.append(
            {
                "openalex_id": f"W{i:03d}",
                "title": f"Study {i} of {topic}",
                "abstract": (
                    f"This study number {i} examined {topic}. "
                    f"Participants were recruited from site {i % 7} over two years. "
                    f"The findings are reported with confidence intervals throughout."
                ),
                "label_included": int(included),
            }
        )
    return pd.DataFrame(rows)


def _config(tmp_path: Path, name: str, body: str) -> Path:
    path = tmp_path / f"{name}.yaml"
    path.write_text(
        f"name: {name}\n"
        f"db_path: '{(tmp_path / 'slr.db').as_posix()}'\n"
        f"runs_dir: '{(tmp_path / 'runs').as_posix()}'\n"
        f"prompts_dir: '{(REPO / 'prompts').as_posix()}'\n" + body,
        encoding="utf-8",
    )
    return path


SCREEN = f"""
dataset:
  reviews: [{REVIEW}]
  max_records: 40
  seed: 42
ranking:
  strategy: random
screening:
  provider: mock
  model: mock-1
budget:
  ceiling_usd: 1.0
"""

BASELINE = f"""
dataset:
  reviews: [{REVIEW}]
  max_records: null
ranking:
  strategy: bm25
screening:
  enabled: false
"""


@pytest.fixture()
def corpus(tmp_path, monkeypatch):
    monkeypatch.setattr(harness, "git_state", lambda: ("0" * 40, False))
    conn = connect(tmp_path / "slr.db")
    ingest_frame(conn, REVIEW, _corpus())
    conn.close()
    return tmp_path


def _read(run_dir: Path, name: str) -> dict:
    return json.loads((run_dir / name).read_text(encoding="utf-8"))


def test_stored_configuration_reproduces_an_identical_metrics_file(corpus):
    """Weeks 7–8 exit test."""
    cfg = load_config(_config(corpus, "screen", SCREEN))
    first = harness.run(cfg)
    second = harness.run(cfg)

    assert first != second
    assert (first / "metrics.json").read_bytes() == (second / "metrics.json").read_bytes()

    one, two = _read(first, "run.json"), _read(second, "run.json")
    assert one["cached_calls"] == 0 and one["live_spend_usd"] > 0
    assert two["cached_calls"] == 40 and two["live_spend_usd"] == 0


def test_baseline_run_is_reproducible_and_reports_ranking_metrics(corpus):
    cfg = load_config(_config(corpus, "bm25", BASELINE))
    first = harness.run(cfg)
    second = harness.run(cfg)
    assert (first / "metrics.json").read_bytes() == (second / "metrics.json").read_bytes()

    result = _read(first, "metrics.json")
    ranking = result["per_review"][0]["ranking"]
    assert result["mode"] == "baseline"
    assert ranking["complete"] is True
    assert ranking["n_ranked"] == N_RECORDS
    # The synthetic included records share the criteria's vocabulary, so BM25
    # ranks them first and saves nearly all the reading.
    assert ranking["tnr_at_recall"] > 0.9


def test_metrics_file_holds_no_execution_details(corpus):
    run_dir = harness.run(load_config(_config(corpus, "screen", SCREEN)))
    text = (run_dir / "metrics.json").read_text(encoding="utf-8")
    for leaked in ("started_at", "finished_at", "git_sha", "latency", "cached", "run_id"):
        assert leaked not in text


def test_run_directory_contents(corpus):
    run_dir = harness.run(load_config(_config(corpus, "screen", SCREEN)))
    assert sorted(p.name for p in run_dir.iterdir()) == [
        "config.yaml",
        "git_sha.txt",
        "metrics.json",
        "resolved_config.json",
        "responses.jsonl",
        "run.json",
    ]
    metrics_file = _read(run_dir, "metrics.json")
    assert metrics_file["criteria"]["status"] == "working-draft"
    assert metrics_file["per_review"][0]["prevalence"] == pytest.approx(N_INCLUDED / N_RECORDS)


def test_responses_log_carries_no_ground_truth(corpus):
    run_dir = harness.run(load_config(_config(corpus, "screen", SCREEN)))
    for line in (run_dir / "responses.jsonl").read_text(encoding="utf-8").splitlines():
        assert "label" not in json.loads(line)


def test_require_clean_refuses_a_dirty_tree_before_doing_anything(corpus, monkeypatch):
    monkeypatch.setattr(harness, "git_state", lambda: ("0" * 40, True))
    cfg = load_config(_config(corpus, "screen", SCREEN))
    with pytest.raises(harness.DirtyTree):
        harness.run(cfg, require_clean=True)
    assert not (corpus / "runs").exists()


def test_missing_corpus_is_refused_before_a_run_directory_exists(tmp_path, monkeypatch):
    monkeypatch.setattr(harness, "git_state", lambda: ("0" * 40, False))
    cfg = load_config(_config(tmp_path, "screen", SCREEN))
    with pytest.raises(harness.MissingCorpus):
        harness.run(cfg)
    assert not (tmp_path / "runs").exists()


def test_budget_abort_is_recorded(corpus):
    body = SCREEN.replace("ceiling_usd: 1.0", "ceiling_usd: 0.00001")
    run_dir = harness.run(load_config(_config(corpus, "tiny", body)))
    assert _read(run_dir, "metrics.json")["aborted"] is True
    assert "exceeded ceiling" in _read(run_dir, "run.json")["aborted_reason"]


def test_report_tables_from_real_run_directories(corpus):
    harness.run(load_config(_config(corpus, "screen", SCREEN)))
    harness.run(load_config(_config(corpus, "bm25", BASELINE)))

    rows = report_tables.build(corpus / "runs", corpus / "reports")
    assert len(rows) == 2
    assert {r["mode"] for r in rows} == {"screen", "baseline"}

    markdown = (corpus / "reports" / "results.md").read_text(encoding="utf-8")
    assert f"## {REVIEW} — 60 records, 21.7% included" in markdown
    assert "‡" in markdown  # the screening run used draft criteria
    csv_text = (corpus / "reports" / "results.csv").read_text(encoding="utf-8")
    assert csv_text.splitlines()[0].startswith("review,n_records,prevalence")
