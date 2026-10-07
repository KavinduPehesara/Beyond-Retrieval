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

_VERIFIED = {"status": "verified", "value": "v", "quote": "a genuinely long quote here", "note": None}

# One ad-hoc review session, shaped like DiscoverSessionOut. Three papers on
# purpose, one of each outcome: a verified keep that went on to extraction, a
# verified drop that did not, and a referral whose quote wasn't found. The
# page has to render all three differently, and the referral is the one most
# likely to be got wrong -- an include whose quote failed is not a keep.
DISCOVER_SESSION = {
    "query": "hormone therapy cardiovascular outcomes",
    "criteria": "Include randomised controlled trials with a non-user comparison group.",
    "n_found": 3,
    "n_screened": 3,
    "n_included": 1,
    "n_excluded": 1,
    "n_referred": 1,
    "n_verified_quotes": 2,
    "n_gaps": 1,
    "papers": [
        {
            "work_id": "https://openalex.org/W1", "title": "A paper found on the open web",
            "year": 2021, "source_url": "https://doi.org/10.1/1",
            "study_design": _VERIFIED, "sample_size": _VERIFIED,
            "country": _VERIFIED, "key_finding": _VERIFIED,
            "gap": {"status": "gap_stated", "quote": "remains an open question",
                    "rating": None, "kind": None, "note": None},
            "decision": {"status": "include", "confidence": 0.91,
                         "quote": "a randomised controlled trial of 400 women",
                         "span_verified": True, "verify_note": "exact_after_normalisation",
                         "from_cache": False},
        },
        {
            "work_id": "https://openalex.org/W2", "title": "An animal study",
            "year": 2019, "source_url": None,
            "study_design": None, "sample_size": None, "country": None, "key_finding": None,
            "gap": None,
            "decision": {"status": "exclude", "confidence": 0.88,
                         "quote": "we used a murine model",
                         "span_verified": True, "verify_note": "exact_after_normalisation",
                         "from_cache": False},
        },
        {
            "work_id": "https://openalex.org/W3", "title": "A paper whose quote was invented",
            "year": 2020, "source_url": None,
            "study_design": None, "sample_size": None, "country": None, "key_finding": None,
            "gap": None,
            "decision": {"status": "include", "confidence": 0.84,
                         "quote": "a sentence that is not in the abstract",
                         "span_verified": False, "verify_note": "not_found",
                         "from_cache": False},
        },
    ],
}


# Chart fixtures, shaped exactly like slr.eval.charts returns. The numbers
# are the recorded ones where it matters: CHARTS_CONFIDENCE's two means are
# Nelson_2002's real pair, because the Trust Dashboard renders the
# difference between them as a metric and a wrong shape would pass silently.
CHARTS_TRUST = {
    "runs": {"Nelson_2002": "run-screen-1"},
    "verification": [
        {"review": "Nelson_2002", "run_id": "run-screen-1", "n": 366, "verified": 185,
         "verification_rate": 0.505, "prevalence": 0.219},
    ],
    "failures": {
        "notes": ["not_found", "schema_validation_failed"],
        "rows": [
            {"review": "Nelson_2002", "total_failures": 181,
             "counts": {"not_found": 170, "schema_validation_failed": 11},
             "shares": {"not_found": 170 / 181, "schema_validation_failed": 11 / 181}},
        ],
        "totals": {"not_found": 170, "schema_validation_failed": 11},
    },
    "verification_vs_recall": [
        {"review": "Nelson_2002", "run_id": "run-screen-1", "prevalence": 0.219,
         "verification_rate": 0.505, "recall_verified": 0.906,
         "recall_with_referrals": 0.95, "agreement_ac1": 0.28},
    ],
    "overrides": {"n": 13, "changed": 9, "confirmed": 4, "override_rate": 9 / 13,
                  "disposed_referrals": 8, "disposed_verified": 5,
                  "by_review": {"Nelson_2002": 13}},
}

CHARTS_CONFIDENCE = {
    "run_id": "run-screen-1", "review": "Nelson_2002",
    "bin_edges": [i / 10 for i in range(11)],
    "bin_labels": [f"{i / 10:.1f}-{(i + 1) / 10:.1f}" for i in range(10)],
    "verified": [0, 0, 0, 0, 0, 2, 10, 40, 90, 43],
    "unverified": [1, 0, 0, 0, 2, 5, 20, 60, 80, 13],
    "mean_verified": 0.813, "mean_unverified": 0.798,
    "n_verified": 185, "n_unverified": 181,
}

