"""Tests for Europe PMC full-text retrieval and extraction.

Three things are worth guarding here, in order of how badly they would
mislead if they broke:

1. A quote is verified against *exactly* the text the model was shown. If
   those two ever drift apart, every failure becomes the harness's fault
   and the verification rate stops meaning anything.
2. Table and equation content never enters the prose a model may quote.
   A number copied out of a table cell and presented as a sentence from the
   Discussion is a claim the paper does not make.
3. Nothing on this path reaches the evaluation corpus. There is no ground
   truth for extracted values, so if any of this leaked into `work` or
   `extraction` it would contaminate figures that do have ground truth.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from slr.adapters import fulltext as ft
from slr.adapters.llm import Completion, Meter
from slr.db import connect
from slr.services.extract_fulltext import (
    FIELDS,
    build_source,
    extract_fulltext_record,
    load_prompt_template,
)

JATS = """<article>
 <front><article-meta>
   <article-id pub-id-type="doi">10.1/abc</article-id>
   <article-id pub-id-type="pmcid">PMC123</article-id>
   <title-group><article-title>A trial of <italic>X</italic> in adults</article-title></title-group>
   <abstract><p>We ran a trial.</p></abstract>
 </article-meta></front>
 <body>
  <sec><title>Introduction</title><p>Background prose that nobody needs.</p></sec>
  <sec><title>Methods</title><p>We used Cox proportional hazards regression.</p></sec>
  <sec><title>Results</title>
    <p>The hazard ratio was 0.72 (95% CI 0.61-0.85, p&lt;0.001).</p>
    <table-wrap><label>Table 1</label><caption><p>Baseline characteristics</p></caption>
      <table><thead><tr><th>Group</th><th>n</th></tr></thead>
      <tbody><tr><td>Intervention</td><td>120</td></tr></tbody></table></table-wrap>
    <fig><label>Figure 2</label><caption><p>Correlation heat map of all measures</p></caption></fig>
  </sec>
  <sec><title>Strengths and limitations</title><p>We did not measure diet in this cohort.</p></sec>
  <sec><title>Discussion</title><p>Our findings agree with prior work.</p>
    <disp-formula>HR = exp(b1 x1 + b2 x2)</disp-formula></sec>
 </body></article>"""


@pytest.fixture
def paper():
    return ft.parse_jats(JATS)


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "t.db")
    yield c
    c.close()


# --------------------------------------------------------------------------
# Parsing
# --------------------------------------------------------------------------


def test_parses_identifiers_and_sections(paper):
    assert paper.doi == "10.1/abc"
    assert paper.pmcid == "PMC123"
    assert [s.title for s in paper.sections] == [
        "Introduction", "Methods", "Results", "Strengths and limitations", "Discussion",
    ]


def test_inline_markup_does_not_truncate_a_sentence(paper):
    """JATS sprinkles <italic> and <xref> mid-sentence. Taking only .text
    would cut a quote short, and it would then fail verification for a
    reason that has nothing to do with the model."""
    assert paper.title == "A trial of X in adults"


def test_tables_are_parsed_exactly_with_no_model_involved(paper):
    table = paper.tables[0]
    assert table.label == "Table 1"
    assert table.caption == "Baseline characteristics"
    assert table.rows == [["Group", "n"], ["Intervention", "120"]]


def test_table_content_is_kept_out_of_the_quotable_prose(paper):
    """The guard that matters most in the parser. A model quoting "120"
    from a table and presenting it as a sentence would be making a claim
    the paper never makes in prose."""
    assert "Intervention" not in paper.body
    assert "120" not in paper.body
    assert "The hazard ratio was 0.72" in paper.body


def test_figures_yield_a_caption_and_never_claim_to_read_the_image(paper):
    figure = paper.figures[0]
    assert figure.label == "Figure 2"
    assert "heat map" in figure.caption
    # There is no pixel data and no pretence of any.
    assert not hasattr(figure, "data")


def test_equations_are_captured(paper):
    assert paper.equations == ["HR = exp(b1 x1 + b2 x2)"]


def test_limitations_section_is_found_by_heading(paper):
    assert paper.limitations_text == "We did not measure diet in this cohort."


def test_a_body_with_no_sections_still_yields_prose():
    parsed = ft.parse_jats("<article><body><p>Just one paragraph.</p></body></article>")
    assert parsed.body == "Just one paragraph."


def test_unparseable_xml_raises_rather_than_returning_nonsense():
    with pytest.raises(ValueError, match="not parseable"):
        ft.parse_jats("<article><unclosed>")


def test_a_paper_with_no_tables_is_not_an_error():
    parsed = ft.parse_jats("<article><body><sec><p>Prose only.</p></sec></body></article>")
    assert parsed.tables == [] and parsed.equations == []


# --------------------------------------------------------------------------
# Availability
# --------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, payload=None, text="", status_code=200):
        self._payload = payload
        self.text = text
        self.status_code = status_code

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _FakeClient:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, params))
        return self.response

    def close(self):
        pass


def _availability(**record):
    return _FakeClient(_FakeResponse({"resultList": {"result": [record]}}))


def test_open_access_paper_reports_full_text_available():
    client = _availability(pmcid="PMC1", isOpenAccess="Y", inEPMC="Y", doi="10.1/x")
    result = ft.find_availability(doi="10.1/x", client=client)
    assert result.has_full_text is True
    assert result.reason == ""


def test_paywalled_paper_says_so_rather_than_looking_like_a_bug():
    """"Not in Europe PMC" and "in Europe PMC but paywalled" are different
    facts, and neither is a failure of this code."""
    client = _availability(pmcid="PMC1", isOpenAccess="N", inEPMC="Y")
    result = ft.find_availability(doi="10.1/x", client=client)
    assert result.has_full_text is False
    assert "paywalled" in result.reason


def test_paper_not_indexed_at_all_says_so():
    client = _FakeClient(_FakeResponse({"resultList": {"result": []}}))
    result = ft.find_availability(doi="10.1/x", client=client)
    assert result.found is False
    assert "not indexed" in result.reason


def test_indexed_without_a_pmc_record_says_so():
    client = _availability(pmcid=None, isOpenAccess="N")
    result = ft.find_availability(doi="10.1/x", client=client)
    assert "no PMC record" in result.reason


def test_lookup_falls_back_to_title_when_there_is_no_doi():
    """About 1 record in 20 of this project's corpus has no DOI."""
    client = _availability(pmcid="PMC1", isOpenAccess="Y")
    ft.find_availability(title="A trial of X", client=client)
    _, params = client.calls[0]
    assert params["query"].startswith("TITLE:")


