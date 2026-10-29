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


def _run(tmp_path, name, metrics, config=None):
    d = tmp_path / name
    d.mkdir()
    (d / "metrics.json").write_text(json.dumps(metrics), encoding="utf-8")
    if config is not None:
        (d / "resolved_config.json").write_text(json.dumps(config), encoding="utf-8")
    return d


def test_a_smoke_run_never_becomes_the_current_run(tmp_path):
    """A five-record debugging run must not displace a full one.

    Found on 29 October: two provider smoke runs over 5 records of
    Nelson_2002 became "latest" for that review, and the reported gap rate
    silently recomputed from 5 records instead of 114.
    """
    from slr.api.runs_index import latest_gap_run

    _run(tmp_path, "20260101T000000Z-gap-aaaaaaaaaa",
         {"review": "Nelson_2002", "records": 114}, {"max_records": None})
    _run(tmp_path, "20261029T000000Z-gap-bbbbbbbbbb",
         {"review": "Nelson_2002", "records": 5}, {"max_records": 5})

    assert latest_gap_run(tmp_path, "Nelson_2002") == "20260101T000000Z-gap-aaaaaaaaaa"


def test_a_later_full_run_still_wins(tmp_path):
    from slr.api.runs_index import latest_gap_run

    _run(tmp_path, "20260101T000000Z-gap-aaaaaaaaaa",
         {"review": "Nelson_2002", "records": 114}, {"max_records": None})
    _run(tmp_path, "20261029T000000Z-gap-cccccccccc",
         {"review": "Nelson_2002", "records": 114}, {"max_records": None})

    assert latest_gap_run(tmp_path, "Nelson_2002") == "20261029T000000Z-gap-cccccccccc"


def test_a_run_with_no_resolved_config_is_treated_as_full(tmp_path):
    """Older runs predate the field and must keep counting."""
    from slr.api.runs_index import latest_gap_run

    _run(tmp_path, "20260101T000000Z-gap-dddddddddd", {"review": "Smid_2020", "records": 10})
    assert latest_gap_run(tmp_path, "Smid_2020") == "20260101T000000Z-gap-dddddddddd"
