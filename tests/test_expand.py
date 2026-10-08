"""Tests for query expansion.

This is the one model stage with no span to verify, so the tests carry more
of the weight: what the filter accepts, that a failure never blocks a
search, and that the cache behaves exactly as it does everywhere else.
"""

from __future__ import annotations

import json

import pytest

import pandas as pd

from slr.adapters.llm import CacheMismatch, Completion, Meter
from slr.db import connect
from slr.eval.expansion_eval import rank_with
from slr.services import expand
from slr.services.ingest import ingest_frame

QUESTION = "Include randomised controlled trials of vitamin D supplementation reporting mortality."


@pytest.fixture()
def conn(tmp_path):
    c = connect(tmp_path / "expand.db")
    yield c
    c.close()


class _Provider:
    """Returns whatever JSON it was given, and counts calls."""

    name, model = "fake", "fake-1"

    def __init__(self, payload="{}", fail=False):
        self.payload = payload
        self.fail = fail
        self.calls = 0

    def complete(self, prompt, *, temperature=0.0, max_tokens=512, seed=None, response_schema=None):
        self.calls += 1
        if self.fail:
            raise RuntimeError("model is down")
        return Completion(text=self.payload, tokens_in=10, tokens_out=5)


def _meter():
    return Meter(ceiling_usd=1.0, usd_per_1m_input=0.0, usd_per_1m_output=0.0)


def _expand(conn, provider, *, template="Q: {question}", **kwargs):
    return expand.expand_query(
        QUESTION, provider=provider, template=template, meter=_meter(), conn=conn, **kwargs
    )


# --------------------------------------------------------------------------
# Which terms survive
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "term, why",
    [
        ('"deep learning" AND trials', "search syntax, not vocabulary"),
        ("vitamin D", "every word already in the question"),
        ("a phrase that runs on well past six words in total", "longer than a phrase"),
        ("   ", "empty"),
    ],
)
def test_terms_that_are_not_worth_searching_are_dropped(term, why):
    assert expand.accept_terms(QUESTION, [term]) == [], why


def test_useful_terms_are_kept_in_order():
    terms = ["cholecalciferol", "all-cause death", "placebo-controlled"]
    assert expand.accept_terms(QUESTION, terms) == terms


def test_duplicates_are_dropped_case_insensitively():
    assert expand.accept_terms(QUESTION, ["Cholecalciferol", "cholecalciferol"]) == ["Cholecalciferol"]


def test_term_count_is_capped():
    assert len(expand.accept_terms(QUESTION, [f"term{i}" for i in range(20)])) == expand.MAX_TERMS


def test_the_question_leads_the_query():
    query = expand.expanded_query("vitamin D and mortality", ["cholecalciferol"])
    assert query == "vitamin D and mortality cholecalciferol"
    assert expand.expanded_query("vitamin D", []) == "vitamin D"


def test_question_key_ignores_spacing_and_case():
    assert expand.question_key("Vitamin  D") == expand.question_key("vitamin d")
    assert expand.question_key("vitamin d") != expand.question_key("vitamin e")


# --------------------------------------------------------------------------
# Failure never blocks a search
# --------------------------------------------------------------------------


def test_provider_failure_returns_the_original_question(conn):
    result = _expand(conn, _Provider(fail=True))
    assert result.query == QUESTION.strip()
    assert result.terms == [] and not result.expanded
    assert result.note == "provider_error"


def test_malformed_response_returns_the_original_question(conn):
    result = _expand(conn, _Provider(payload="not json"))
    assert result.query == QUESTION.strip()
    assert result.note == "schema_validation_failed"


def test_an_empty_term_list_is_recorded_as_such(conn):
    result = _expand(conn, _Provider(payload=json.dumps({"terms": []})))
    assert result.note == "no_terms"
    assert result.query == QUESTION.strip()


def test_an_empty_question_is_refused(conn):
    with pytest.raises(ValueError):
        expand.expand_query("   ", provider=_Provider(), template="{question}", meter=_meter(), conn=conn)


# --------------------------------------------------------------------------
# Cache, same contract as every other service
# --------------------------------------------------------------------------


def test_the_same_question_is_asked_once(conn):
    provider = _Provider(payload=json.dumps({"terms": ["cholecalciferol"]}))
    first = _expand(conn, provider)
    second = _expand(conn, provider)
    assert provider.calls == 1
    assert not first.from_cache and second.from_cache
    assert first.terms == second.terms == ["cholecalciferol"]


def test_a_changed_prompt_under_the_same_version_is_refused(conn):
    provider = _Provider(payload=json.dumps({"terms": ["cholecalciferol"]}))
    _expand(conn, provider)
    with pytest.raises(CacheMismatch):
        _expand(conn, provider, template="Different prompt: {question}")


# --------------------------------------------------------------------------
# The measurement
# --------------------------------------------------------------------------


def test_extra_terms_can_lift_a_known_include_up_the_ranking(conn):
    """The measurement, end to end, on a corpus whose answer is known.

    The included paper never uses the question's words; it uses the
    synonym. Unexpanded BM25 cannot see it, so it sits below the noise.
    """
    ingest_frame(
        conn,
        "Nelson_2002",
        pd.DataFrame(
            {
                # The include sorts last, so an unexpanded query that matches
                # nothing leaves it at the bottom of the fallback order
                # rather than at the top by alphabetical accident.
                "openalex_id": ["z_hit"] + [f"a_miss{i}" for i in range(8)],
                "title": ["Cholecalciferol intake and all-cause death"]
                + [f"Hormone therapy trial {i}" for i in range(8)],
                "abstract": ["Cholecalciferol intake and all-cause death among older adults."]
                + [f"Hormone therapy and mortality outcomes, cohort {i}." for i in range(8)],
                "label_included": [1] + [0] * 8,
            }
        ),
    )
    labels = {"z_hit": 1, **{f"a_miss{i}": 0 for i in range(8)}}
    # Not one of these words appears in the included paper, which is the
    # whole point: the question and the paper use different vocabularies.
    question = "vitamin mortality"

    plain = rank_with(conn, "Nelson_2002", question, labels, recall_target=0.95)
    expanded = rank_with(
        conn,
        "Nelson_2002",
        expand.expanded_query(question, ["cholecalciferol", "all-cause death"]),
        labels,
        recall_target=0.95,
    )
    assert expanded["cutoff"] < plain["cutoff"]
    assert expanded["tnr_at_recall"] > plain["tnr_at_recall"]
