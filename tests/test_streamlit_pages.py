"""Smoke tests for the dashboard.

Streamlit's AppTest runs the page script for real (real widgets, real
session_state, real rendering) but api_client's HTTP calls are monkeypatched
to canned data shaped like the API's response models, so these run with no
server and no database.
"""

from __future__ import annotations

import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1] / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

import pytest
from streamlit.testing.v1 import AppTest

import account_view
import api_client


def _paper(work_id, title, *, status="include", verified=True, quote="we studied X in children",
           gap=None, relevance=0.9, gap_match=None):
    return {
        "work_id": work_id, "title": title, "year": 2021, "abstract": "An abstract.",
        "source_url": "https://example.org/" + work_id, "doi": "10.1/" + work_id,
        "decision": {"status": status, "confidence": 0.8, "quote": quote, "span_verified": verified,
                     "verify_note": "exact_after_normalisation" if verified else "not_found",
                     "from_cache": False},
        "gap": gap or {"status": "not_stated"},
        "relevance": relevance, "gap_match": gap_match,
    }


SESSION = {
    "session_id": None, "query": "vitamin D and asthma in children", "criteria": "...",
    "n_found": 3, "n_screened": 3, "n_included": 1, "n_excluded": 1, "n_referred": 1,
    "n_verified_quotes": 2, "n_gaps": 1, "n_candidates": 48, "ranking": "specter2",
    "ranking_note": "Ranked by SPECTER2 similarity between your question and each title and abstract.",
    "papers": [
        _paper("W1", "Vitamin D trial in asthmatic children",
               gap={"status": "gap_stated", "quote": "long-term effects remain unknown"}, gap_match=0.81),
        _paper("W2", "A paper whose reason did not verify", status="include", verified=False,
               quote="invented sentence", relevance=0.8),
        _paper("W3", "Vitamin D and bone density", status="exclude", quote="bone density in adults",
               relevance=0.7),
    ],
}

FULLTEXT = {
    "n_requested": 2, "n_with_full_text": 1,
    "papers": [
        {"work_id": "W1", "title": "Vitamin D trial in asthmatic children", "found": True,
         "note": "full text from PMC1: 1 of 5 fields verified",
         "primary_outcome": {"status": "verified", "value": "fewer attacks", "quote": "fewer attacks were seen"},
         "effect_size": {"status": "unverified"},
         "statistical_methods": {"status": "not_stated"},
         "tables": [], "equations": [], "figures": [], "coverage": []},
        {"work_id": "W3", "title": "Vitamin D and bone density", "found": False,
         "note": "in Europe PMC but not open access -- full text is paywalled",
         "tables": [], "equations": [], "figures": [], "coverage": []},
    ],
}


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    monkeypatch.setattr(api_client, "health", lambda: True)
    monkeypatch.setattr(
        account_view, "account_request",
        lambda method, path, **kw: [] if path == "/discover/sessions" else {"configured": False},
    )


def _home(session_state=None):
    at = AppTest.from_file(str(APP_DIR / "Home.py"), default_timeout=30)
    at.session_state["guest_access"] = True
    for key, value in (session_state or {}).items():
        at.session_state[key] = value
    return at.run()


def _button(at, label):
    return next(b for b in at.button if b.label == label)


def _signed_in():
    return {"google_account": {"name": "R", "email": "r@example.org", "token": "t"},
            "active_project": "p1", "project_name": "Asthma"}


def test_there_are_no_validation_pages():
    assert not (APP_DIR / "pages").exists() or not any((APP_DIR / "pages").glob("*.py"))


def test_home_asks_for_a_research_question():
    at = _home()
    assert not at.exception
    assert at.text_area[0].label == "What is your research question?"


def test_an_empty_question_is_refused(monkeypatch):
    called = []
    monkeypatch.setattr(api_client, "suggest_watched", lambda *a, **kw: called.append(1))
    at = _home()
    _button(at, "Find papers").click().run()
    assert not called


def test_asking_a_question_shows_ranked_suggestions(monkeypatch):
    seen = {}

    def fake_suggest_watched(query, n, on_progress):
        seen.update(query=query, n=n)
        return SESSION

    monkeypatch.setattr(api_client, "suggest_watched", fake_suggest_watched)
    at = _home()
    at.text_area[0].input("vitamin D and asthma in children")
    _button(at, "Find papers").click().run()
    assert not at.exception
    assert seen == {"query": "vitamin D and asthma in children", "n": 20}
    md = " ".join(m.value for m in at.markdown)
    assert "#1 · \U0001f7e2 Addresses your question — Vitamin D trial in asthmatic children" in md
    assert "Check it yourself — A paper whose reason did not verify" in md
    assert "Probably off-topic — Vitamin D and bone density" in md


