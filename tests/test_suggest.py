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
