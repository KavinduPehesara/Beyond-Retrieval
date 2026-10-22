"""Research gaps stated in the body of a paper, not just in its abstract.

``gap.py`` reads abstracts, which is where this project's measured
gap-discovery figures come from. Most abstracts state no gap at all: the
sentence a researcher actually wants -- "we did not examine whether X", "no
trial has compared Y" -- is usually in the Discussion or the last paragraph
of the Conclusion, and never survives into the 250-word summary. So a reader
who has gone to the trouble of opening the full paper should be shown those
sentences too.

Same three stages as every other service here: ask, validate the shape,
verify the quote. Two differences from its abstract-reading sibling:

* **A paper states several gaps, an abstract states at most one.** This
  returns a list, each entry carrying its own quote, and each quote
  verified on its own. One invented sentence costs its own statement, not
  the whole set.
* **The section is reported.** A gap quoted from the Discussion and one
  quoted from the Introduction are different claims -- the first is the
  authors on their own work, the second is often them describing someone
  else's. Naming the section lets a reader tell them apart without
  reopening the paper.

Nothing here is scored. There is no published answer sheet saying which
sentences in a paper are its real gaps, so this reports what verified and
never how often it was right -- the same boundary ``extract_fulltext`` keeps.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import asdict, dataclass, field
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
from slr.services.extract_fulltext import MAX_PROMPT_CHARS, PromptSource
from slr.services.verify import normalise, verify_span

MAX_GAPS = 5

#: Sections where authors say what is left undone, best first. Deliberately
#: not the same ordering ``extract_fulltext.build_source`` uses: that one
#: leads with Results because that is where its numbers are. Changing that
#: function to suit this one would alter the text every cached extraction
#: was produced from, and the cache would refuse every one of them.
_GAP_SECTIONS = ("future", "conclusion", "discussion", "limitation", "implication")

#: A gap statement looks forward: it says something is missing, unresolved,
#: or left for someone else to do. Verification proves a sentence exists in
#: the paper; it cannot prove the sentence states a gap, and on live data the
#: difference showed up immediately -- the model answered with results
#: sentences ("no significant association was found"), each one genuinely in
#: the paper and none of them a gap. So the quote must also carry
#: forward-looking language, checked here rather than trusted from the model.
#: A statement whose quote carries none is withheld and counted, the same way
#: an unverified quote is.
_GAP_CUES = re.compile(
    r"\b("
    r"further (?:research|work|stud\w+|investigation)|future (?:research|work|stud\w+|trial\w*)|"
    r"more (?:research|work|stud\w+|data|evidence)|additional (?:research|work|stud\w+)|"
    r"research is needed|studies are needed|remains? (?:to be|unclear|unknown|unanswered)|"
    r"not (?:yet )?(?:been )?(?:examined|investigated|studied|established|explored|known|clear)|"
    r"we did not (?:examine|investigate|study|assess|measure|address)|"
    r"no (?:stud\w+|trial\w*|research) (?:has|have)|little is known|warrants? further|"
    r"should be (?:examined|investigated|explored|studied|addressed)|"
    r"needs? (?:to be|further)|unanswered|open question"
    r")\b",
    re.I,
)


def quote_states_a_gap(span: str) -> bool:
    """Whether the authors' sentence actually points at something undone."""
    return bool(_GAP_CUES.search(span or ""))


# A sentence ends at punctuation, and also at a line break: section titles
# carry no full stop, so without the second case a heading is swallowed by
# the sentence after it and the candidate reads "Discussion Further research
# is needed...", which is not a sentence the authors wrote.
_SENTENCE = re.compile(r"(?<=[.!?])\s+|\n+")
MAX_CANDIDATES = 12


