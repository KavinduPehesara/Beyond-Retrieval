"""Europe PMC full text: fetch the paper, not just its abstract.

Everything else in this project reads a title and an abstract, because that
is all SYNERGY ships and all the first stage of a systematic review needs.
Effect sizes, confidence intervals, equations and the contents of tables
live in the body of the paper, and are unreachable from an abstract.

Europe PMC publishes the full text of its open-access subset as JATS XML,
free and without an API key. This module turns a DOI into that XML and the
XML into something the extraction pipeline can use.

**The split that matters.** What comes back is of two kinds, and they are
kept apart on purpose:

* **Structured content** -- tables, equations, figure captions, section
  headings -- is parsed directly out of the XML. No model is involved, so
  there is nothing to hallucinate and nothing to verify: a table cell is
  the table cell. These are exact by construction.
* **Narrative content** -- the prose of the Results, Discussion and
  Limitations sections -- is what the model reads, and every claim it makes
  about that prose still goes through ``verify_span`` exactly as abstracts
  do.

That split is the honest answer to "can the system extract statistical
results". The numbers printed in a table, it can read exactly. A claim
*about* those numbers, it can only quote and have the quote checked.

Two limits worth stating plainly rather than discovering later:

* **Coverage is partial and domain-skewed.** Europe PMC is life sciences.
  It will not have software-engineering or statistics papers, which is two
  of this project's six reviews and about 68% of its records. Open access
  also thins out sharply for older work.
* **Figures stay out of reach.** A heat map or a scatter plot is an image
  file. This module returns the *caption*, which is honest about what it
  is; reading the plot itself would need image analysis and is not
  attempted.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field

import httpx

SEARCH_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
FULLTEXT_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML"

# Section headings that usually carry stated limitations. Matched loosely on
# the heading text, because journals name this section a dozen ways.
LIMITATION_HEADINGS = re.compile(
    r"\b(limitation|weakness|caveat|future (work|research|direction)|"
    r"strengths? and limitations)\b",
    re.IGNORECASE,
)
RESULTS_HEADINGS = re.compile(r"\b(result|finding|outcome)s?\b", re.IGNORECASE)
_WHITESPACE = re.compile(r"\s+")


@dataclass
class Table:
    """One table, as published. Exact -- no model read this."""

    label: str | None
    caption: str | None
    # Rows of cells, header row first when the XML marks one.
    rows: list[list[str]] = field(default_factory=list)

    def as_text(self) -> str:
        """Flattened for a prompt or for span verification."""
        lines = []
        if self.label or self.caption:
            lines.append(" ".join(x for x in (self.label, self.caption) if x))
        lines.extend(" | ".join(cells) for cells in self.rows)
        return "\n".join(lines)

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class Figure:
    """A figure's label, caption, and what the body text says about it.

    The image itself is never fetched. A heat map's *meaning* is in the
    pixels, and reading those would need image analysis this project does
    not do.

    ``mentions`` is the honest substitute. Papers describe their own
    figures in prose -- "As shown in Figure 2, mortality declined steadily
    across all three cohorts" -- and that sentence is real text that can be
    quoted and checked. So a reader gets what the authors say the chart
    shows, sourced and verifiable, without anyone pretending the plot was
    read. For most questions ("what does this figure show?") that is the
    answer they actually wanted.
    """

    label: str | None
    caption: str | None
    mentions: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class Section:
    title: str | None
    text: str

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class FullText:
    """One paper's full text, parsed."""

    pmcid: str | None
    doi: str | None
    title: str | None
    abstract: str | None
    sections: list[Section] = field(default_factory=list)
    tables: list[Table] = field(default_factory=list)
    figures: list[Figure] = field(default_factory=list)
    equations: list[str] = field(default_factory=list)

    @property
    def body(self) -> str:
        """Every section's prose, joined. This is what a span is verified
        against -- a quote from the Discussion has to be found in the
        Discussion, not merely be plausible."""
        return "\n\n".join(
            f"{s.title}\n{s.text}" if s.title else s.text for s in self.sections
        ).strip()

    @property
    def limitations_text(self) -> str:
        """Sections whose heading names limitations or future work."""
        return "\n\n".join(
            s.text for s in self.sections if s.title and LIMITATION_HEADINGS.search(s.title)
        ).strip()

    @property
    def results_text(self) -> str:
        return "\n\n".join(
            s.text for s in self.sections if s.title and RESULTS_HEADINGS.search(s.title)
        ).strip()

    def as_dict(self) -> dict:
        return {
            "pmcid": self.pmcid,
            "doi": self.doi,
            "title": self.title,
            "abstract": self.abstract,
            "sections": [s.as_dict() for s in self.sections],
            "tables": [t.as_dict() for t in self.tables],
            "figures": [f.as_dict() for f in self.figures],
            "equations": self.equations,
            "n_sections": len(self.sections),
            "n_tables": len(self.tables),
            "n_figures": len(self.figures),
            "n_equations": len(self.equations),
        }


