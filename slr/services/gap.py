"""Gap-statement discovery: extraction's sibling for one field (RQ2).

Runs over records a prior screening run verified as included. Same three
stages as screen.py and extract.py -- ask, validate shape, verify quote. RQ2
asks whether the system can surface the research gaps authors state in
their own abstracts; a claimed gap that cannot be found verbatim in the
source is not reported as one, same trust mechanism as everywhere else in
this project.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, ValidationError

from slr.adapters.llm import (
    CacheMismatch,
    Completion,
    Meter,
    Provider,
    cache_key,
    request_fingerprint,
)
from slr.services.verify import source_text, verify_span

NOT_STATED = "not_stated"
GAP_STATED = "gap_stated"

# Passed explicitly to provider.complete() -- a provider's own RESPONSE_SCHEMA
# default is screening-shaped, and this has nothing to do with that. See the
# note on Provider.complete in slr/adapters/llm.py.
GAP_SCHEMA = {
    "type": "object",
    "properties": {"value": {"type": "string"}, "evidence_span": {"type": "string"}},
    "required": ["value", "evidence_span"],
}


class GapResponse(BaseModel):
    """The shape a response must have. Anything else is an error, not a guess."""

    value: str
    evidence_span: str


@dataclass
class GapExtraction:
    """One record's gap-statement result, ready for the database and the log."""

    work_id: str
    review: str
    value: str | None  # 'gap_stated' | 'not_stated' | None (unverified/error)
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
            f"prompts/ and are referenced by extraction.prompt_version."
        )
    return path.read_text(encoding="utf-8")


def build_gap_prompt(template: str, *, title: str | None, abstract: str | None) -> str:
    return template.format(title=(title or "").strip(), abstract=(abstract or "").strip())


def _error(row: sqlite3.Row, *, verify_note: str, error: str, completion: Completion | None = None) -> GapExtraction:
    return GapExtraction(
        work_id=row["work_id"],
        review=row["review"],
        value=None,
        evidence_span=None,
        span_verified=False,
        verify_note=verify_note,
        from_cache=completion.from_cache if completion else False,
        tokens_in=completion.tokens_in if completion else 0,
        tokens_out=completion.tokens_out if completion else 0,
        cost_usd=0.0,
        latency_ms=completion.latency_ms if completion else 0,
        error=error[:500],
    )


def extract_gap(
    row: sqlite3.Row,
    *,
    provider: Provider,
    template: str,
    meter: Meter,
    conn: sqlite3.Connection,
    prompt_version: str,
    temperature: float,
    max_tokens: int,
    seed: int | None = None,
    use_cache: bool = True,
) -> GapExtraction:
    """Look for a stated research gap in one record. Never raises for model failure.

    Does raise ``CacheMismatch`` when a cached response was produced by a
    different request -- same contract as ``screen_record``/``extract_record``.
    """
    prompt = build_gap_prompt(template, title=row["title"], abstract=row["abstract"])
    fingerprint = request_fingerprint(
        prompt,
        model=provider.model,
        temperature=temperature,
        max_tokens=max_tokens,
        seed=seed,
        response_schema=GAP_SCHEMA,
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
                    f"request. Bump the gap prompt_version, or delete that "
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
                prompt,
                temperature=temperature,
                max_tokens=max_tokens,
                seed=seed,
                response_schema=GAP_SCHEMA,
            )
        except Exception as exc:  # provider errors are data, not crashes
            return _error(row, verify_note="provider_error", error=str(exc))
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

    try:
        parsed = GapResponse.model_validate_json(completion.text)
    except ValidationError as exc:
        return _error(row, verify_note="schema_validation_failed", error=str(exc), completion=completion)

    if parsed.value.strip().lower() == NOT_STATED:
        return GapExtraction(
            work_id=row["work_id"],
            review=row["review"],
            value=NOT_STATED,
            evidence_span=None,
            span_verified=False,
            verify_note=NOT_STATED,
            from_cache=completion.from_cache,
            tokens_in=completion.tokens_in,
            tokens_out=completion.tokens_out,
            cost_usd=cost,
            latency_ms=completion.latency_ms,
        )

    result = verify_span(parsed.evidence_span, source_text(row["title"], row["abstract"]))
    return GapExtraction(
        work_id=row["work_id"],
        review=row["review"],
        value=GAP_STATED if result.verified else None,
        evidence_span=parsed.evidence_span,
        span_verified=result.verified,
        verify_note=result.note,
        from_cache=completion.from_cache,
        tokens_in=completion.tokens_in,
        tokens_out=completion.tokens_out,
        cost_usd=cost,
        latency_ms=completion.latency_ms,
    )


def persist(conn: sqlite3.Connection, run_id: str, source_run_id: str, row: GapExtraction) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO gap_statement "
        "(run_id, source_run_id, review, work_id, value, evidence_span, "
        " span_verified, verify_note, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
        (
            run_id,
            source_run_id,
            row.review,
            row.work_id,
            row.value,
            row.evidence_span,
            int(row.span_verified),
            row.verify_note,
            datetime.now(timezone.utc).isoformat(),
        ),
    )


def to_jsonl(row: GapExtraction) -> str:
    return json.dumps(asdict(row), ensure_ascii=False)


RATINGS = ("valid", "invalid")


def rate(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    review: str,
    work_id: str,
    rating: str,
    rating_note: str | None = None,
) -> None:
    """Record a human precision judgement on one discovered gap statement.

    Only a row whose value is ``gap_stated`` can be rated -- rating
    ``not_stated`` or a failed attempt would be rating the absence of a
    claim, not a claim. The week 11 checkpoint's precision number is
    ``valid`` / (``valid`` + ``invalid``) over the rated subset.
    """
    if rating not in RATINGS:
        raise ValueError(f"rating must be one of {RATINGS}, got {rating!r}")
    row = conn.execute(
        "SELECT value FROM gap_statement WHERE run_id = ? AND review = ? AND work_id = ?",
        (run_id, review, work_id),
    ).fetchone()
    if row is None:
        raise ValueError(f"{review}/{work_id} has no gap_statement row in run {run_id!r}")
    if row["value"] != GAP_STATED:
        raise ValueError(
            f"{review}/{work_id} in run {run_id!r} is {row['value']!r}, not "
            f"{GAP_STATED!r} -- nothing to rate"
        )
    conn.execute(
        "UPDATE gap_statement SET rating = ?, rating_note = ? "
        "WHERE run_id = ? AND review = ? AND work_id = ?",
        (rating, rating_note, run_id, review, work_id),
    )
    conn.commit()


@dataclass
class PrecisionSummary:
    n_gap_stated: int
    n_rated: int
    n_valid: int
    n_invalid: int
    precision: float | None  # n_valid / n_rated

    def as_dict(self) -> dict:
        return asdict(self)


def precision(conn: sqlite3.Connection, run_id: str, review: str) -> PrecisionSummary:
    rows = conn.execute(
        "SELECT rating FROM gap_statement WHERE run_id = ? AND review = ? AND value = ?",
        (run_id, review, GAP_STATED),
    ).fetchall()
    rated = [r["rating"] for r in rows if r["rating"] is not None]
    n_valid = sum(1 for r in rated if r == "valid")
    n_invalid = sum(1 for r in rated if r == "invalid")
    return PrecisionSummary(
        n_gap_stated=len(rows),
        n_rated=len(rated),
        n_valid=n_valid,
        n_invalid=n_invalid,
        precision=n_valid / len(rated) if rated else None,
    )
