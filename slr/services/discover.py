"""Open-web paper discovery: OpenAlex search, then this project's own
ask -> validate shape -> verify quote extraction and gap discovery over
whatever comes back. Reuses ``extract.py``/``gap.py`` unchanged -- they
only need a title and an abstract, and don't care whether a record came
from the ingested SYNERGY corpus or a live web search.

This is explicitly not part of the evaluation corpus: discovered records
carry ``review="_discover"`` (never a real review name) and are never
written to the ``work`` table, so they can't be mistaken for, or silently
mixed into, a reported figure. Same spirit as ``POST /query/screen``'s
``api-*`` run_id convention -- an interactive feature, not a number for
the report.

OpenAlex's abstracts are legally redistributable for roughly half of
indexed works (publisher restrictions withhold the rest, via a null
``abstract_inverted_index``). Records without one are filtered out here
rather than handed to extraction with nothing to extract from.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass

import httpx

from slr.adapters.llm import Meter, Provider
from slr.services.extract import FieldExtraction, extract_record
from slr.services.extract_fulltext import FullTextExtraction, extract_fulltext_record
from slr.services.gap import GapExtraction, extract_gap
from slr.services.screen import Decision, screen_record

DISCOVER_REVIEW = "_discover"
OPENALEX_WORKS_URL = "https://api.openalex.org/works"
MIN_ABSTRACT_CHARS = 200


def criteria_prompt_version(base: str, criteria: str) -> str:
    """``screen_v1`` plus a short hash of the criteria text.

    The response cache is keyed on (model, prompt_version, review, work_id).
    On the ingested corpus a review's criteria are pinned, so that key is
    stable. Here the criteria come from whoever is sitting at the dashboard
    and change between sessions, which would make two different requests for
    the same paper collide on one cache key -- and the request fingerprint
    would then correctly raise ``CacheMismatch`` and abort a query the user
    did nothing wrong in.

    Folding the criteria into the version string gives each distinct set its
    own cache namespace. Note what this is *not*: the cache is still checked
    before every call, exactly as the budget rules require. Re-running the
    same topic with the same criteria is still served from cache for free.
    Only a genuinely different question is treated as a different request.
    """
    digest = hashlib.sha256(criteria.strip().encode("utf-8")).hexdigest()[:12]
    return f"{base}+adhoc-{digest}"


def reconstruct_abstract(inverted_index: dict[str, list[int]] | None) -> str | None:
    """OpenAlex stores abstracts as {word: [positions]} instead of plain
    text (a side effect of how they're licensed to redistribute it)."""
    if not inverted_index:
        return None
    positions: dict[int, str] = {}
    for word, idxs in inverted_index.items():
        for i in idxs:
            positions[i] = word
    if not positions:
        return None
    return " ".join(positions[i] for i in range(max(positions) + 1))


def search_openalex(
    query: str,
    *,
    limit: int = 5,
    fetch_multiplier: int = 4,
    timeout: float = 15.0,
    client: httpx.Client | None = None,
) -> list[dict]:
    """Search OpenAlex, return up to ``limit`` records that actually have an
    abstract available. Fetches more than requested since roughly half of
    OpenAlex's index has none to redistribute.

    Each record is shaped like a ``work`` row (``work_id``, ``review``,
    ``title``, ``abstract``), so it can be passed straight into
    ``extract_record``/``extract_gap`` without change.
    """
    if not query or not query.strip():
        raise ValueError("query must not be empty")

    params = {
        "search": query,
        "per-page": min(limit * fetch_multiplier, 50),
        # doi is requested so a caller can look the paper up in Europe PMC
        # for full text; without it only a fuzzy title match is possible.
        "select": "id,doi,title,abstract_inverted_index,publication_year,primary_location",
    }
    mailto = os.getenv("OPENALEX_MAILTO")
    if mailto:
        params["mailto"] = mailto

    owns_client = client is None
    client = client or httpx.Client()
    try:
        resp = client.get(OPENALEX_WORKS_URL, params=params, timeout=timeout)
        resp.raise_for_status()
        payload = resp.json()
    finally:
        if owns_client:
            client.close()

    results: list[dict] = []
    for w in payload.get("results", []):
        abstract = reconstruct_abstract(w.get("abstract_inverted_index"))
        if not abstract or len(abstract) < MIN_ABSTRACT_CHARS:
            continue
        loc = w.get("primary_location") or {}
        results.append(
            {
                "work_id": w["id"],
                "review": DISCOVER_REVIEW,
                "title": w.get("title"),
                "abstract": abstract,
                "year": w.get("publication_year"),
                "doi": w.get("doi"),
                "source_url": loc.get("landing_page_url"),
            }
        )
        if len(results) >= limit:
            break
    return results


@dataclass
class DiscoverPaper:
    """One discovered paper: the screening decision, if criteria were given,
    then the extracted fields and the gap check.

    ``decision`` is ``None`` when no criteria were supplied — there is nothing
    to screen against, so the paper is reported without an include/exclude
    call rather than with a guessed one. ``fields`` and ``gap`` are ``None``
    when the paper was screened out, mirroring the ingested pipeline, where
    extraction only ever reads a screening run's verified includes.
    """

    work_id: str
    title: str | None
    year: int | None
    source_url: str | None
    fields: list[FieldExtraction] | None
    gap: GapExtraction | None
    decision: Decision | None = None

    # Full text, when it was asked for and Europe PMC had it. ``fulltext``
    # is the five model-extracted fields, each with a verified quote;
    # ``tables``, ``equations`` and ``figures`` are parsed straight from the
    # publisher's XML with no model involved, and are exact. ``fulltext_note``
    # says why there is nothing here when there isn't -- "paywalled" and
    # "not indexed" are facts about the world, not failures of this code.
    fulltext: list["FullTextExtraction"] | None = None
    tables: list[dict] | None = None
    equations: list[str] | None = None
    figures: list[dict] | None = None
    fulltext_note: str = ""

    @property
    def included(self) -> bool:
        """Verified include. An unverified decision is a referral, not a yes."""
        return bool(
            self.decision
            and self.decision.decision == "include"
            and self.decision.span_verified
        )


def run_discover(
    conn,
    query: str,
    *,
    provider: Provider,
    extract_template: str,
    gap_template: str,
    meter: Meter,
    limit: int = 5,
    extract_prompt_version: str = "extract_v1",
    gap_prompt_version: str = "gap_v1",
    use_cache: bool = True,
    candidates: list[dict] | None = None,
    criteria: str | None = None,
    screen_template: str | None = None,
    screen_prompt_version: str = "screen_v1",
    fulltext_template: str | None = None,
    fetch_full_text=None,
) -> list[DiscoverPaper]:
    """Search the open web for ``query``, then run every result through the
    same verified pipeline the rest of this project uses on its ingested
    corpus.

    Give ``criteria`` and ``screen_template`` together and every result is
    screened first, against whatever eligibility criteria the user wrote,
    using ``screen.screen_record`` unchanged — it already takes criteria as
    a plain string, so an ad-hoc question needs no separate code path. Only
    papers whose include decision verified go on to extraction and gap
    discovery, exactly as ``extract_harness`` only ever reads a screening
    run's verified includes.

    Without criteria there is nothing to screen against, so every result is
    extracted and gap-checked and ``decision`` stays ``None``. Guessing an
    include/exclude with no stated criteria would be the one thing this
    project refuses to do.

    ``candidates`` lets a caller (tests, or a future non-OpenAlex source)
    supply records directly instead of calling OpenAlex.
    """
    if (criteria is None) != (screen_template is None):
        raise ValueError("criteria and screen_template must be given together")
    if criteria is not None and not criteria.strip():
        raise ValueError("criteria must not be empty")

    # Injected so tests never touch the network, same reason ``candidates``
    # exists for the OpenAlex call.
    if fetch_full_text is None:
        from slr.adapters.fulltext import get_full_text as fetch_full_text

    rows = candidates if candidates is not None else search_openalex(query, limit=limit)
    screening = criteria is not None
    version = (
        criteria_prompt_version(screen_prompt_version, criteria) if screening else None
    )

    results = []
    for row in rows:
        decision = None
        if screening:
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
            # Screened out, or referred to a human. Either way there is no
            # verified include to extract from, so stop here for this paper
            # rather than extracting data from a paper the criteria reject.
            if not (decision.decision == "include" and decision.span_verified):
                results.append(
                    DiscoverPaper(
                        work_id=row["work_id"],
                        title=row["title"],
                        year=row.get("year"),
                        source_url=row.get("source_url"),
                        fields=None,
                        gap=None,
                        decision=decision,
                    )
                )
                continue

        fields = extract_record(
            row,
            provider=provider,
            template=extract_template,
            meter=meter,
            conn=conn,
            prompt_version=extract_prompt_version,
            temperature=0.0,
            max_tokens=512,
            seed=42,
            use_cache=use_cache,
        )
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
        paper = DiscoverPaper(
            work_id=row["work_id"],
            title=row["title"],
            year=row.get("year"),
            source_url=row.get("source_url"),
            fields=fields,
            gap=gap,
            decision=decision,
        )

        if fulltext_template is not None:
            _attach_full_text(
                paper,
                row,
                provider=provider,
                template=fulltext_template,
                meter=meter,
                conn=conn,
                use_cache=use_cache,
                fetch=fetch_full_text,
            )

        results.append(paper)
    return results


def _attach_full_text(
    paper: DiscoverPaper,
    row: dict,
    *,
    provider: Provider,
    template: str,
    meter: Meter,
    conn,
    use_cache: bool,
    fetch,
) -> None:
    """Look the paper up in Europe PMC and extract from its full text.

    Never raises. Every way this can come back empty -- no DOI, not
    indexed, paywalled, network down -- is recorded as a note rather than
    an exception, because none of them is a fault in this project and all
    of them are normal for most papers. Coverage is the headline limitation
    of this feature and it should be visible, not swallowed.
    """
    doi = (row.get("doi") or "").strip()
    title = row.get("title")
    if not doi and not title:
        paper.fulltext_note = "no DOI or title to look up"
        return

    try:
        full_text, availability = fetch(doi=doi or None, title=title)
    except Exception as exc:  # network, timeout, malformed XML
        paper.fulltext_note = f"full-text lookup failed: {exc}"
        return

    if full_text is None:
        paper.fulltext_note = availability.reason or "no full text available"
        return

    paper.tables = [t.as_dict() for t in full_text.tables]
    paper.equations = list(full_text.equations)
    paper.figures = [f.as_dict() for f in full_text.figures]

    try:
        paper.fulltext = extract_fulltext_record(
            full_text,
            work_id=paper.work_id,
            review=DISCOVER_REVIEW,
            provider=provider,
            template=template,
            meter=meter,
            conn=conn,
            use_cache=use_cache,
        )
    except Exception as exc:
        paper.fulltext_note = f"full-text extraction failed: {exc}"
        return

    verified = sum(1 for f in paper.fulltext if f.span_verified)
    paper.fulltext_note = (
        f"full text from {availability.pmcid}: {verified} of {len(paper.fulltext)} "
        f"fields verified, {len(paper.tables)} tables, {len(paper.equations)} equations"
    )