def candidate_sentences(text: str, *, limit: int = MAX_CANDIDATES) -> list[str]:
    """The sentences in a paper that read like a gap statement.

    Found by the cue vocabulary above, not by a model, and this is the
    heart of the design. Asked to find gaps in 24,000 characters, a small
    local model returns plausible-sounding summaries attached to whatever
    sentence it happened to be looking at: on the first live paper it
    proposed four, three of which quoted results, and missed the one real
    gap sentence the paper contains.

    So the choosing is done here, deterministically, and the model is left
    the job it is good at -- saying in one line what a sentence means. It
    can only quote from this list, which is the same fix this project
    applied to criteria echoes, table cells and boilerplate: control what
    the model may use rather than catching a bad answer afterwards.
    """
    found: list[str] = []
    seen: set[str] = set()
    for raw in _SENTENCE.split(text or ""):
        sentence = " ".join(raw.split())
        if len(sentence) < 25 or not quote_states_a_gap(sentence):
            continue
        folded = normalise(sentence)
        if folded in seen:
            continue
        seen.add(folded)
        found.append(sentence)
        if len(found) >= limit:
            break
    return found


GAP_ITEM_SCHEMA = {
    "type": "object",
    "properties": {"value": {"type": "string"}, "evidence_span": {"type": "string"}},
    "required": ["value", "evidence_span"],
}

# Passed explicitly: a provider's default RESPONSE_SCHEMA is screening-shaped.
GAP_FULLTEXT_SCHEMA = {
    "type": "object",
    "properties": {"gaps": {"type": "array", "items": GAP_ITEM_SCHEMA}},
    "required": ["gaps"],
}


class _GapItem(BaseModel):
    value: str
    evidence_span: str


class GapFullTextResponse(BaseModel):
    """The shape a response must have. Anything else is an error, not a guess."""

    gaps: list[_GapItem]


@dataclass
class StatedGap:
    """One gap the authors state, with the sentence that states it."""

    value: str
    evidence_span: str
    section: str | None  # where in the paper the sentence was found
    verify_note: str

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class GapFullTextResult:
    """Every stated gap found in one paper, and what it cost to find them."""

    work_id: str
    review: str
    gaps: list[StatedGap] = field(default_factory=list)
    n_proposed: int = 0  # what the model offered
    n_withheld: int = 0  # offered, but the quote was not in the paper
    n_unsupported: int = 0  # quoted a real sentence that states no gap
    note: str = ""  # found | none_stated | provider_error | schema_validation_failed
    truncated: bool = False
    chars_shown: int = 0
    chars_available: int = 0
    from_cache: bool = False
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    latency_ms: int = 0
    error: str | None = None

    def as_dict(self) -> dict:
        out = asdict(self)
        out["gaps"] = [g.as_dict() for g in self.gaps]
        return out


