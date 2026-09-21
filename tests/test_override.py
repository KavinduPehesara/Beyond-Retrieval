"""Tests for the human-override mechanism (RQ1, overridable).

The system proposes (screening_decision), the reviewer disposes
(human_decision). These tests cover: an override can't be recorded without a
system proposal to override; a confirmed decision and a changed decision are
both recorded and distinguished; override_summary reflects both correctly.
"""

from __future__ import annotations

import pytest

from slr.db import connect
from slr.services.override import (
    ModelDecision,
    model_decision,
    override_summary,
    record_override,
)


@pytest.fixture()
def conn(tmp_path):
    c = connect(tmp_path / "test.db")
    c.execute(
        "INSERT INTO run (run_id, config_hash, config_name) VALUES ('R1', 'h', 'test')"
    )
    c.execute(
        "INSERT INTO work (work_id, review, title, abstract, label_included) "
        "VALUES ('W1', 'Nelson_2002', 't', 'a', 1)"
    )
    c.execute(
        "INSERT INTO work (work_id, review, title, abstract, label_included) "
        "VALUES ('W2', 'Nelson_2002', 't', 'a', 0)"
    )
    c.execute(
        "INSERT INTO screening_decision "
        "(run_id, review, work_id, decision, confidence, span_verified, verify_note) "
        "VALUES ('R1', 'Nelson_2002', 'W1', 'unverified', NULL, 0, 'not_found')"
    )
    c.execute(
        "INSERT INTO screening_decision "
        "(run_id, review, work_id, decision, confidence, span_verified, verify_note) "
        "VALUES ('R1', 'Nelson_2002', 'W2', 'exclude', 0.9, 1, 'ok')"
    )
    c.commit()
    yield c
    c.close()


def test_model_decision_reads_the_system_proposal(conn):
    before = model_decision(conn, "R1", "Nelson_2002", "W2")
    assert before == ModelDecision("exclude", 0.9, True)


def test_model_decision_is_none_for_an_unscreened_record(conn):
    assert model_decision(conn, "R1", "Nelson_2002", "W999") is None


def test_override_requires_a_system_proposal(conn):
    with pytest.raises(ValueError, match="nothing to override"):
        record_override(conn, run_id="R1", review="Nelson_2002", work_id="W999", decision="include")


def test_override_rejects_an_unknown_decision(conn):
    with pytest.raises(ValueError, match="include.*exclude"):
        record_override(conn, run_id="R1", review="Nelson_2002", work_id="W1", decision="maybe")


def test_disposing_a_referral_is_recorded(conn):
    # W1 was unverified -- a referral, not a prediction. The human disposes it.
    record_override(conn, run_id="R1", review="Nelson_2002", work_id="W1", decision="include", rationale="clear RCT")
    row = conn.execute(
        "SELECT decision, rationale FROM human_decision WHERE run_id='R1' AND work_id='W1'"
    ).fetchone()
    assert row["decision"] == "include"
    assert row["rationale"] == "clear RCT"


def test_confirming_a_verified_decision_is_not_a_change(conn):
    record_override(conn, run_id="R1", review="Nelson_2002", work_id="W2", decision="exclude")
    summary = override_summary(conn, "R1", "Nelson_2002")
    assert summary.n_overrides == 1
    assert summary.n_confirmed == 1
    assert summary.n_changed == 0
    assert summary.override_rate == 0.0


def test_overturning_a_verified_decision_is_a_change(conn):
    record_override(conn, run_id="R1", review="Nelson_2002", work_id="W2", decision="include")
    summary = override_summary(conn, "R1", "Nelson_2002")
    assert summary.n_changed == 1
    assert summary.override_rate == 1.0


def test_override_summary_breaks_down_by_the_original_system_decision(conn):
    record_override(conn, run_id="R1", review="Nelson_2002", work_id="W1", decision="include")
    record_override(conn, run_id="R1", review="Nelson_2002", work_id="W2", decision="exclude")
    summary = override_summary(conn, "R1", "Nelson_2002")
    assert summary.by_model_decision == {"unverified": 1, "exclude": 1}


def test_override_summary_with_no_overrides_recorded(conn):
    summary = override_summary(conn, "R1", "Nelson_2002")
    assert summary.n_overrides == 0
    assert summary.override_rate is None


def test_recording_an_override_twice_replaces_it(conn):
    record_override(conn, run_id="R1", review="Nelson_2002", work_id="W1", decision="exclude")
    record_override(conn, run_id="R1", review="Nelson_2002", work_id="W1", decision="include")
    row = conn.execute(
        "SELECT decision FROM human_decision WHERE run_id='R1' AND work_id='W1'"
    ).fetchone()
    assert row["decision"] == "include"
