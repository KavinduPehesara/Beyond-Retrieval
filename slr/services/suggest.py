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

from collections.abc import Callable
from dataclasses import dataclass, field

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
class Arm:
    """One model to put the papers to, with its own spend ceiling.

    Each arm meters itself, so one vendor's spend is never charged against
    another's ceiling and each cost can be reported on its own.
    """

    label: str  # "ChatGPT"
    model: str  # "gpt-5-nano"
    provider: Provider
    meter: Meter


@dataclass
class Verdict:
    """What one model said about one paper."""

    label: str  # "ChatGPT"
    model: str  # "gpt-5-nano"
    decision: Decision
    gap: GapExtraction

    @property
    def says_relevant(self) -> bool:
        return self.decision.decision == "include" and bool(self.decision.span_verified)


AGREED = "agreed"  # every arm substantiated the same answer
SPLIT = "split"  # the arms substantiated opposite answers
PARTIAL = "partial"  # an arm could not substantiate its answer, so no comparison
SINGLE = "single"  # only one arm ran


@dataclass
class Suggestion:
    row: dict
    similarity: float | None
    decision: Decision
    gap: GapExtraction
    gap_similarity: float | None = None
    #: One per arm, in the order they ran. Empty on the single-model path.
    verdicts: list[Verdict] = field(default_factory=list)
    agreement: str = SINGLE
    #: Which arms stated a gap, by label. A gap found by one model only is
    #: still shown -- see ``_combine`` for why the union is used here.
    gap_sources: list[str] = field(default_factory=list)

    @property
    def relevant(self) -> bool:
        """A verified include that every arm substantiated the same way.

        Three different things keep a paper out of this group, and the
        distinction between them is the whole argument of this project. An
        unverified include is a referral: no quote, no claim. A split is two
        models that both produced a quote and disagreed. A partial is one
        model that could not substantiate itself, so the second opinion
        never arrived. All three are handed back; only the first is what the
        literature would call an error.
        """
        if self.agreement in (SPLIT, PARTIAL):
            return False
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


def _progress_fn(on_progress: Callable[[str, int, int], None] | None):
    def progress(stage: str, done: int, total: int) -> None:
        if on_progress is None:
            return
        try:
            on_progress(stage, done, total)
        except Exception:
            # A caller's progress display must never take down the search.
            pass

    return progress


def _rank(
    question: str,
    *,
    n: int,
    pool: int,
    embedder,
    candidates: list[dict] | None,
    progress: Callable[[str, int, int], None],
) -> tuple[list[tuple[dict, float | None]], int, str, str]:
    """Search, then order the pool by closeness to the question.

    Pulled out of ``suggest`` so the cross-checked path can search and embed
    once and then put the same papers to each model. Ranking twice would be
    the expensive half of the work done for nothing, and worse, two arms
    could end up judging two different candidate sets if OpenAlex changed
    between the calls -- which would make a disagreement between them
    unreadable.
    """
    progress("searching", 0, 0)
    rows = (
        candidates
        if candidates is not None
        else search_openalex(question, limit=pool, per_page=50, pages=2)
    )

    scores: list[float | None] = [None] * len(rows)
    ranking, note = "openalex", "Ranked by OpenAlex's search relevance."
    progress("ranking", 0, 0)
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
    return [(rows[i], scores[i]) for i in order[:n]], len(rows), ranking, note


