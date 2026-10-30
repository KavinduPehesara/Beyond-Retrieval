"""Tests for question -> suggested papers. No network, no SPECTER2: OpenAlex
is replaced by ``candidates`` and the embedder by a bag-of-words stand-in."""

from __future__ import annotations

import json

import numpy as np
import pytest

from slr.adapters.llm import Completion, Meter
from slr.db import connect
from slr.services.suggest import relevance_criteria, similarities, suggest

VOCAB = ["vitamin", "asthma", "children", "bone", "software", "unknown"]


class _BagOfWords:
    def encode(self, texts):
        return np.array([[t.lower().count(w) for w in VOCAB] for t in texts], dtype=float)


class _Broken:
    def encode(self, texts):
        raise RuntimeError("no weights")


class _FakeProvider:
    """Includes anything mentioning asthma, quoting the abstract's first
    sentence; states a gap when the abstract has one."""

    name, model = "fake", "fake-1"

    def complete(self, prompt, *, temperature=0.0, max_tokens=512, seed=None, response_schema=None):
        abstract = prompt.split("ABSTRACT:")[-1].strip()
        first = abstract.split(".")[0].strip()
        if prompt.startswith("GAP"):
            if "unknown" in abstract:
                payload = {"value": "gap_stated", "evidence_span": "long-term effects remain unknown"}
            else:
                payload = {"value": "not_stated", "evidence_span": ""}
        else:
            payload = {"decision": "include" if "asthma" in abstract else "exclude",
                       "confidence": 0.8, "evidence_span": first}
        return Completion(text=json.dumps(payload), tokens_in=10, tokens_out=10)


def _row(i, title, abstract):
    return {"work_id": f"W{i}", "review": "_discover", "title": title, "abstract": abstract,
            "year": 2020, "doi": None, "source_url": None}


ROWS = [
    _row(1, "Software defects", "Software defect prediction with metrics in large open source projects."),
    _row(2, "Vitamin D and asthma in children",
         "Vitamin D supplementation reduced asthma attacks in children. Long-term effects remain unknown."),
    _row(3, "Vitamin D and bone", "Vitamin D improved bone density in older adults over two years."),
]

SCREEN = "SCREEN {criteria}\nTITLE: {title}\nABSTRACT: {abstract}"
GAP = "GAP\nTITLE: {title}\nABSTRACT: {abstract}"


@pytest.fixture()
def conn(tmp_path):
    c = connect(tmp_path / "test.db")
    yield c
    c.close()


def _suggest(conn, **kw):
    return suggest(
        conn, "vitamin D for asthma in children",
        provider=_FakeProvider(), screen_template=SCREEN, gap_template=GAP,
        meter=Meter(ceiling_usd=1.0, usd_per_1m_input=0.0, usd_per_1m_output=0.0),
        candidates=ROWS, use_cache=False, **kw,
    )


def test_similarities_rank_the_closer_text_higher():
    sims = similarities("vitamin asthma", ["vitamin asthma children", "software"], _BagOfWords())
    assert sims[0] > sims[1]


def test_the_question_becomes_the_inclusion_rule():
    assert "vitamin D for asthma" in relevance_criteria("vitamin D for asthma")


def test_top_n_keeps_the_closest_papers(conn):
    result = _suggest(conn, n=2, embedder=_BagOfWords())
    assert result.ranking == "specter2"
    assert result.n_candidates == 3
    assert {s.row["work_id"] for s in result.suggestions} == {"W2", "W3"}


def test_verified_relevant_papers_come_first(conn):
    result = _suggest(conn, n=3, embedder=_BagOfWords())
    first = result.suggestions[0]
    assert first.row["work_id"] == "W2"
    assert first.relevant
    assert not result.suggestions[-1].relevant


def test_a_stated_gap_is_matched_against_the_question(conn):
    result = _suggest(conn, n=3, embedder=_BagOfWords())
    w2 = next(s for s in result.suggestions if s.row["work_id"] == "W2")
    assert w2.gap.value == "gap_stated" and w2.gap.span_verified
    assert w2.gap_similarity is not None
    assert all(s.gap_similarity is None for s in result.suggestions if s.row["work_id"] != "W2")


