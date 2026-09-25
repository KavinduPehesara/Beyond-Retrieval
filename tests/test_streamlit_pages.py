"""Smoke tests for the dashboard panels.

Streamlit's AppTest runs each page script for real (real widgets, real
session_state, real rendering) but api_client's HTTP calls are monkeypatched
to canned data shaped exactly like the API's response models, so these run
with no server and no database. They exist to catch what a read-through
can't: an unscaled percentage, a KeyError on a field that's sometimes None,
an import that only fails once Streamlit actually executes the module.
"""

from __future__ import annotations

import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1] / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

import pytest
from streamlit.testing.v1 import AppTest

import api_client

REVIEWS = [
    {
        "review": "Nelson_2002", "domain": "Medicine", "n_records": 366, "n_included": 80,
        "prevalence": 0.219, "criteria_status": "published",
        "screen_run": "run-screen-1", "extract_run": "run-extract-1", "gap_run": "run-gap-1",
    },
    {
        "review": "Smid_2020", "domain": "Computer science", "n_records": 2627, "n_included": 27,
        "prevalence": 0.010, "criteria_status": "published",
        "screen_run": None, "extract_run": None, "gap_run": None,
    },
]

PAPERS = [
    {"work_id": "W1", "title": "A randomised trial of X", "year": 2019, "venue": "J. Testing",
     "decision": "include", "confidence": 0.9, "span_verified": True},
    {"work_id": "W2", "title": "A survey of Y", "year": 2020, "venue": None,
     "decision": "unverified", "confidence": 0.4, "span_verified": False},
]

PAPER_DETAIL = {
    "work_id": "W1", "title": "A randomised trial of X", "year": 2019, "venue": "J. Testing", "doi": None,
    "decision": "include", "confidence": 0.9, "span_verified": True,
    "screen_quote": "a randomised trial of 100 patients", "screen_note": "exact_after_normalisation",
    "study_design": {"status": "verified", "value": "RCT", "quote": "a randomised trial", "note": "exact_after_normalisation"},
    "sample_size": {"status": "not_stated"},
    "country": {"status": "unverified", "quote": "somewhere"},
    "key_finding": {"status": "missing"},
    "gap": {"status": "gap_stated", "quote": "further studies are needed", "rating": "valid", "kind": "open"},
}

GAPS = [
    {"work_id": "W1", "title": "A randomised trial of X", "status": "gap_stated",
     "quote": "further studies are needed", "rating": "valid", "kind": "open"},
    {"work_id": "W2", "title": "A survey of Y", "status": "gap_stated",
     "quote": "we discuss limitations", "rating": "invalid", "kind": None},
]

METRICS = {
    "run_id": "run-screen-1", "review": "Nelson_2002", "verification_rate": 0.505,
    "recall_verified": 0.938, "precision_verified": 0.409, "agreement_ac1": 0.28,
}

EXTRACTION_SUMMARY = {
    "run_id": "run-extract-1", "review": "Nelson_2002",
    "fields": {
        "study_design": {"verified": 70, "not_stated": 5, "unverified": 5},
        "sample_size": {"verified": 60, "not_stated": 15, "unverified": 5},
        "country": {"verified": 18, "not_stated": 60, "unverified": 2},
        "key_finding": {"verified": 78, "not_stated": 0, "unverified": 2},
    },
}