CHARTS_RECALL_CURVE = {
    "strategy": "screening confidence", "review": "Nelson_2002",
    "n_ranked": 366, "n_included": 80,
    "x": [0, 100, 200, 300, 366],
    "y": [0.0, 0.5, 0.8, 0.95, 1.0],
    "cutoff_95": 300,
    "random_baseline": [0.0, 100 / 366, 200 / 366, 300 / 366, 1.0],
}


CHARTS_CORPUS = {
    "prevalence": [
        {"review": "Smid_2020", "n": 2627, "included": 27, "prevalence": 0.010,
         "without_abstract": 110},
        {"review": "Nelson_2002", "n": 366, "included": 80, "prevalence": 0.219,
         "without_abstract": 8},
    ],
    "years": {"review": None, "years": [1990, 2000, 2010], "counts": [5, 50, 100],
              "included": [1, 10, 20], "span": (1990, 2010)},
    # Every optional column is empty in the real database; the page must say
    # so rather than drawing an empty axis.
    "metadata_coverage": [
        {"column": "venue", "filled": 0, "total": 2993, "share": 0.0, "chartable": False},
        {"column": "country", "filled": 0, "total": 2993, "share": 0.0, "chartable": False},
        {"column": "doi", "filled": 2993, "total": 2993, "share": 1.0, "chartable": True},
    ],
}

CHARTS_EXTRACTION = {
    "run_id": "run-extract-1",
    "status": [
        {"field": "study_design", "n": 114, "verified": 102, "not_stated": 7, "unverified": 5},
        {"field": "sample_size", "n": 114, "verified": 91, "not_stated": 10, "unverified": 13},
        {"field": "country", "n": 114, "verified": 22, "not_stated": 90, "unverified": 2},
        {"field": "key_finding", "n": 114, "verified": 110, "not_stated": 0, "unverified": 4},
    ],
    "coverage": {
        "fields": ["study_design", "sample_size", "country", "key_finding"],
        "rows": [
            {"review": "Nelson_2002", "run_id": "run-extract-1", "prevalence": 0.219,
             "fields": {
                 "study_design": {"n": 114, "verified": 102, "share": 102 / 114},
                 "sample_size": {"n": 114, "verified": 91, "share": 91 / 114},
                 "country": {"n": 114, "verified": 22, "share": 22 / 114},
                 # Never attempted -> must be dropped, not drawn as 0%.
                 "key_finding": {"n": 0, "verified": 0, "share": None},
             }},
        ],
    },
}

CHARTS_GAPS = {
    "runs": {"Nelson_2002": "run-gap-1"},
    "rates": [
        {"review": "Nelson_2002", "run_id": "run-gap-1", "prevalence": 0.219,
         "n_records": 114, "gap_stated": 12, "gap_rate": 12 / 114,
         "valid": 11, "invalid": 1, "unrated": 0, "precision": 11 / 12},
    ],
    "precision_vs_recall": [
        {"review": "Nelson_2002", "prevalence": 0.219, "precision": 11 / 12, "n_rated": 12,
         "recall_estimate": 0.52, "recall_worst_case": 0.21, "recall_sampled": 10,
         "recall_source": "runs/20260924T120813705057Z-gaprecall-d6901cb0a0"},
        # A review with precision but no recall pass: one bar, not two.
        {"review": "Smid_2020", "prevalence": 0.010, "precision": 1.0, "n_rated": 1,
         "recall_estimate": None, "recall_worst_case": None, "recall_sampled": None,
         "recall_source": None},
    ],
    "recall_source": "runs/20260924T120813705057Z-gaprecall-d6901cb0a0",
}

CHARTS_PERFORMANCE = {
    "run_id": "run-screen-1",
    "latency": {"run_id": "run-screen-1", "review": "Nelson_2002", "n": 3,
                "values": [900, 1200, 2400], "mean_ms": 1500.0, "p50_ms": 1200.0,
                "p90_ms": 2400.0, "p99_ms": 2400.0, "total_hours": 0.00125},
    "cache": {"run_id": "run-screen-1", "live_calls": 3, "cached_calls": 363,
              "cache_hit_rate": 363 / 366, "tokens_in": 500000, "tokens_out": 20000,
              "cost_usd": 0.0, "hours_saved": 0.15},
}

