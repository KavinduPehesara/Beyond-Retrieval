"""Which suggested papers can actually be read in full, before one is chosen.

Europe PMC holds the biomedical open-access subset, so most of a typical
result list cannot be read here. Finding that out after choosing wastes the
choice; measured on one live question, 19 of 45 candidates were readable
and 23 more were free somewhere else.

Filtering the unreadable ones out of the list was considered and rejected:
on that same question it would have discarded the systematic reviews and
meta-analyses at the top, since those are the papers publishers keep
behind a paywall. Replacing them with readable but less relevant papers
would quietly turn "the papers that answer your question" into "the
papers that answer your question and happen to be hosted conveniently" --
an exclusion the researcher could not see. So this reports, and the
researcher still decides.
"""

from __future__ import annotations

import concurrent.futures as futures
from dataclasses import dataclass

HELD = "held"  # Europe PMC has the full text
ELSEWHERE = "elsewhere"  # free to read, but not somewhere this tool can parse
NONE = "none"  # no free copy found
UNKNOWN = "unknown"  # the lookup failed, which is not a fact about the paper

# Each lookup is a Europe PMC search and sometimes an OpenAlex call. Done one
# at a time, twenty papers cost about thirty seconds; eight at a time, five.
MAX_WORKERS = 8


@dataclass(frozen=True)
class Readability:
    """Whether one paper can be read in full, and where if not here."""

    status: str
    url: str | None = None
    host: str | None = None


def readability_of(paper: dict, *, find_availability=None, open_access_copy=None) -> Readability:
    """Where one paper's full text can be had, if anywhere.

    The two lookups are injected so this can be tested without a network,
    and so a caller that already knows an answer need not ask twice.
    """
    if find_availability is None:
        from slr.adapters.fulltext import find_availability
    if open_access_copy is None:
        from slr.services.discover import open_access_copy

    doi = (paper.get("doi") or "").replace("https://doi.org/", "")
    try:
        availability = find_availability(doi=doi, title=paper.get("title"))
        if availability.has_full_text:
            return Readability(HELD)
    except Exception:
        # A failed lookup says nothing about the paper, so it must not be
        # reported as "no free copy".
        return Readability(UNKNOWN)

    try:
        copy = open_access_copy(paper.get("work_id") or "")
    except Exception:
        return Readability(UNKNOWN)
    if copy:
        return Readability(ELSEWHERE, url=copy.url, host=copy.host)
    return Readability(NONE)


def readability_of_each(papers: list[dict], **lookups) -> list[Readability]:
    """The same, for a list, in order, several at a time."""
    if not papers:
        return []
    with futures.ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(papers))) as pool:
        return list(pool.map(lambda p: readability_of(p, **lookups), papers))
