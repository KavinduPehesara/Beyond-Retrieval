"""Tests for structured data extraction — screening's sibling.

Covers the same boundary screening's tests do: a field is only reported if
its quote is verified, and "not_stated" is not scored as a failed attempt.
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from slr.adapters.llm import Completion, Meter
from slr.db import connect
from slr.services.extract import (
    FIELDS,
    ExtractionResponse,
    build_extract_prompt,
    extract_record,
)


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
            "women in Denmark. Hormone therapy reduced fracture risk by 30%.",
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


def _field(value: str, span: str) -> dict:
    return {"value": value, "evidence_span": span}


VALID_PAYLOAD = {
    "study_design": _field("randomised controlled trial", "a randomised controlled trial of 240"),
    "sample_size": _field("240", "randomised controlled trial of 240 postmenopausal"),
    "country": _field("Denmark", "postmenopausal women in Denmark"),
    "key_finding": _field("Hormone therapy reduced fracture risk by 30%.", "Hormone therapy reduced fracture risk by 30%."),
}


def test_prompt_template_has_the_fields_extraction_needs():
    from pathlib import Path

    text = Path("prompts/extract_v1.txt").read_text(encoding="utf-8")
    for field in ("{title}", "{abstract}"):
        assert field in text
    assert "not_stated" in text


def test_extraction_response_rejects_malformed():
    with pytest.raises(ValidationError):
        ExtractionResponse.model_validate({"study_design": "not an object"})


def test_verified_field_is_reported(conn):
    row = conn.execute("SELECT * FROM work WHERE work_id = 'W1'").fetchone()
    provider = _FakeProvider(VALID_PAYLOAD)
    meter = Meter(ceiling_usd=1.0, usd_per_1m_input=0.0, usd_per_1m_output=0.0)

    results = extract_record(
        row, provider=provider, template=open("prompts/extract_v1.txt", encoding="utf-8").read(),
        meter=meter, conn=conn, prompt_version="extract_v1",
        temperature=0.0, max_tokens=512, seed=42, use_cache=False,
    )

    by_field = {r.field_name: r for r in results}
    assert set(by_field) == set(FIELDS)
    assert by_field["country"].span_verified is True
    assert by_field["country"].value == "Denmark"
    assert by_field["country"].verify_note == "exact_after_normalisation"


def test_fabricated_span_is_not_reported(conn):
    row = conn.execute("SELECT * FROM work WHERE work_id = 'W1'").fetchone()
    payload = dict(VALID_PAYLOAD)
    payload["country"] = _field("France", "a country never mentioned in this abstract")
    provider = _FakeProvider(payload)
    meter = Meter(ceiling_usd=1.0, usd_per_1m_input=0.0, usd_per_1m_output=0.0)

    results = extract_record(
        row, provider=provider, template=open("prompts/extract_v1.txt", encoding="utf-8").read(),
        meter=meter, conn=conn, prompt_version="extract_v1",
        temperature=0.0, max_tokens=512, seed=42, use_cache=False,
    )

    country = next(r for r in results if r.field_name == "country")
    assert country.span_verified is False
    assert country.value is None  # not reported as a fact
    assert country.verify_note == "not_found"


def test_not_stated_is_distinct_from_a_failed_verification(conn):
    row = conn.execute("SELECT * FROM work WHERE work_id = 'W1'").fetchone()
    payload = dict(VALID_PAYLOAD)
    payload["sample_size"] = _field("not_stated", "")
    provider = _FakeProvider(payload)
    meter = Meter(ceiling_usd=1.0, usd_per_1m_input=0.0, usd_per_1m_output=0.0)

    results = extract_record(
        row, provider=provider, template=open("prompts/extract_v1.txt", encoding="utf-8").read(),
        meter=meter, conn=conn, prompt_version="extract_v1",
        temperature=0.0, max_tokens=512, seed=42, use_cache=False,
    )

    sample_size = next(r for r in results if r.field_name == "sample_size")
    assert sample_size.span_verified is False
    assert sample_size.verify_note == "not_stated"
    assert sample_size.value == "not_stated"  # distinct from a failed attempt


def test_ground_truth_never_reaches_the_extraction_prompt(conn):
    row = conn.execute("SELECT * FROM work WHERE work_id = 'W1'").fetchone()
    template = open("prompts/extract_v1.txt", encoding="utf-8").read()
    prompt = build_extract_prompt(template, title=row["title"], abstract=row["abstract"])
    assert "label_included" not in prompt