CHARTS_SEMANTIC_MAP = {
    "available": True, "review": "Nelson_2002", "n_plotted": 300, "n_total": 366,
    "downsampled": True, "variance_explained": 0.21,
    "points": [
        {"work_id": f"W{i}", "x": i * 0.1, "y": -i * 0.05, "included": i % 10 == 0}
        for i in range(300)
    ],
}


@pytest.fixture(autouse=True)
def _patched(monkeypatch):
    monkeypatch.setattr(api_client, "charts_trust", lambda: CHARTS_TRUST)
    monkeypatch.setattr(api_client, "charts_corpus", lambda review=None: CHARTS_CORPUS)
    monkeypatch.setattr(api_client, "charts_extraction", lambda review, run_id=None: CHARTS_EXTRACTION)
    monkeypatch.setattr(api_client, "charts_gaps", lambda: CHARTS_GAPS)
    monkeypatch.setattr(api_client, "charts_performance", lambda review=None, run_id=None: CHARTS_PERFORMANCE)
    monkeypatch.setattr(api_client, "charts_semantic_map", lambda review, max_points=1500: CHARTS_SEMANTIC_MAP)
    monkeypatch.setattr(api_client, "charts_confidence", lambda review, run_id=None: CHARTS_CONFIDENCE)
    monkeypatch.setattr(api_client, "charts_recall_curve", lambda review, run_id=None: CHARTS_RECALL_CURVE)
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
    monkeypatch.setattr(
        api_client, "discover", lambda query, limit=5, criteria=None, fulltext=False: DISCOVER_SESSION
    )
    monkeypatch.setattr(api_client, "discover_fulltext", lambda papers: FULLTEXT_RESULT)


def _run(path):
    at = AppTest.from_file(str(APP_DIR / path))
    at.run()
    assert not at.exception, [str(e) for e in at.exception]
    return at


def test_home_leads_with_a_search_box_not_the_test_reviews():
    """The front door asks the question a researcher arrives with.

    This is the whole point of the restructure: leading with the six test
    reviews made the tool look like a report about six old medical reviews.
    """
    at = _run("Home.py")
    assert "Beyond Retrieval" in at.title[0].value
    assert at.text_input, "there must be a topic box"
    assert at.text_input[0].label == "What are you researching?"
    assert [b for b in at.button if b.label == "Start a review"]


def test_home_summarises_the_evidence_without_making_it_the_point():
    at = _run("Home.py")
    labels = {m.label: m.value for m in at.metric}
    assert labels["Test reviews"] == "2"  # the fixture has two
    assert labels["Papers screened"] == "2,993"
    assert labels["Correct answers known"] == "107"
    # Difficulty range, not an average -- rule 5 in the UI.
    assert labels["Difficulty range"] == "1.0%–21.9%"


def test_home_states_the_negative_results_on_the_front_page():
    """A landing page that only claims success is a sales page. The three
    recorded shortfalls belong where someone will actually read them."""
    at = _run("Home.py")
    text = " ".join(c.value for c in at.caption)
    assert "99% verification target" in text
    assert "half the research gaps" in text
    assert "out-ranks it" in text


def test_home_warns_about_unscreened_reviews():
    at = _run("Home.py")
    assert any("Smid_2020" in w.value for w in at.warning)


def test_home_explains_a_test_review_for_a_non_researcher():
    at = _run("Home.py")
    text = " ".join(m.value for m in at.markdown)
    assert "crash-test dummies" in text


def test_search_and_screen_ranks_and_screens():
    at = _run("pages/3_Validation_Screening.py")
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
    at = _run("pages/4_Validation_Decisions.py")
    assert not at.exception
    submit = [b for b in at.button if "disposition" in b.label.lower()]
    assert submit
    submit[0].click().run()
    assert not at.exception
    assert any("Overrode" in s.value or "Confirmed" in s.value for s in at.success)


def test_extraction_page_shows_field_coverage():
    at = _run("pages/5_Validation_Extraction.py")
    assert not at.exception
    metric_labels = [m.label for m in at.metric]
    assert set(metric_labels) >= {"study_design", "sample_size", "country", "key_finding"}


def test_gap_discovery_page_shows_precision():
    at = _run("pages/6_Validation_Gaps.py")
    assert not at.exception
    precision = next(m for m in at.metric if m.label == "Precision")
    assert precision.value == "50%"  # 1 valid of 2 rated in the fixture


