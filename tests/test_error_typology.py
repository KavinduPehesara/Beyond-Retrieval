"""Tests for the error typology.

The category that matters most is ``echoed_criteria``, and the test that
matters most is the one asserting it is checked *before* the generic
content categories. Without that precedence the dominant failure mode is
reported as fabrication, which is both wrong and much more damning than the
truth.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from slr.db import connect
from slr.eval import error_typology as et

DB_PATH = Path("data/slr.db")
RUNS_DIR = Path("runs")

ABSTRACT = (
    "This randomised controlled trial enrolled 240 adults in New Zealand. "
    "The intervention reduced hospital admissions over twelve months. "
    "Long-term outcomes were not assessed."
)
TITLE = "A randomised trial of an intervention"
CRITERIA = (
    "Include randomised controlled trials in adults. "
    "Exclude studies discussing software metrics in a context other than fault prediction."
)


# --------------------------------------------------------------------------
# Classification
# --------------------------------------------------------------------------


def test_a_span_lifted_from_the_criteria_is_not_fabrication():
    """The finding this module exists for. Classified without the criteria,
    this span looks invented; it was quoted from the prompt."""
    span = "Exclude studies discussing software metrics in a context other than fault prediction."
    assert et.classify_failure(span, TITLE, ABSTRACT, CRITERIA).category == et.ECHOED_CRITERIA
    # Same span, no criteria supplied -> misreported.
    assert et.classify_failure(span, TITLE, ABSTRACT, None).category == et.FABRICATED


def test_criteria_are_checked_before_the_content_categories():
    """A criteria echo that is also longer than the abstract is still an
    echo. Reporting it as "longer than source" would hide the real cause."""
    long_criteria = "x " * 200 + "a very distinctive clause about eligibility"
    span = "a very distinctive clause about eligibility"
    result = et.classify_failure(span, TITLE, "short abstract.", long_criteria)
    assert result.category == et.ECHOED_CRITERIA


def test_a_genuinely_invented_span_is_still_called_fabricated():
    span = "The authors conclude that quantum entanglement explains the result."
    assert et.classify_failure(span, TITLE, ABSTRACT, CRITERIA).category == et.FABRICATED


def test_a_reworded_real_sentence_is_a_paraphrase_not_an_invention():
    # Almost all of this appears verbatim; one word differs.
    span = "This randomised controlled trial enrolled 240 adults in New Zealandia."
    assert et.classify_failure(span, TITLE, ABSTRACT, CRITERIA).category == et.NEAR_PARAPHRASE


def test_two_real_sentences_joined_are_stitched():
    span = "This randomised controlled trial enrolled 240 adults Long-term outcomes were not assessed."
    assert et.classify_failure(span, TITLE, ABSTRACT, CRITERIA).category == et.STITCHED


def test_a_record_with_no_abstract_is_not_blamed_on_the_model():
    assert et.classify_failure("anything at all here", None, None, CRITERIA).category == et.NO_SOURCE


def test_a_span_below_the_minimum_length_is_reported_as_such():
    result = et.classify_failure("too short", TITLE, ABSTRACT, CRITERIA)
    assert result.category == et.TOO_SHORT


def test_a_span_longer_than_the_source_is_reported_as_such():
    result = et.classify_failure("word " * 200, TITLE, ABSTRACT, CRITERIA)
    assert result.category == et.LONGER_THAN_SOURCE


def test_a_quote_from_the_title_is_distinguished_from_the_abstract():
    span = "A randomised trial of an intervention"
    result = et.classify_failure(span, span, ABSTRACT, CRITERIA)
    assert result.category == et.FROM_TITLE


def test_an_empty_span_does_not_crash():
    assert et.classify_failure("", TITLE, ABSTRACT, CRITERIA).category == et.FABRICATED
    assert et.classify_failure(None, TITLE, ABSTRACT, CRITERIA).category == et.FABRICATED


def test_classification_agrees_with_the_verifier():
    """Anything this module says is "in the source" must be something the
    verifier would have accepted. If these two ever disagree, a category
    here is describing a decision that didn't happen."""
    from slr.services.verify import verify_span, source_text

    span = "The intervention reduced hospital admissions over twelve months."
    assert verify_span(span, source_text(TITLE, ABSTRACT)).verified is True
    # A verified span would never reach the classifier, but the normalisation
    # the classifier uses must find it fully present.
    result = et.classify_failure(span, TITLE, ABSTRACT, CRITERIA)
    assert result.best_match_ratio == pytest.approx(1.0)


# --------------------------------------------------------------------------
# Sampling
# --------------------------------------------------------------------------


def _items(review, n, category="echoed_criteria"):
    return [
        {
            "review": review,
            "work_id": f"{review}-{i}",
            "span": "s",
            "decision": "unverified",
            "category": category,
            "truly_included": False,
        }
        for i in range(n)
    ]


