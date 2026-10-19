"""Suggest the papers worth reading for one research question.

The product path, start to finish:

1. search OpenAlex for a pool of candidates (only those with an abstract);
2. rank the pool by how close each paper is to the question, using the same
   SPECTER2 embeddings the dense retrieval arm uses;
3. for the top ``n``, ask the model two things, each answered with a quote
   that is checked verbatim against the abstract: does this paper address
   the question, and does it state a research gap?
4. rank the stated gaps by how close they are to the question, so a
   researcher can see whether other authors already name their question as
   open.

The researcher then picks which suggestions to read in full; that stage is
``POST /discover/fulltext``, unchanged.

The similarity score is a ranking signal, not a measurement of relevance.
Nothing here is scored against ground truth, because there is none for a
question typed a minute ago. Records carry ``review="_discover"`` and are
never written to ``work``, the same boundary ``discover.py`` keeps.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from slr.adapters.llm import Meter, Provider
from slr.services.discover import criteria_prompt_version, search_openalex
from slr.services.gap import GapExtraction, extract_gap
from slr.services.screen import Decision, screen_record

DEFAULT_SUGGESTIONS = 20
DEFAULT_POOL = 50


def relevance_criteria(question: str) -> str:
    """The question, phrased as eligibility criteria for ``screen_v1``.

    ``screen_record`` already judges a paper against criteria given as plain
    sentences, so "is this relevant to my question?" needs no new prompt: the
    question becomes the inclusion rule. ``criteria_prompt_version`` then
    gives every distinct question its own cache namespace.
    """
    return (
        f"Include papers whose title and abstract directly address this research question: "
        f"{question.strip()}\n"
        "Exclude papers that only mention the topic in passing or study a different question."
    )


def _unit(vectors: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return vectors / norms


def similarities(question: str, texts: list[str], embedder) -> list[float]:
    """Cosine similarity of each text to the question, in input order."""
    if not texts:
        return []
    vectors = _unit(np.asarray(embedder.encode([question, *texts]), dtype=float))
    return [float(x) for x in vectors[1:] @ vectors[0]]


def _paper_text(row: dict, sep: str = " [SEP] ") -> str:
    # SPECTER2's own input convention: title, separator, abstract.
    return f"{row.get('title') or ''}{sep}{row.get('abstract') or ''}"


@dataclass
class Suggestion:
    row: dict
    similarity: float | None
    decision: Decision
    gap: GapExtraction
    gap_similarity: float | None = None

    @property
    def relevant(self) -> bool:
        """Verified include. An unverified include is a referral, not a yes."""
        return self.decision.decision == "include" and bool(self.decision.span_verified)


@dataclass
class SuggestResult:
    question: str
    n_candidates: int
    ranking: str  # "specter2" | "openalex"
    ranking_note: str
    suggestions: list[Suggestion]


def _order(s: Suggestion) -> tuple:
    """Verified relevant first, then referrals, then verified not-relevant.

    Within each group, closest to the question first. Same reading order the
    rest of the product uses: what the system backs, then what it could not
    answer, then what it set aside.
    """
    group = 0 if s.relevant else (1 if not s.decision.span_verified else 2)
    return (group, -(s.similarity if s.similarity is not None else 0.0))


def suggest(
    conn,
    question: str,
    *,
    provider: Provider,
    screen_template: str,
    gap_template: str,
    meter: Meter,
    n: int = DEFAULT_SUGGESTIONS,
    pool: int = DEFAULT_POOL,
    embedder=None,
    candidates: list[dict] | None = None,
    screen_prompt_version: str = "screen_v1",
    gap_prompt_version: str = "gap_v1",
    use_cache: bool = True,
) -> SuggestResult:
    """Search, rank by closeness to ``question``, then judge the top ``n``.

    ``embedder`` is anything with ``encode(list[str]) -> ndarray``. When it is
    missing or fails, the pool keeps OpenAlex's own relevance order and the
    result says so in ``ranking_note``: a slower ranking is not a reason to
    return nothing, but a different one must not be passed off as the same.
    ``candidates`` replaces the OpenAlex call, for tests.
    """
    if not question or not question.strip():
        raise ValueError("question must not be empty")

    rows = (
        candidates
        if candidates is not None
        else search_openalex(question, limit=pool, per_page=50, pages=2)
    )

    scores: list[float | None] = [None] * len(rows)
    ranking, note = "openalex", "Ranked by OpenAlex's search relevance."
    if embedder is not None and rows:
        try:
            scores = similarities(question, [_paper_text(r) for r in rows], embedder)
            ranking = "specter2"
            note = "Ranked by SPECTER2 similarity between your question and each title and abstract."
        except Exception as exc:  # model missing, out of memory, bad weights
            note = f"SPECTER2 was unavailable ({exc}); kept OpenAlex's search relevance order."

    order = sorted(
        range(len(rows)),
        key=lambda i: (-(scores[i]) if scores[i] is not None else 0.0, i),
    )
    top = [(rows[i], scores[i]) for i in order[:n]]

    criteria = relevance_criteria(question)
    version = criteria_prompt_version(screen_prompt_version, criteria)
    suggestions: list[Suggestion] = []
    for row, score in top:
        decision = screen_record(
            row,
            provider=provider,
            template=screen_template,
            criteria=criteria,
            meter=meter,
            conn=conn,
            prompt_version=version,
            temperature=0.0,
            max_tokens=512,
            seed=42,
            use_cache=use_cache,
        )
        # Commit each cached answer as it arrives. Left open, this one
        # transaction held SQLite's write lock for the whole request (minutes),
        # so a second search failed with "database is locked" -- and the
        # answers rolled back with the request instead of being cached.
        conn.commit()
        gap = extract_gap(
            row,
            provider=provider,
            template=gap_template,
            meter=meter,
            conn=conn,
            prompt_version=gap_prompt_version,
            temperature=0.0,
            max_tokens=512,
            seed=42,
            use_cache=use_cache,
        )
        conn.commit()
        suggestions.append(Suggestion(row=row, similarity=score, decision=decision, gap=gap))

    # Only a gap whose quote verified is compared with the question: an
    # unverified one is not a statement anyone made.
    stated = [s for s in suggestions if s.gap.value == "gap_stated" and s.gap.span_verified]
    if ranking == "specter2" and stated:
        try:
            for s, sim in zip(stated, similarities(question, [s.gap.evidence_span for s in stated], embedder)):
                s.gap_similarity = sim
        except Exception:
            pass

    suggestions.sort(key=_order)
    return SuggestResult(
        question=question,
        n_candidates=len(rows),
        ranking=ranking,
        ranking_note=note,
        suggestions=suggestions,
    )