def test_the_page_says_how_far_the_search_has_got(monkeypatch):
    """A spinner says only that something is happening.

    The page shows papers judged out of papers to judge, which is the only
    reassurance it can give honestly while a model works.
    """
    shown = []

    def fake_suggest_watched(query, n, on_progress):
        on_progress(10, "screening", 0, 3)
        on_progress(40, "screening", 1, 3)
        on_progress(100, "done", 3, 3)
        shown.append(True)
        return SESSION

    monkeypatch.setattr(api_client, "suggest_watched", fake_suggest_watched)
    at = _home()
    at.text_area[0].input("vitamin D and asthma in children")
    _button(at, "Find papers").click().run()

    assert not at.exception
    assert shown, "the page never ran the watched search"
    # The answer still arrives; progress is reporting, not replacing it.
    assert at.session_state["session"] == SESSION


def test_nothing_found_and_nothing_readable_are_told_apart():
    """Two different failures used to read identically.

    Nothing matching the wording is the researcher's to fix; matches with
    no redistributable abstract is the index's limit, and telling them to
    reword a perfectly good question wastes their time.
    """
    nothing = _home({"session": {**SESSION, "papers": [], "n_candidates": 0}})
    said = " ".join(w.value for w in nothing.warning)
    assert "found nothing" in said
    assert "abstract" not in said

    unreadable = _home({"session": {**SESSION, "papers": [], "n_candidates": 37}})
    said = " ".join(w.value for w in unreadable.warning)
    assert "37 papers" in said
    assert "none had an abstract" in said


def test_each_suggestion_says_whether_it_can_be_read_in_full():
    """Told before the pick, not after, and nothing removed for it."""
    session = {**SESSION, "papers": [
        {**SESSION["papers"][0], "fulltext_status": "held"},
        {**SESSION["papers"][1], "fulltext_status": "elsewhere",
         "oa_host": "World Journal of Gastroenterology"},
        {**SESSION["papers"][2], "fulltext_status": "none"},
    ]}
    at = _home({"session": session})
    captions = " ".join(c.value for c in at.caption)

    assert "readable in full" in captions
    assert "free copy at World Journal of Gastroenterology" in captions
    assert "abstract only" in captions
    # All three are still on the list: a paywall is not a judgement about
    # the research.
    md = " ".join(m.value for m in at.markdown)
    for paper in session["papers"]:
        assert paper["title"] in md


def test_a_failed_availability_lookup_shows_no_badge_at_all():
    at = _home({"session": {**SESSION, "papers": [
        {**SESSION["papers"][0], "fulltext_status": "unknown"}]}})
    captions = " ".join(c.value for c in at.caption)
    assert "readable in full" not in captions
    assert "abstract only" not in captions


def test_an_unverified_reason_is_never_shown_as_one():
    at = _home({"session": SESSION})
    md = " ".join(m.value for m in at.markdown)
    assert "invented sentence" not in md
    assert "Why: “we studied X in children”" in md


def test_stated_gaps_are_shown_against_the_question():
    at = _home({"session": SESSION})
    md = " ".join(m.value for m in at.markdown)
    captions = " ".join(c.value for c in at.caption)
    assert "Is your question an open gap?" in md
    assert "long-term effects remain unknown" in md
    assert "similarity 0.81" in captions


def test_the_page_says_what_the_search_cost():
    """RQ2 asks what the tool costs; the page should not make that a mystery.

    A cached answer is not paid for twice, so the call counts have to be
    there or a repeat looks like a cheaper model rather than a free one.
    """
    priced = _home({"session": {**SESSION, "answered_by": "Gemini", "model": "gemini-3.5-flash-lite",
                                "cost_usd": 0.0045, "model_calls": 40, "cached_calls": 17}})
    said = " ".join(c.value for c in priced.caption)
    assert "Screened by Gemini (gemini-3.5-flash-lite)." in said
    assert "40 model calls, 17 from an earlier run: US$0.0045 for the other 23." in said

    free = _home({"session": {**SESSION, "answered_by": "Local model", "model": "qwen2.5:7b-instruct",
                              "cost_usd": 0.0, "model_calls": 40, "cached_calls": 0}})
    said = " ".join(c.value for c in free.caption)
    assert "40 model calls: no cost, the model runs on this machine." in said

    # A rehearsed question is answered entirely from cache. Saying so stops
    # a free repeat reading as a free model.
    repeated = _home({"session": {**SESSION, "answered_by": "Gemini", "model": "gemini-3.5-flash-lite",
                                  "cost_usd": 0.0, "model_calls": 40, "cached_calls": 40}})
    said = " ".join(c.value for c in repeated.caption)
    assert "all answered from an earlier run: nothing new was spent." in said


