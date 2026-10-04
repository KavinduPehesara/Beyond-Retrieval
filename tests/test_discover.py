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
    criteria_prompt_version,
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


# --------------------------------------------------------------------------
# Screening against the user's own criteria -- the product path
#
# The point of these is that an ad-hoc question gets the *same* treatment as
# a reported run: the same prompt, the same shape validation, the same span
# verifier, and the same rule that an unverified include is a referral and
# not a yes. What it must never get is a route into the evaluation corpus.
# --------------------------------------------------------------------------


class _ScriptedProvider:
    """Returns a queued payload per call, so one run can mix outcomes."""

    name = "fake"
    model = "fake-1"

    def __init__(self, screen_payloads, extract_payload, gap_payload):
        self.screen_payloads = list(screen_payloads)
        self.extract_payload = extract_payload
        self.gap_payload = gap_payload
        self.prompts = []

    def complete(self, prompt, *, temperature=0.0, max_tokens=512, seed=None, response_schema=None):
        self.prompts.append(prompt)
        if prompt.startswith("screen"):
            payload = self.screen_payloads.pop(0)
        elif prompt.startswith("research gap"):
            payload = self.gap_payload
        else:
            payload = self.extract_payload
        return Completion(text=json.dumps(payload), tokens_in=10, tokens_out=10)


ABSTRACT = (
    "This randomised controlled trial of 240 patients in the United States "
    "found that the intervention reduced symptoms. However, long-term "
    "outcomes were not assessed and remain an important direction for "
    "future research."
)

EXTRACT_PAYLOAD = {
    "study_design": {"value": "randomised controlled trial", "evidence_span": "randomised controlled trial"},
    "sample_size": {"value": "240", "evidence_span": "240 patients in the United States"},
    "country": {"value": "United States", "evidence_span": "patients in the United States found"},
    "key_finding": {"value": "reduced symptoms", "evidence_span": "the intervention reduced symptoms"},
}
GAP_PAYLOAD = {"value": "gap_stated", "evidence_span": "remain an important direction for future research"}


def _candidates(n: int):
    return [
        {
            "work_id": f"https://openalex.org/W{i}",
            "review": DISCOVER_REVIEW,
            "title": f"Paper {i}",
            "abstract": ABSTRACT,
            "year": 2021,
            "source_url": None,
        }
        for i in range(n)
    ]


def _run(conn, provider, *, criteria="Include randomised controlled trials.", n=1):
    return run_discover(
        conn,
        "trial symptoms",
        provider=provider,
        extract_template="extract {title} {abstract}",
        gap_template="research gap {title} {abstract}",
        meter=Meter(ceiling_usd=1.0, usd_per_1m_input=0.0, usd_per_1m_output=0.0),
        use_cache=False,
        candidates=_candidates(n),
        criteria=criteria,
        screen_template="screen {criteria} {title} {abstract}" if criteria else None,
    )


def test_a_verified_include_is_screened_then_extracted(conn):
    provider = _ScriptedProvider(
        [{"decision": "include", "confidence": 0.9, "evidence_span": "randomised controlled trial"}],
        EXTRACT_PAYLOAD,
        GAP_PAYLOAD,
    )
    paper = _run(conn, provider)[0]

    assert paper.decision.decision == "include"
    assert paper.decision.span_verified is True
    assert paper.included is True
    assert paper.fields is not None and len(paper.fields) == 4
    assert paper.gap.value == "gap_stated"


def test_a_screened_out_paper_is_not_extracted(conn):
    """Extraction reads verified includes and nothing else -- the same
    boundary extract_harness keeps on the ingested corpus. Pulling data out
    of a paper the criteria reject would be inventing a result."""
    provider = _ScriptedProvider(
        [{"decision": "exclude", "confidence": 0.9, "evidence_span": "the intervention reduced symptoms"}],
        EXTRACT_PAYLOAD,
        GAP_PAYLOAD,
    )
    paper = _run(conn, provider)[0]

    assert paper.decision.decision == "exclude"
    assert paper.included is False
    assert paper.fields is None
    assert paper.gap is None
    # Only the screening call was made: no extract, no gap.
    assert len([p for p in provider.prompts if p.startswith("screen")]) == 1
    assert not [p for p in provider.prompts if p.startswith("extract")]


def test_an_include_whose_quote_is_invented_is_a_referral_not_a_keep(conn):
    """The whole mechanism, on the product path: a confident include whose
    quote isn't in the abstract must not become an include."""
    provider = _ScriptedProvider(
        [{"decision": "include", "confidence": 0.99, "evidence_span": "a sentence nobody wrote in this abstract"}],
        EXTRACT_PAYLOAD,
        GAP_PAYLOAD,
    )
    paper = _run(conn, provider)[0]

    assert paper.decision.decision == "unverified"
    assert paper.decision.span_verified is False
    assert paper.decision.verify_note == "not_found"
    assert paper.included is False
    assert paper.fields is None, "nothing is extracted from a referral"


