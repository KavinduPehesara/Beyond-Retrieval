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

import os
from dataclasses import dataclass

import httpx

from slr.adapters.llm import Meter, Provider
from slr.services.extract import FieldExtraction, extract_record
from slr.services.gap import GapExtraction, extract_gap

DISCOVER_REVIEW = "_discover"
OPENALEX_WORKS_URL = "https://api.openalex.org/works"
MIN_ABSTRACT_CHARS = 200


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
        "select": "id,title,abstract_inverted_index,publication_year,primary_location",
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
                "source_url": loc.get("landing_page_url"),
            }
        )
        if len(results) >= limit:
            break
    return results


@dataclass
class DiscoverPaper:
    """One discovered paper, with its extracted fields and gap check."""

    work_id: str
    title: str | None
    year: int | None
    source_url: str | None
    fields: list[FieldExtraction]
    gap: GapExtraction


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
) -> list[DiscoverPaper]:
    """Search the open web for ``query``, then run every result through the
    same verified extraction and gap-discovery pipeline the rest of this
    project uses on its ingested corpus.

    ``candidates`` lets a caller (tests, or a future non-OpenAlex source)
    supply records directly instead of calling OpenAlex.
    """
    rows = candidates if candidates is not None else search_openalex(query, limit=limit)
    results = []
    for row in rows:
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
        results.append(
            DiscoverPaper(
                work_id=row["work_id"],
                title=row["title"],
                year=row.get("year"),
                source_url=row.get("source_url"),
                fields=fields,
                gap=gap,
            )
        )
    return results