# --------------------------------------------------------------------------
# Parsing -- no network, fully testable offline
# --------------------------------------------------------------------------


def _text_of(element: ET.Element | None) -> str:
    """All descendant text, whitespace collapsed.

    ``itertext`` rather than ``.text`` because JATS sprinkles inline markup
    (``<italic>``, ``<xref>``, ``<sup>``) through sentences, and taking only
    ``.text`` would silently truncate a quote at the first italic word --
    which would then fail verification for a reason that has nothing to do
    with the model.
    """
    if element is None:
        return ""
    return _WHITESPACE.sub(" ", "".join(element.itertext())).strip()


def _parse_table(wrap: ET.Element) -> Table:
    rows: list[list[str]] = []
    for row in wrap.iter("tr"):
        cells = [_text_of(cell) for cell in row if cell.tag in ("td", "th")]
        if cells:
            rows.append(cells)
    return Table(
        label=_text_of(wrap.find("label")) or None,
        caption=_text_of(wrap.find("caption")) or None,
        rows=rows,
    )


# "Figure 2", "Fig. 2", "Figs 2 and 3", "FIG 2B" -- journals write this a
# dozen ways, so match the number and let the label supply what to look for.
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z(])")


def _figure_number(label: str | None) -> str | None:
    """The bare number from a label like "Figure 2" or "Fig. 3a"."""
    if not label:
        return None
    match = re.search(r"(\d+)", label)
    return match.group(1) if match else None


def _mention_pattern(number: str) -> re.Pattern:
    """Matches a reference to this figure number, not to figure 20 or 2.1.

    Two guards, and they pull in opposite directions. Without the first,
    "Figure 1" matches inside "Figure 12" and a reader is shown a sentence
    about a different chart. But a naive guard that also rejects a
    following period throws away "...as shown in Fig. 1." -- a reference
    at the end of a sentence, which is where many of them live. So the
    rule is: not followed by a digit, and not followed by a decimal point
    that has a digit after it.
    """
    return re.compile(
        rf"\b(?:fig(?:ure|s|\.)?|figures)\s*\.?\s*{number}(?!\d)(?!\.\d)",
        re.IGNORECASE,
    )


def find_figure_mentions(body: str, label: str | None, *, limit: int = 3) -> list[str]:
    """Sentences in the body that refer to this figure.

    Returns whole sentences, so each one can be quoted and verified against
    the paper exactly like any other claim here. Capped at ``limit``
    because a heavily-referenced figure can be cited a dozen times and the
    first few carry the description; the rest are usually bookkeeping.
    """
    number = _figure_number(label)
    if not number or not body:
        return []
    pattern = _mention_pattern(number)
    out: list[str] = []
    for sentence in _SENTENCE_SPLIT.split(body):
        text = sentence.strip()
        if text and pattern.search(text):
            out.append(text)
            if len(out) >= limit:
                break
    return out


