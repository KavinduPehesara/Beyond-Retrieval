"""Which suggested papers can be read in full, told before one is picked.

The decision this encodes is that nothing is removed for being unreadable:
on a live question that would have discarded the systematic reviews at the
top of the list, because those are what publishers keep behind a paywall.
"""

from __future__ import annotations

from dataclasses import dataclass

from slr.services.availability import (
    ELSEWHERE,
    HELD,
    NONE,
    UNKNOWN,
    readability_of,
    readability_of_each,
)


@dataclass
class _Availability:
    has_full_text: bool


@dataclass
class _Copy:
    url: str
    host: str
    is_pdf: bool = True


def _held(**kw):
    return _Availability(has_full_text=True)


def _not_held(**kw):
    return _Availability(has_full_text=False)


def _no_copy(work_id):
    return None


def _a_copy(work_id):
    return _Copy(url="https://journal.example/paper.pdf", host="Example Journal")


PAPER = {"work_id": "https://openalex.org/W1", "title": "A trial", "doi": "https://doi.org/10.1/x"}


def test_a_paper_europe_pmc_holds_is_readable_in_full():
    got = readability_of(PAPER, find_availability=_held, open_access_copy=_no_copy)
    assert got.status == HELD


def test_a_paper_free_elsewhere_names_where():
    got = readability_of(PAPER, find_availability=_not_held, open_access_copy=_a_copy)
    assert got.status == ELSEWHERE
    assert got.host == "Example Journal"
    assert got.url.endswith(".pdf")


def test_a_paper_with_no_free_copy_says_so():
    got = readability_of(PAPER, find_availability=_not_held, open_access_copy=_no_copy)
    assert got.status == NONE


def test_a_failed_lookup_is_not_reported_as_a_paywall():
    """A network failure says nothing about the paper.

    Reporting it as "no free copy" would put a judgement about a
    publisher on what is really a judgement about the connection.
    """

    def explodes(**kw):
        raise RuntimeError("Europe PMC is down")

    got = readability_of(PAPER, find_availability=explodes, open_access_copy=_no_copy)
    assert got.status == UNKNOWN

    def copy_explodes(work_id):
        raise RuntimeError("OpenAlex is down")

    got = readability_of(PAPER, find_availability=_not_held, open_access_copy=copy_explodes)
    assert got.status == UNKNOWN


def test_a_list_keeps_its_order():
    """Badges are matched to papers by position, so order is not cosmetic."""
    papers = [{**PAPER, "work_id": f"W{i}"} for i in range(6)]

    def held_for_even(doi=None, title=None, **kw):
        return _Availability(has_full_text=False)

    got = readability_of_each(papers, find_availability=held_for_even, open_access_copy=_no_copy)
    assert len(got) == len(papers)
    assert all(r.status == NONE for r in got)


def test_no_papers_means_no_lookups():
    assert readability_of_each([]) == []