def _ask(
    row: dict,
    *,
    provider: Provider,
    screen_template: str,
    gap_template: str,
    criteria: str,
    screen_version: str,
    gap_prompt_version: str,
    meter: Meter,
    conn,
    use_cache: bool,
) -> tuple[Decision, GapExtraction]:
    """The two questions put to one model about one paper."""
    decision = screen_record(
        row,
        provider=provider,
        template=screen_template,
        criteria=criteria,
        meter=meter,
        conn=conn,
        prompt_version=screen_version,
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
    return decision, gap


def _score_gaps(question: str, suggestions: list[Suggestion], ranking: str, embedder) -> None:
    """Rank stated gaps by closeness to the question, in place.

    Only a gap whose quote verified is compared with the question: an
    unverified one is not a statement anyone made.
    """
    stated = [s for s in suggestions if s.gap.value == "gap_stated" and s.gap.span_verified]
    if ranking != "specter2" or not stated:
        return
    try:
        spans = [s.gap.evidence_span for s in stated]
        for s, sim in zip(stated, similarities(question, spans, embedder)):
            s.gap_similarity = sim
    except Exception:
        pass


def _states_gap(gap: GapExtraction) -> bool:
    """A gap the authors stated, in words found verbatim in their abstract."""
    return gap.value == "gap_stated" and bool(gap.span_verified)


def _combine(row: dict, similarity: float | None, verdicts: list[Verdict]) -> Suggestion:
    """One paper's answer, from however many models were asked.

    Relevance takes the intersection and gaps take the union, deliberately in
    opposite directions. A split verdict on relevance is handed back to the
    reader rather than settled by vote, because with two arms a vote is a coin
    toss wearing a method's clothes. A gap is kept when either model found
    one, because the measured weakness of gap suggestion here is recall, not
    precision: 0.40 to 1.00 across four reviews. Both policies are computed
    rather than assumed in slr/eval/gap_consensus.py, which is where that
    choice is argued and measured.

    The decision shown is always one a model actually returned, never an
    average of two. A quote has to be somebody's quote, or the verifier that
    checked it is checking nothing.
    """
    lead = next((v for v in verdicts if v.says_relevant), verdicts[0])
    stated = [v for v in verdicts if _states_gap(v.gap)]
    substantiated = [v for v in verdicts if v.decision.span_verified]
    if len(verdicts) == 1:
        agreement = SINGLE
    elif len(substantiated) < len(verdicts):
        # An arm whose quote was not found did not say no -- it said nothing
        # that can be checked. Calling that a disagreement would put words in
        # its mouth, and would hide the one failure this project measures.
        agreement = PARTIAL
    elif len({v.says_relevant for v in substantiated}) == 1:
        agreement = AGREED
    else:
        agreement = SPLIT
    return Suggestion(
        row=row,
        similarity=similarity,
        decision=lead.decision,
        gap=stated[0].gap if stated else verdicts[0].gap,
        verdicts=verdicts,
        agreement=agreement,
        gap_sources=[v.label for v in stated],
    )


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
    on_progress: Callable[[str, int, int], None] | None = None,
) -> SuggestResult:
    """Search, rank by closeness to ``question``, then judge the top ``n``.

    ``embedder`` is anything with ``encode(list[str]) -> ndarray``. When it is
    missing or fails, the pool keeps OpenAlex's own relevance order and the
    result says so in ``ranking_note``: a slower ranking is not a reason to
    return nothing, but a different one must not be passed off as the same.
    ``candidates`` replaces the OpenAlex call, for tests.

    ``on_progress(stage, done, total)`` is called as work completes, so a
    caller can show how far along it is rather than a spinner that means
    only "something is happening". It is called after each paper is judged,
    which is the only point at which real progress is known: the stages
    before it are single steps of unpredictable length.

    One model. ``suggest_cross_checked`` puts the same papers to several.
    """
    return suggest_cross_checked(
        conn,
        question,
        arms=[Arm(label="", model="", provider=provider, meter=meter)],
        screen_template=screen_template,
        gap_template=gap_template,
        n=n,
        pool=pool,
        embedder=embedder,
        candidates=candidates,
        screen_prompt_version=screen_prompt_version,
        gap_prompt_version=gap_prompt_version,
        use_cache=use_cache,
        on_progress=on_progress,
    )


def suggest_cross_checked(
    conn,
    question: str,
    *,
    arms: list[Arm],
    screen_template: str,
    gap_template: str,
    n: int = DEFAULT_SUGGESTIONS,
    pool: int = DEFAULT_POOL,
    embedder=None,
    candidates: list[dict] | None = None,
    screen_prompt_version: str = "screen_v1",
    gap_prompt_version: str = "gap_v1",
    use_cache: bool = True,
    on_progress: Callable[[str, int, int], None] | None = None,
) -> SuggestResult:
    """The same papers and the same prompt, put to every arm in ``arms``.

    Searching and embedding happen once; only the model calls repeat. Each
    arm carries its own ``Meter``, so one vendor's spend cannot be charged
    against another's ceiling and the cost of each is reportable on its own.

    What a second model buys is a second rater, and therefore a disagreement
    worth showing. It does not establish correctness: two models can agree
    and both be wrong, and these two share a great deal of training data.
    That caveat belongs wherever this result is displayed.
    """
    if not question or not question.strip():
        raise ValueError("question must not be empty")
    if not arms:
        raise ValueError("no model is configured to answer")

    progress = _progress_fn(on_progress)
    top, n_candidates, ranking, note = _rank(
        question, n=n, pool=pool, embedder=embedder, candidates=candidates, progress=progress
    )

    criteria = relevance_criteria(question)
    version = criteria_prompt_version(screen_prompt_version, criteria)
    suggestions: list[Suggestion] = []
    # Progress counts model calls, not papers: with two arms, half the bar
    # moving per paper is what is actually happening.
    total = len(top) * len(arms)
    done = 0
    progress("screening", 0, total)
    for row, score in top:
        verdicts = []
        for arm in arms:
            decision, gap = _ask(
                row,
                provider=arm.provider,
                screen_template=screen_template,
                gap_template=gap_template,
                criteria=criteria,
                screen_version=version,
                gap_prompt_version=gap_prompt_version,
                meter=arm.meter,
                conn=conn,
                use_cache=use_cache,
            )
            verdicts.append(Verdict(label=arm.label, model=arm.model, decision=decision, gap=gap))
            done += 1
            progress("screening", done, total)
        suggestions.append(_combine(row, score, verdicts))

    _score_gaps(question, suggestions, ranking, embedder)
    suggestions.sort(key=_order)
    return SuggestResult(
        question=question,
        n_candidates=n_candidates,
        ranking=ranking,
        ranking_note=note,
        suggestions=suggestions,
    )