def _parse_sections(parent: ET.Element) -> list[Section]:
    """Flatten nested ``<sec>`` into a list, keeping headings.

    Nested sections are flattened rather than kept as a tree: the consumers
    want "the prose under a heading that mentions limitations", and a tree
    would make that a traversal for no benefit. Tables and figures are
    pulled out separately, so their text is removed here to stop a table's
    numbers being quoted as if they were prose.
    """
    out: list[Section] = []
    for sec in parent.findall(".//sec"):
        title = _text_of(sec.find("title")) or None
        parts = []
        for para in sec.findall("p"):
            text = _text_of(para)
            if text:
                parts.append(text)
        if parts:
            out.append(Section(title=title, text="\n".join(parts)))
    if not out:  # a body with no <sec> at all -- take its paragraphs
        parts = [_text_of(p) for p in parent.findall(".//p")]
        parts = [p for p in parts if p]
        if parts:
            out.append(Section(title=None, text="\n".join(parts)))
    return out


def parse_jats(xml: str) -> FullText:
    """Parse Europe PMC's JATS XML into sections, tables, figures, equations.

    Raises ``ValueError`` on XML that will not parse at all. Missing pieces
    are returned empty rather than raising: a paper with no tables is a
    normal paper, not an error.
    """
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        raise ValueError(f"not parseable as JATS XML: {exc}") from exc

    front = root.find(".//front")
    title = None
    abstract = None
    doi = None
    pmcid = None
    if front is not None:
        title = _text_of(front.find(".//article-title")) or None
        abstract = _text_of(front.find(".//abstract")) or None
        for ident in front.findall(".//article-id"):
            kind = ident.get("pub-id-type")
            if kind == "doi":
                doi = _text_of(ident) or None
            elif kind == "pmcid" or kind == "pmc":
                pmcid = _text_of(ident) or None

    body = root.find(".//body")
    sections = _parse_sections(body) if body is not None else []

    tables = [_parse_table(w) for w in root.iter("table-wrap")]

    # Figures need the body prose to find their own mentions, so the body
    # is assembled before they are built rather than after.
    body_text = "\n\n".join(
        f"{s.title}\n{s.text}" if s.title else s.text for s in sections
    ).strip()
    figures = []
    for element in root.iter("fig"):
        label = _text_of(element.find("label")) or None
        figures.append(
            Figure(
                label=label,
                caption=_text_of(element.find("caption")) or None,
                mentions=find_figure_mentions(body_text, label),
            )
        )
    equations = []
    for formula in list(root.iter("disp-formula")) + list(root.iter("inline-formula")):
        text = _text_of(formula)
        if text:
            equations.append(text)

    return FullText(
        pmcid=pmcid,
        doi=doi,
        title=title,
        abstract=abstract,
        sections=sections,
        tables=tables,
        figures=figures,
        equations=equations,
    )


# --------------------------------------------------------------------------
# Fetching
# --------------------------------------------------------------------------


@dataclass
class Availability:
    """What Europe PMC knows about one paper, before fetching anything big."""

    found: bool
    pmcid: str | None = None
    doi: str | None = None
    title: str | None = None
    is_open_access: bool = False
    in_epmc: bool = False
    reason: str = ""

    @property
    def has_full_text(self) -> bool:
        return bool(self.pmcid) and self.is_open_access

    def as_dict(self) -> dict:
        return asdict(self)


def _escape(value: str) -> str:
    return value.replace('"', " ").strip()


def normalise_doi(value: str | None) -> str | None:
    """A bare DOI, whatever form it arrived in.

    OpenAlex returns DOIs as resolver URLs -- ``https://doi.org/10.1002/
    jrsm.1715`` -- and Europe PMC's ``DOI:"..."`` query expects the bare
    ``10.1002/jrsm.1715``. Passing the URL through finds nothing, and the
    result is indistinguishable from the paper genuinely not being indexed,
    which is exactly the wrong thing for this module to be vague about.
    """
    if not value:
        return None
    doi = value.strip()
    for prefix in ("https://doi.org/", "http://doi.org/", "https://dx.doi.org/", "doi:"):
        if doi.lower().startswith(prefix):
            doi = doi[len(prefix) :]
            break
    return doi.strip().lower() or None