# ---------------------------------------------------------------------------
# Run a Review -- the product path
# ---------------------------------------------------------------------------


def _run_a_review(topic="hormone therapy", criteria="Include randomised controlled trials."):
    at = AppTest.from_file(str(APP_DIR / "pages/1_Run_a_Review.py"))
    at.run()
    assert not at.exception, [str(e) for e in at.exception]
    at.text_input[0].set_value(topic).run()
    if criteria is not None:
        at.text_area[0].set_value(criteria).run()
    [b for b in at.button if b.label == "Screen these papers"][0].click().run()
    assert not at.exception, [str(e) for e in at.exception]
    return at


def test_run_a_review_screens_extracts_and_shows_gaps():
    at = _run_a_review()
    text = " ".join(m.value for m in at.markdown)
    assert "A paper found on the open web" in text
    assert "remains an open question" in text
    labels = {m.label: m.value for m in at.metric}
    assert labels["Papers found"] == "3"
    assert labels["Kept"] == "1"
    assert labels["Dropped"] == "1"
    assert labels["Needs your eye"] == "1"


def test_run_a_review_does_not_present_an_unverified_include_as_a_keep():
    """The single most important rendering rule on this page.

    W3's decision is `include` with confidence 0.84, but its quote was not
    found in the abstract. Showing that as "Keep" would be exactly the
    failure the span verifier exists to prevent, surfaced in the UI instead
    of in the data.
    """
    at = _run_a_review()
    headings = [m.value for m in at.markdown if "A paper whose quote was invented" in m.value]
    assert headings, "the referred paper should still be listed"
    assert "Needs your eye" in headings[0]
    assert "Keep" not in headings[0]


def test_run_a_review_explains_referrals_rather_than_hiding_them():
    at = _run_a_review()
    assert any("came back as a referral" in i.value for i in at.info)


def test_run_a_review_withholds_extraction_for_papers_it_dropped():
    """Extraction only ever reads verified includes -- the same boundary the
    ingested pipeline keeps. The page must say why a paper has no fields
    rather than rendering four empty columns."""
    at = _run_a_review()
    captions = " ".join(c.value for c in at.caption)
    assert "doesn't meet your criteria" in captions
    assert "referred to you first" in captions


def test_run_a_review_without_criteria_does_not_invent_decisions(monkeypatch):
    """No criteria, no include/exclude. The system does not guess."""
    no_screening = dict(DISCOVER_SESSION)
    no_screening["criteria"] = None
    no_screening["n_screened"] = 0
    no_screening["n_included"] = no_screening["n_excluded"] = no_screening["n_referred"] = 0
    no_screening["papers"] = [
        {**DISCOVER_SESSION["papers"][0], "decision": None},
    ]
    monkeypatch.setattr(
        api_client, "discover", lambda query, limit=5, criteria=None, fulltext=False: no_screening
    )
    at = _run_a_review(criteria="")
    assert any("No criteria given" in i.value for i in at.info)
    labels = {m.label for m in at.metric}
    assert "Kept" not in labels, "nothing should be reported as kept"


def test_run_a_review_requires_a_topic():
    at = AppTest.from_file(str(APP_DIR / "pages/1_Run_a_Review.py"))
    at.run()
    [b for b in at.button if b.label == "Screen these papers"][0].click().run()
    assert not at.exception
    assert any("Type a topic" in w.value for w in at.warning)


def test_run_a_review_points_at_the_validation_pages_for_accuracy():
    """There is no ground truth for an ad-hoc topic, so this page must not
    imply a measured accuracy -- it should say where the real numbers are."""
    at = _run_a_review()
    captions = " ".join(c.value for c in at.caption)
    assert "nothing on this page is scored" in captions.lower()
    assert "12,598" in captions


def test_run_a_review_surfaces_a_cache_mismatch_as_a_guard_not_a_crash(monkeypatch):
    import httpx

    def boom(query, limit=5, criteria=None, fulltext=False):
        request = httpx.Request("POST", "http://test/discover")
        response = httpx.Response(409, text="CacheMismatch", request=request)
        raise httpx.HTTPStatusError("conflict", request=request, response=response)

    monkeypatch.setattr(api_client, "discover", boom)
    at = AppTest.from_file(str(APP_DIR / "pages/1_Run_a_Review.py"))
    at.run()
    at.text_input[0].set_value("x").run()
    at.text_area[0].set_value("y").run()
    [b for b in at.button if b.label == "Screen these papers"][0].click().run()
    assert not at.exception
    assert any("cache guard doing its job" in e.value for e in at.error)