@pytest.fixture(autouse=True)
def _patched(monkeypatch):
    monkeypatch.setattr(api_client, "health", lambda: True)
    monkeypatch.setattr(api_client, "list_reviews", lambda: REVIEWS)
    monkeypatch.setattr(api_client, "review_criteria", lambda review: {"review": review, "text": "Include RCTs.", "status": "published", "source": "test"})
    monkeypatch.setattr(api_client, "list_papers", lambda review, **kw: PAPERS)
    monkeypatch.setattr(api_client, "paper_detail", lambda review, work_id, **kw: PAPER_DETAIL)
    monkeypatch.setattr(api_client, "list_gaps", lambda review, run_id=None: GAPS)
    monkeypatch.setattr(api_client, "review_metrics", lambda review, run_id=None: METRICS)
    monkeypatch.setattr(api_client, "extraction_summary", lambda review, run_id=None: EXTRACTION_SUMMARY)
    monkeypatch.setattr(api_client, "override_summary", lambda review, run_id: {"n_overrides": 0, "n_changed": 0, "n_confirmed": 0, "override_rate": None, "by_model_decision": {}})
    monkeypatch.setattr(api_client, "query_rank", lambda review, strategy, query_text, top_n: [
        {"rank": 1, "work_id": "W1", "title": "A randomised trial of X", "year": 2019},
        {"rank": 2, "work_id": "W2", "title": "A survey of Y", "year": 2020},
    ])
    monkeypatch.setattr(api_client, "query_screen", lambda review, work_ids, model, prompt_version: [
        {"work_id": wid, "decision": "include", "confidence": 0.9, "quote": "a randomised trial",
         "span_verified": True, "verify_note": "exact_after_normalisation", "from_cache": False}
        for wid in work_ids
    ])
    monkeypatch.setattr(api_client, "create_override", lambda run_id, review, work_id, decision, rationale: {
        "work_id": work_id, "model_decision": "unverified", "model_verified": False,
        "human_decision": decision, "changed": True,
    })


def _run(path):
    at = AppTest.from_file(str(APP_DIR / path))
    at.run()
    assert not at.exception, [str(e) for e in at.exception]
    return at


def test_home_renders_the_review_table():
    at = _run("Home.py")
    assert "Beyond Retrieval" in at.title[0].value
    # prevalence is pre-scaled to a percent value before the dataframe is built
    row = next(r for r in at.dataframe[0].value.to_dict("records") if r["review"] == "Nelson_2002")
    assert row["prevalence"] == pytest.approx(21.9)


def test_home_warns_about_unscreened_reviews():
    at = _run("Home.py")
    assert any("Smid_2020" in w.value for w in at.warning)


def test_search_and_screen_ranks_and_screens():
    at = _run("pages/1_Search_and_Screen.py")
    submit = [b for b in at.button if b.label == "Rank"][0]
    submit.click().run()
    assert not at.exception
    assert any("candidates" in s.value.lower() for s in at.subheader)

    picker = at.multiselect[0]
    picker.select(picker.options[0]).run()
    screen = [b for b in at.button if b.label == "Screen selected"][0]
    screen.click().run()
    assert not at.exception
    assert any(s.value.lower() == "decisions" for s in at.subheader)


def test_results_and_override_shows_the_selected_record_and_can_submit():
    at = _run("pages/2_Results_and_Override.py")
    assert not at.exception
    submit = [b for b in at.button if "disposition" in b.label.lower()]
    assert submit
    submit[0].click().run()
    assert not at.exception
    assert any("Overrode" in s.value or "Confirmed" in s.value for s in at.success)


def test_extraction_page_shows_field_coverage():
    at = _run("pages/3_Extraction.py")
    assert not at.exception
    metric_labels = [m.label for m in at.metric]
    assert set(metric_labels) >= {"study_design", "sample_size", "country", "key_finding"}


def test_gap_discovery_page_shows_precision():
    at = _run("pages/4_Gap_Discovery.py")
    assert not at.exception
    precision = next(m for m in at.metric if m.label == "Precision")
    assert precision.value == "50%"  # 1 valid of 2 rated in the fixture


def test_trust_dashboard_scales_percentages_before_display():
    at = _run("pages/5_Trust_Dashboard.py")
    assert not at.exception
    rows = {r["Review"]: r for r in at.dataframe[0].value.to_dict("records")}
    # verification_rate 0.505 must be scaled to 50.5, not left as 0.505 (the bug this test exists to catch)
    assert rows["Nelson_2002"]["Verified"] == pytest.approx(50.5)
    assert rows["Nelson_2002"]["Prevalence"] == pytest.approx(21.9)
    assert pytest.approx(rows["Smid_2020"]["Prevalence"]) == 1.0
    assert rows["Smid_2020"]["Verified"] is None or rows["Smid_2020"]["Verified"] != rows["Smid_2020"]["Verified"]  # NaN or None: not screened
