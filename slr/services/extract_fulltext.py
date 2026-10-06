"""Extraction over a paper's full text, not just its abstract.

The sibling of ``extract.py``, with the same three stages -- ask, validate
shape, verify quote -- pointed at the body of a paper instead of its
abstract. The fields are the ones that only exist in full text: the
statistical result and its interval, the methods behind it, the sample, and
the limitations the authors state.

**What is and is not model output.** A caller gets two kinds of thing back
and they must not be confused:

* ``tables``, ``equations`` and ``figure_captions`` come from
  ``adapters.fulltext``, parsed out of the publisher's own XML. No model
  touched them, so there is nothing to verify and nothing to doubt -- a
  cell is the cell. ``FullTextExtraction`` does not carry them; they stay
  on the ``FullText`` object, precisely so a reader of this module is never
  tempted to treat an exact table as a model claim or vice versa.
* The five fields below *are* model output, and every one of them is
  withheld unless its quote is found verbatim in the paper.

**Why spans are verified against the body, not the whole document.** The
source for verification is the body prose with tables stripped out. A model
that quotes "54.2" from a table cell and presents it as a sentence from the
Discussion is making a claim the paper does not make, and the verifier
should catch that rather than wave it through because the characters appear
somewhere in the file.

**There is no ground truth for any of this.** SYNERGY publishes which
papers the original reviewers included; nothing publishes the correct
effect size for a paper. So this module can report how often a quote
verifies, and cannot report how often a value is right. Everything here is
outside the evaluation corpus for that reason -- see ``run_fulltext`` and
the ``_discover`` convention it follows.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, ValidationError

from slr.adapters.fulltext import FullText
from slr.adapters.llm import (
    CacheMismatch,
    Completion,
    Meter,
    Provider,
    cache_key,
    request_fingerprint,
)
from slr.services.verify import verify_span

FIELDS = [
    "primary_outcome",
    "effect_size",
    "statistical_methods",
    "sample_characteristics",
    "limitations",
]

NOT_STATED = "not_stated"

_FIELD_SCHEMA = {
    "type": "object",
    "properties": {"value": {"type": "string"}, "evidence_span": {"type": "string"}},
    "required": ["value", "evidence_span"],
}

# Passed explicitly: a provider's default RESPONSE_SCHEMA is screening-shaped.
FULLTEXT_SCHEMA = {
    "type": "object",
    "properties": {name: _FIELD_SCHEMA for name in FIELDS},
    "required": FIELDS,
}

# Full text is long. Sending an entire paper would blow the context window of
# a 7B local model and cost real money on a paid one, so the prompt gets the
# sections that carry these fields, capped. The cap is generous enough that
# truncation is rare and is reported when it happens -- a field marked
# not_stated because its sentence was cut off is a different failure from
# one the paper genuinely does not state.
MAX_PROMPT_CHARS = 24_000


@dataclass
class FullTextExtraction:
    """One field, extracted from one paper's full text."""

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

    def as_dict(self) -> dict:
        return asdict(self)


class FieldAnswer(BaseModel):
    value: str
    evidence_span: str


class FullTextResponse(BaseModel):
    """The shape a response must have. Anything else is an error, not a guess."""

    primary_outcome: FieldAnswer
    effect_size: FieldAnswer
    statistical_methods: FieldAnswer
    sample_characteristics: FieldAnswer
    limitations: FieldAnswer