def test_the_sample_is_stratified_so_one_review_cannot_dominate():
    """Radjenovic_2013 contributes 3,821 of 5,909 failures. An unstratified
    draw of 50 would be almost entirely that review and would say nothing
    about the other five."""
    classified = _items("Big", 3821) + _items("Small", 51) + _items("Mid", 440)
    sheet = et.sample_for_rating(classified, n=50, seed=42)

    assert len(sheet) == 50
    reviews = {row["review"] for row in sheet}
    assert reviews == {"Big", "Small", "Mid"}, "every review must appear"
    big = sum(1 for row in sheet if row["review"] == "Big")
    assert big < 50, "the largest review must not take the whole sheet"


def test_the_sample_is_reproducible_from_its_seed():
    classified = _items("A", 100) + _items("B", 100)
    first = et.sample_for_rating(classified, n=20, seed=42)
    second = et.sample_for_rating(classified, n=20, seed=42)
    assert [r["work_id"] for r in first] == [r["work_id"] for r in second]

    different = et.sample_for_rating(classified, n=20, seed=43)
    assert [r["work_id"] for r in first] != [r["work_id"] for r in different]


def test_the_sheet_hides_the_automatic_label_behind_an_underscore():
    """A rater who can see the machine's answer is not rating blind."""
    sheet = et.sample_for_rating(_items("A", 10), n=5, seed=42)
    for row in sheet:
        assert row["rating"] is None
        assert "_auto_category" in row, "kept for scoring, prefixed so it can be stripped"
        visible = {k for k in row if not k.startswith("_")}
        assert "category" not in visible


def test_sampling_an_empty_set_returns_nothing():
    assert et.sample_for_rating([], n=50) == []


def test_asking_for_more_than_exists_returns_what_exists():
    sheet = et.sample_for_rating(_items("A", 3), n=50, seed=42)
    assert len(sheet) == 3


# --------------------------------------------------------------------------
# Distribution
# --------------------------------------------------------------------------


def test_distribution_counts_per_review_and_overall():
    classified = _items("A", 3, "echoed_criteria") + _items("B", 1, "fabricated")
    dist = et.distribution(classified)

    assert dist["n_failures"] == 4
    assert dist["overall"]["echoed_criteria"] == 3
    rows = {r["review"]: r for r in dist["per_review"]}
    assert rows["A"]["shares"]["echoed_criteria"] == pytest.approx(1.0)


def test_the_table_reports_counts_per_review_never_only_pooled():
    classified = _items("A", 3) + _items("B", 1, "fabricated")
    table = et.format_distribution(et.distribution(classified))
    assert "| A |" in table and "| B |" in table
    assert "All six" in table  # the pooled row is present but is not the only row


# --------------------------------------------------------------------------
# Against the real database
# --------------------------------------------------------------------------

real_db = pytest.mark.skipif(not DB_PATH.exists(), reason="no local data/slr.db")


@pytest.fixture(scope="module")
def real():
    if not DB_PATH.exists():
        pytest.skip("no local data/slr.db")
    c = connect(DB_PATH)
    yield c
    c.close()


@real_db
def test_the_dominant_failure_is_echoed_criteria_not_fabrication(real):
    """The recorded finding, as a regression test.

    If this ever flips to fabrication the project's central claim about the
    model changes, and the report needs rewriting. It is not a flaky test.
    """
    if not RUNS_DIR.exists():
        pytest.skip("no local runs/")
    from slr.api.runs_index import list_reviews_with_screen_runs

    runs = list_reviews_with_screen_runs(RUNS_DIR)
    if not runs:
        pytest.skip("no screening runs")

    classified = []
    for review, run_id in runs.items():
        classified.extend(et.classify_run(real, run_id, review))

    dist = et.distribution(classified)
    echoed = dist["overall"].get(et.ECHOED_CRITERIA, 0)
    fabricated = dist["overall"].get(et.FABRICATED, 0)

    assert echoed / dist["n_failures"] > 0.90, (
        f"echoed_criteria is {echoed / dist['n_failures']:.1%} of failures; "
        "CLAUDE.md records 97.8%"
    )
    assert fabricated / dist["n_failures"] < 0.05, (
        f"genuine fabrication is {fabricated / dist['n_failures']:.1%}; "
        "CLAUDE.md records 0.2%"
    )


@real_db
def test_every_failure_gets_exactly_one_category(real):
    if not RUNS_DIR.exists():
        pytest.skip("no local runs/")
    from slr.api.runs_index import list_reviews_with_screen_runs

    runs = list_reviews_with_screen_runs(RUNS_DIR)
    if not runs:
        pytest.skip("no screening runs")

    for review, run_id in runs.items():
        classified = et.classify_run(real, run_id, review)
        n_failures = real.execute(
            "SELECT COUNT(*) AS n FROM screening_decision "
            "WHERE run_id = ? AND review = ? AND span_verified = 0",
            (run_id, review),
        ).fetchone()["n"]
        assert len(classified) == n_failures, review
        assert all(item["category"] in et.CATEGORIES for item in classified), review
