"""Tests for open-web paper discovery: OpenAlex search plus this project's
own verified extraction/gap pipeline over whatever comes back. No real
network calls -- OpenAlex is mocked with httpx.MockTransport.
"""

from __future__ import annotations

import json

import httpx
import pytest

from slr.adapters.llm import Completion, Meter
from slr.db import connect
from slr.services.discover import (
    DISCOVER_REVIEW,
    reconstruct_abstract,
    run_discover,
    search_openalex,
)


def test_reconstruct_abstract_from_inverted_index():
    # "the cat sat" -> {"the": [0], "cat": [1], "sat": [2]}
    inverted = {"the": [0], "cat": [1], "sat": [2]}
    assert reconstruct_abstract(inverted) == "the cat sat"


def test_reconstruct_abstract_handles_repeated_words():
    # "the cat and the dog" -> "the" appears at positions 0 and 3
    inverted = {"the": [0, 3], "cat": [1], "and": [2], "dog": [4]}
    assert reconstruct_abstract(inverted) == "the cat and the dog"


def test_reconstruct_abstract_of_none_is_none():
    assert reconstruct_abstract(None) is None
    assert reconstruct_abstract({}) is None


def _openalex_payload(n_with_abstract: int, n_without: int):
    results = []
    long_abstract = {f"word{i}": [i] for i in range(60)}  # ~360 chars, well over MIN_ABSTRACT_CHARS
    for i in range(n_with_abstract):
        results.append(
            {
                "id": f"https://openalex.org/W{i}",
                "title": f"Paper {i}",
                "abstract_inverted_index": long_abstract,
                "publication_year": 2020,
                "primary_location": {"landing_page_url": f"https://doi.org/10.1/{i}"},
            }
        )
    for i in range(n_without):
        results.append(
            {
                "id": f"https://openalex.org/Wno{i}",
                "title": f"No abstract {i}",
                "abstract_inverted_index": None,
                "publication_year": 2020,
                "primary_location": None,
            }
        )
    return {"results": results}


def test_search_openalex_filters_records_with_no_abstract():
    payload = _openalex_payload(n_with_abstract=2, n_without=3)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    results = search_openalex("fault prediction", limit=5, client=client)

    assert len(results) == 2
    assert all(r["abstract"] for r in results)
    assert all(r["review"] == DISCOVER_REVIEW for r in results)
    assert results[0]["work_id"] == "https://openalex.org/W0"


def test_search_openalex_stops_at_limit():
    payload = _openalex_payload(n_with_abstract=10, n_without=0)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    results = search_openalex("anything", limit=3, client=client)

    assert len(results) == 3


def test_search_openalex_rejects_an_empty_query():
    with pytest.raises(ValueError):
        search_openalex("   ")


class _FakeProvider:
    name = "fake"
    model = "fake-1"

    def __init__(self, extract_payload: dict, gap_payload: dict):
        self.extract_payload = extract_payload
        self.gap_payload = gap_payload

    def complete(self, prompt, *, temperature=0.0, max_tokens=512, seed=None, response_schema=None):
        # extract_v1's schema has 4 top-level fields; gap_v1's has one ("value").
        payload = self.gap_payload if "gap_stated" in prompt or "research gap" in prompt.lower() else self.extract_payload
        return Completion(text=json.dumps(payload), tokens_in=10, tokens_out=10)


@pytest.fixture()
def conn(tmp_path):
    c = connect(tmp_path / "test.db")
    yield c
    c.close()


def test_run_discover_extracts_and_checks_gaps_without_touching_the_work_table(conn):
    abstract = (
        "This randomised controlled trial of 240 patients in the United "
        "States found that the intervention reduced symptoms. However, "
        "long-term outcomes were not assessed and remain an important "
        "direction for future research."
    )
    candidates = [
        {
            "work_id": "https://openalex.org/W999",
            "review": DISCOVER_REVIEW,
            "title": "A trial of something",
            "abstract": abstract,
            "year": 2021,
            "source_url": "https://doi.org/10.1/999",
        }
    ]
    provider = _FakeProvider(
        extract_payload={
            "study_design": {"value": "randomised controlled trial", "evidence_span": "randomised controlled trial"},
            "sample_size": {"value": "240", "evidence_span": "240 patients in the United States"},
            "country": {"value": "United States", "evidence_span": "patients in the United States found"},
            "key_finding": {"value": "reduced symptoms", "evidence_span": "the intervention reduced symptoms"},
        },
        gap_payload={"value": "gap_stated", "evidence_span": "remain an important direction for future research"},
    )
    meter = Meter(ceiling_usd=1.0, usd_per_1m_input=0.0, usd_per_1m_output=0.0)

    results = run_discover(
        conn,
        "trial symptoms",
        provider=provider,
        extract_template="extract {title} {abstract}",
        gap_template="research gap {title} {abstract}",
        meter=meter,
        use_cache=False,
        candidates=candidates,
    )

    assert len(results) == 1
    paper = results[0]
    assert paper.work_id == "https://openalex.org/W999"
    assert len(paper.fields) == 4
    assert all(f.span_verified for f in paper.fields)
    assert paper.gap.value == "gap_stated"
    assert paper.gap.span_verified is True

    # Never written to the ingested corpus -- "_discover" is not a real review.
    assert conn.execute("SELECT COUNT(*) AS n FROM work WHERE review = ?", (DISCOVER_REVIEW,)).fetchone()["n"] == 0
