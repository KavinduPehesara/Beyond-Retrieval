"""Tests for the rest of the walking skeleton.

Covers the boundaries that would silently corrupt results if they broke:
ground truth staying out of prompts, the budget ceiling actually aborting,
and the cache returning what it stored.
"""

from __future__ import annotations

import sqlite3

import pytest

from slr.adapters.llm import (
    BudgetExceeded,
    CacheMismatch,
    Completion,
    Meter,
    MockProvider,
    OllamaProvider,
    build_provider,
    cache_key,
)
from slr.config import SUBSET, Config, DatasetConfig
from slr.db import connect
from slr.services.screen import ScreeningResponse, build_prompt, screen_record
from slr.services.verify import verify_span


@pytest.fixture()
def conn(tmp_path):
    c = connect(tmp_path / "test.db")
    c.execute(
        "INSERT INTO work (work_id, review, title, abstract, label_included) "
        "VALUES (?,?,?,?,?)",
        (
            "W1",
            "Smid_2020",
            "Bayesian estimation in small samples",
            "We compared maximum likelihood and Bayesian estimation across "
            "sample sizes. Bayesian methods showed less bias at n below fifty.",
            1,
        ),
    )
    c.commit()
    yield c
    c.close()


# --------------------------------------------------------------------------
# The boundary that makes accuracy figures mean anything
# --------------------------------------------------------------------------


def test_ground_truth_never_reaches_the_prompt(conn):
    """Rule 4. If this test fails, every accuracy figure is worthless."""
    row = conn.execute("SELECT * FROM work WHERE work_id = 'W1'").fetchone()
    template = "CRITERIA:\n{criteria}\n\nTITLE:\n{title}\n\nABSTRACT:\n{abstract}\n"
    prompt = build_prompt(
        template, criteria="Include methodological studies.",
        title=row["title"], abstract=row["abstract"],
    )
    assert "label_included" not in prompt
    assert "label" not in prompt.lower().replace("labelled", "")


def test_prompt_template_has_the_fields_screening_needs():
    from pathlib import Path

    text = Path("prompts/screen_v1.txt").read_text(encoding="utf-8")
    for field in ("{criteria}", "{title}", "{abstract}"):
        assert field in text
    assert "ABSTRACT:" in text  # the mock provider keys off this marker


# --------------------------------------------------------------------------
# Budget
# --------------------------------------------------------------------------


def test_meter_computes_cost():
    m = Meter(ceiling_usd=10.0, usd_per_1m_input=0.15, usd_per_1m_output=0.60)
    m.record(Completion(text="{}", tokens_in=1_000_000, tokens_out=1_000_000))
    assert m.spend_usd == pytest.approx(0.75)


def test_budget_ceiling_aborts_rather_than_warning():
    m = Meter(ceiling_usd=0.10, usd_per_1m_input=0.15, usd_per_1m_output=0.60)
    with pytest.raises(BudgetExceeded):
        for _ in range(10):
            m.record(Completion(text="{}", tokens_in=500_000, tokens_out=100_000))


def test_cached_calls_are_free():
    m = Meter(ceiling_usd=0.01, usd_per_1m_input=0.15, usd_per_1m_output=0.60)
    for _ in range(1000):
        m.record(Completion(text="{}", tokens_in=999_999, tokens_out=999_999, from_cache=True))
    assert m.spend_usd == 0.0
    assert m.cached_calls == 1000


# --------------------------------------------------------------------------
# Cache
# --------------------------------------------------------------------------


def test_cache_key_depends_on_model_prompt_and_record():
    base = cache_key("m1", "v1", "Smid_2020", "W1")
    assert base != cache_key("m2", "v1", "Smid_2020", "W1")
    assert base != cache_key("m1", "v2", "Smid_2020", "W1")
    assert base != cache_key("m1", "v1", "Smid_2020", "W2")
    assert base != cache_key("m1", "v1", "Menon_2022", "W1")  # same paper, other review
    assert base == cache_key("m1", "v1", "Smid_2020", "W1")


def _screen_kwargs(conn, **overrides):
    kwargs = dict(
        provider=MockProvider(),
        template="CRITERIA:\n{criteria}\n\nTITLE:\n{title}\n\nABSTRACT:\n{abstract}\n",
        criteria="Include methodological studies.",
        meter=Meter(ceiling_usd=1.0, usd_per_1m_input=0.15, usd_per_1m_output=0.60),
        conn=conn,
        prompt_version="v1",
        temperature=0.0,
        max_tokens=256,
        seed=42,
    )
    kwargs.update(overrides)
    return kwargs


