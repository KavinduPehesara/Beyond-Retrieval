"""Response and request shapes for the API.

Field names match what the services already produce (``span_verified``,
``verify_note``, ...) rather than inventing a parallel vocabulary.
"""

from __future__ import annotations
from typing import Literal

from pydantic import BaseModel, Field

from slr.api.deps import MAX_LIVE_SCREEN


class ReviewSummary(BaseModel):
    review: str
    domain: str | None
    n_records: int
    n_included: int
    prevalence: float
    criteria_status: str
    screen_run: str | None
    extract_run: str | None
    gap_run: str | None


class PaperSummary(BaseModel):
    work_id: str
    title: str | None
    year: int | None
    venue: str | None
    decision: str | None  # include | exclude | unverified | error | None (unscreened)
    confidence: float | None
    span_verified: bool | None


class FieldValue(BaseModel):
    status: str  # verified | not_stated | unverified | missing
    value: str | None = None
    quote: str | None = None
    note: str | None = None


class GapValue(BaseModel):
    status: str  # gap_stated | not_stated | failed | missing
    quote: str | None = None
    rating: str | None = None  # valid | invalid | None (unrated)
    kind: str | None = None  # open | motivating | None
    note: str | None = None


class PaperDetail(PaperSummary):
    doi: str | None
    screen_quote: str | None
    screen_note: str | None
    study_design: FieldValue
    sample_size: FieldValue
    country: FieldValue
    key_finding: FieldValue
    gap: GapValue


class OverrideRequest(BaseModel):
    run_id: str
    review: str
    work_id: str
    decision: str = Field(pattern="^(include|exclude)$")
    rationale: str | None = None


class OverrideResult(BaseModel):
    model_config = {"protected_namespaces": ()}

    work_id: str
    model_decision: str | None
    model_verified: bool
    human_decision: str
    changed: bool


class OverrideSummaryOut(BaseModel):
    n_overrides: int
    n_changed: int
    n_confirmed: int
    override_rate: float | None
    by_model_decision: dict[str, int]


class QueryRequest(BaseModel):
    review: str
    strategy: str = "bm25"
    query_text: str | None = None
    top_n: int = Field(default=20, ge=1, le=200)


class RankedPaper(BaseModel):
    rank: int
    work_id: str
    title: str | None
    year: int | None


class ScreenRequest(BaseModel):
    review: str
    work_ids: list[str] = Field(min_length=1, max_length=MAX_LIVE_SCREEN)
    model: str = "qwen2.5:7b-instruct"
    prompt_version: str = "screen_v1"


class ScreenResult(BaseModel):
    work_id: str
    decision: str
    confidence: float | None
    quote: str | None
    span_verified: bool
    verify_note: str
    from_cache: bool


class GapStatementOut(BaseModel):
    work_id: str
    title: str | None
    status: str
    quote: str | None
    rating: str | None
    kind: str | None


class DiscoverRequest(BaseModel):
    project_id: str | None = Field(default=None, max_length=100)
    query: str = Field(min_length=1)
    limit: int = Field(default=5, ge=1, le=10)
    # Optional. Given, every result is screened against it and only verified
    # includes are extracted. Omitted, nothing is screened -- the system does
    # not invent an include/exclude with no criteria to judge against.
    criteria: str | None = Field(default=None, max_length=4000)
    # Look each paper up in Europe PMC and read its body, not just the
    # abstract. Slower, and most papers won't have open-access full text.
    fulltext: bool = False
    # Ask the model for extra search terms before searching. Off by default:
    # measured over the six reviews it helps on three and hurts on three, so
    # it is offered, not applied.
    expand: bool = False


class ExpansionOut(BaseModel):
    """The search terms the model added, and what was actually searched.

    Shown rather than applied silently: the terms are the model's claim
    about vocabulary, and a reviewer who can see them can tell when one has
    pulled the search into the wrong field.
    """

    terms: list[str]
    query: str
    note: str


class FullTextRequest(BaseModel):
    """Read the full text of papers the reviewer chose, after screening.

    Stage two of the review. The papers are identified by DOI and title
    rather than by any stored id, because nothing about an ad-hoc session
    is persisted -- there is no row to point at, by design.
    """

    papers: list["FullTextTarget"] = Field(min_length=1, max_length=10)
    include_assets: bool = False
    project_id: str | None = Field(default=None, max_length=100)


class FullTextTarget(BaseModel):
    work_id: str
    title: str | None = None
    doi: str | None = None


class TableOut(BaseModel):
    """One table as the publisher printed it. Exact -- no model read this."""

    label: str | None = None
    caption: str | None = None
    rows: list[list[str]] = Field(default_factory=list)
    footnotes: list[str] = Field(default_factory=list)
    cell_spans: list[list[dict]] = Field(default_factory=list)


