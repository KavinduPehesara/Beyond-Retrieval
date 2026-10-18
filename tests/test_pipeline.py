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
    OpenAIProvider,
    ProviderError,
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


def test_build_provider_dispatches_openai(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-a-real-key")
    provider = build_provider("openai", "gpt-5-nano")
    assert isinstance(provider, OpenAIProvider)
    assert provider.name == "openai"
    assert provider.model == "gpt-5-nano"


def test_openai_provider_says_what_is_missing_rather_than_failing_obscurely(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(ProviderError) as excinfo:
        OpenAIProvider("gpt-5-nano")
    message = str(excinfo.value)
    assert "OPENAI_API_KEY" in message
    assert "no free tier" in message  # the thing that actually trips people up


def test_openai_strict_schema_closes_the_object(monkeypatch):
    """Strict structured output needs additionalProperties false and every
    property required, or the API rejects the schema outright."""
    loose = {"type": "object", "properties": {"a": {"type": "string"}, "b": {"type": "number"}},
             "required": ["a"]}
    strict = OpenAIProvider._strict(loose)
    assert strict["additionalProperties"] is False
    assert sorted(strict["required"]) == ["a", "b"]
    assert loose["required"] == ["a"], "must not mutate the caller's schema"


def test_openai_sends_the_schema_and_reports_real_token_counts(monkeypatch):
    """The contract every provider shares: constrained JSON out, true usage back."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-a-real-key")
    provider = OpenAIProvider("gpt-5-nano")
    sent = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "choices": [{"message": {"content": '{"gap_stated":"not_stated"}'}}],
                "usage": {"prompt_tokens": 811, "completion_tokens": 57},
            }

    def fake_post(path, json=None):
        sent["path"] = path
        sent["payload"] = json
        return FakeResponse()

    monkeypatch.setattr(provider._client, "post", fake_post)
    schema = {"type": "object", "properties": {"gap_stated": {"type": "string"}}}
    completion = provider.complete("is there a gap?", max_tokens=128, seed=42, response_schema=schema)

    assert completion.text == '{"gap_stated":"not_stated"}'
    assert (completion.tokens_in, completion.tokens_out) == (811, 57)
    fmt = sent["payload"]["response_format"]
    assert fmt["type"] == "json_schema"
    assert fmt["json_schema"]["strict"] is True
    assert fmt["json_schema"]["schema"]["properties"] == schema["properties"]
    assert sent["payload"]["seed"] == 42


def test_openai_refusal_is_an_error_not_an_empty_answer(monkeypatch):
    """A refusal returned as empty text would be scored as a real response."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-a-real-key")
    provider = OpenAIProvider("gpt-5-nano")

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"refusal": "I cannot help with that."}}], "usage": {}}

    monkeypatch.setattr(provider._client, "post", lambda path, json=None: FakeResponse())
    with pytest.raises(ProviderError, match="refused"):
        provider.complete("anything")


def test_build_provider_rejects_unknown_name():
    with pytest.raises(ValueError):
        build_provider("not-a-provider", "some-model")


# --------------------------------------------------------------------------
# on_completion -- the raw prompt/response hook, for showing the unprocessed
# model exchange rather than the parsed decision
# --------------------------------------------------------------------------


def test_on_completion_sees_the_prompt_and_raw_completion_before_parsing(conn):
    row = conn.execute("SELECT * FROM work WHERE work_id = 'W1'").fetchone()
    seen = []
    screen_record(row, **_screen_kwargs(conn, on_completion=lambda prompt, completion: seen.append((prompt, completion))))
    assert len(seen) == 1
    prompt, completion = seen[0]
    assert "Bayesian estimation in small samples" in prompt  # the real title, not a placeholder
    assert isinstance(completion, Completion)
    assert completion.text  # the raw, unparsed JSON text


def test_on_completion_is_not_called_on_a_provider_error(conn, monkeypatch):
    row = conn.execute("SELECT * FROM work WHERE work_id = 'W1'").fetchone()

    class _BrokenProvider:
        name = "broken"
        model = "broken-1"

        def complete(self, *a, **k):
            raise RuntimeError("the model is unreachable")

    seen = []
    kwargs = _screen_kwargs(conn, provider=_BrokenProvider(), on_completion=lambda p, c: seen.append((p, c)))
    decision = screen_record(row, **kwargs)
    assert decision.decision == "error"
    assert seen == []


def test_three_models_over_one_record_get_three_cache_entries():
    """The week-14 multi-model gap arms depend on this. If two providers shared
    a cache key, the second model's run would silently serve the first model's
    answers and the agreement figure would be 1.0 by construction -- a perfect
    result that measured nothing."""
    keys = {
        cache_key(model, "gap_v1", "Nelson_2002", "W123")
        for model in ("qwen2.5:7b-instruct", "gemini-3.5-flash-lite", "gpt-5-nano")
    }
    assert len(keys) == 3