def test_lookup_without_doi_or_title_is_rejected():
    with pytest.raises(ValueError, match="doi or a title"):
        ft.find_availability()


def test_a_404_on_full_text_is_a_normal_outcome_not_an_exception():
    client = _FakeClient(_FakeResponse(status_code=404))
    assert ft.fetch_full_text("PMC1", client=client) is None


def test_get_full_text_always_returns_a_reason_when_it_returns_nothing():
    client = _availability(pmcid="PMC1", isOpenAccess="N")
    text, availability = ft.get_full_text(doi="10.1/x", client=client)
    assert text is None
    assert availability.reason


# --------------------------------------------------------------------------
# Building the prompt source
# --------------------------------------------------------------------------


def test_results_and_limitations_come_before_the_introduction(paper):
    """Truncation should eat the Introduction, not the numbers."""
    source = build_source(paper)
    assert source.text.index("hazard ratio") < source.text.index("Background prose")


def test_truncation_is_reported_not_silent(paper):
    source = build_source(paper, max_chars=50)
    assert source.truncated is True
    assert source.chars_available > 50


def test_a_truncated_not_stated_is_distinguished_from_a_real_one(paper, conn):
    """A field missing because its sentence was cut off is a different
    failure from one the paper genuinely does not state."""
    payload = {name: {"value": "not_stated", "evidence_span": ""} for name in FIELDS}
    rows = extract_fulltext_record(
        paper, work_id="W1", review="_discover",
        provider=_ScriptedProvider(payload),
        template="{title} {body}",
        meter=Meter(ceiling_usd=1.0, usd_per_1m_input=0.0, usd_per_1m_output=0.0),
        conn=conn, use_cache=False, max_chars=40,
    )
    assert all(r.verify_note == "not_stated_possibly_truncated" for r in rows)