def load_prompt_template(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(f"prompt template not found: {path}")
    return path.read_text(encoding="utf-8")


@dataclass
class PromptSource:
    """The text sent to the model, and the text a span is verified against.

    These are the same string. Keeping them as one object rather than two
    arguments is deliberate: if they ever drift apart, a model could be
    shown text it is then forbidden from quoting, and every failure would
    be the harness's fault rather than the model's.
    """

    text: str
    truncated: bool
    chars_available: int


def build_source(full_text: FullText, *, max_chars: int = MAX_PROMPT_CHARS) -> PromptSource:
    """The prose a model may quote from, in the order it is most likely to
    need it.

    Results and Limitations come first, because that is where four of the
    five fields live, so truncation eats the Introduction rather than the
    numbers. Tables are excluded -- see the module docstring.
    """
    parts: list[str] = []
    seen: set[int] = set()

    for section in full_text.sections:
        title = (section.title or "").lower()
        if any(k in title for k in ("result", "finding", "limitation", "discussion")):
            parts.append(f"{section.title}\n{section.text}" if section.title else section.text)
            seen.add(id(section))
    for section in full_text.sections:
        if id(section) in seen:
            continue
        parts.append(f"{section.title}\n{section.text}" if section.title else section.text)

    joined = "\n\n".join(p for p in parts if p.strip()).strip()
    available = len(joined)
    if available > max_chars:
        return PromptSource(text=joined[:max_chars], truncated=True, chars_available=available)
    return PromptSource(text=joined, truncated=False, chars_available=available)


def build_prompt(template: str, *, title: str | None, body: str) -> str:
    return template.format(title=(title or "").strip(), body=body.strip())


def _error_rows(
    work_id: str, review: str, *, verify_note: str, error: str
) -> list[FullTextExtraction]:
    return [
        FullTextExtraction(
            work_id=work_id,
            review=review,
            field_name=name,
            value=None,
            evidence_span=None,
            span_verified=False,
            verify_note=verify_note,
            from_cache=False,
            tokens_in=0,
            tokens_out=0,
            cost_usd=0.0,
            latency_ms=0,
            error=error,
        )
        for name in FIELDS
    ]


def extract_fulltext_record(
    full_text: FullText,
    *,
    work_id: str,
    review: str,
    provider: Provider,
    template: str,
    meter: Meter,
    conn: sqlite3.Connection,
    prompt_version: str = "extract_fulltext_v1",
    temperature: float = 0.0,
    max_tokens: int = 1024,
    seed: int | None = 42,
    use_cache: bool = True,
    max_chars: int = MAX_PROMPT_CHARS,
    on_completion: Callable[[str, Completion], None] | None = None,
) -> list[FullTextExtraction]:
    """Extract all five fields from one paper. Never raises for model failure.

    Raises ``CacheMismatch`` when a cached response came from a different
    request -- the same contract every other service here keeps.
    """
    source = build_source(full_text, max_chars=max_chars)
    if not source.text:
        return _error_rows(work_id, review, verify_note="no_body_text", error="no prose to read")

    prompt = build_prompt(template, title=full_text.title, body=source.text)
    fingerprint = request_fingerprint(
        prompt,
        model=provider.model,
        temperature=temperature,
        max_tokens=max_tokens,
        seed=seed,
        response_schema=FULLTEXT_SCHEMA,
    )
    key = cache_key(provider.model, prompt_version, review, work_id)
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
                    f"{review}/{work_id}: the cached response for prompt version "
                    f"{prompt_version!r} came from a different request. Bump the "
                    f"prompt version, or delete that version's cached rows."
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
                response_schema=FULLTEXT_SCHEMA,
            )
        except Exception as exc:  # provider errors are data, not crashes
            return _error_rows(work_id, review, verify_note="provider_error", error=str(exc))
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

    if on_completion:
        on_completion(prompt, completion)

    cost = meter.record(completion)

    try:
        parsed = FullTextResponse.model_validate_json(completion.text)
    except ValidationError as exc:
        return _error_rows(work_id, review, verify_note="schema_validation_failed", error=str(exc))

    rows: list[FullTextExtraction] = []
    for name in FIELDS:
        answer: FieldAnswer = getattr(parsed, name)
        if answer.value.strip().lower() == NOT_STATED:
            rows.append(
                FullTextExtraction(
                    work_id=work_id,
                    review=review,
                    field_name=name,
                    value=NOT_STATED,
                    evidence_span=None,
                    span_verified=False,
                    # A field the paper doesn't state, and one whose sentence
                    # was cut off by the cap, are different outcomes.
                    verify_note=(
                        "not_stated_possibly_truncated" if source.truncated else NOT_STATED
                    ),
                    from_cache=completion.from_cache,
                    tokens_in=completion.tokens_in,
                    tokens_out=completion.tokens_out,
                    cost_usd=cost,
                    latency_ms=completion.latency_ms,
                )
            )
            continue

        # Verified against exactly the text the model was shown.
        result = verify_span(answer.evidence_span, source.text)
        rows.append(
            FullTextExtraction(
                work_id=work_id,
                review=review,
                field_name=name,
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
