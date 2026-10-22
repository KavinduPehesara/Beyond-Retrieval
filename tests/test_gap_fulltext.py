"""Tests for gap discovery over a paper's full text.

The claim this feature makes is narrow and checkable: every gap shown to a
researcher is a sentence that exists in the paper. These tests are mostly
about what happens when that is not true.
"""

from __future__ import annotations

import json

import pytest

from slr.adapters.fulltext import FullText, Section
from slr.adapters.llm import CacheMismatch, Completion, Meter
from slr.db import connect
from slr.services import gap_fulltext

DISCUSSION = (
    "Our trial showed a reduction in symptom scores at twelve weeks. "
    "Further research is needed to establish whether the effect persists beyond one year. "
    "We did not examine participants over the age of eighty."
)
METHODS = "Participants were randomised in a one to one ratio using a computer generated sequence."


def paper(sections=None, title="A trial of something"):
    return FullText(
        pmcid="PMC1",
        doi="10.1/x",
        title=title,
        abstract="An abstract that states nothing about gaps.",
        sections=sections
        if sections is not None
        else [Section(title="Methods", text=METHODS), Section(title="Discussion", text=DISCUSSION)],
    )


class _Provider:
    name, model = "fake", "fake-1"

    def __init__(self, payload="{}", fail=False):
        self.payload = payload
        self.fail = fail
        self.calls = 0

    def complete(self, prompt, *, temperature=0.0, max_tokens=512, seed=None, response_schema=None):
        self.calls += 1
        if self.fail:
            raise RuntimeError("model is down")
        self.prompt = prompt
        return Completion(text=self.payload, tokens_in=20, tokens_out=10)


def payload(*pairs):
    return json.dumps({"gaps": [{"value": v, "evidence_span": s} for v, s in pairs]})


@pytest.fixture()
def conn(tmp_path):
    c = connect(tmp_path / "gaps.db")
    yield c
    c.close()


def run(conn, provider, *, full_text=None, **kwargs):
    return gap_fulltext.find_gaps(
        full_text or paper(),
        work_id="W1",
        review="_discover",
        provider=provider,
        template="{title} {candidates}",
        meter=Meter(ceiling_usd=1.0, usd_per_1m_input=0.0, usd_per_1m_output=0.0),
        conn=conn,
        **kwargs,
    )


# --------------------------------------------------------------------------
# What a researcher is shown
# --------------------------------------------------------------------------


def test_a_real_sentence_is_reported_with_the_section_it_came_from(conn):
    quote = "Further research is needed to establish whether the effect persists beyond one year."
    result = run(conn, _Provider(payload(("Long-term effect is unknown", quote))))

    assert result.note == "found"
    assert len(result.gaps) == 1
    gap = result.gaps[0]
    assert gap.evidence_span == quote
    assert gap.value == "Long-term effect is unknown"
    assert gap.section == "Discussion"
    assert result.n_withheld == 0


def test_an_invented_sentence_is_withheld(conn):
    """The whole point: a gap nobody wrote is not shown, and is counted."""
    result = run(
        conn,
        _Provider(payload(("Invented", "No study has examined this in dogs."))),
    )
    assert result.gaps == []
    assert result.n_proposed == 1 and result.n_withheld == 1
    assert result.note == "none_stated"


def test_one_bad_quote_does_not_lose_the_good_ones(conn):
    good = "We did not examine participants over the age of eighty."
    result = run(
        conn,
        _Provider(payload(("Older adults", good), ("Fabricated", "A sentence nobody wrote here."))),
    )
    assert [g.evidence_span for g in result.gaps] == [good]
    assert result.n_proposed == 2 and result.n_withheld == 1


def test_a_real_sentence_that_states_no_gap_is_withheld(conn):
    """Found on the first live paper, which is why this check exists.

    The model answered with results sentences -- each one genuinely in the
    paper, so each one verified -- and summarised them as gaps. Verification
    proves a sentence is real; it cannot prove it points at something
    undone, so the quote must carry forward-looking language too.
    """
    results_sentence = "Our trial showed a reduction in symptom scores at twelve weeks."
    result = run(conn, _Provider(payload(("Long-term effect unknown", results_sentence))))

    assert result.gaps == []
    assert result.n_unsupported == 1
    assert result.n_withheld == 0, "the quote was real; it just states no gap"


@pytest.mark.parametrize(
    "sentence, states_a_gap",
    [
        ("Further research is needed to confirm this.", True),
        ("Future studies should examine older adults.", True),
        ("We did not examine participants over the age of eighty.", True),
        ("The mechanism remains unclear.", True),
        ("No study has compared the two directly.", True),
        ("Symptom scores fell by four points.", False),
        ("The intervention was delivered twice weekly.", False),
    ],
)
def test_which_sentences_read_as_a_gap(sentence, states_a_gap):
    assert gap_fulltext.quote_states_a_gap(sentence) is states_a_gap