class FigureOut(BaseModel):
    """A figure's label, caption, and what the paper says about it.

    The image is never fetched or interpreted. A heat map's meaning is in
    the picture, and reading it would need image analysis this system does
    not do. ``mentions`` is the honest substitute: the sentences in the
    body that cite this figure, so a reader gets what the authors say it
    shows, quotable and checkable, without anyone pretending the plot was
    read.
    """

    label: str | None = None
    caption: str | None = None
    mentions: list[str] = Field(default_factory=list)
    asset_refs: list[str] = Field(default_factory=list)
    kind: str = "figure"
    images: list[dict] = Field(default_factory=list)
    analysis_status: str = "needs_human_review"


class ScreenDecisionOut(BaseModel):
    """A screening decision on an ad-hoc paper.

    ``status`` is one of include / exclude / unverified / error, and
    ``span_verified`` is what separates a decision from a referral: an
    include whose quote wasn't found in the abstract is not an include.
    """

    status: str
    confidence: float | None
    quote: str | None
    span_verified: bool
    verify_note: str
    from_cache: bool


class DiscoverPaperOut(BaseModel):
    work_id: str
    abstract: str = ""
    title: str | None
    year: int | None
    source_url: str | None
    # None when the paper was screened out or referred: there is no verified
    # include to extract from, same boundary the ingested pipeline keeps.
    study_design: FieldValue | None = None
    sample_size: FieldValue | None = None
    country: FieldValue | None = None
    key_finding: FieldValue | None = None
    gap: GapValue | None = None
    # None when no criteria were supplied.
    decision: ScreenDecisionOut | None = None

    # --- full text, when it was asked for and Europe PMC had it ----------
    # Model-extracted, each with a verified quote. Same rules as any other
    # field here: an unverified value is not reported.
    primary_outcome: FieldValue | None = None
    effect_size: FieldValue | None = None
    statistical_methods: FieldValue | None = None
    sample_characteristics: FieldValue | None = None
    limitations: FieldValue | None = None
    # Parsed straight from the publisher's XML. No model involved, so these
    # are exact and carry no verification status -- there is nothing to
    # verify. Kept in separate fields from the five above for that reason.
    tables: list[TableOut] | None = None
    equations: list[str] | None = None
    figures: list[FigureOut] | None = None
    # Why there is no full text, when there isn't. "paywalled" and "not
    # indexed" are facts about the paper, not failures.
    fulltext_note: str = ""
    coverage: list[dict] = Field(default_factory=list)
    evidence: dict[str, list[dict]] = Field(default_factory=dict)
    supplements: list[dict] = Field(default_factory=list)
    equation_details: list[dict] = Field(default_factory=list)
    assets_note: str = ""


class LiveReviewerAction(BaseModel):
    work_id: str = Field(min_length=1, max_length=500)
    decision: Literal["include", "exclude", "pending"]
    rationale: str = Field(default="", max_length=4000)
    technique: str = Field(default="", max_length=120)
    domain: str = Field(default="", max_length=120)
    quote: str = Field(default="", max_length=12000)


class DiscoverSessionOut(BaseModel):
    """One ad-hoc review session: the papers, plus the session's own counts.

    These counts are a summary of what the user just ran, not a reported
    figure -- there is no ground truth for an ad-hoc query, so there is no
    recall or accuracy here, only what was found and what verified.
    """

    session_id: str | None = None
    query: str
    criteria: str | None
    n_found: int
    n_screened: int
    n_included: int
    n_excluded: int
    n_referred: int
    n_verified_quotes: int
    n_gaps: int
    papers: list[DiscoverPaperOut]
    # None unless the caller asked for expansion.
    expansion: ExpansionOut | None = None


class FullTextPaperOut(BaseModel):
    """One paper's full-text result, from stage two."""

    work_id: str
    title: str | None = None
    primary_outcome: FieldValue | None = None
    effect_size: FieldValue | None = None
    statistical_methods: FieldValue | None = None
    sample_characteristics: FieldValue | None = None
    limitations: FieldValue | None = None
    tables: list[TableOut] = Field(default_factory=list)
    equations: list[str] = Field(default_factory=list)
    figures: list[FigureOut] = Field(default_factory=list)
    # Why there is nothing here, when there isn't. Paywalled and
    # not-indexed are facts about the paper, not failures of the system.
    note: str = ""
    found: bool = False
    coverage: list[dict] = Field(default_factory=list)
    evidence: dict[str, list[dict]] = Field(default_factory=dict)
    supplements: list[dict] = Field(default_factory=list)
    equation_details: list[dict] = Field(default_factory=list)
    source_url: str | None = None
    assets_note: str = ""


class FullTextSessionOut(BaseModel):
    n_requested: int
    n_with_full_text: int
    papers: list[FullTextPaperOut]


class ProjectName(BaseModel):
    name: str = Field(min_length=1, max_length=120)