def test_a_broken_embedder_falls_back_and_says_so(conn):
    result = _suggest(conn, n=3, embedder=_Broken())
    assert result.ranking == "openalex"
    assert "unavailable" in result.ranking_note
    assert [s.row["work_id"] for s in result.suggestions][0] == "W2"
    assert all(s.similarity is None for s in result.suggestions)


def test_suggestions_never_touch_the_work_table(conn):
    _suggest(conn, n=3, embedder=_BagOfWords())
    assert conn.execute("SELECT COUNT(*) FROM work").fetchone()[0] == 0


def test_an_empty_question_is_refused(conn):
    with pytest.raises(ValueError):
        suggest(conn, "  ", provider=_FakeProvider(), screen_template=SCREEN, gap_template=GAP,
                meter=Meter(ceiling_usd=1.0, usd_per_1m_input=0.0, usd_per_1m_output=0.0),
                candidates=ROWS)


def test_each_answer_is_committed_as_it_arrives(tmp_path):
    """The cache is written per answer and committed straight away, so a
    second request is never locked out for the length of this one, and an
    answer survives the request rather than rolling back with it."""
    db = tmp_path / "shared.db"
    conn = connect(db, check_same_thread=False)
    seen_by_other = []

    class _Watching(_FakeProvider):
        def complete(self, prompt, **kw):
            other = connect(db)
            seen_by_other.append(other.execute("SELECT COUNT(*) FROM cached_response").fetchone()[0])
            # A second writer must not be locked out mid-request.
            other.execute("BEGIN IMMEDIATE"); other.rollback(); other.close()
            return super().complete(prompt, **kw)

    suggest(conn, "vitamin D for asthma in children", provider=_Watching(), screen_template=SCREEN,
            gap_template=GAP, meter=Meter(ceiling_usd=1.0, usd_per_1m_input=0.0, usd_per_1m_output=0.0),
            candidates=ROWS, n=2, embedder=_BagOfWords())
    conn.close()
    assert seen_by_other == [0, 1, 2, 3]
    other = connect(db)
    assert other.execute("SELECT COUNT(*) FROM cached_response").fetchone()[0] == 4


# --- two models over the same papers -----------------------------------


class _AlwaysExclude:
    """A second opinion that never agrees the paper is relevant."""

    name, model = "fake2", "fake-2"

    def complete(self, prompt, *, temperature=0.0, max_tokens=512, seed=None, response_schema=None):
        abstract = prompt.split("ABSTRACT:")[-1].strip()
        first = abstract.split(".")[0].strip()
        if prompt.startswith("GAP"):
            payload = {"value": "not_stated", "evidence_span": ""}
        else:
            payload = {"decision": "exclude", "confidence": 0.8, "evidence_span": first}
        return Completion(text=json.dumps(payload), tokens_in=10, tokens_out=10)


def _arm(label, provider):
    from slr.services.suggest import Arm

    return Arm(
        label=label,
        model=provider.model,
        provider=provider,
        meter=Meter(ceiling_usd=1.0, usd_per_1m_input=0.0, usd_per_1m_output=0.0),
    )


def _cross(conn, arms, **kw):
    from slr.services.suggest import suggest_cross_checked

    return suggest_cross_checked(
        conn, "vitamin D for asthma in children",
        arms=arms, screen_template=SCREEN, gap_template=GAP,
        candidates=ROWS, use_cache=False, **kw,
    )


def _by_id(result):
    return {s.row["work_id"]: s for s in result.suggestions}


def test_two_models_that_agree_are_marked_agreed(conn):
    arms = [_arm("A", _FakeProvider()), _arm("B", _FakeProvider())]
    got = _by_id(_cross(conn, arms, n=3, embedder=_BagOfWords()))
    assert got["W2"].agreement == "agreed"
    assert got["W2"].relevant
    assert [v.label for v in got["W2"].verdicts] == ["A", "B"]