def test_validation_pages_say_they_are_validation():
    """Every six-review page must label itself, or the restructure only
    moved the confusion somewhere less visible."""
    for page in [
        "pages/2_Validation_Trust.py",
        "pages/3_Validation_Screening.py",
        "pages/4_Validation_Decisions.py",
        "pages/5_Validation_Extraction.py",
        "pages/6_Validation_Gaps.py",
    ]:
        at = _run(page)
        banners = [i.value for i in at.info if "validation evidence, not the tool" in i.value]
        assert banners, f"{page} does not identify itself as validation"
        assert "Run a review" in banners[0], f"{page} does not point at the tool"


def test_trust_dashboard_scales_percentages_before_display():
    at = _run("pages/2_Validation_Trust.py")
    assert not at.exception
    rows = {r["Review"]: r for r in at.dataframe[0].value.to_dict("records")}
    # verification_rate 0.505 must be scaled to 50.5, not left as 0.505 (the bug this test exists to catch)
    assert rows["Nelson_2002"]["Verified"] == pytest.approx(50.5)
    assert rows["Nelson_2002"]["Prevalence"] == pytest.approx(21.9)
    assert pytest.approx(rows["Smid_2020"]["Prevalence"]) == 1.0
    assert rows["Smid_2020"]["Verified"] is None or rows["Smid_2020"]["Verified"] != rows["Smid_2020"]["Verified"]  # NaN or None: not screened


# ---------------------------------------------------------------------------
# Charts
#
# AppTest records altair charts, so these assert the charts are actually
# built and rendered -- not merely that the page didn't raise. A chart that
# silently fails to render looks identical to a page with no charts.
# ---------------------------------------------------------------------------


def test_trust_dashboard_renders_its_charts():
    at = _run("pages/2_Validation_Trust.py")
    assert len(at.get("arrow_vega_lite_chart")) >= 4, "verification, failures, confidence, scatter"
    assert not any("Charts unavailable" in w.value for w in at.warning)


def test_trust_dashboard_shows_the_calibration_gap_as_a_signed_number():
    """The confidence finding is the difference between two means, and it is
    small. If this metric ever renders unsigned or unscaled, the chart's
    whole point is lost."""
    at = _run("pages/2_Validation_Trust.py")
    difference = next(m for m in at.metric if m.label == "Difference")
    assert difference.value == "+0.015"


def test_trust_dashboard_survives_a_failing_chart_route():
    """The RQ1 table is the page's reason to exist; a broken chart route must
    degrade to a warning, not take the table down with it."""

    def boom():
        raise RuntimeError("chart route down")

    at = AppTest.from_file(str(APP_DIR / "pages/2_Validation_Trust.py"))
    at.run()
    import api_client as client

    original = client.charts_trust
    try:
        client.charts_trust = boom
        at = AppTest.from_file(str(APP_DIR / "pages/2_Validation_Trust.py"))
        at.run()
        assert not at.exception
        assert any("Charts unavailable" in w.value for w in at.warning)
        assert at.dataframe, "the RQ1 table still renders"
    finally:
        client.charts_trust = original


def test_search_and_screen_shows_the_recall_curve_before_any_query():
    """The curve is context for the ranking, so it renders on page load --
    a reviewer shouldn't have to run a query to see what the saving is."""
    at = _run("pages/3_Validation_Screening.py")
    assert at.get("arrow_vega_lite_chart"), "recall curve should render immediately"
    labels = {m.label: m.value for m in at.metric}
    assert labels["Read to reach 95%"] == "300"
    assert labels["Of the review"] == "82%"  # 300 of 366


def test_search_and_screen_handles_a_review_with_no_screening_run(monkeypatch):
    def boom(review, run_id=None):
        raise RuntimeError("no run")

    monkeypatch.setattr(api_client, "charts_recall_curve", boom)
    at = _run("pages/3_Validation_Screening.py")
    assert any("no curve to draw" in c.value for c in at.caption)