def load_prompt_template(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(f"prompt template not found: {path}")
    return path.read_text(encoding="utf-8")


def build_gap_source(full_text: FullText, *, max_chars: int = MAX_PROMPT_CHARS) -> PromptSource:
    """The prose a model may quote a gap from, best sections first.

    Discussion and Conclusion lead, so that truncating a long paper eats the
    Methods rather than the sentences this is looking for. The text returned
    is the text spans are verified against -- one string, for the reason
    ``PromptSource`` exists.
    """
    ranked: list[tuple[int, int, str]] = []
    for position, section in enumerate(full_text.sections):
        title = (section.title or "").lower()
        rank = next(
            (i for i, keyword in enumerate(_GAP_SECTIONS) if keyword in title),
            len(_GAP_SECTIONS),
        )
        text = f"{section.title}\n{section.text}" if section.title else section.text
        if text.strip():
            ranked.append((rank, position, text))

    joined = "\n\n".join(text for _, _, text in sorted(ranked, key=lambda r: (r[0], r[1]))).strip()
    available = len(joined)
    if available > max_chars:
        return PromptSource(text=joined[:max_chars], truncated=True, chars_available=available)
    return PromptSource(text=joined, truncated=False, chars_available=available)


def build_prompt(template: str, *, title: str | None, candidates: list[str]) -> str:
    """Fill the template with the sentences the model is allowed to quote."""
    listed = "\n".join(f"- {sentence}" for sentence in candidates)
    return template.format(title=(title or "").strip(), candidates=listed)


def section_for(span: str, full_text: FullText) -> str | None:
    """Which section a verified quote came from, if it can be placed.

    Compared after the same normalisation the verifier uses, so a sentence
    that verified against the prompt source is found here too.
    """
    needle = normalise(span)
    if not needle:
        return None
    for section in full_text.sections:
        if needle in normalise(section.text):
            return section.title or None
    return None


def _result(work_id: str, review: str, source: PromptSource, **kwargs) -> GapFullTextResult:
    return GapFullTextResult(
        work_id=work_id,
        review=review,
        chars_shown=len(source.text),
        chars_available=source.chars_available,
        truncated=source.truncated,
        **kwargs,
    )


def find_gaps(
    full_text: FullText,
    *,
    work_id: str,
    review: str,
    provider: Provider,
    template: str,
    meter: Meter,
    conn: sqlite3.Connection,
    prompt_version: str = "gap_fulltext_v2",
    temperature: float = 0.0,
    max_tokens: int = 1024,
    seed: int | None = None,
    use_cache: bool = True,
    max_gaps: int = MAX_GAPS,
) -> GapFullTextResult:
    """Find the gaps one paper states. Never raises for model failure.

    Does raise ``CacheMismatch`` when a cached response was produced by a
    different request -- same contract as every other service here.
    """
    source = build_gap_source(full_text)
    if not source.text:
        return _result(work_id, review, source, note="no_body_text")

    candidates = candidate_sentences(source.text)
    if not candidates:
        # No sentence in the paper reads as a gap, so there is nothing for
        # the model to choose between. Asking anyway invites it to invent
        # one, and costs a call to be told what is already known.
        return _result(work_id, review, source, note="none_stated")

    prompt = build_prompt(template, title=full_text.title, candidates=candidates)
    fingerprint = request_fingerprint(
        prompt,
        model=provider.model,
        temperature=temperature,
        max_tokens=max_tokens,
        seed=seed,
        response_schema=GAP_FULLTEXT_SCHEMA,
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
                    f"{review}/{work_id}: the cached full-text gap response for prompt "
                    f"version {prompt_version!r} came from a different request. Bump the "
                    f"prompt version, or delete that version's cached rows, before running."
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
                response_schema=GAP_FULLTEXT_SCHEMA,
            )
        except Exception as exc:  # provider errors are data, not crashes
            return _result(
                work_id, review, source, note="provider_error", error=str(exc)[:500]
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
    usage = dict(
        from_cache=completion.from_cache,
        tokens_in=completion.tokens_in,
        tokens_out=completion.tokens_out,
        cost_usd=cost,
        latency_ms=completion.latency_ms,
    )

    try:
        parsed = GapFullTextResponse.model_validate_json(completion.text)
    except ValidationError as exc:
        return _result(
            work_id,
            review,
            source,
            note="schema_validation_failed",
            error=str(exc)[:500],
            **usage,
        )

    kept: list[StatedGap] = []
    seen: set[str] = set()
    offered = {normalise(sentence) for sentence in candidates}
    withheld = 0
    unsupported = 0
    for item in parsed.gaps:
        if len(kept) >= max_gaps:
            break
        result = verify_span(item.evidence_span, source.text)
        if not result.verified:
            withheld += 1
            continue
        # Verified means the sentence is in the paper. It still has to be one
        # of the sentences offered: a model that reaches past the list and
        # quotes a results sentence elsewhere in the body would otherwise
        # pass, which is the failure this design exists to prevent.
        if normalise(item.evidence_span) not in offered or not quote_states_a_gap(
            item.evidence_span
        ):
            unsupported += 1
            continue
        folded = normalise(item.evidence_span)
        if folded in seen:  # the same sentence offered twice is one gap
            continue
        seen.add(folded)
        kept.append(
            StatedGap(
                value=item.value.strip(),
                evidence_span=item.evidence_span.strip(),
                section=section_for(item.evidence_span, full_text),
                verify_note=result.note,
            )
        )

    return _result(
        work_id,
        review,
        source,
        gaps=kept,
        n_proposed=len(parsed.gaps),
        n_withheld=withheld,
        n_unsupported=unsupported,
        note="found" if kept else "none_stated",
        **usage,
    )
