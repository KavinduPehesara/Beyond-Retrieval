"""Tests for the report tables and the run index.

``results.md`` tabulates the runs whose metrics share the screening schema.
``run_index.md`` exists because the others -- extraction, gap discovery, gap
recall, ablation, error typology, query expansion, the ASReview baseline --
also write run directories, and figures from all of them are reported.
"""

from __future__ import annotations

import json

# --------------------------------------------------------------------------
# The run index. Week 14's exit test is that every figure traces to a run
# directory and a commit hash; load_runs only accepts the screening schema, so
# 36 of 79 directories were invisible in the one artefact meant to be the index.
# --------------------------------------------------------------------------


def test_the_index_lists_every_directory_not_just_tabulatable_ones(tmp_path):
    from slr.eval.report_tables import run_index

    runs = tmp_path / "runs"
    (runs / "20261001T000000000000Z-gap-aaaaaaaaaa").mkdir(parents=True)
    (runs / "20261001T000000000000Z-gap-aaaaaaaaaa" / "metrics.json").write_text(
        json.dumps({"name": "gap_demo", "review": "Nelson_2002"}), encoding="utf-8"
    )
    (runs / "20261001T000000000000Z-gap-aaaaaaaaaa" / "git_sha.txt").write_text("abc1234567890\n")
    (runs / "20261002T000000000000Z-ablation-bbbbbbbbbb").mkdir()
    (runs / "20261002T000000000000Z-ablation-bbbbbbbbbb" / "metrics.json").write_text("{}")

    index = {r["run"]: r for r in run_index(runs)}
    assert len(index) == 2
    assert index["20261001T000000000000Z-gap-aaaaaaaaaa"]["kind"] == "gap"
    assert index["20261001T000000000000Z-gap-aaaaaaaaaa"]["git_sha"] == "abc1234567"
    assert index["20261002T000000000000Z-ablation-bbbbbbbbbb"]["kind"] == "ablation"
    assert all(r["tabulated"] is False for r in index.values())


def test_a_directory_with_no_metrics_is_listed_not_silently_dropped(tmp_path):
    """A run killed before it wrote metrics, and ASReview's own project
    directory, both leave something under runs/. An unexplained directory
    invites a reader to wonder what figure came out of it; the answer is none,
    and the index has to say so."""
    from slr.eval.report_tables import index_to_markdown, run_index

    runs = tmp_path / "runs"
    (runs / "20261003T000000000000Z-cccccccccc").mkdir(parents=True)
    (runs / "20261003T000000000000Z-cccccccccc" / "responses.jsonl").write_text("{}\n")
    (runs / "asreview-nelson2002").mkdir()
    (runs / "asreview-nelson2002" / "project.asreview").write_bytes(b"zip")

    index = {r["run"]: r for r in run_index(runs)}
    assert index["20261003T000000000000Z-cccccccccc"]["kind"] == "incomplete"
    assert index["asreview-nelson2002"]["kind"] == "asreview-project"
    assert all(r["has_metrics"] is False for r in index.values())

    markdown = index_to_markdown(list(index.values()))
    assert "no metrics.json" in markdown
    assert "produced no figure" in markdown
    assert "No reported number comes from any" in markdown


def test_build_writes_the_index_beside_the_results(tmp_path):
    from slr.eval.report_tables import build

    runs = tmp_path / "runs"
    (runs / "20261004T000000000000Z-typology-dddddddddd").mkdir(parents=True)
    (runs / "20261004T000000000000Z-typology-dddddddddd" / "metrics.json").write_text("{}")
    out = tmp_path / "reports"
    build(runs, out)

    assert (out / "run_index.md").exists()
    assert (out / "run_index.csv").exists()
    assert "typology" in (out / "run_index.md").read_text(encoding="utf-8")