def test_search_and_screen_says_so_when_a_review_has_no_embeddings(monkeypatch):
    monkeypatch.setattr(
        api_client,
        "charts_semantic_map",
        lambda review, max_points=1500: {
            "available": False, "review": review,
            "reason": "no cached embeddings for Radjenovic_2013; run a dense/hybrid config first",
        },
    )
    at = _run("pages/3_Validation_Screening.py")
    assert any("No semantic map" in c.value for c in at.caption)


def test_validation_trust_charts_the_corpus_and_names_what_it_cannot_chart():
    """The corpus charts live on the validation page, not Home.

    How hard each review is *is* validation evidence -- a verification rate
    is unreadable without it -- so it belongs beside the results it
    qualifies rather than on the product's front door.
    """
    at = _run("pages/2_Validation_Trust.py")
    assert len(at.get("arrow_vega_lite_chart")) >= 6, "corpus pair plus the four trust charts"
    # venue and country are empty in the real database; saying so is the point.
    assert any("Not chartable" in c.value and "venue" in c.value for c in at.caption)


def test_extraction_page_renders_both_charts():
    at = _run("pages/5_Validation_Extraction.py")
    assert len(at.get("arrow_vega_lite_chart")) >= 2, "status bars and coverage heatmap"


def test_extraction_coverage_drops_never_attempted_fields():
    """A field extracted zero times must not be shaded as 0% verified --
    "never attempted" and "attempted, never verified" are different findings.
    """
    import plots

    chart = plots.extraction_coverage_heatmap(CHARTS_EXTRACTION["coverage"])
    fields = {row["field"] for row in chart.data.to_dict("records")}
    assert "key_finding" not in fields
    assert "country" in fields


def test_gap_page_renders_rate_and_precision_recall_charts():
    at = _run("pages/6_Validation_Gaps.py")
    assert len(at.get("arrow_vega_lite_chart")) >= 2
    assert any("either one alone misrepresents" in c.value for c in at.caption)


def test_gap_precision_recall_omits_the_bar_it_cannot_measure():
    """Smid_2020 has rated precision but no blind recall sample. It gets one
    bar; it must not inherit another review's recall figure."""
    import plots

    chart = plots.gap_precision_recall_bars(CHARTS_GAPS["precision_vs_recall"])
    records = chart.data.to_dict("records")
    smid = [r for r in records if r["review"] == "Smid_2020"]
    assert len(smid) == 1
    assert smid[0]["measure"] == "Precision (rated)"


def test_trust_dashboard_renders_performance_and_override_sections():
    at = _run("pages/2_Validation_Trust.py")
    labels = {m.label for m in at.metric}
    assert {"Dispositions recorded", "Override rate"} <= labels
    assert any("Cost and speed" in s.value for s in at.subheader)


