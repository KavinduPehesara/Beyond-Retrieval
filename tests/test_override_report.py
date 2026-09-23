"""Tests for the overrides.json export -- rule 2 needs this in a run directory."""

from __future__ import annotations

import json

import pytest

from slr.db import connect
from slr.eval.override_report import build_report, main
from slr.services.override import record_override


@pytest.fixture()
def conn(tmp_path):
    c = connect(tmp_path / "test.db")
    c.execute("INSERT INTO run (run_id, config_hash) VALUES ('R1', 'h')")
    c.execute(
        "INSERT INTO work (work_id, review, title, abstract, label_included) "
        "VALUES ('W1', 'Nelson_2002', 't', 'a', 1)"
    )
    c.execute(
        "INSERT INTO screening_decision "
        "(run_id, review, work_id, decision, confidence, span_verified, verify_note) "
        "VALUES ('R1', 'Nelson_2002', 'W1', 'unverified', NULL, 0, 'not_found')"
    )
    c.commit()
    yield c
    c.close()


def test_build_report_combines_summary_and_records(conn):
    record_override(conn, run_id="R1", review="Nelson_2002", work_id="W1", decision="include", rationale="clear RCT")
    report = build_report(conn, "R1", "Nelson_2002")
    assert report["run_id"] == "R1"
    assert report["summary"]["n_overrides"] == 1
    assert report["summary"]["n_changed"] == 1
    assert report["records"][0]["work_id"] == "W1"
    assert report["records"][0]["matches_truth"] is True


def test_main_writes_to_the_run_directory(tmp_path, conn, monkeypatch):
    db_path = tmp_path / "db.sqlite"
    conn.close()
    c = connect(db_path)
    c.execute("INSERT INTO run (run_id, config_hash) VALUES ('R1', 'h')")
    c.execute(
        "INSERT INTO work (work_id, review, title, abstract, label_included) "
        "VALUES ('W1', 'Nelson_2002', 't', 'a', 1)"
    )
    c.execute(
        "INSERT INTO screening_decision "
        "(run_id, review, work_id, decision, confidence, span_verified, verify_note) "
        "VALUES ('R1', 'Nelson_2002', 'W1', 'unverified', NULL, 0, 'not_found')"
    )
    record_override(c, run_id="R1", review="Nelson_2002", work_id="W1", decision="include")
    c.close()

    (tmp_path / "runs" / "R1").mkdir(parents=True)
    rc = main(["--db", str(db_path), "--run-id", "R1", "--review", "Nelson_2002", "--runs-dir", str(tmp_path / "runs")])
    assert rc == 0
    out = tmp_path / "runs" / "R1" / "overrides.json"
    assert out.exists()
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["summary"]["n_overrides"] == 1


def test_main_fails_cleanly_with_no_overrides(tmp_path, conn):
    db_path = tmp_path / "empty.db"
    c = connect(db_path)
    c.close()
    (tmp_path / "runs" / "R1").mkdir(parents=True)
    rc = main(["--db", str(db_path), "--run-id", "R1", "--review", "Nelson_2002", "--runs-dir", str(tmp_path / "runs")])
    assert rc == 2