def test_a_split_verdict_is_handed_back_rather_than_voted_on(conn):
    """One yes and one no is not half a yes.

    With two arms a majority vote is a coin toss, so the paper leaves the
    relevant group and is shown to the reader as something to check.
    """
    arms = [_arm("A", _FakeProvider()), _arm("B", _AlwaysExclude())]
    got = _by_id(_cross(conn, arms, n=3, embedder=_BagOfWords()))
    assert got["W2"].agreement == "split"
    assert not got["W2"].relevant, "a disputed paper is not a verified include"
    assert {v.decision.decision for v in got["W2"].verdicts} == {"include", "exclude"}


def test_a_gap_found_by_one_model_is_kept_and_attributed(conn):
    """Gaps take the union while relevance takes the intersection.

    The measured weakness of gap suggestion in this project is recall, so
    dropping a gap because only one model saw it would cost the thing that
    is already scarce.
    """
    arms = [_arm("A", _FakeProvider()), _arm("B", _AlwaysExclude())]
    got = _by_id(_cross(conn, arms, n=3, embedder=_BagOfWords()))
    assert got["W2"].gap.value == "gap_stated"
    assert got["W2"].gap_sources == ["A"], "the model that found it is named"


def test_each_arm_is_metered_on_its_own(conn):
    arms = [_arm("A", _FakeProvider()), _arm("B", _FakeProvider())]
    _cross(conn, arms, n=2, embedder=_BagOfWords())
    assert all(a.meter.calls == 4 for a in arms), "two papers, two questions each"


def test_one_arm_behaves_exactly_as_the_single_model_path(conn):
    arms = [_arm("A", _FakeProvider())]
    got = _by_id(_cross(conn, arms, n=3, embedder=_BagOfWords()))
    assert got["W2"].agreement == "single"
    assert got["W2"].relevant


def test_cross_checking_needs_at_least_one_model(conn):
    with pytest.raises(ValueError, match="no model"):
        _cross(conn, [], n=2, embedder=_BagOfWords())


class _IncludesButMisquotes:
    """Says the paper is relevant, but its quote is not in the abstract.

    The failure this project measures most carefully: an answer that cannot
    be substantiated is not the same as an answer of "no".
    """

    name, model = "fake3", "fake-3"

    def complete(self, prompt, *, temperature=0.0, max_tokens=512, seed=None, response_schema=None):
        if prompt.startswith("GAP"):
            payload = {"value": "not_stated", "evidence_span": ""}
        else:
            payload = {"decision": "include", "confidence": 0.8,
                       "evidence_span": "a sentence that appears in no abstract anywhere"}
        return Completion(text=json.dumps(payload), tokens_in=10, tokens_out=10)


def test_an_unsubstantiated_second_opinion_is_not_a_disagreement(conn):
    """A quote that was not found is silence, not a no.

    Reporting it as a split would put a verdict in the model's mouth that it
    never substantiated, and would hide the verification failure behind a
    word that sounds like a considered judgement.
    """
    arms = [_arm("A", _FakeProvider()), _arm("B", _IncludesButMisquotes())]
    got = _by_id(_cross(conn, arms, n=3, embedder=_BagOfWords()))
    assert got["W2"].agreement == "partial", "not 'split': B said include, it just could not prove it"
    assert not got["W2"].relevant, "a paper nobody could cross-check is handed back"
    # B asked for "include" and the verifier downgraded it, which is the
    # behaviour that was already there: a decision whose quote cannot be
    # found is withheld rather than recorded as the judgement it claimed.
    assert [v.decision.decision for v in got["W2"].verdicts] == ["include", "unverified"]


def test_a_split_needs_both_models_to_have_substantiated_themselves(conn):
    arms = [_arm("A", _FakeProvider()), _arm("B", _AlwaysExclude())]
    got = _by_id(_cross(conn, arms, n=3, embedder=_BagOfWords()))
    assert got["W2"].agreement == "split"
    assert all(v.decision.span_verified for v in got["W2"].verdicts)