def find_availability(
    *,
    doi: str | None = None,
    title: str | None = None,
    client: httpx.Client | None = None,
    timeout: float = 15.0,
) -> Availability:
    """Is this paper's full text available, and under what id?

    Looks up by DOI when there is one and falls back to an exact-ish title
    search, because roughly 1 record in 20 of this project's corpus has no
    DOI. Returns a reason when the answer is no, so a caller can tell "not
    in Europe PMC" from "in Europe PMC but paywalled" -- those are different
    facts and the second one is not a failure of this code.
    """
    doi = normalise_doi(doi)
    if not doi and not title:
        raise ValueError("need a doi or a title to look up")

    # DOI first when there is one, then the title. The fallback matters:
    # a DOI that Europe PMC does not hold under that exact string would
    # otherwise report "not indexed" for a paper it does have, and the two
    # are indistinguishable to a reader.
    queries = []
    if doi:
        queries.append(f'DOI:"{_escape(doi)}"')
    if title:
        queries.append(f'TITLE:"{_escape(title)}"')

    owns = client is None
    client = client or httpx.Client()
    record = None
    try:
        for query in queries:
            params = {
                "query": query,
                "resultType": "core",
                "format": "json",
                "pageSize": 1,
            }
            response = client.get(SEARCH_URL, params=params, timeout=timeout)
            response.raise_for_status()
            results = (response.json().get("resultList") or {}).get("result") or []
            if results:
                record = results[0]
                break
    finally:
        if owns:
            client.close()

    if record is None:
        return Availability(found=False, reason="not indexed in Europe PMC")
    pmcid = record.get("pmcid")
    open_access = str(record.get("isOpenAccess", "")).upper() == "Y"
    in_epmc = str(record.get("inEPMC", "")).upper() == "Y"

    reason = ""
    if not pmcid:
        reason = "indexed, but no PMC record -- full text not held here"
    elif not open_access:
        reason = "in Europe PMC but not open access -- full text is paywalled"

    return Availability(
        found=True,
        pmcid=pmcid,
        doi=record.get("doi") or doi,
        title=record.get("title") or title,
        is_open_access=open_access,
        in_epmc=in_epmc,
        reason=reason,
    )


def fetch_full_text(
    pmcid: str,
    *,
    client: httpx.Client | None = None,
    timeout: float = 30.0,
) -> FullText | None:
    """Fetch and parse one paper's JATS XML. ``None`` when it isn't served.

    Europe PMC answers 404 for a PMCID whose full text it does not hold,
    which is a normal outcome rather than an error worth raising.
    """
    owns = client is None
    client = client or httpx.Client()
    try:
        response = client.get(FULLTEXT_URL.format(pmcid=pmcid), timeout=timeout)
        if response.status_code == 404:
            return None
        response.raise_for_status()
        xml = response.text
    finally:
        if owns:
            client.close()

    if not xml.strip():
        return None
    return parse_jats(xml)


def get_full_text(
    *,
    doi: str | None = None,
    title: str | None = None,
    client: httpx.Client | None = None,
) -> tuple[FullText | None, Availability]:
    """Look up a paper and fetch its full text if it is available.

    Returns the text (or ``None``) *and* the availability record, so a
    caller can always say why it got nothing. Reporting "no full text"
    without the reason would make a paywalled paper indistinguishable from
    a bug.
    """
    availability = find_availability(doi=doi, title=title, client=client)
    if not availability.has_full_text:
        return None, availability

    text = fetch_full_text(availability.pmcid, client=client)
    if text is None:
        availability.reason = "listed as open access but full text not served"
    return text, availability
