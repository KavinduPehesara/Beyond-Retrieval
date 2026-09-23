"""Tests for gap-statement discovery — extraction's sibling for one field.

Covers the same boundary screening's and extraction's tests do: a claimed
gap is only reported if its quote is verified, and "not_stated" is not
scored as a failed attempt.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from slr.adapters.llm import Completion, Meter
from slr.db import connect
from slr.services.gap import GapResponse, build_gap_prompt, extract_gap


@pytest.fixture()
def conn(tmp_path):
    c = connect(tmp_path / "test.db")
    c.execute(
        "INSERT INTO work (work_id, review, title, abstract, label_included) "
        "VALUES (?,?,?,?,?)",
        (
            "W1",
            "Nelson_2002",
            "Hormone therapy in postmenopausal women",
            "We conducted a randomised controlled trial of 240 postmenopausal "
            "women. Long-term cardiovascular outcomes were not assessed and "
            "remain an important direction for future research.",
            1,
        ),
    )
    c.commit()
    yield c
    c.close()


class _FakeProvider:
    """Returns a canned payload, ignoring the prompt — deterministic by design."""

    name = "fake"
    model = "fake-1"

    def __init__(self, payload: dict):
        self.payload = payload

    def complete(self, prompt, *, temperature=0.0, max_tokens=512, seed=None, response_schema=None):
        return Completion(text=json.dumps(self.payload), tokens_in=10, tokens_out=10)


def _run(conn, provider, use_cache=False):
    row = conn.execute("SELECT * FROM work WHERE work_id = 'W1'").fetchone()
    meter = Meter(ceiling_usd=1.0, usd_per_1m_input=0.0, usd_per_1m_output=0.0)
    return extract_gap(
        row, provider=provider, template=Path("prompts/gap_v1.txt").read_text(encoding="utf-8"),
        meter=meter, conn=conn, prompt_version="gap_v1",
        temperature=0.0, max_tokens=512, seed=42, use_cache=use_cache,
    )


def test_prompt_template_has_what_gap_discovery_needs():
    text = Path("prompts/gap_v1.txt").read_text(encoding="utf-8")
    for field in ("{title}", "{abstract}"):
        assert field in text
    assert "not_stated" in text
    assert "gap_stated" in text


def test_gap_response_rejects_malformed():
    with pytest.raises(ValidationError):
        GapResponse.model_validate({"value": "gap_stated"})  # missing evidence_span


def test_verified_gap_statement_is_reported(conn):
    provider = _FakeProvider({
        "value": "gap_stated",
        "evidence_span": "remain an important direction for future research",
    })
    result = _run(conn, provider)
    assert result.value == "gap_stated"
    assert result.span_verified is True
    assert result.verify_note == "exact_after_normalisation"


def test_fabricated_gap_span_is_not_reported(conn):
    provider = _FakeProvider({
        "value": "gap_stated",
        "evidence_span": "a sentence never present in this abstract",
    })
    result = _run(conn, provider)
    assert result.span_verified is False
    assert result.value is None  # not reported as a fact
    assert result.verify_note == "not_found"


def test_not_stated_is_distinct_from_a_failed_verification(conn):
    provider = _FakeProvider({"value": "not_stated", "evidence_span": ""})
    result = _run(conn, provider)
    assert result.span_verified is False
    assert result.verify_note == "not_stated"
    assert result.value == "not_stated"  # distinct from a failed attempt


def test_schema_validation_failure_is_recorded_not_raised(conn):
    provider = _FakeProvider({"value": "gap_stated"})  # missing evidence_span
    result = _run(conn, provider)
    assert result.verify_note == "schema_validation_failed"
    assert result.value is None


def test_ground_truth_never_reaches_the_gap_prompt(conn):
    row = conn.execute("SELECT * FROM work WHERE work_id = 'W1'").fetchone()
    template = Path("prompts/gap_v1.txt").read_text(encoding="utf-8")
    prompt = build_gap_prompt(template, title=row["title"], abstract=row["abstract"])
    assert "label_included" not in prompt
