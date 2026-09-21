"""Tests for the inter-run AC1 CLI's config_hash guard.

The number it prints is only meaningful if every run directory really is a
repeat of the same configuration -- this is the check that catches feeding
it runs from different configs by mistake.
"""

from __future__ import annotations

import json

import pytest

from slr.eval.inter_run import load_run_ids


def _make_run_dir(tmp_path, run_id: str, config_hash: str):
    run_dir = tmp_path / run_id
    run_dir.mkdir()
    (run_dir / "metrics.json").write_text(
        json.dumps({"config_hash": config_hash}), encoding="utf-8"
    )
    return run_dir


def test_shared_config_hash_returns_run_ids_in_order(tmp_path):
    a = _make_run_dir(tmp_path, "run-a", "abc123")
    b = _make_run_dir(tmp_path, "run-b", "abc123")
    assert load_run_ids([a, b]) == ["run-a", "run-b"]


def test_mismatched_config_hash_is_rejected(tmp_path):
    a = _make_run_dir(tmp_path, "run-a", "abc123")
    b = _make_run_dir(tmp_path, "run-b", "def456")
    with pytest.raises(ValueError, match="do not share one config_hash"):
        load_run_ids([a, b])
