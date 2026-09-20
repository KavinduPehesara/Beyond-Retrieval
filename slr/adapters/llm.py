"""LLM providers behind one interface, with caching and a hard budget ceiling.

The abstraction exists for a stated reason: comparing model tiers is a
research requirement (RQ2 asks what the accuracy-cost trade-off is), and it
must be a config change rather than a code change, or the comparison is not
worth reporting.

Four providers:

* ``mock``   — deterministic, free, no network. Used by the tests and by
               anyone running the pipeline without a key. Its decisions are
               nonsense, but it exercises every code path including the
               verification failure path.
* ``gemini`` — Google AI Studio. Cheapest viable option with JSON mode.
* ``ollama`` — local inference against the developer's own GPU, via Ollama's
               HTTP API. $0 marginal cost by construction; added week 8 when
               gemini-2.5-flash-lite became unavailable to this account and
               its replacement cost ~4x more. Not a replacement for the
               Gemini arm — RQ2's cost/time comparison is between them.
* (a second Gemini tier is added in week 10 for the cost comparison)
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import time
from dataclasses import dataclass
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


class CacheMismatch(RuntimeError):
    """A cached response was produced by a different request.

    Raised when the prompt text or generation settings changed but the prompt
    version did not. This aborts the run: serving the old response would
    report results for criteria that were not the ones in the config.
    """


@dataclass
class Completion:
    """One model response, with everything needed to cost and audit it."""

    text: str
    tokens_in: int = 0
    tokens_out: int = 0
    latency_ms: int = 0
    from_cache: bool = False


class Provider(Protocol):
    """What every provider must offer. Deliberately tiny.

    ``response_schema`` lets a caller override the JSON shape the provider
    constrains output to. A provider's own ``RESPONSE_SCHEMA`` is only the
    *default* it uses when no schema is given — screening relies on that
    default rather than passing one explicitly. Any caller that needs a
    different shape (e.g. extraction's multi-field response) MUST pass its
    own schema: leaving this to a provider-side default means every new
    response shape silently gets forced into whatever shape the provider
    happened to be built for first, which is exactly the bug this parameter
    exists to prevent.
    """

    name: str
    model: str

    def complete(
        self,
        prompt: str,
        *,
        temperature: float,
        max_tokens: int,
        seed: int | None = None,
        response_schema: dict | None = None,
    ) -> Completion:
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

    def complete(
        self,
        prompt: str,
        *,
        temperature: float = 0.0,
        max_tokens: int = 512,
        seed: int | None = None,
        response_schema: dict | None = None,
    ) -> Completion:
        # Always fabricates a screening-shaped response, regardless of
        # response_schema — it exists to exercise screening's verification
        # failure path, not to stand in for every provider's response shape.
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

    def complete(
        self,
        prompt: str,
        *,
        temperature: float = 0.0,
        max_tokens: int = 512,
        seed: int | None = None,
        response_schema: dict | None = None,
    ) -> Completion:
        config = {
            "temperature": temperature,
            "max_output_tokens": max_tokens,
            "response_mime_type": "application/json",
            "response_schema": response_schema or self.RESPONSE_SCHEMA,
        }
        if seed is not None:
            # Best effort on the provider's side, not a guarantee — which is
            # why run-to-run agreement is measured rather than assumed.
            config["seed"] = seed

        @retry(
            stop=stop_after_attempt(self.max_retries),
            wait=wait_exponential(multiplier=1, min=2, max=20),
            retry=retry_if_exception_type(Exception),
            reraise=True,
        )
        def _call():
            return self._client.models.generate_content(
                model=self.model, contents=prompt, config=config
            )

        started = time.perf_counter()
        try:
            response = _call()
        except Exception as exc:
            raise ProviderError(f"Gemini call failed after retries: {exc}") from exc
        latency_ms = int((time.perf_counter() - started) * 1000)

        usage = getattr(response, "usage_metadata", None)
        # Thinking tokens are billed as output but reported separately by
        # models that use them. Leaving them out would let the budget meter
        # undercount, and the ceiling would stop being a ceiling.
        tokens_out = (getattr(usage, "candidates_token_count", 0) or 0) + (
            getattr(usage, "thoughts_token_count", 0) or 0
        )
        return Completion(
            text=response.text or "",
            tokens_in=getattr(usage, "prompt_token_count", 0) or 0,
            tokens_out=tokens_out,
            latency_ms=latency_ms,
        )


# --------------------------------------------------------------------------
# Ollama provider (local GPU)
# --------------------------------------------------------------------------


class OllamaProvider:
    """Local inference via Ollama's HTTP API, on the developer's own GPU.

    Same JSON-schema-constrained approach as ``GeminiProvider`` — Ollama's
    ``format`` parameter takes a JSON schema and constrains generation to it,
    so parse-failure rates stay comparable across providers rather than being
    confounded by one provider having weaker JSON discipline than the other.

    $0 marginal cost by construction: there is no per-token bill. The budget
    config should set ``usd_per_1m_input``/``usd_per_1m_output`` to 0 for an
    accurate ``run.json`` — that is a real price, not a placeholder.
    """

    name = "ollama"

    RESPONSE_SCHEMA = GeminiProvider.RESPONSE_SCHEMA

    def __init__(
        self,
        model: str,
        base_url: str = "http://localhost:11434",
        max_retries: int = 3,
    ) -> None:
        self.model = model
        self.max_retries = max_retries
        try:
            import httpx
        except ImportError as exc:  # pragma: no cover
            raise ProviderError(
                "httpx is not installed. pip install -r requirements.txt"
            ) from exc
        self._client = httpx.Client(base_url=base_url, timeout=120.0)

    def complete(
        self,
        prompt: str,
        *,
        temperature: float = 0.0,
        max_tokens: int = 512,
        seed: int | None = None,
        response_schema: dict | None = None,
    ) -> Completion:
        options = {"temperature": temperature, "num_predict": max_tokens}
        if seed is not None:
            # Best effort on the provider's side, not a guarantee — which is
            # why run-to-run agreement is measured rather than assumed.
            options["seed"] = seed
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "format": response_schema or self.RESPONSE_SCHEMA,
            "options": options,
        }

        @retry(
            stop=stop_after_attempt(self.max_retries),
            wait=wait_exponential(multiplier=1, min=2, max=20),
            retry=retry_if_exception_type(Exception),
            reraise=True,
        )
        def _call():
            response = self._client.post("/api/generate", json=payload)
            response.raise_for_status()
            return response.json()

        started = time.perf_counter()
        try:
            data = _call()
        except Exception as exc:
            raise ProviderError(f"Ollama call failed after retries: {exc}") from exc
        latency_ms = int((time.perf_counter() - started) * 1000)

        return Completion(
            text=data.get("response", ""),
            tokens_in=data.get("prompt_eval_count", 0) or 0,
            tokens_out=data.get("eval_count", 0) or 0,
            latency_ms=latency_ms,
        )


# --------------------------------------------------------------------------
# Caching and budget wrapper
# --------------------------------------------------------------------------


def cache_key(model: str, prompt_version: str, review: str, work_id: str) -> str:
    """Keyed on model, prompt version and record — nothing else.

    A record is (review, work_id): the same paper screened for two reviews is
    screened against two sets of criteria, and must not share a response.

    The prompt text is deliberately not part of the key. It is recorded
    alongside the response instead (``request_fingerprint``), and a mismatch
    aborts the run — so a prompt edited without a version bump is caught
    rather than silently served stale.
    """
    raw = f"{model}\x1f{prompt_version}\x1f{review}\x1f{work_id}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def request_fingerprint(
    prompt: str,
    *,
    model: str,
    temperature: float,
    max_tokens: int,
    seed: int | None,
) -> str:
    """Hash of everything that determines what was asked of the model."""
    payload = json.dumps(
        {
            "prompt": prompt,
            "model": model,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "seed": seed,
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


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
        return self.cost_of(self.tokens_in, self.tokens_out)

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
    if provider == "ollama":
        return OllamaProvider(model=model, max_retries=max_retries)
    raise ValueError(f"Unknown provider: {provider!r}. Use 'mock', 'gemini' or 'ollama'.")