def test_a_guest_is_asked_to_sign_in_rather_than_shown_a_dead_button():
    """One thing to act on, not a greyed control under a message."""
    at = _home({"session": SESSION})
    assert not [b for b in at.button if b.label.startswith("Extract full text")]
    assert "Sign in" in " ".join(i.value for i in at.info)


def test_a_signed_in_reader_with_nothing_picked_sees_the_button_disabled():
    at = _home({"session": SESSION, **_signed_in()})
    button = next(b for b in at.button if b.label.startswith("Extract full text"))
    assert button.disabled
    assert button.label == "Extract full text from 0 paper(s)"


def test_selected_papers_are_sent_for_full_text(monkeypatch):
    sent = []
    monkeypatch.setattr(
        api_client, "discover_fulltext_watched",
        lambda targets, on_progress: sent.extend(targets),
    )
    monkeypatch.setattr(api_client, "read_live_session", lambda sid: {"fulltext": FULLTEXT})
    at = _home({"session": SESSION, **_signed_in()})
    at.checkbox(key="pick-W1").check()
    at.checkbox(key="pick-W3").check()
    at.run()
    button = next(b for b in at.button if b.label.startswith("Extract full text"))
    assert button.label == "Extract full text from 2 paper(s)"
    assert not button.disabled
    button.click().run()
    assert not at.exception
    assert [t["work_id"] for t in sent] == ["W1", "W3"]
    assert sent[0]["doi"] == "10.1/W1"


def test_the_page_names_the_paper_it_is_reading(monkeypatch):
    """Reading is the slowest thing the tool does, and a spinner says least.

    Each paper is a lookup, a download and two long model calls, so the
    page reports which one of how many it is on.
    """
    reported = []

    def fake_watched(targets, on_progress):
        on_progress(10, "reading", 0, len(targets))
        on_progress(55, "reading", 1, len(targets))
        reported.append(len(targets))

    monkeypatch.setattr(api_client, "discover_fulltext_watched", fake_watched)
    monkeypatch.setattr(api_client, "read_live_session", lambda sid: {"fulltext": FULLTEXT})
    at = _home({"session": SESSION, **_signed_in()})
    at.checkbox(key="pick-W1").check()
    at.run()
    next(b for b in at.button if b.label.startswith("Extract full text")).click().run()

    assert not at.exception
    assert reported == [1], "the page never ran the watched reading"


def test_full_text_results_are_compared_and_withhold_unverified_values():
    at = _home({"session": SESSION, **_signed_in(), "fulltext": FULLTEXT})
    assert not at.exception
    table = at.dataframe[0].value
    w1 = table[table["Paper"] == "Vitamin D trial in asthmatic children"].iloc[0]
    assert w1["Main result"] == "fewer attacks"
    assert w1["Effect size"] == "withheld (quote not found)"
    assert w1["Method"] == "not stated"
    assert w1["Relevance"] == "Addresses your question"
    captions = " ".join(c.value for c in at.caption)
    assert "paywalled" in captions


def test_eight_category_view_keeps_empty_categories_and_source_passages_visible():
    from slr.adapters.fulltext import parse_jats
    from slr.services.fulltext_categories import enrich_fulltext
    paper = parse_jats('<article><body><sec><title>Methods</title><p>We recruited adults and used a regression model.</p></sec><sec><title>Limitations</title><p>We did not measure diet in the cohort.</p></sec></body></article>')
    view = {"work_id": "eight-category-test", "tables": [], "equations": [], **enrich_fulltext(paper)}
    at = AppTest.from_string("import streamlit as st\nfrom fulltext_view import render_categories\nrender_categories(st.session_state['paper'])")
    at.session_state["paper"] = view
    at.run()
    assert not at.exception
    assert len(at.subheader) == 8
    assert not at.dataframe
    assert len(at.get("popover")) == 1
    source_text = " ".join(t.value for t in at.text)
    assert "We did not measure diet in the cohort." in source_text
    assert "We recruited adults and used a regression model." in source_text