# --------------------------------------------------------------------------
# Extraction
# --------------------------------------------------------------------------


class _ScriptedProvider:
    name = "scripted"
    model = "scripted-1"

    def __init__(self, payload):
        self.payload = payload
        self.prompts = []

    def complete(self, prompt, *, temperature=0.0, max_tokens=512, seed=None, response_schema=None):
        self.prompts.append(prompt)
        return Completion(text=json.dumps(self.payload), tokens_in=10, tokens_out=10)


REAL_QUOTES = {
    "primary_outcome": "The hazard ratio was 0.72 (95% CI 0.61-0.85, p<0.001).",
    "effect_size": "The hazard ratio was 0.72 (95% CI 0.61-0.85, p<0.001).",
    "statistical_methods": "We used Cox proportional hazards regression.",
    "sample_characteristics": "Our findings agree with prior work.",
    "limitations": "We did not measure diet in this cohort.",
}


def _run(paper, conn, payload, **kw):
    return extract_fulltext_record(
        paper, work_id="W1", review="_discover",
        provider=_ScriptedProvider(payload),
        template="{title} {body}",
        meter=Meter(ceiling_usd=1.0, usd_per_1m_input=0.0, usd_per_1m_output=0.0),
        conn=conn, use_cache=False, **kw,
    )


def test_real_quotes_from_the_full_text_verify(paper, conn):
    payload = {k: {"value": f"v-{k}", "evidence_span": q} for k, q in REAL_QUOTES.items()}
    rows = _run(paper, conn, payload)
    assert len(rows) == 5
    assert all(r.span_verified for r in rows), [r.verify_note for r in rows]
    assert all(r.value.startswith("v-") for r in rows)


def test_an_invented_quote_is_caught_and_its_value_withheld(paper, conn):
    payload = {k: {"value": f"v-{k}", "evidence_span": q} for k, q in REAL_QUOTES.items()}
    payload["limitations"] = {
        "value": "diet not measured",
        "evidence_span": "A sentence that appears nowhere in this paper at all.",
    }
    rows = {r.field_name: r for r in _run(paper, conn, payload)}
    assert rows["limitations"].span_verified is False
    assert rows["limitations"].value is None, "an unverified value is never reported"
    assert rows["primary_outcome"].span_verified is True, "one bad field doesn't poison the rest"


def test_a_quote_lifted_from_a_table_does_not_verify(paper, conn):
    """Table cells are real text in the document but are not prose the
    paper asserts. Quoting one as a sentence must fail."""
    payload = {k: {"value": "v", "evidence_span": q} for k, q in REAL_QUOTES.items()}
    payload["sample_characteristics"] = {
        "value": "120 per group",
        "evidence_span": "Intervention | 120 Baseline characteristics",
    }
    rows = {r.field_name: r for r in _run(paper, conn, payload)}
    assert rows["sample_characteristics"].span_verified is False


def test_a_quote_lifted_from_the_instructions_does_not_verify(paper, conn):
    """The failure mode the error typology found: 97.8% of screening
    verification failures were the model quoting the prompt back. The span
    is checked against the paper only, so this cannot pass."""
    payload = {k: {"value": "v", "evidence_span": q} for k, q in REAL_QUOTES.items()}
    payload["effect_size"] = {
        "value": "x",
        "evidence_span": "The magnitude of the main effect and its uncertainty",
    }
    rows = {r.field_name: r for r in _run(paper, conn, payload)}
    assert rows["effect_size"].span_verified is False


