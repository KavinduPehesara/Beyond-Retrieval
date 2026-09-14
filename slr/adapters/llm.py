"""LLM providers behind one interface, with caching and a hard budget ceiling.

The abstraction exists for a stated reason: comparing model tiers is a
research requirement (RQ2 asks what the accuracy-cost trade-off is), and it
must be a config change rather than a code change, or the comparison is not
worth reporting.

Three providers:

* ``mock``   — deterministic, free, no network. Used by the tests and by
               anyone running the pipeline without a key. Its decisions are
               nonsense, but it exercises every code path including the
               verification failure path.
* ``gemini`` — Google AI Studio. Cheapest viable option with JSON mode.
* (a second tier is added in week 10 for the cost comparison)
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import time
from dataclasses import dataclass, field
from typing import Protocol

from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)


class BudgetExceeded(RuntimeError):
    """Raised when the configured ceiling is reached.

    This aborts the run. It does not warn: a warning at 2am is a warning
    nobody reads, and an overrun is money that cannot be recovered.
    """


class ProviderError(RuntimeError):
    """Transport or API failure, after retries."""


@dataclass
class Completion:
    """One model response, with everything needed to cost and audit it."""

    text: str
    tokens_in: int = 0
    tokens_out: int = 0
    latency_ms: int = 0
    from_cache: bool = False


class Provider(Protocol):
    """What every provider must offer. Deliberately tiny."""

    name: str
    model: str

    def complete(self, prompt: str, *, temperature: float, max_tokens: int) -> Completion:
        ...


# --------------------------------------------------------------------------
# Mock provider
# --------------------------------------------------------------------------


class MockProvider:
    """Deterministic fake. No network, no cost, no key.

    Quotes a real sentence from the prompt roughly four times in five, and
    invents one otherwise. That ratio is arbitrary — the point is that the
    verification failure path gets exercised on every test run, rather than
    only being discovered in week 10 when it matters.
    """

    name = "mock"

    def __init__(self, model: str = "mock-1", fabricate_rate: float = 0.2) -> None:
        self.model = model
        self.fabricate_rate = fabricate_rate

    def complete(self, prompt: str, *, temperature: float = 0.0, max_tokens: int = 512) -> Completion:
        # Seed on the prompt so the same input always gives the same output.
        rng = random.Random(hashlib.sha256(prompt.encode()).hexdigest())

        abstract = ""
        if "ABSTRACT:" in prompt:
            abstract = prompt.split("ABSTRACT:", 1)[1]
            abstract = abstract.split("\n\n", 1)[0].strip()

        sentences = [s.strip() for s in abstract.split(". ") if len(s.strip()) > 25]

        if sentences and rng.random() > self.fabricate_rate:
            span = sentences[rng.randrange(len(sentences))]
            if not span.endswith("."):
                span += "."
        else:
            span = "This study demonstrates a statistically significant effect across all cohorts."

        payload = {
            "decision": "include" if rng.random() < 0.3 else "exclude",
            "confidence": round(rng.uniform(0.5, 0.99), 2),
            "evidence_span": span,
        }
        return Completion(
            text=json.dumps(payload),
            tokens_in=len(prompt) // 4,
            tokens_out=len(json.dumps(payload)) // 4,
            latency_ms=1,
        )


# --------------------------------------------------------------------------
# Gemini provider
# --------------------------------------------------------------------------


class GeminiProvider:
    """Google AI Studio, in JSON mode.

    JSON mode matters. Parsing prose with regular expressions to find the
    model's answer is how you end up with a silent failure that looks like a
    result. If the response cannot be parsed, that is recorded as an error and
    counted, not patched over.
    """

    name = "gemini"

    RESPONSE_SCHEMA = {
        "type": "object",
        "properties": {
            "decision": {"type": "string", "enum": ["include", "exclude"]},
            "confidence": {"type": "number"},
            "evidence_span": {"type": "string"},
        },
        "required": ["decision", "confidence", "evidence_span"],
    }

    def __init__(self, model: str, api_key: str | None = None, max_retries: int = 3) -> None:
        self.model = model
        self.max_retries = max_retries
        key = api_key or os.getenv("GEMINI_API_KEY")
        if not key:
            raise ProviderError(
                "GEMINI_API_KEY is not set. Copy .env.example to .env and add "
                "your key from https://aistudio.google.com/apikey — or set "
                "provider: mock in the config to run without one."
            )
        try:
            from google import genai  # imported lazily so mock runs need no SDK
        except ImportError as exc:  # pragma: no cover
            raise ProviderError(
                "google-genai is not installed. pip install -r requirements.txt"
            ) from exc
        self._genai = genai
        self._client = genai.Client(api_key=key)

    def complete(self, prompt: str, *, temperature: float = 0.0, max_tokens: int = 512) -> Completion:
        @retry(
            stop=stop_after_attempt(self.max_retries),
            wait=wait_exponential(multiplier=1, min=2, max=20),
            retry=retry_if_exception_type(Exception),
            reraise=True,
        )
        def _call():
            return self._client.models.generate_content(
                model=self.model,
                contents=prompt,
                config={
                    "temperature": temperature,
                    "max_output_tokens": max_tokens,
                    "response_mime_type": "application/json",
                    "response_schema": self.RESPONSE_SCHEMA,
                },
            )

        started = time.perf_counter()
        try:
            response = _call()
        except Exception as exc:
            raise ProviderError(f"Gemini call failed after retries: {exc}") from exc
        latency_ms = int((time.perf_counter() - started) * 1000)

        usage = getattr(response, "usage_metadata", None)
        return Completion(
            text=response.text or "",
            tokens_in=getattr(usage, "prompt_token_count", 0) or 0,
            tokens_out=getattr(usage, "candidates_token_count", 0) or 0,
            latency_ms=latency_ms,
        )


# --------------------------------------------------------------------------
# Caching and budget wrapper
# --------------------------------------------------------------------------


def cache_key(model: str, prompt_version: str, work_id: str) -> str:
    """Keyed on model, prompt version and record — nothing else.

    Deliberately *not* keyed on the prompt text itself. If the prompt changes
    without its version changing, that is a bug in the experiment, and a cache
    that silently absorbs it would hide the bug.
    """
    raw = f"{model}\x1f{prompt_version}\x1f{work_id}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@dataclass
class Meter:
    """Running cost, and the ceiling it must not cross."""

    ceiling_usd: float
    usd_per_1m_input: float
    usd_per_1m_output: float
    tokens_in: int = 0
    tokens_out: int = 0
    calls: int = 0
    cached_calls: int = 0

    @property
    def spend_usd(self) -> float:
        return (
            self.tokens_in / 1_000_000 * self.usd_per_1m_input
            + self.tokens_out / 1_000_000 * self.usd_per_1m_output
        )

    def cost_of(self, tokens_in: int, tokens_out: int) -> float:
        return (
            tokens_in / 1_000_000 * self.usd_per_1m_input
            + tokens_out / 1_000_000 * self.usd_per_1m_output
        )

    def record(self, completion: Completion) -> float:
        """Add a completion to the tally, and abort if the ceiling is crossed."""
        self.calls += 1
        if completion.from_cache:
            self.cached_calls += 1
            return 0.0
        self.tokens_in += completion.tokens_in
        self.tokens_out += completion.tokens_out
        cost = self.cost_of(completion.tokens_in, completion.tokens_out)
        if self.spend_usd > self.ceiling_usd:
            raise BudgetExceeded(
                f"Spend ${self.spend_usd:.4f} exceeded ceiling "
                f"${self.ceiling_usd:.2f} after {self.calls} calls. "
                f"Run aborted. Raise budget.ceiling_usd in the config if this "
                f"is expected."
            )
        return cost


def build_provider(provider: str, model: str, api_key: str | None = None, max_retries: int = 3) -> Provider:
    if provider == "mock":
        return MockProvider(model=model)
    if provider == "gemini":
        return GeminiProvider(model=model, api_key=api_key, max_retries=max_retries)
    raise ValueError(f"Unknown provider: {provider!r}. Use 'mock' or 'gemini'.")