def test_table_grid_preserves_headers_merged_cell_positions_and_all_values():
    from fulltext_view import _grid
    table = {"rows": [["Treatment"], ["A", "4.5"], ["6.9"]],
             "cell_spans": [[{"colspan": "2"}], [{"rowspan": "2"}, {}], [{}]]}
    assert _grid(table) == [["Treatment", ""], ["A", "4.5"], ["", "6.9"]]


def test_full_text_results_offer_a_download(monkeypatch):
    monkeypatch.setattr(api_client, "export_project", lambda sid: ("asthma.zip", b"PK fake zip"))
    at = _home({"session": SESSION, **_signed_in(), "fulltext": FULLTEXT})
    _button(at, "Prepare download").click().run()
    assert not at.exception
    downloads = at.get("download_button")
    assert any(d.proto.label == "Download folder (.zip)" for d in downloads)


# --- two models over the same papers -----------------------------------


def _verdict(label, model, status, verified, quote, gap_status="not_stated"):
    return {"label": label, "model": model, "status": status, "span_verified": verified,
            "quote": quote, "verify_note": "exact_after_normalisation" if verified else "not_found",
            "gap_status": gap_status, "gap_quote": None}


def _cross_session(agreement, verdicts, **extra):
    paper = _paper("W9", "A contested paper")
    paper["agreement"] = agreement
    paper["verdicts"] = verdicts
    session = {
        **SESSION,
        "papers": [paper],
        "answered_by": "ChatGPT and Gemini",
        "model": "gpt-5-nano, gemini-3.5-flash-lite",
        "cost_usd": 0.0036, "model_calls": 24, "cached_calls": 0,
        "arms": [
            {"label": "ChatGPT", "model": "gpt-5-nano", "cost_usd": 0.0005,
             "model_calls": 12, "cached_calls": 0},
            {"label": "Gemini", "model": "gemini-3.5-flash-lite", "cost_usd": 0.0031,
             "model_calls": 12, "cached_calls": 0},
        ],
    }
    session.update(extra)
    return session


def test_a_split_paper_names_which_model_said_what():
    at = _home({"session": _cross_session("split", [
        _verdict("ChatGPT", "gpt-5-nano", "exclude", True, "about adults, not children"),
        _verdict("Gemini", "gemini-3.5-flash-lite", "include", True, "we studied X in children"),
    ], n_split=1)})
    page = " ".join(m.value for m in at.markdown) + " ".join(c.value for c in at.caption)
    assert "Gemini says this addresses your question" in page
    assert "ChatGPT says it does not" in page


def test_a_split_paper_is_not_counted_as_addressing_the_question():
    at = _home({"session": _cross_session("split", [
        _verdict("ChatGPT", "gpt-5-nano", "exclude", True, "about adults"),
        _verdict("Gemini", "gemini-3.5-flash-lite", "include", True, "we studied X in children"),
    ], n_split=1)})
    page = " ".join(m.value for m in at.markdown)
    assert "Check it yourself" in page
    assert "Addresses your question" not in page


def test_an_unverified_second_opinion_is_not_described_as_disagreement():
    """The two failures must not be worded the same.

    One model saying no is a judgement. One model failing to produce a
    findable quote is an absence of judgement, and the page has to say which
    of the two happened.
    """
    at = _home({"session": _cross_session("partial", [
        _verdict("ChatGPT", "gpt-5-nano", "include", True, "we studied X in children"),
        _verdict("Gemini", "gemini-3.5-flash-lite", "unverified", False, "an invented sentence"),
    ])})
    page = " ".join(m.value for m in at.markdown) + " ".join(c.value for c in at.caption)
    assert "not found in the abstract" in page
    assert "was not cross-checked" in page
    assert "says it does not" not in page, "an unverified quote is not a no"


def test_the_page_splits_the_cost_by_vendor_and_keeps_the_caveat():
    at = _home({"session": _cross_session("agreed", [
        _verdict("ChatGPT", "gpt-5-nano", "include", True, "we studied X in children"),
        _verdict("Gemini", "gemini-3.5-flash-lite", "include", True, "we studied X in children"),
    ])})
    said = " ".join(c.value for c in at.caption)
    assert "ChatGPT US$0.0005" in said and "Gemini US$0.0031" in said
    assert "consistency, not correctness" in said