def test_malformed_json_is_recorded_not_raised(paper, conn):
    class Broken(_ScriptedProvider):
        def complete(self, prompt, **kw):
            return Completion(text="not json at all", tokens_in=1, tokens_out=1)

    rows = extract_fulltext_record(
        paper, work_id="W1", review="_discover", provider=Broken({}),
        template="{title} {body}",
        meter=Meter(ceiling_usd=1.0, usd_per_1m_input=0.0, usd_per_1m_output=0.0),
        conn=conn, use_cache=False,
    )
    assert all(r.verify_note == "schema_validation_failed" for r in rows)
    assert len(rows) == 5


def test_a_provider_error_is_recorded_not_raised(paper, conn):
    class Exploding(_ScriptedProvider):
        def complete(self, prompt, **kw):
            raise RuntimeError("ollama is down")

    rows = extract_fulltext_record(
        paper, work_id="W1", review="_discover", provider=Exploding({}),
        template="{title} {body}",
        meter=Meter(ceiling_usd=1.0, usd_per_1m_input=0.0, usd_per_1m_output=0.0),
        conn=conn, use_cache=False,
    )
    assert all(r.verify_note == "provider_error" for r in rows)


def test_the_model_is_shown_exactly_the_text_it_may_quote(paper, conn):
    """If the prompt and the verification source ever drift apart, every
    failure becomes the harness's fault."""
    provider = _ScriptedProvider(
        {k: {"value": "v", "evidence_span": q} for k, q in REAL_QUOTES.items()}
    )
    extract_fulltext_record(
        paper, work_id="W1", review="_discover", provider=provider,
        template="{title}|{body}",
        meter=Meter(ceiling_usd=1.0, usd_per_1m_input=0.0, usd_per_1m_output=0.0),
        conn=conn, use_cache=False,
    )
    shown = provider.prompts[0].split("|", 1)[1]
    assert shown == build_source(paper).text


def test_the_shipped_prompt_template_has_the_placeholders_the_code_fills():
    template = load_prompt_template(Path("prompts/extract_fulltext_v1.txt"))
    assert "{title}" in template and "{body}" in template
    for name in FIELDS:
        assert name in template, f"{name} is extracted but never asked for"


# --------------------------------------------------------------------------
# The boundary
# --------------------------------------------------------------------------


def test_full_text_extraction_never_reaches_the_evaluation_corpus(paper, conn):
    """There is no ground truth for an extracted effect size. If any of this
    leaked into `work` or `extraction` it would contaminate figures that do
    have ground truth."""
    payload = {k: {"value": "v", "evidence_span": q} for k, q in REAL_QUOTES.items()}
    _run(paper, conn, payload)

    for table in ("work", "extraction", "screening_decision", "gap_statement"):
        n = conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]  # noqa: S608
        assert n == 0, f"{table} was written to"


def test_the_discover_review_name_is_not_a_real_review():
    from slr.config import SUBSET
    from slr.services.discover import DISCOVER_REVIEW

    assert DISCOVER_REVIEW not in SUBSET


# --------------------------------------------------------------------------
# DOI normalisation
#
# Found live: OpenAlex returns DOIs as resolver URLs, Europe PMC's query
# wants the bare DOI, and passing the URL straight through reported
# "not indexed" for a paper Europe PMC actually holds. The two outcomes
# are indistinguishable to a reader, which is the worst kind of bug for a
# module whose whole job is saying why there is no full text.
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    [
        "https://doi.org/10.1002/jrsm.1715",
        "http://doi.org/10.1002/jrsm.1715",
        "https://dx.doi.org/10.1002/jrsm.1715",
        "doi:10.1002/jrsm.1715",
        "10.1002/jrsm.1715",
        "  10.1002/JRSM.1715  ",
    ],
)
def test_every_doi_form_normalises_to_the_bare_identifier(raw):
    assert ft.normalise_doi(raw) == "10.1002/jrsm.1715"