@pytest.mark.parametrize(
    "change",
    [
        {"criteria": "Include only randomised trials."},  # criteria replaced
        {"template": "{criteria}\n{title}\nABSTRACT:\n{abstract}"},  # template edited
        {"temperature": 0.7},
        {"max_tokens": 1024},
        {"seed": 7},
    ],
)
def test_changed_request_under_same_prompt_version_is_refused(conn, change):
    """Swapping in the published criteria must not be served stale answers."""
    row = conn.execute("SELECT * FROM work WHERE work_id = 'W1'").fetchone()
    screen_record(row, **_screen_kwargs(conn))
    with pytest.raises(CacheMismatch):
        screen_record(row, **_screen_kwargs(conn, **change))


def test_changed_request_under_new_prompt_version_is_screened_afresh(conn):
    row = conn.execute("SELECT * FROM work WHERE work_id = 'W1'").fetchone()
    screen_record(row, **_screen_kwargs(conn))
    d = screen_record(row, **_screen_kwargs(conn, criteria="Other.", prompt_version="v2"))
    assert not d.from_cache


def test_second_screening_hits_the_cache(conn):
    row = conn.execute("SELECT * FROM work WHERE work_id = 'W1'").fetchone()
    template = "CRITERIA:\n{criteria}\n\nTITLE:\n{title}\n\nABSTRACT:\n{abstract}\n"
    provider = MockProvider()
    meter = Meter(ceiling_usd=1.0, usd_per_1m_input=0.15, usd_per_1m_output=0.60)

    kwargs = dict(
        provider=provider, template=template, criteria="Include everything.",
        meter=meter, conn=conn, prompt_version="v1", temperature=0.0,
        max_tokens=256,
    )
    first = screen_record(row, **kwargs)
    second = screen_record(row, **kwargs)

    assert not first.from_cache
    assert second.from_cache
    assert second.cost_usd == 0.0
    assert first.evidence_span == second.evidence_span


# --------------------------------------------------------------------------
# Schema validation
# --------------------------------------------------------------------------


def test_valid_response_parses():
    r = ScreeningResponse.model_validate_json(
        '{"decision":"include","confidence":0.9,"evidence_span":"some text here"}'
    )
    assert r.decision == "include"


@pytest.mark.parametrize(
    "payload",
    [
        '{"decision":"maybe","confidence":0.9,"evidence_span":"x"}',   # bad enum
        '{"decision":"include","confidence":1.7,"evidence_span":"x"}',  # out of range
        '{"decision":"include","confidence":0.9}',                      # missing field
        "not json at all",
        "Here is my answer: {\"decision\":\"include\"}",                # prose wrapper
    ],
)
def test_malformed_responses_are_rejected(payload):
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ScreeningResponse.model_validate_json(payload)


def test_unverified_decision_is_not_reported_as_a_prediction(conn):
    """An unverified span must not surface as include/exclude."""
    row = conn.execute("SELECT * FROM work WHERE work_id = 'W1'").fetchone()

    class Fabricator:
        name, model = "fab", "fab-1"

        def complete(self, prompt, *, temperature=0.0, max_tokens=512, seed=None):
            return Completion(
                text='{"decision":"include","confidence":0.99,'
                     '"evidence_span":"This sentence is nowhere in the abstract at all."}',
                tokens_in=10, tokens_out=10,
            )

    d = screen_record(
        row, provider=Fabricator(), template="{criteria}{title}{abstract}",
        criteria="c", meter=Meter(1.0, 0.15, 0.60), conn=conn,
        prompt_version="v1", temperature=0.0, max_tokens=256, use_cache=False,
    )
    assert d.decision == "unverified"
    assert not d.span_verified


# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------


def test_config_rejects_reviews_outside_the_subset():
    with pytest.raises(ValueError):
        DatasetConfig(reviews=["Walker_2018"])  # real SYNERGY review, not in our six


def test_subset_matches_the_proposal():
    assert len(SUBSET) == 6
    assert sum(v[1] for v in SUBSET.values()) == 12598
    assert sum(v[2] for v in SUBSET.values()) == 351


def test_config_hash_is_stable_and_sensitive(tmp_path):
    from slr.config import load_config

    p = tmp_path / "c.yaml"
    p.write_text("name: t\ndataset:\n  reviews: [Smid_2020]\n", encoding="utf-8")
    a = load_config(p).config_hash
    b = load_config(p).config_hash
    assert a == b

    p.write_text("name: t\ndataset:\n  reviews: [Menon_2022]\n", encoding="utf-8")
    assert load_config(p).config_hash != a


# --------------------------------------------------------------------------
# Providers
# --------------------------------------------------------------------------


def test_build_provider_dispatches_ollama():
    provider = build_provider("ollama", "qwen2.5:7b-instruct")
    assert isinstance(provider, OllamaProvider)
    assert provider.name == "ollama"
    assert provider.model == "qwen2.5:7b-instruct"


def test_build_provider_rejects_unknown_name():
    with pytest.raises(ValueError):
        build_provider("not-a-provider", "some-model")
