"""Tests for the one-paper live-demo command: screen, then (only if included
and verified) extract and look for a gap -- and stop cleanly otherwise.
"""

from __future__ import annotations

import json

import pytest

from slr.adapters.llm import Completion, Meter
from slr.db import connect
from slr.eval import one_paper


@pytest.fixture()
def conn(tmp_path):
    c = connect(tmp_path / "test.db")
    c.execute(
        "INSERT INTO work (work_id, review, title, abstract, label_included) VALUES "
        "('W1', 'Nelson_2002', 'A trial of X', "
        "'We conducted a randomised controlled trial of 100 patients in Canada. "
        "Treatment X reduced symptom Y by 10 percent. Further studies are needed to confirm this.', 1)"
    )
    c.execute(
        "INSERT INTO review_criteria (review, criteria, source, sha256) VALUES "
        "('Nelson_2002', 'Include RCTs.', 'test', 'x')"
    )
    c.commit()
    yield c
    c.close()


class _QueueProvider:
    """Returns payloads from a fixed queue, one per call, in order -- the
    one_paper pipeline calls the provider exactly once per stage, always in
    the same order (screen, extract, gap), so a queue is enough."""

    name = "fake"
    model = "fake-1"

    def __init__(self, payloads: list[dict]):
        self.payloads = list(payloads)
        self.calls = 0

    def complete(self, prompt, *, temperature=0.0, max_tokens=512, seed=None, response_schema=None):
        payload = self.payloads[self.calls]
        self.calls += 1
        return Completion(text=json.dumps(payload), tokens_in=10, tokens_out=10)


def _patch_provider(monkeypatch, payloads):
    monkeypatch.setattr(one_paper, "build_provider", lambda provider, model: _QueueProvider(payloads))


def test_included_and_verified_record_runs_all_three_stages(conn, monkeypatch):
    _patch_provider(monkeypatch, [
        {"decision": "include", "confidence": 0.9, "evidence_span": "randomised controlled trial of 100 patients"},
        {
            "study_design": {"value": "RCT", "evidence_span": "a randomised controlled trial of 100 patients"},
            "sample_size": {"value": "100", "evidence_span": "a randomised controlled trial of 100 patients"},
            "country": {"value": "Canada", "evidence_span": "of 100 patients in Canada"},
            "key_finding": {"value": "Treatment X reduced symptom Y by 10 percent.", "evidence_span": "Treatment X reduced symptom Y by 10 percent."},
        },
        {"value": "gap_stated", "evidence_span": "Further studies are needed to confirm this."},
    ])
    run_id = one_paper.run(conn, review="Nelson_2002", work_id="W1", use_cache=False, db_path=":memory:", prompts_dir=__import__("pathlib").Path("prompts"))

    sd = conn.execute("SELECT * FROM screening_decision WHERE run_id=?", (run_id,)).fetchone()
    assert sd["decision"] == "include" and sd["span_verified"]

    ext = conn.execute("SELECT field_name, span_verified FROM extraction WHERE run_id=?", (run_id,)).fetchall()
    assert {e["field_name"] for e in ext} == {"study_design", "sample_size", "country", "key_finding"}
    assert all(e["span_verified"] for e in ext)

    gap = conn.execute("SELECT * FROM gap_statement WHERE run_id=?", (run_id,)).fetchone()
    assert gap["value"] == "gap_stated" and gap["span_verified"]


def test_excluded_record_stops_after_screening(conn, monkeypatch):
    _patch_provider(monkeypatch, [
        {"decision": "exclude", "confidence": 0.8, "evidence_span": "randomised controlled trial of 100 patients"},
    ])
    run_id = one_paper.run(conn, review="Nelson_2002", work_id="W1", use_cache=False, db_path=":memory:", prompts_dir=__import__("pathlib").Path("prompts"))

    assert conn.execute("SELECT COUNT(*) c FROM screening_decision WHERE run_id=?", (run_id,)).fetchone()["c"] == 1
    assert conn.execute("SELECT COUNT(*) c FROM extraction WHERE run_id=?", (run_id,)).fetchone()["c"] == 0
    assert conn.execute("SELECT COUNT(*) c FROM gap_statement WHERE run_id=?", (run_id,)).fetchone()["c"] == 0


def test_unverified_record_stops_after_screening(conn, monkeypatch):
    _patch_provider(monkeypatch, [
        {"decision": "include", "confidence": 0.8, "evidence_span": "a sentence never present in this abstract"},
    ])
    run_id = one_paper.run(conn, review="Nelson_2002", work_id="W1", use_cache=False, db_path=":memory:", prompts_dir=__import__("pathlib").Path("prompts"))

    sd = conn.execute("SELECT * FROM screening_decision WHERE run_id=?", (run_id,)).fetchone()
    assert sd["decision"] == "unverified"
    assert conn.execute("SELECT COUNT(*) c FROM extraction WHERE run_id=?", (run_id,)).fetchone()["c"] == 0


def test_pick_work_id_defaults_to_first_record_in_the_review(conn):
    assert one_paper._pick_work_id(conn, "Nelson_2002", None, pick_random=False) == "W1"


def test_pick_work_id_honours_an_explicit_id(conn):
    assert one_paper._pick_work_id(conn, "Nelson_2002", "W1", pick_random=False) == "W1"


def test_unknown_review_raises_a_clear_error(conn):
    with pytest.raises(SystemExit, match="ingested"):
        one_paper._pick_work_id(conn, "NoSuchReview", None, pick_random=False)