def test_the_users_criteria_reach_the_prompt_and_ground_truth_does_not(conn):
    provider = _ScriptedProvider(
        [{"decision": "include", "confidence": 0.9, "evidence_span": "randomised controlled trial"}],
        EXTRACT_PAYLOAD,
        GAP_PAYLOAD,
    )
    _run(conn, provider, criteria="Only double-blind trials in adults.")

    screen_prompt = next(p for p in provider.prompts if p.startswith("screen"))
    assert "Only double-blind trials in adults." in screen_prompt
    assert "label_included" not in screen_prompt


def test_without_criteria_nothing_is_screened(conn):
    """No criteria, no decision. The system does not guess an include."""
    provider = _ScriptedProvider([], EXTRACT_PAYLOAD, GAP_PAYLOAD)
    paper = _run(conn, provider, criteria=None)[0]

    assert paper.decision is None
    assert paper.included is False
    assert paper.fields is not None, "still extracted, just not screened"
    assert not [p for p in provider.prompts if p.startswith("screen")]


def test_criteria_and_template_must_be_given_together(conn):
    provider = _ScriptedProvider([], EXTRACT_PAYLOAD, GAP_PAYLOAD)
    with pytest.raises(ValueError, match="together"):
        run_discover(
            conn, "q", provider=provider,
            extract_template="extract {title} {abstract}",
            gap_template="research gap {title} {abstract}",
            meter=Meter(ceiling_usd=1.0, usd_per_1m_input=0.0, usd_per_1m_output=0.0),
            candidates=_candidates(1), criteria="Include trials.", screen_template=None,
        )


def test_blank_criteria_is_rejected_rather_than_screened_against_nothing(conn):
    provider = _ScriptedProvider([], EXTRACT_PAYLOAD, GAP_PAYLOAD)
    with pytest.raises(ValueError, match="must not be empty"):
        _run(conn, provider, criteria="   ")


def test_screening_ad_hoc_records_never_reaches_the_evaluation_corpus(conn):
    """The guard that matters most.

    An ad-hoc session must leave no trace that any reported figure could
    pick up: nothing in `work`, and nothing in `screening_decision` under a
    real review name. `run_discover` doesn't persist at all, and this test
    is what keeps it that way if someone later adds a persist() call.
    """
    provider = _ScriptedProvider(
        [
            {"decision": "include", "confidence": 0.9, "evidence_span": "randomised controlled trial"},
            {"decision": "exclude", "confidence": 0.8, "evidence_span": "the intervention reduced symptoms"},
        ],
        EXTRACT_PAYLOAD,
        GAP_PAYLOAD,
    )
    results = _run(conn, provider, n=2)
    assert len(results) == 2

    assert conn.execute("SELECT COUNT(*) AS n FROM work").fetchone()["n"] == 0
    assert conn.execute("SELECT COUNT(*) AS n FROM screening_decision").fetchone()["n"] == 0
    assert conn.execute("SELECT COUNT(*) AS n FROM extraction").fetchone()["n"] == 0
    assert conn.execute("SELECT COUNT(*) AS n FROM gap_statement").fetchone()["n"] == 0
    # And the review name it carries is not one config.py would accept, so
    # a config could not point a reported run at it even by mistake.
    from slr.config import SUBSET

    assert DISCOVER_REVIEW not in SUBSET


def test_criteria_get_their_own_cache_namespace(conn):
    """Two different criteria for the same paper must not collide on one
    cache key -- that would make the request fingerprint raise
    CacheMismatch and abort a query the user did nothing wrong in."""
    base = criteria_prompt_version("screen_v1", "Include randomised trials.")
    same = criteria_prompt_version("screen_v1", "  Include randomised trials.  ")
    other = criteria_prompt_version("screen_v1", "Include cohort studies.")

    assert base == same, "whitespace alone is not a different question"
    assert base != other
    assert base.startswith("screen_v1+adhoc-")


def test_the_same_criteria_twice_is_served_from_cache(conn):
    """The cache is still checked before every call. Re-running an identical
    session is free, exactly as the budget rules require -- the namespacing
    above does not bypass caching, it only separates genuinely different
    requests."""
    payload = {"decision": "include", "confidence": 0.9, "evidence_span": "randomised controlled trial"}
    first = _ScriptedProvider([payload], EXTRACT_PAYLOAD, GAP_PAYLOAD)
    run = lambda provider: run_discover(  # noqa: E731
        conn, "q", provider=provider,
        extract_template="extract {title} {abstract}",
        gap_template="research gap {title} {abstract}",
        meter=Meter(ceiling_usd=1.0, usd_per_1m_input=0.0, usd_per_1m_output=0.0),
        use_cache=True, candidates=_candidates(1),
        criteria="Include randomised trials.",
        screen_template="screen {criteria} {title} {abstract}",
    )
    assert run(first)[0].decision.from_cache is False

    # A provider with nothing queued: if the cache misses, this raises.
    second = _ScriptedProvider([], EXTRACT_PAYLOAD, GAP_PAYLOAD)
    paper = run(second)[0]
    assert paper.decision.from_cache is True
    assert not [p for p in second.prompts if p.startswith("screen")]