def test_the_same_sentence_twice_is_one_gap(conn):
    quote = "We did not examine participants over the age of eighty."
    result = run(conn, _Provider(payload(("Age", quote), ("Age again", quote))))
    assert len(result.gaps) == 1


def test_a_paper_stating_nothing_returns_an_empty_list(conn):
    result = run(conn, _Provider(json.dumps({"gaps": []})))
    assert result.gaps == [] and result.note == "none_stated"
    assert result.n_withheld == 0


def test_the_number_of_gaps_is_capped(conn):
    sentences = [s.strip() + "." for s in DISCUSSION.split(".") if s.strip()]
    pairs = [(f"gap {i}", sentences[i % len(sentences)]) for i in range(8)]
    result = run(conn, _Provider(payload(*pairs)), max_gaps=2)
    assert len(result.gaps) <= 2


# --------------------------------------------------------------------------
# Failure is data, not a crash
# --------------------------------------------------------------------------


def test_provider_failure_is_recorded(conn):
    result = run(conn, _Provider(fail=True))
    assert result.note == "provider_error" and result.gaps == []
    assert "model is down" in result.error


def test_malformed_response_is_recorded(conn):
    result = run(conn, _Provider("not json at all"))
    assert result.note == "schema_validation_failed" and result.gaps == []


def test_candidate_sentences_are_the_forward_looking_ones_only():
    text = (
        "Symptom scores fell by four points. "
        "Further research is needed to confirm the effect. "
        "Participants were recruited from three clinics. "
        "We did not examine adults over eighty."
    )
    found = gap_fulltext.candidate_sentences(text)
    assert found == [
        "Further research is needed to confirm the effect.",
        "We did not examine adults over eighty.",
    ]


def test_a_paper_with_no_forward_looking_sentence_is_not_sent_to_the_model(conn):
    """Nothing to choose between, so there is nothing to ask.

    Asking anyway invites the model to invent a gap, and costs a call to be
    told what the text already shows.
    """
    flat = paper(
        sections=[Section(title="Results", text="Symptom scores fell by four points in both arms.")]
    )
    provider = _Provider(payload(("Invented", "Something nobody wrote.")))
    result = run(conn, provider, full_text=flat)

    assert provider.calls == 0
    assert result.note == "none_stated" and result.gaps == []


def test_a_paper_with_no_body_is_not_sent_to_the_model(conn):
    provider = _Provider(payload(("x", "y")))
    result = run(conn, provider, full_text=paper(sections=[]))
    assert result.note == "no_body_text"
    assert provider.calls == 0


# --------------------------------------------------------------------------
# The prompt source
# --------------------------------------------------------------------------


def test_discussion_leads_the_text_the_model_is_shown(conn):
    """Truncating a long paper must eat the Methods, not the Discussion."""
    source = gap_fulltext.build_gap_source(paper())
    assert source.text.index("Discussion") < source.text.index("Methods")
    assert not source.truncated


def test_truncation_is_reported(conn):
    long_paper = paper(sections=[Section(title="Discussion", text="word " * 8000)])
    source = gap_fulltext.build_gap_source(long_paper, max_chars=500)
    assert source.truncated
    assert source.chars_available > len(source.text)


def test_a_quote_is_verified_against_exactly_what_was_shown(conn):
    """A sentence cut off by truncation cannot verify, and must not."""
    long_paper = paper(
        sections=[
            Section(title="Discussion", text="filler " * 400),
            Section(title="Methods", text=METHODS),
        ]
    )
    source = gap_fulltext.build_gap_source(long_paper, max_chars=200)
    assert METHODS not in source.text


# --------------------------------------------------------------------------
# Cache, same contract as every other service
# --------------------------------------------------------------------------


def test_the_same_paper_is_asked_once(conn):
    quote = "We did not examine participants over the age of eighty."
    provider = _Provider(payload(("Age", quote)))
    first = run(conn, provider)
    second = run(conn, provider)
    assert provider.calls == 1
    assert not first.from_cache and second.from_cache
    assert [g.evidence_span for g in second.gaps] == [quote]


def test_a_changed_prompt_under_the_same_version_is_refused(conn):
    quote = "We did not examine participants over the age of eighty."
    provider = _Provider(payload(("Age", quote)))
    run(conn, provider)
    with pytest.raises(CacheMismatch):
        gap_fulltext.find_gaps(
            paper(),
            work_id="W1",
            review="_discover",
            provider=provider,
            template="A different prompt: {title} {candidates}",
            meter=Meter(ceiling_usd=1.0, usd_per_1m_input=0.0, usd_per_1m_output=0.0),
            conn=conn,
        )
