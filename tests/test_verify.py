"""Tests for the span verifier.

This function decides whether a screening decision is trustworthy. If it is
wrong in the permissive direction, the headline claim of the whole project is
false. It gets tested harder than anything else here.
"""

from __future__ import annotations

import pytest

from slr.services.verify import (
    MIN_SPAN_CHARS,
    normalise,
    source_text,
    verify_span,
)

ABSTRACT = (
    "Software fault prediction models are built using metrics collected from "
    "source code. We evaluated eleven object-oriented metrics against defect "
    "data from five open-source projects. The results show that coupling "
    "measures outperform size measures for predicting post-release defects."
)


# --------------------------------------------------------------------------
# Accept: genuine quotations
# --------------------------------------------------------------------------


def test_exact_quotation_verifies():
    span = "coupling measures outperform size measures for predicting post-release defects"
    assert verify_span(span, ABSTRACT).verified


def test_full_sentence_verifies():
    span = "We evaluated eleven object-oriented metrics against defect data from five open-source projects."
    assert verify_span(span, ABSTRACT).verified


def test_case_difference_verifies():
    span = "COUPLING MEASURES OUTPERFORM SIZE MEASURES"
    assert verify_span(span, ABSTRACT).verified


def test_collapsed_whitespace_verifies():
    """Line wrapping in the source is not a difference in what was said."""
    span = "We  evaluated\neleven   object-oriented\tmetrics against defect data"
    assert verify_span(span, ABSTRACT).verified


def test_curly_quotes_verify():
    source = 'The authors state that "the effect was not significant" in cohort two.'
    span = "the authors state that “the effect was not significant”"
    assert verify_span(span, source).verified


def test_en_dash_verifies():
    """Models routinely return typographic dashes where the source has hyphens."""
    span = "eleven object–oriented metrics against defect data"
    assert verify_span(span, ABSTRACT).verified


def test_surrounding_punctuation_is_stripped():
    span = '"coupling measures outperform size measures for predicting"'
    result = verify_span(span, ABSTRACT)
    assert result.verified
    assert result.note == "exact_after_punctuation_strip"


def test_title_is_part_of_the_source():
    title = "An Evaluation of Object-Oriented Metrics for Fault Prediction"
    src = source_text(title, ABSTRACT)
    assert verify_span("An Evaluation of Object-Oriented Metrics", src).verified


# --------------------------------------------------------------------------
# Reject: the failure modes that matter
# --------------------------------------------------------------------------


def test_fabricated_span_is_rejected():
    """The case the whole mechanism exists for."""
    span = "The authors conclude that machine learning solves fault prediction entirely."
    result = verify_span(span, ABSTRACT)
    assert not result.verified
    assert result.note == "not_found"


def test_paraphrase_is_rejected():
    """A reworded quote must fail. Fuzzy matching here would defeat the point."""
    span = "coupling metrics performed better than size metrics for defects after release"
    assert not verify_span(span, ABSTRACT).verified


def test_single_word_changed_is_rejected():
    span = "coupling measures outperform complexity measures for predicting post-release defects"
    assert not verify_span(span, ABSTRACT).verified


def test_partial_match_is_diagnosed_but_rejected():
    """A truncated-then-invented quote is reported distinctly, not accepted."""
    span = "We evaluated eleven object-oriented metrics using a novel Bayesian framework"
    result = verify_span(span, ABSTRACT)
    assert not result.verified
    assert result.note == "partial_match_only"


def test_empty_span_is_rejected():
    assert verify_span("", ABSTRACT).note == "empty_span"
    assert verify_span(None, ABSTRACT).note == "empty_span"
    assert verify_span("   ", ABSTRACT).note == "empty_span"


def test_missing_source_is_rejected_not_crashed():
    """No abstract is not the model's fault, but it is still unverifiable."""
    result = verify_span("some span of reasonable length here", None)
    assert not result.verified
    assert result.note == "no_source_text"
    assert not verify_span("some span of reasonable length here", "").verified


def test_short_span_is_rejected():
    """'the' appears in every abstract ever written."""
    result = verify_span("the results", ABSTRACT)
    assert not result.verified
    assert "span_too_short" in result.note


@pytest.mark.parametrize(
    "span",
    [
        '"(((((((((((((((((( results',  # 7 real characters behind padding
        '"............... cohorts ....',
    ],
)
def test_punctuation_padding_cannot_bypass_minimum_length(span):
    source = "The results were mixed across all five cohorts studied."
    result = verify_span(span, source)
    assert not result.verified


def test_span_longer_than_source_is_rejected():
    result = verify_span(ABSTRACT + " And then some more invented text.", ABSTRACT)
    assert not result.verified
    assert result.note == "span_longer_than_source"


@pytest.mark.parametrize("length", [MIN_SPAN_CHARS - 1, MIN_SPAN_CHARS + 1])
def test_minimum_length_boundary(length):
    source = "x" * 200
    result = verify_span("x" * length, source)
    assert result.verified == (length >= MIN_SPAN_CHARS)


# --------------------------------------------------------------------------
# Normalisation
# --------------------------------------------------------------------------


def test_normalise_is_idempotent():
    text = "  The  “Results” — as  shown… "
    assert normalise(normalise(text)) == normalise(text)


def test_normalise_folds_typography():
    assert normalise("“quoted”") == normalise('"quoted"')
    assert normalise("en–dash") == normalise("en-dash")
    assert normalise("non breaking") == normalise("non breaking")


def test_result_is_falsy_when_unverified():
    assert not verify_span("invented text of sufficient length", ABSTRACT)
    assert verify_span("coupling measures outperform size measures", ABSTRACT)
