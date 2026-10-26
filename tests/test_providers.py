"""Which model answers, and what stops it spending.

The choice matters to a claim the report makes: that the same records can be
put to a second vendor. These tests are mostly about refusing to answer on a
model other than the one asked for.
"""

from __future__ import annotations

import pytest

from slr.api import providers


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in ("LLM_PROVIDER", "GEMINI_API_KEY", "OPENAI_API_KEY", "BUDGET_CEILING_USD"):
        monkeypatch.delenv(name, raising=False)


def test_the_local_model_needs_no_key(monkeypatch):
    choice = providers.resolve("ollama")
    assert choice.model == "qwen2.5:7b-instruct"
    assert providers.is_configured(choice)


def test_a_provider_without_its_key_is_refused_not_substituted():
    """Answering on a different model would break the comparison silently."""
    with pytest.raises(ValueError) as exc:
        providers.resolve("gemini")
    assert "GEMINI_API_KEY" in str(exc.value)


def test_a_provider_with_its_key_resolves(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-a-real-key")
    choice = providers.resolve("openai")
    assert choice.key == "openai" and choice.label == "ChatGPT"


def test_an_unknown_provider_names_the_ones_that_exist():
    with pytest.raises(ValueError) as exc:
        providers.resolve("llama-on-a-toaster")
    for known in ("ollama", "gemini", "openai"):
        assert known in str(exc.value)


def test_the_default_is_the_local_model_unless_the_environment_says_otherwise(monkeypatch):
    assert providers.default_key() == "ollama"
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    assert providers.default_key() == "gemini"


def test_an_unusable_default_falls_back_rather_than_crashing(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "nonsense")
    assert providers.default_key() == "ollama"


def test_the_catalogue_says_why_a_provider_cannot_be_picked(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    by_key = {p["key"]: p for p in providers.catalogue()}

    assert by_key["gemini"]["configured"] is True
    assert by_key["openai"]["configured"] is False
    assert "OPENAI_API_KEY" in by_key["openai"]["note"]
    assert by_key["ollama"]["free"] is True
    assert by_key["gemini"]["free"] is False


# --------------------------------------------------------------------------
# The ceiling, which aborts rather than warning
# --------------------------------------------------------------------------


def test_a_paid_provider_gets_a_ceiling_it_can_actually_spend_under(monkeypatch):
    """A zero ceiling would abort a paid call on its first tokens."""
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    _provider, meter, choice = providers.build("gemini")

    assert meter.ceiling_usd > 0
    assert (meter.usd_per_1m_input, meter.usd_per_1m_output) == (
        choice.usd_per_1m_input,
        choice.usd_per_1m_output,
    )


def test_the_ceiling_comes_from_the_environment(monkeypatch):
    monkeypatch.setenv("BUDGET_CEILING_USD", "0.25")
    assert providers.ceiling_usd() == 0.25


@pytest.mark.parametrize("value", ["", "not a number", "0", "-1"])
def test_a_nonsense_ceiling_falls_back_to_the_default(monkeypatch, value):
    monkeypatch.setenv("BUDGET_CEILING_USD", value)
    assert providers.ceiling_usd() == providers.DEFAULT_CEILING_USD


def test_the_local_model_costs_nothing_so_no_ceiling_can_stop_it():
    _provider, meter, _choice = providers.build("ollama")
    assert meter.usd_per_1m_input == 0.0 and meter.usd_per_1m_output == 0.0


def test_prices_match_the_costed_comparison_configs():
    """The app and the gap arms must agree on what a call is worth.

    If these drift, the cost reported in section 11 describes a different
    price than the one the product charged.
    """
    assert providers.CHOICES["gemini"].usd_per_1m_input == 0.3
    assert providers.CHOICES["gemini"].usd_per_1m_output == 2.5
    assert providers.CHOICES["openai"].usd_per_1m_input == 0.05
    assert providers.CHOICES["openai"].usd_per_1m_output == 0.4