def test_normalise_doi_of_nothing_is_none():
    assert ft.normalise_doi(None) is None
    assert ft.normalise_doi("   ") is None


def test_an_openalex_style_doi_url_is_queried_as_a_bare_doi():
    client = _availability(pmcid="PMC1", isOpenAccess="Y")
    ft.find_availability(doi="https://doi.org/10.1002/jrsm.1715", client=client)
    _, params = client.calls[0]
    assert params["query"] == 'DOI:"10.1002/jrsm.1715"'
    assert "doi.org" not in params["query"]


class _SequencedClient:
    """Returns a different response per call, for the fallback path."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, params))
        return self.responses.pop(0)

    def close(self):
        pass


def test_a_doi_miss_falls_back_to_the_title():
    """A DOI Europe PMC does not hold under that exact string must not be
    reported as "not indexed" when it holds the paper under its title."""
    empty = _FakeResponse({"resultList": {"result": []}})
    found = _FakeResponse(
        {"resultList": {"result": [{"pmcid": "PMC7", "isOpenAccess": "Y", "inEPMC": "Y"}]}}
    )
    client = _SequencedClient([empty, found])

    result = ft.find_availability(doi="10.1/nope", title="A trial of X", client=client)
    assert result.has_full_text is True
    assert len(client.calls) == 2
    assert client.calls[0][1]["query"].startswith("DOI:")
    assert client.calls[1][1]["query"].startswith("TITLE:")


def test_the_title_fallback_is_not_tried_when_the_doi_hits():
    """One request, not two, when the first answer is good."""
    client = _availability(pmcid="PMC1", isOpenAccess="Y")
    ft.find_availability(doi="10.1/x", title="A trial of X", client=client)
    assert len(client.calls) == 1


def test_still_not_indexed_when_neither_lookup_finds_anything():
    empty = _FakeResponse({"resultList": {"result": []}})
    client = _SequencedClient([empty, empty])
    result = ft.find_availability(doi="10.1/x", title="Nothing", client=client)
    assert result.found is False
    assert "not indexed" in result.reason


# --------------------------------------------------------------------------
# Fragment detection
#
# Found live on PMC7508247, a BMJ meta-analysis: Europe PMC flagged the
# record open access and served 1,058 characters -- one untitled section, no
# table-wrap or fig elements anywhere in the XML. The model then answered
# "not stated" to four of five fields, correctly, about text it had never
# been shown. Without a name for that state the symptom is indistinguishable
# from the extraction being weak.
# --------------------------------------------------------------------------


def _fragment_xml(chars: int = 1000) -> str:
    return (
        "<article><front><article-meta>"
        "<article-id pub-id-type='pmcid'>PMC7508247</article-id>"
        "<title-group><article-title>A meta-analysis</article-title></title-group>"
        "</article-meta></front>"
        f"<body><sec><p>{'word ' * (chars // 5)}</p></sec></body></article>"
    )


def test_a_stub_record_is_recognised_as_a_fragment():
    parsed = ft.parse_jats(_fragment_xml())
    assert parsed.is_fragment is True
    assert len(parsed.body) < ft.MIN_PLAUSIBLE_BODY_CHARS
    assert parsed.tables == [] and parsed.figures == []


def test_a_real_paper_is_not_called_a_fragment(paper):
    """The fixture is short but has section headings, a table and a figure
    -- structure a stub never has. Length alone must not condemn it."""
    assert paper.is_fragment is False


def test_a_long_body_is_not_a_fragment_even_without_tables():
    """Plenty of real papers have no tables. Length is the other half of
    the test for exactly this reason."""
    long_xml = (
        "<article><body><sec><p>"
        + ("sentence about the study. " * 1000)
        + "</p></sec></body></article>"
    )
    parsed = ft.parse_jats(long_xml)
    assert len(parsed.body) > ft.MIN_PLAUSIBLE_BODY_CHARS
    assert parsed.is_fragment is False


def test_a_short_paper_with_real_structure_is_not_a_fragment():
    structured = (
        "<article><body>"
        "<sec><title>Methods</title><p>We did the thing.</p></sec>"
        "<sec><title>Results</title><p>It worked.</p></sec>"
        "</body></article>"
    )
    parsed = ft.parse_jats(structured)
    assert parsed.is_fragment is False, "section headings mean this is a real paper"


# --------------------------------------------------------------------------
# Back matter
#
# Found live on PMC8056687 (a PRISMA editorial in Systematic Reviews): eight
# of its nine body sections were journal boilerplate -- Acknowledgements,
# Funding, Competing interests, Consent for publication -- and only one was
# the article.
#
# The size is not the point. That text is *quotable*. "The authors declare
# that they have no competing interests" is a real sentence that would
# verify, so a model reaching for a limitations field could return it and
# the verifier would pass it: a true quote backing a claim the paper never
# made. The verifier checks that a sentence is real, not that it is
# relevant, so relevance has to be handled before the text is ever shown.
# --------------------------------------------------------------------------


def _article_with_back_matter() -> str:
    sections = [
        ("Editorial", "It has been more than a decade since PRISMA was published. " * 20),
        ("Acknowledgements", "NA"),
        ("Authors' contributions", "All authors read and approved the final manuscript."),
        ("Funding", "No funding was received for this work."),
        ("Availability of data and materials", "Not applicable."),
        ("Ethics approval and consent to participate", "Not applicable."),
        ("Consent for publication", "Not applicable."),
        ("Competing interests", "The authors declare that they have no competing interests."),
        ("Data Availability Statement", "Not applicable."),
    ]
    body = "".join(f"<sec><title>{t}</title><p>{b}</p></sec>" for t, b in sections)
    return f"<article><body>{body}</body></article>"


def test_journal_boilerplate_is_dropped_from_the_body():
    parsed = ft.parse_jats(_article_with_back_matter())
    assert [s.title for s in parsed.sections] == ["Editorial"]


def test_boilerplate_is_not_quotable():
    """The failure this prevents: a verified quote from the competing
    interests statement, offered as the paper's limitations."""
    parsed = ft.parse_jats(_article_with_back_matter())
    assert "no competing interests" not in parsed.body
    assert "Not applicable" not in parsed.body


def test_the_article_itself_survives():
    parsed = ft.parse_jats(_article_with_back_matter())
    assert "more than a decade since PRISMA" in parsed.body


@pytest.mark.parametrize(
    "heading",
    [
        "Acknowledgements", "Acknowledgments", "Authors' contributions",
        "Author information", "Funding", "Competing interests",
        "Conflict of interest", "Declarations", "Data availability statement",
        "Availability of data and materials", "Ethics approval and consent to participate",
        "Consent for publication", "Abbreviations", "Supplementary information",
        "Additional file 1", "Publisher's Note", "Peer review",
    ],
)
def test_every_known_back_matter_heading_is_recognised(heading):
    assert ft.BACK_MATTER_HEADINGS.search(heading), heading


@pytest.mark.parametrize(
    "heading",
    [
        "Introduction", "Methods", "Results", "Discussion", "Conclusion",
        "Limitations", "Statistical analysis", "Study design",
        "Data extraction", "Data collection and analysis",
    ],
)
def test_real_section_headings_are_not_mistaken_for_boilerplate(heading):
    """"Data extraction" and "Data collection" must survive, even though
    "Data availability" does not -- they are a methods section, not a
    statement."""
    assert not ft.BACK_MATTER_HEADINGS.search(heading), heading
