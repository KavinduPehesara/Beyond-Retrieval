"""Tests for the API. Every route either reads what a harness already wrote
or calls the same service functions the CLIs do -- these tests check the
wiring, not the underlying logic (which has its own tests already).
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from slr.api import app as app_module
from slr.api.deps import get_conn
from slr.db import connect


@pytest.fixture()
def conn(tmp_path):
    c = connect(tmp_path / "test.db", check_same_thread=False)
    for wid, title, inc in [("W1", "Trial of X in Y patients", 1), ("W2", "A survey of Z", 0)]:
        c.execute(
            "INSERT INTO work (review, work_id, title, abstract, year, venue, doi, label_included) "
            "VALUES ('R1', ?, ?, 'Randomised trial. Further studies are needed.', 2020, 'J. Testing', NULL, ?)",
            (wid, title, inc),
        )
    c.execute(
        "INSERT INTO review_criteria (review, criteria, source, sha256) VALUES ('R1', 'Include RCTs.', 'test', 'x')"
    )
    c.commit()
    yield c
    c.close()


@pytest.fixture()
def runs_dir(tmp_path):
    d = tmp_path / "runs"
    d.mkdir()
    return d


@pytest.fixture()
def client(conn, runs_dir, monkeypatch):
    monkeypatch.setattr(app_module, "RUNS_DIR", runs_dir)
    monkeypatch.setattr(app_module, "PROMPTS_DIR", app_module.PROMPTS_DIR)  # real prompts/ dir, read-only

    def override_get_conn():
        yield conn

    app_module.app.dependency_overrides[get_conn] = override_get_conn
    yield TestClient(app_module.app)
    app_module.app.dependency_overrides.clear()


def _write_run(runs_dir, name, metrics):
    d = runs_dir / name
    d.mkdir()
    (d / "metrics.json").write_text(json.dumps(metrics), encoding="utf-8")
    return d


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_list_reviews_reflects_the_corpus_and_criteria(client):
    resp = client.get("/reviews")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    r = body[0]
    assert r["review"] == "R1"
    assert r["n_records"] == 2
    assert r["n_included"] == 1
    assert r["prevalence"] == pytest.approx(0.5)
    assert r["criteria_status"] == "published"
    assert r["screen_run"] is None


def test_review_metrics_404_when_no_screening_run_exists(client):
    assert client.get("/reviews/R1/metrics").status_code == 404


def test_review_metrics_reads_the_named_run(client, runs_dir):
    _write_run(runs_dir, "20260101T000000Z-aaa", {
        "mode": "screen", "reviews_completed": ["R1"],
        "per_review": [{"review": "R1", "verification_rate": 0.9}],
    })
    resp = client.get("/reviews/R1/metrics")
    assert resp.status_code == 200
    assert resp.json()["verification_rate"] == 0.9
    assert resp.json()["run_id"] == "20260101T000000Z-aaa"


def test_list_papers_without_a_screening_run_is_404(client):
    assert client.get("/reviews/R1/papers").status_code == 404


def test_list_papers_joins_screening_decisions(client, conn, runs_dir):
    _write_run(runs_dir, "20260101T000000Z-aaa", {"mode": "screen", "reviews_completed": ["R1"]})
    conn.execute("INSERT INTO run (run_id, config_hash) VALUES ('20260101T000000Z-aaa', 'h')")
    conn.execute(
        "INSERT INTO screening_decision (run_id, review, work_id, decision, confidence, span_verified, verify_note) "
        "VALUES ('20260101T000000Z-aaa', 'R1', 'W1', 'include', 0.9, 1, 'ok')"
    )
    conn.commit()
    resp = client.get("/reviews/R1/papers")
    assert resp.status_code == 200
    by_id = {p["work_id"]: p for p in resp.json()}
    assert by_id["W1"]["decision"] == "include"
    assert by_id["W2"]["decision"] is None  # unscreened, still listed


def test_paper_detail_assembles_screen_extract_and_gap(client, conn, runs_dir):
    _write_run(runs_dir, "20260101T000000Z-aaa", {"mode": "screen", "reviews_completed": ["R1"]})
    _write_run(runs_dir, "20260101T000000Z-extract-bbb", {"review": "R1"})
    _write_run(runs_dir, "20260101T000000Z-gap-ccc", {"review": "R1"})
    conn.execute("INSERT INTO run (run_id, config_hash) VALUES ('20260101T000000Z-aaa', 'h')")
    conn.execute(
        "INSERT INTO screening_decision (run_id, review, work_id, decision, confidence, evidence_span, span_verified, verify_note) "
        "VALUES ('20260101T000000Z-aaa', 'R1', 'W1', 'include', 0.9, 'Randomised trial', 1, 'ok')"
    )
    conn.execute(
        "INSERT INTO extraction (run_id, source_run_id, review, work_id, field_name, value, evidence_span, span_verified, verify_note) "
        "VALUES ('20260101T000000Z-extract-bbb', '20260101T000000Z-aaa', 'R1', 'W1', 'study_design', 'RCT', 'Randomised trial', 1, 'exact_after_normalisation')"
    )
    conn.execute(
        "INSERT INTO extraction (run_id, source_run_id, review, work_id, field_name, value, evidence_span, span_verified, verify_note) "
        "VALUES ('20260101T000000Z-extract-bbb', '20260101T000000Z-aaa', 'R1', 'W1', 'country', 'not_stated', NULL, 0, 'not_stated')"
    )
    conn.execute(
        "INSERT INTO gap_statement (run_id, source_run_id, review, work_id, value, evidence_span, span_verified, rating, rating_note) "
        "VALUES ('20260101T000000Z-gap-ccc', '20260101T000000Z-aaa', 'R1', 'W1', 'gap_stated', 'Further studies are needed', 1, 'valid', 'valid -- open future-work statement')"
    )
    conn.commit()
    resp = client.get("/reviews/R1/papers/W1")
    assert resp.status_code == 200
    body = resp.json()
    assert body["decision"] == "include"
    assert body["study_design"] == {"status": "verified", "value": "RCT", "quote": "Randomised trial", "note": "exact_after_normalisation"}
    assert body["country"]["status"] == "not_stated"
    assert body["sample_size"]["status"] == "missing"  # never extracted for this paper
    assert body["gap"]["status"] == "gap_stated"
    assert body["gap"]["kind"] == "open"


def test_paper_detail_404_for_unknown_paper(client):
    assert client.get("/reviews/R1/papers/nope").status_code == 404


def test_override_flow(client, conn, runs_dir):
    _write_run(runs_dir, "20260101T000000Z-aaa", {"mode": "screen", "reviews_completed": ["R1"]})
    conn.execute(
        "INSERT INTO run (run_id, config_hash) VALUES ('20260101T000000Z-aaa', 'h')"
    )
    conn.execute(
        "INSERT INTO screening_decision (run_id, review, work_id, decision, confidence, span_verified, verify_note) "
        "VALUES ('20260101T000000Z-aaa', 'R1', 'W1', 'unverified', NULL, 0, 'not_found')"
    )
    conn.commit()

    resp = client.post("/overrides", json={"run_id": "20260101T000000Z-aaa", "review": "R1", "work_id": "W1", "decision": "exclude", "rationale": "no RCT design stated"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["model_decision"] == "unverified"
    assert body["changed"] is True

    summary = client.get("/reviews/R1/overrides", params={"run_id": "20260101T000000Z-aaa"})
    assert summary.status_code == 200
    assert summary.json() == {"n_overrides": 1, "n_changed": 1, "n_confirmed": 0, "override_rate": 1.0, "by_model_decision": {"unverified": 1}}


def test_override_404_for_unscreened_paper(client, conn):
    conn.execute("INSERT INTO run (run_id, config_hash) VALUES ('r1', 'h')")
    conn.commit()
    resp = client.post("/overrides", json={"run_id": "r1", "review": "R1", "work_id": "W1", "decision": "include"})
    assert resp.status_code == 404


def test_list_gaps_returns_only_gap_stated_rows(client, conn, runs_dir):
    _write_run(runs_dir, "20260101T000000Z-gap-ccc", {"review": "R1"})
    conn.execute(
        "INSERT INTO gap_statement (run_id, source_run_id, review, work_id, value, evidence_span, span_verified, rating) "
        "VALUES ('20260101T000000Z-gap-ccc', 's', 'R1', 'W1', 'gap_stated', 'more research needed', 1, 'valid')"
    )
    conn.execute(
        "INSERT INTO gap_statement (run_id, source_run_id, review, work_id, value, span_verified) "
        "VALUES ('20260101T000000Z-gap-ccc', 's', 'R1', 'W2', 'not_stated', 0)"
    )
    conn.commit()
    resp = client.get("/reviews/R1/gaps")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["work_id"] == "W1"


def test_query_bm25_ranks_by_the_review_criteria_by_default(client):
    resp = client.post("/query", json={"review": "R1", "strategy": "bm25", "top_n": 5})
    assert resp.status_code == 200
    ids = [r["work_id"] for r in resp.json()]
    assert set(ids) == {"W1", "W2"}  # bm25 always returns the full review, ranked


def test_query_rejects_an_unknown_strategy(client):
    resp = client.post("/query", json={"review": "R1", "strategy": "nonsense"})
    assert resp.status_code == 400


def test_review_criteria(client):
    resp = client.get("/reviews/R1/criteria")
    assert resp.status_code == 200
    assert resp.json() == {"review": "R1", "text": "Include RCTs.", "status": "published", "source": "test"}


def test_extraction_summary_without_a_run_is_404(client):
    assert client.get("/reviews/R1/extraction-summary").status_code == 404


def test_extraction_summary_counts_by_field(client, conn, runs_dir):
    _write_run(runs_dir, "20260101T000000Z-extract-bbb", {"review": "R1"})
    rows = [
        ("W1", "study_design", "RCT", "q1", 1, "exact_after_normalisation"),
        ("W2", "study_design", None, None, 0, "not_stated"),
        ("W1", "country", None, "q2", 0, "not_found"),
    ]
    for wid, field, value, span, verified, note in rows:
        conn.execute(
            "INSERT INTO extraction (run_id, source_run_id, review, work_id, field_name, value, evidence_span, span_verified, verify_note) "
            "VALUES ('20260101T000000Z-extract-bbb', 's', 'R1', ?, ?, ?, ?, ?, ?)",
            (wid, field, value, span, verified, note),
        )
    conn.commit()
    resp = client.get("/reviews/R1/extraction-summary")
    assert resp.status_code == 200
    body = resp.json()
    assert body["fields"]["study_design"] == {"verified": 1, "not_stated": 1, "unverified": 0}
    assert body["fields"]["country"] == {"verified": 0, "not_stated": 0, "unverified": 1}


def test_query_screen_rejects_more_than_the_cap(client):
    ids = [f"W{i}" for i in range(20)]
    resp = client.post("/query/screen", json={"review": "R1", "work_ids": ids})
    assert resp.status_code == 422  # pydantic max_length on the request body
