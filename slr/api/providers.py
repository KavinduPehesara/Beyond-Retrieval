"""Which model answers a request, and what that model costs.

The provider interface has been there since week 7, but the API only ever
built the local one, so a choice the architecture already allowed was
invisible to anyone using the tool. Two models from two vendors is what the
supervisor asked for, and a demonstration cannot show it if the running
system can only reach one.

Prices live here beside the model because ``Meter`` aborts a run rather than
warning, and a ceiling of zero aborts a paid provider on its first call. The
figures match ``configs/gap_*.yaml`` so the app and the costed comparison
arms agree on what a call is worth.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from slr.adapters.llm import Meter, Provider, build_provider

# Enough for an interactive session many times over; a runaway loop still
# stops. The evaluation harnesses set their own, far smaller, ceilings.
DEFAULT_CEILING_USD = 1.0


@dataclass(frozen=True)
class Choice:
    """One selectable model, with the price this project costed it at."""

    key: str
    label: str
    model: str
    env_key: str | None
    usd_per_1m_input: float
    usd_per_1m_output: float
    missing_note: str


CHOICES: dict[str, Choice] = {
    "ollama": Choice(
        key="ollama",
        label="Local model",
        model="qwen2.5:7b-instruct",
        env_key=None,
        usd_per_1m_input=0.0,
        usd_per_1m_output=0.0,
        missing_note="Needs Ollama running (ollama pull qwen2.5:7b-instruct).",
    ),
    "gemini": Choice(
        key="gemini",
        label="Gemini",
        model="gemini-3.5-flash-lite",
        env_key="GEMINI_API_KEY",
        usd_per_1m_input=0.3,
        usd_per_1m_output=2.5,
        missing_note="Add GEMINI_API_KEY to .env to use Gemini.",
    ),
    "openai": Choice(
        key="openai",
        label="ChatGPT",
        model="gpt-5-nano",
        env_key="OPENAI_API_KEY",
        usd_per_1m_input=0.05,
        usd_per_1m_output=0.4,
        missing_note="Add OPENAI_API_KEY to .env to use ChatGPT.",
    ),
}

FALLBACK_KEY = "ollama"


def default_key() -> str:
    """The provider used when a request does not name one."""
    key = os.getenv("LLM_PROVIDER", FALLBACK_KEY).strip().lower()
    return key if key in CHOICES else FALLBACK_KEY


def is_configured(choice: Choice) -> bool:
    """Whether this choice could run now.

    Only the key is checked. Whether Ollama is actually up, or a key is still
    valid, is not knowable without spending a call, so that failure surfaces
    where it happens rather than being guessed at here.
    """
    return choice.env_key is None or bool(os.getenv(choice.env_key, "").strip())


def ceiling_usd() -> float:
    try:
        value = float(os.getenv("BUDGET_CEILING_USD", ""))
    except ValueError:
        return DEFAULT_CEILING_USD
    return value if value > 0 else DEFAULT_CEILING_USD


def catalogue() -> list[dict]:
    """Every choice, and whether it can run, for the interface to offer."""
    return [
        {
            "key": c.key,
            "label": c.label,
            "model": c.model,
            "configured": is_configured(c),
            "free": c.usd_per_1m_input == 0.0 and c.usd_per_1m_output == 0.0,
            "note": "" if is_configured(c) else c.missing_note,
        }
        for c in CHOICES.values()
    ]


def resolve(key: str | None) -> Choice:
    """The choice a request asked for, or the default.

    Raises ``ValueError`` for an unknown provider, or for one whose key is
    not set: answering on a different model than the one asked for would
    quietly break the comparison the choice exists to make.
    """
    wanted = (key or default_key()).strip().lower()
    choice = CHOICES.get(wanted)
    if choice is None:
        known = ", ".join(sorted(CHOICES))
        raise ValueError(f"Unknown provider {wanted!r}. Choose one of: {known}.")
    if not is_configured(choice):
        raise ValueError(choice.missing_note)
    return choice


def build(key: str | None) -> tuple[Provider, Meter, Choice]:
    """A provider and a meter that will stop it, for the chosen model."""
    choice = resolve(key)
    provider = build_provider(
        choice.key,
        choice.model,
        api_key=os.getenv(choice.env_key, "") or None if choice.env_key else None,
    )
    meter = Meter(
        ceiling_usd=ceiling_usd(),
        usd_per_1m_input=choice.usd_per_1m_input,
        usd_per_1m_output=choice.usd_per_1m_output,
    )
    return provider, meter, choice
