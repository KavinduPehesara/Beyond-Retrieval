"""Tests for the gap_ratings.json export -- rule 2 needs this in a run directory."""

from __future__ import annotations

import json

import pytest

from slr.db import connect
from slr.eval.gap_report import build_report, main
from slr.services.gap import GapExtraction, persist, rate


def _seed(conn):
    conn.execute(
        "INSERT INTO work (work_id, review, title, abstract, label_included) "
        "VALUES ('W1', 'Nelson_2002', 't', 'a', 1)"
    )
    persist(
        conn, "R1", "S1",
        GapExtraction(
            work_id="W1", review="Nelson_2002", value="gap_stated",
            evidence_span="further study is warranted", span_verified=True,
            verify_note="exact_after_normalisation", from_cache=False,
            tokens_in=10, tokens_out=10, cost_usd=0.0, latency_ms=0,
        ),
    )
    conn.commit()


@pytest.fixture()
def conn(tmp_path):
    c = connect(tmp_path / "test.db")
    _seed(c)
    yield c
    c.close()


def test_build_report_combines_summary_and_records(conn):
    rate(conn, run_id="R1", review="Nelson_2002", work_id="W1", rating="valid", rating_note="genuine future work")
    report = build_report(conn, "R1", "Nelson_2002")
    assert report["run_id"] == "R1"
    assert report["summary"]["n_gap_stated"] == 1
    assert report["summary"]["precision"] == 1.0
    assert report["records"][0]["work_id"] == "W1"


def test_main_writes_to_the_run_directory(tmp_path):
    db_path = tmp_path / "db.sqlite"
    c = connect(db_path)
    _seed(c)
    rate(c, run_id="R1", review="Nelson_2002", work_id="W1", rating="invalid", rating_note="not a gap")
    c.close()

    (tmp_path / "runs" / "R1").mkdir(parents=True)
    rc = main(["--db", str(db_path), "--run-id", "R1", "--review", "Nelson_2002", "--runs-dir", str(tmp_path / "runs")])
    assert rc == 0
    out = tmp_path / "runs" / "R1" / "gap_ratings.json"
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["summary"]["n_invalid"] == 1


def test_main_fails_cleanly_with_no_gap_statements(tmp_path):
    db_path = tmp_path / "empty.db"
    c = connect(db_path)
    c.close()
    (tmp_path / "runs" / "R1").mkdir(parents=True)
    rc = main(["--db", str(db_path), "--run-id", "R1", "--review", "Nelson_2002", "--runs-dir", str(tmp_path / "runs")])
    assert rc == 2
