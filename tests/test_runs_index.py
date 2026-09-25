"""Tests for picking the current run per review, per harness kind."""

from __future__ import annotations

import json

from slr.api.runs_index import (
    latest_extract_run,
    latest_gap_run,
    latest_screen_run,
    list_reviews_with_screen_runs,
)


def _write(runs_dir, name, data):
    d = runs_dir / name
    d.mkdir()
    (d / "metrics.json").write_text(json.dumps(data), encoding="utf-8")
    return d


def test_latest_screen_run_picks_the_last_covering_run(tmp_path):
    _write(tmp_path, "20260101T000000Z-aaa", {"mode": "screen", "reviews_completed": ["R1"]})
    _write(tmp_path, "20260102T000000Z-bbb", {"mode": "screen", "reviews_completed": ["R1", "R2"]})
    assert latest_screen_run(tmp_path, "R1") == "20260102T000000Z-bbb"
    assert latest_screen_run(tmp_path, "R2") == "20260102T000000Z-bbb"
    assert latest_screen_run(tmp_path, "R3") is None


def test_extract_and_gap_runs_are_identified_by_name_and_review_field(tmp_path):
    _write(tmp_path, "20260101T000000Z-extract-aaa", {"review": "R1"})
    _write(tmp_path, "20260102T000000Z-extract-bbb", {"review": "R1"})
    _write(tmp_path, "20260101T000000Z-gap-ccc", {"review": "R1"})
    assert latest_extract_run(tmp_path, "R1") == "20260102T000000Z-extract-bbb"
    assert latest_gap_run(tmp_path, "R1") == "20260101T000000Z-gap-ccc"
    assert latest_extract_run(tmp_path, "R2") is None


def test_gaprecall_runs_are_excluded_from_screen_and_gap_lookups(tmp_path):
    _write(tmp_path, "20260101T000000Z-gaprecall-aaa", {"review": "R1", "mode": "screen", "reviews_completed": ["R1"]})
    assert latest_screen_run(tmp_path, "R1") is None
    assert latest_gap_run(tmp_path, "R1") is None


def test_run_missing_or_malformed_metrics_json_is_skipped(tmp_path):
    d = tmp_path / "20260101T000000Z-aaa"
    d.mkdir()
    (d / "metrics.json").write_text("{not json", encoding="utf-8")
    (tmp_path / "20260102T000000Z-bbb").mkdir()  # no metrics.json at all
    assert latest_screen_run(tmp_path, "R1") is None


def test_list_reviews_with_screen_runs_takes_the_latest_per_review(tmp_path):
    _write(tmp_path, "20260101T000000Z-aaa", {"mode": "screen", "reviews_completed": ["R1"]})
    _write(tmp_path, "20260102T000000Z-bbb", {"mode": "screen", "reviews_completed": ["R1"]})
    _write(tmp_path, "20260103T000000Z-extract-ccc", {"review": "R1"})
    assert list_reviews_with_screen_runs(tmp_path) == {"R1": "20260102T000000Z-bbb"}
