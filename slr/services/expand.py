"""Query expansion: the researcher's question, plus the words it didn't use.

Promised in the proposal (Figure 2, "LLM turns the question into search
terms") and missing from the artefact until now: the topic a user typed went
to OpenAlex verbatim, so a review written in one vocabulary never saw papers
written in another.

**The one model stage with nothing to verify, and why that is honest.**
Everywhere else in this project the model makes a claim about a source, and
the claim is withheld unless its quote is found in that source. Here the
model is not describing a paper -- it is proposing words to search with.
There is no source to check them against, so a span verifier would have
nothing to do. The check is empirical instead, and it is stronger: run the
six SYNERGY reviews with and without expansion and count how many of the
papers the original human reviewers included each candidate set actually
retrieves (``slr.eval.expansion_eval``). Terms that do not earn their place
show up as a number that did not move.

**Failure never blocks a search.** A provider error, a malformed response or
an empty list all return the question unchanged, with the reason recorded.
Expansion is an improvement to a search, not a precondition for one.
"""

from __future__ import annotations

import hashlib
import json
import re
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

#: Expansion is not about one record, and never touches the evaluation
#: corpus. The cache is keyed by review like everything else, so it needs a
#: review name of its own -- the same convention ``discover`` uses.
EXPAND_REVIEW = "_expand"

MAX_TERMS = 8
MAX_TERM_WORDS = 6
MAX_TERM_CHARS = 60

# Passed explicitly to provider.complete() -- a provider's own default schema
# is screening-shaped and has nothing to do with this.
EXPAND_SCHEMA = {
    "type": "object",
    "properties": {"terms": {"type": "array", "items": {"type": "string"}}},
    "required": ["terms"],
}

# Operators and syntax a search engine would read as instructions rather than
# as words. A model that returns 'AND "deep learning"' is proposing syntax,
# not vocabulary, and OpenAlex would treat it as text anyway.
_SYNTAX = re.compile(r'["()\[\]{}*?:^~]|\b(AND|OR|NOT|NEAR)\b')
_WORD = re.compile(r"\w+", re.UNICODE)


class ExpansionResponse(BaseModel):
    """The shape a response must have. Anything else is an error, not a guess."""

    terms: list[str]


@dataclass
class Expansion:
    """One expansion: what was asked, what came back, and what will be searched."""

    question: str
    terms: list[str]  # accepted terms, after filtering
    query: str  # what to send to the search API
    note: str  # expanded | no_terms | provider_error | schema_validation_failed
    from_cache: bool = False
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    latency_ms: int = 0
    error: str | None = None

    @property
    def expanded(self) -> bool:
        return bool(self.terms)

    def as_dict(self) -> dict:
        return asdict(self)


def load_prompt_template(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(
            f"Prompt template not found: {path}. Prompt versions live in "
            f"prompts/ and are referenced by the expansion prompt_version."
        )
    return path.read_text(encoding="utf-8")


def build_prompt(template: str, *, question: str) -> str:
    return template.format(question=question.strip())


def question_key(question: str) -> str:
    """A stable cache id for a question.

    The cache is keyed on (model, prompt version, review, record). A question
    is not a record, so it stands in as one: the same question asked twice
    costs one call, and a different question is a different key.
    """
    return hashlib.sha256(" ".join(question.split()).casefold().encode("utf-8")).hexdigest()[:32]


def accept_terms(question: str, terms: list[str], *, max_terms: int = MAX_TERMS) -> list[str]:
    """Keep the terms that are worth searching, in the order proposed.

    Dropped: search syntax, terms longer than a phrase, duplicates, and
    anything whose words the question already contains -- those are searched
    regardless, and repeating them only makes the query longer.
    """
    asked = {w.casefold() for w in _WORD.findall(question)}
    kept: list[str] = []
    seen: set[str] = set()
    for term in terms:
        text = " ".join(str(term).split())
        if not text or len(text) > MAX_TERM_CHARS or _SYNTAX.search(text):
            continue
        words = _WORD.findall(text)
        if not words or len(words) > MAX_TERM_WORDS:
            continue
        folded = text.casefold()
        if folded in seen or all(w.casefold() in asked for w in words):
            continue
        seen.add(folded)
        kept.append(text)
        if len(kept) >= max_terms:
            break
    return kept


def expanded_query(question: str, terms: list[str]) -> str:
    """The question first, then the extra terms.

    The researcher's own words lead: OpenAlex ranks on the whole string, and
    burying the question under eight synonyms would answer a question nobody
    asked.
    """
    return " ".join([question.strip(), *terms]).strip() if terms else question.strip()


def expand_query(
    question: str,
    *,
    provider: Provider,
    template: str,
    meter: Meter,
    conn: sqlite3.Connection,
    prompt_version: str = "expand_v1",
    temperature: float = 0.0,
    max_tokens: int = 256,
    seed: int | None = None,
    use_cache: bool = True,
    max_terms: int = MAX_TERMS,
) -> Expansion:
    """Ask the model for extra search terms. Never raises for model failure.

    Does raise ``CacheMismatch`` when a cached response was produced by a
    different request -- same contract as every other service here.
    """
    if not question or not question.strip():
        raise ValueError("question must not be empty")

    prompt = build_prompt(template, question=question)
    fingerprint = request_fingerprint(
        prompt,
        model=provider.model,
        temperature=temperature,
        max_tokens=max_tokens,
        seed=seed,
        response_schema=EXPAND_SCHEMA,
    )
    key = cache_key(provider.model, prompt_version, EXPAND_REVIEW, question_key(question))
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
                    f"The cached expansion for prompt version {prompt_version!r} came "
                    f"from a different request. Bump the expansion prompt_version, or "
                    f"delete that version's cached rows, before running."
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
                response_schema=EXPAND_SCHEMA,
            )
        except Exception as exc:  # provider errors are data, not crashes
            return Expansion(
                question=question.strip(),
                terms=[],
                query=question.strip(),
                note="provider_error",
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

    try:
        parsed = ExpansionResponse.model_validate_json(completion.text)
    except ValidationError as exc:
        return Expansion(
            question=question.strip(),
            terms=[],
            query=question.strip(),
            note="schema_validation_failed",
            from_cache=completion.from_cache,
            tokens_in=completion.tokens_in,
            tokens_out=completion.tokens_out,
            cost_usd=cost,
            latency_ms=completion.latency_ms,
            error=str(exc)[:500],
        )

    terms = accept_terms(question, parsed.terms, max_terms=max_terms)
    return Expansion(
        question=question.strip(),
        terms=terms,
        query=expanded_query(question, terms),
        note="expanded" if terms else "no_terms",
        from_cache=completion.from_cache,
        tokens_in=completion.tokens_in,
        tokens_out=completion.tokens_out,
        cost_usd=cost,
        latency_ms=completion.latency_ms,
    )


def to_json(expansion: Expansion) -> str:
    return json.dumps(expansion.as_dict(), ensure_ascii=False)
