"""Structured data extraction: screening's sibling, not a bolt-on.

Runs over records a prior screening run already verified as included. Same
three stages as ``screen.py`` — ask, validate shape, verify quote — just
once per field instead of once per decision. A field whose value is not
independently verifiable against the source is not reported as a fact.
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

FIELDS = ["study_design", "sample_size", "country", "key_finding"]

NOT_STATED = "not_stated"

_FIELD_SCHEMA = {
    "type": "object",
    "properties": {"value": {"type": "string"}, "evidence_span": {"type": "string"}},
    "required": ["value", "evidence_span"],
}

# Passed explicitly to provider.complete() — a provider's own RESPONSE_SCHEMA
# default is screening-shaped, and extraction's shape has nothing to do with
# that. See the note on Provider.complete in slr/adapters/llm.py.
EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {field: _FIELD_SCHEMA for field in FIELDS},
    "required": FIELDS,
}


class FieldAnswer(BaseModel):
    value: str
    evidence_span: str


class ExtractionResponse(BaseModel):
    """The shape a response must have. Anything else is an error, not a guess."""

    study_design: FieldAnswer
    sample_size: FieldAnswer
    country: FieldAnswer
    key_finding: FieldAnswer


@dataclass
class FieldExtraction:
    """One extracted field, ready to be written to the database and the log."""

    work_id: str
    review: str
    field_name: str
    value: str | None
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


def build_extract_prompt(template: str, *, title: str | None, abstract: str | None) -> str:
    return template.format(title=(title or "").strip(), abstract=(abstract or "").strip())


def _error_rows(row: sqlite3.Row, *, verify_note: str, error: str) -> list[FieldExtraction]:
    return [
        FieldExtraction(
            work_id=row["work_id"],
            review=row["review"],
            field_name=field,
            value=None,
            evidence_span=None,
            span_verified=False,
            verify_note=verify_note,
            from_cache=False,
            tokens_in=0,
            tokens_out=0,
            cost_usd=0.0,
            latency_ms=0,
            error=error[:500],
        )
        for field in FIELDS
    ]


def extract_record(
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
) -> list[FieldExtraction]:
    """Extract all fields for one record. Never raises for model failure.

    Does raise ``CacheMismatch`` when a cached response was produced by a
    different request — same contract as ``screen_record``.
    """
    prompt = build_extract_prompt(template, title=row["title"], abstract=row["abstract"])
    fingerprint = request_fingerprint(
        prompt, model=provider.model, temperature=temperature, max_tokens=max_tokens, seed=seed
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
                    f"request. Bump extraction.prompt_version, or delete that "
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
                response_schema=EXTRACTION_SCHEMA,
            )
        except Exception as exc:  # provider errors are data, not crashes
            return _error_rows(row, verify_note="provider_error", error=str(exc))
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
        parsed = ExtractionResponse.model_validate_json(completion.text)
    except ValidationError as exc:
        return _error_rows(row, verify_note="schema_validation_failed", error=str(exc))

    source = source_text(row["title"], row["abstract"])
    rows: list[FieldExtraction] = []
    for field in FIELDS:
        answer: FieldAnswer = getattr(parsed, field)
        if answer.value.strip().lower() == NOT_STATED:
            rows.append(
                FieldExtraction(
                    work_id=row["work_id"],
                    review=row["review"],
                    field_name=field,
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
            )
            continue

        result = verify_span(answer.evidence_span, source)
        rows.append(
            FieldExtraction(
                work_id=row["work_id"],
                review=row["review"],
                field_name=field,
                value=answer.value if result.verified else None,
                evidence_span=answer.evidence_span,
                span_verified=result.verified,
                verify_note=result.note,
                from_cache=completion.from_cache,
                tokens_in=completion.tokens_in,
                tokens_out=completion.tokens_out,
                cost_usd=cost,
                latency_ms=completion.latency_ms,
            )
        )
    return rows


def persist(conn: sqlite3.Connection, run_id: str, source_run_id: str, row: FieldExtraction) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO extraction "
        "(run_id, source_run_id, review, work_id, field_name, value, evidence_span, "
        " span_verified, verify_note, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (
            run_id,
            source_run_id,
            row.review,
            row.work_id,
            row.field_name,
            row.value,
            row.evidence_span,
            int(row.span_verified),
            row.verify_note,
            datetime.now(timezone.utc).isoformat(),
        ),
    )


def to_jsonl(row: FieldExtraction) -> str:
    return json.dumps(asdict(row), ensure_ascii=False)
