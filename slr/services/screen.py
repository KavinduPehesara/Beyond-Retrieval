"""Screening: ask the model, validate the shape, verify the quote.

The order matters. A response is only a decision once it has passed all three
stages; anything that falls out earlier is recorded as unverified or error and
goes to a human. That is the mechanism behind the *verifiable* and
*overridable* properties in RQ1.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError

from slr.adapters.llm import (
    CacheMismatch,
    Completion,
    Meter,
    Provider,
    cache_key,
    request_fingerprint,
)
from slr.services.verify import source_text, verify_span


class ScreeningResponse(BaseModel):
    """The shape a response must have. Anything else is an error, not a guess."""

    decision: str = Field(pattern="^(include|exclude)$")
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_span: str


@dataclass
class Decision:
    """One screened record, ready to be written to the database and the log."""

    work_id: str
    review: str
    decision: str  # include | exclude | unverified | error
    confidence: float | None
    evidence_span: str | None
    span_verified: bool
    verify_note: str
    from_cache: bool
    tokens_in: int
    tokens_out: int
    cost_usd: float
    latency_ms: int
    error: str | None = None


def load_prompt_template(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(
            f"Prompt template not found: {path}. Prompt versions live in "
            f"prompts/ and are referenced by screening.prompt_version."
        )
    return path.read_text(encoding="utf-8")


def build_prompt(template: str, *, criteria: str, title: str | None, abstract: str | None) -> str:
    """Fill the template.

    Note what is absent: ``label_included`` never reaches this function. The
    ground truth column is read by the metrics module and by nothing else.
    """
    return template.format(
        criteria=criteria.strip(),
        title=(title or "").strip(),
        abstract=(abstract or "").strip(),
    )


def screen_record(
    row: sqlite3.Row,
    *,
    provider: Provider,
    template: str,
    criteria: str,
    meter: Meter,
    conn: sqlite3.Connection,
    prompt_version: str,
    temperature: float,
    max_tokens: int,
    seed: int | None = None,
    use_cache: bool = True,
) -> Decision:
    """Screen one record. Never raises for model failure — records it.

    Does raise ``CacheMismatch`` when a cached response was produced by a
    different request: that is a fault in the experiment, not in the model.
    """

    prompt = build_prompt(
        template, criteria=criteria, title=row["title"], abstract=row["abstract"]
    )
    fingerprint = request_fingerprint(
        prompt,
        model=provider.model,
        temperature=temperature,
        max_tokens=max_tokens,
        seed=seed,
    )
    key = cache_key(provider.model, prompt_version, row["review"], row["work_id"])
    completion: Completion | None = None

    if use_cache:
        cached = conn.execute(
            "SELECT request_sha256, raw_response, tokens_in, tokens_out "
            "FROM cached_response WHERE cache_key = ?",
            (key,),
        ).fetchone()
        if cached:
            if cached["request_sha256"] != fingerprint:
                raise CacheMismatch(
                    f"{row['review']}/{row['work_id']}: the cached response for "
                    f"prompt version {prompt_version!r} came from a different "
                    f"request (criteria, template or generation settings "
                    f"changed). Bump screening.prompt_version, or delete that "
                    f"version's cached rows, before running."
                )
            completion = Completion(
                text=cached["raw_response"],
                tokens_in=cached["tokens_in"],
                tokens_out=cached["tokens_out"],
                from_cache=True,
            )

    if completion is None:
        try:
            completion = provider.complete(
                prompt, temperature=temperature, max_tokens=max_tokens, seed=seed
            )
        except Exception as exc:  # provider errors are data, not crashes
            return Decision(
                work_id=row["work_id"],
                review=row["review"],
                decision="error",
                confidence=None,
                evidence_span=None,
                span_verified=False,
                verify_note="provider_error",
                from_cache=False,
                tokens_in=0,
                tokens_out=0,
                cost_usd=0.0,
                latency_ms=0,
                error=str(exc)[:500],
            )
        if use_cache:
            conn.execute(
                "INSERT OR REPLACE INTO cached_response "
                "(cache_key, request_sha256, raw_response, tokens_in, tokens_out, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    key,
                    fingerprint,
                    completion.text,
                    completion.tokens_in,
                    completion.tokens_out,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )

    cost = meter.record(completion)

    # Stage 2: does the response have the required shape?
    try:
        parsed = ScreeningResponse.model_validate_json(completion.text)
    except ValidationError as exc:
        # A parse failure rate is itself a reportable number. Do not paper
        # over this with regular expressions.
        return Decision(
            work_id=row["work_id"],
            review=row["review"],
            decision="error",
            confidence=None,
            evidence_span=None,
            span_verified=False,
            verify_note="schema_validation_failed",
            from_cache=completion.from_cache,
            tokens_in=completion.tokens_in,
            tokens_out=completion.tokens_out,
            cost_usd=cost,
            latency_ms=completion.latency_ms,
            error=str(exc)[:500],
        )

    # Stage 3: is the quote real?
    result = verify_span(
        parsed.evidence_span, source_text(row["title"], row["abstract"])
    )

    return Decision(
        work_id=row["work_id"],
        review=row["review"],
        # An unverified decision is not the model's decision. It is a referral.
        decision=parsed.decision if result.verified else "unverified",
        confidence=parsed.confidence,
        evidence_span=parsed.evidence_span,
        span_verified=result.verified,
        verify_note=result.note,
        from_cache=completion.from_cache,
        tokens_in=completion.tokens_in,
        tokens_out=completion.tokens_out,
        cost_usd=cost,
        latency_ms=completion.latency_ms,
    )


def persist(conn: sqlite3.Connection, run_id: str, decision: Decision) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO screening_decision "
        "(run_id, review, work_id, decision, confidence, evidence_span, span_verified, "
        " verify_note, from_cache, tokens_in, tokens_out, cost_usd, latency_ms, created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            run_id,
            decision.review,
            decision.work_id,
            decision.decision,
            decision.confidence,
            decision.evidence_span,
            int(decision.span_verified),
            decision.verify_note,
            int(decision.from_cache),
            decision.tokens_in,
            decision.tokens_out,
            decision.cost_usd,
            decision.latency_ms,
            datetime.now(timezone.utc).isoformat(),
        ),
    )


def to_jsonl(decision: Decision) -> str:
    return json.dumps(asdict(decision), ensure_ascii=False)