def test_trust_dashboard_explains_an_all_cached_run_instead_of_an_empty_chart(monkeypatch):
    monkeypatch.setattr(
        api_client,
        "charts_performance",
        lambda review=None, run_id=None: {
            "run_id": "r", "latency": {"n": 0},
            "cache": {"live_calls": 0, "cached_calls": 366, "cache_hit_rate": 1.0,
                      "tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0, "hours_saved": None},
        },
    )
    at = _run("pages/2_Validation_Trust.py")
    assert any("served from the cache" in i.value for i in at.info)


# ---------------------------------------------------------------------------
# Full text on the review page
#
# The rule these guard: model-extracted fields carry a verification status
# and are withheld when their quote fails; tables and equations came out of
# the publisher's file with no model involved and carry no status at all.
# Showing them the same way would misrepresent both.
# ---------------------------------------------------------------------------

_FT_VERIFIED = {
    "status": "verified",
    "value": "HR 0.72 (95% CI 0.61-0.85)",
    "quote": "The hazard ratio was 0.72 (95% CI 0.61-0.85, p<0.001).",
    "note": None,
}

FULLTEXT_RESULT = {
    "n_requested": 1,
    "n_with_full_text": 1,
    "papers": [
        {
            "work_id": "https://openalex.org/W1",
            "title": "A paper found on the open web",
            "primary_outcome": _FT_VERIFIED,
            "effect_size": _FT_VERIFIED,
            "statistical_methods": {"status": "not_stated"},
            "sample_characteristics": {
                "status": "unverified",
                "quote": "a sentence not in the paper",
                "note": "not_found",
            },
            "limitations": _FT_VERIFIED,
            "tables": [
                {"label": "Table 1", "caption": "Baseline", "rows": [["Group", "n"], ["A", "120"]]}
            ],
            "equations": ["HR = exp(b1 x1)"],
            "figures": [
                {
                    "label": "Figure 2",
                    "caption": "Correlation heat map",
                    # What the authors say the chart shows -- the honest
                    # substitute for reading the image.
                    "mentions": ["As shown in Figure 2, risk declined across all cohorts."],
                }
            ],
            "note": "full text from PMC9: 3 of 5 fields verified, 1 tables, 1 equations, 1 figures",
            "found": True,
        }
    ],
}


def _run_with_fulltext(monkeypatch, result=None):
    """Screen, pick a paper, then read it in full -- the two real stages."""
    monkeypatch.setattr(
        api_client, "discover_fulltext", lambda papers: result or FULLTEXT_RESULT
    )
    at = AppTest.from_file(str(APP_DIR / "pages/1_Run_a_Review.py"))
    at.run()
    at.text_input[0].set_value("hormone therapy").run()
    at.text_area[0].set_value("Include randomised trials.").run()
    [b for b in at.button if b.label == "Screen these papers"][0].click().run()
    assert not at.exception, [str(e) for e in at.exception]

    picker = at.multiselect[0]
    picker.select(picker.options[0]).run()
    [b for b in at.button if b.label == "Read these in full"][0].click().run()
    assert not at.exception, [str(e) for e in at.exception]
    return at


def test_the_first_pass_screens_abstracts_only():
    """Stage one does not fetch full text. That is PRISMA's own shape, and
    it is also why screening stays fast: full text costs a lookup, a
    download and a long model call per paper."""
    at = AppTest.from_file(str(APP_DIR / "pages/1_Run_a_Review.py"))
    at.run()
    assert [b for b in at.button if b.label == "Screen these papers"]
    assert not [b for b in at.button if b.label == "Read these in full"], (
        "stage two must not be reachable before anything has been screened"
    )
    captions = " ".join(c.value for c in at.caption)
    assert "titles and abstracts only" in captions


def test_stage_two_only_offers_papers_that_were_kept(monkeypatch):
    """Reading the full text of a paper the criteria rejected would be
    doing work on a paper the reviewer already excluded."""
    at = AppTest.from_file(str(APP_DIR / "pages/1_Run_a_Review.py"))
    at.run()
    at.text_input[0].set_value("hormone therapy").run()
    at.text_area[0].set_value("Include randomised trials.").run()
    [b for b in at.button if b.label == "Screen these papers"][0].click().run()

    options = at.multiselect[0].options
    assert any("found on the open web" in o for o in options), "the kept paper is offered"
    assert not any("animal study" in o.lower() for o in options), "the dropped one is not"
    assert not any("quote was invented" in o.lower() for o in options), "nor is the referral"


def test_verified_full_text_fields_are_shown_with_their_quote(monkeypatch):
    at = _run_with_fulltext(monkeypatch)
    text = " ".join(m.value for m in at.markdown)
    assert "Main result" in text
    assert "HR 0.72" in text
    captions = " ".join(c.value for c in at.caption)
    assert "The hazard ratio was 0.72" in captions


def test_an_unverified_full_text_field_is_withheld_not_shown(monkeypatch):
    """Same rule as every other claim in this project: no verified quote,
    no value."""
    at = _run_with_fulltext(monkeypatch)
    text = " ".join(m.value for m in at.markdown)
    assert "**Sample:** withheld" in text
    captions = " ".join(c.value for c in at.caption)
    assert "wasn't found in the paper" in captions


def test_tables_are_presented_as_exact_not_as_a_model_claim(monkeypatch):
    at = _run_with_fulltext(monkeypatch)
    captions = " ".join(c.value for c in at.caption)
    assert "No model was involved" in captions
    assert "could have been invented" in captions


def test_figures_say_the_image_was_not_read(monkeypatch):
    """A heat map's meaning is in the picture. Showing its caption is
    honest; implying the chart was read would not be."""
    at = _run_with_fulltext(monkeypatch)
    captions = " ".join(c.value for c in at.caption)
    assert "not fetched or interpreted" in captions
    assert "would need image analysis" in captions


def test_a_paper_with_no_full_text_says_why(monkeypatch):
    """Paywalled and not-indexed are facts about the paper, not failures,
    and the page has to distinguish them from a bug."""
    result = {
        "n_requested": 1,
        "n_with_full_text": 0,
        "papers": [
            {
                "work_id": "https://openalex.org/W1",
                "title": "A paper found on the open web",
                "tables": [],
                "equations": [],
                "figures": [],
                "note": "in Europe PMC but not open access -- full text is paywalled",
                "found": False,
            }
        ],
    }
    at = _run_with_fulltext(monkeypatch, result)
    captions = " ".join(c.value for c in at.caption)
    warnings = " ".join(w.value for w in at.warning)
    assert "paywalled" in captions
    assert "coverage limit, not a failure" in warnings


def test_what_the_authors_say_a_figure_shows_is_quoted(monkeypatch):
    """The honest substitute for reading a chart: the image is never
    fetched, but the sentence where the authors describe it is real text
    and can be checked."""
    at = _run_with_fulltext(monkeypatch)
    captions = " ".join(c.value for c in at.caption)
    assert "As shown in Figure 2, risk declined across all cohorts." in captions
    assert "not fetched or interpreted" in captions


# ---------------------------------------------------------------------------
# Relevance ranking
#
# "Kept" as an undifferentiated pile is survivable at ten papers and useless
# at a hundred. Ordering the kept group by the model's own confidence turns
# it into a queue, so a reviewer who runs out of time has stopped at the
# right end of the list.
# ---------------------------------------------------------------------------

RANKED_SESSION = {
    **DISCOVER_SESSION,
    "n_included": 3,
    "n_excluded": 0,
    "n_referred": 0,
    "papers": [
        {
            "work_id": f"https://openalex.org/W{i}",
            "title": title,
            "year": 2021,
            "source_url": None,
            "study_design": _VERIFIED,
            "sample_size": _VERIFIED,
            "country": _VERIFIED,
            "key_finding": _VERIFIED,
            "gap": {"status": "not_stated"},
            "decision": {
                "status": "include",
                "confidence": confidence,
                "quote": "a quote that verified",
                "span_verified": True,
                "verify_note": "exact_after_normalisation",
                "from_cache": False,
            },
        }
        for i, (title, confidence) in enumerate(
            [("Weakest match", 0.55), ("Strongest match", 0.97), ("Middling match", 0.80)]
        )
    ],
}


def _screen_ranked(monkeypatch):
    monkeypatch.setattr(
        api_client,
        "discover",
        lambda query, limit=5, criteria=None, fulltext=False: RANKED_SESSION,
    )
    at = AppTest.from_file(str(APP_DIR / "pages/1_Run_a_Review.py"))
    at.run()
    at.text_input[0].set_value("topic").run()
    at.text_area[0].set_value("Include trials.").run()
    [b for b in at.button if b.label == "Screen these papers"][0].click().run()
    assert not at.exception, [str(e) for e in at.exception]
    return at


def test_kept_papers_are_listed_strongest_first(monkeypatch):
    at = _screen_ranked(monkeypatch)
    headings = [m.value for m in at.markdown if m.value.startswith("#### ")]
    order = [h for h in headings if "match" in h]
    assert "Strongest match" in order[0]
    assert "Middling match" in order[1]
    assert "Weakest match" in order[2]


def test_each_kept_paper_shows_its_rank(monkeypatch):
    at = _screen_ranked(monkeypatch)
    headings = [m.value for m in at.markdown if m.value.startswith("#### ")]
    assert any(h.startswith("#### #1 · ") and "Strongest" in h for h in headings)
    assert any(h.startswith("#### #3 · ") and "Weakest" in h for h in headings)


def test_the_selection_list_uses_the_same_order_as_the_cards(monkeypatch):
    """"The top three" has to mean the same thing in both places."""
    at = _screen_ranked(monkeypatch)
    options = at.multiselect[0].options
    assert options[0].startswith("#1 ·") and "Strongest" in options[0]
    assert options[-1].startswith("#3 ·") and "Weakest" in options[-1]


def test_the_ranking_is_described_as_a_prediction_not_a_measurement(monkeypatch):
    """The system has read an abstract and nothing more. Presenting that
    ordering as established relevance would overclaim."""
    at = _screen_ranked(monkeypatch)
    captions = " ".join(c.value for c in at.caption)
    assert "strongest first" in captions
    assert "a prediction from an abstract, not a measurement" in captions
