"""Tests for the agreement coefficients.

AC2 has no scikit-learn implementation, so before any number it produces is
trusted it must reproduce a published worked example. The reference values
below are those printed in the irrCAC documentation for the dataset
``cac.raw4raters`` (Gwet, K. L., 2014, Handbook of Inter-Rater Reliability,
4th ed.): 12 units, 4 raters, categories 1-5, with missing ratings.
"""

from __future__ import annotations

import pytest

from slr.eval.agreement import gwet_ac1, gwet_ac2, pabak, weight_matrix

NA = None

CAC_RAW4RATERS = [
    [1, 1, NA, 1],
    [2, 2, 3, 2],
    [3, 3, 3, 3],
    [3, 3, 3, 3],
    [2, 2, 2, 2],
    [1, 2, 3, 4],
    [4, 4, 4, 4],
    [1, 1, 2, 1],
    [2, 2, 2, 2],
    [NA, 5, 5, 5],
    [NA, NA, 1, 1],
    [NA, NA, 3, NA],
]


# --------------------------------------------------------------------------
# Published worked example
# --------------------------------------------------------------------------


def test_ac1_matches_published_example():
    result = gwet_ac1(CAC_RAW4RATERS)
    assert result.coefficient == pytest.approx(0.77544, abs=5e-6)
    assert result.pa == pytest.approx(0.81818, abs=5e-6)
    assert result.pe == pytest.approx(0.19032, abs=5e-6)
    assert result.n_units == 12
    assert result.n_units_paired == 11  # unit 12 has a single rating


def test_quadratic_ac2_matches_published_example():
    result = gwet_ac2(CAC_RAW4RATERS, weights="quadratic")
    assert result.coefficient == pytest.approx(0.914, abs=5e-4)
    assert result.pa == pytest.approx(0.97538, abs=5e-6)
    assert result.pe == pytest.approx(0.7137, abs=5e-5)


# --------------------------------------------------------------------------
# Properties
# --------------------------------------------------------------------------


def test_identity_weighted_ac2_is_ac1():
    assert gwet_ac2(CAC_RAW4RATERS).coefficient == gwet_ac1(CAC_RAW4RATERS).coefficient


def test_perfect_agreement_is_one():
    ratings = [["include", "include", "include"], ["exclude", "exclude", "exclude"]] * 5
    assert gwet_ac1(ratings, categories=("include", "exclude")).coefficient == pytest.approx(1.0)


def test_unanimous_single_category_needs_explicit_categories():
    """Five runs that all exclude everything agree perfectly — not an error."""
    ratings = [["exclude"] * 5] * 20
    with pytest.raises(ValueError):
        gwet_ac1(ratings)
    result = gwet_ac1(ratings, categories=("include", "exclude"))
    assert result.coefficient == pytest.approx(1.0)
    assert result.pe == pytest.approx(0.0)


def test_ac1_resists_the_kappa_paradox():
    """High agreement under heavy imbalance should read as high agreement.

    98 units both raters exclude, 2 units they disagree on. Raw agreement is
    98%; Cohen's kappa here is about -0.01. AC1 stays near raw agreement.
    """
    ratings = [["exclude", "exclude"]] * 98 + [["include", "exclude"], ["exclude", "include"]]
    result = gwet_ac1(ratings, categories=("include", "exclude"))
    assert result.pa == pytest.approx(0.98)
    assert result.coefficient > 0.97


def test_two_rater_binary_by_hand():
    """a=40 both include, d=45 both exclude, 10 and 5 disagreements, n=100.

    pa = 0.85; pi_include = (50 + 45) / 200 = 0.475
    pe = 2 * 0.475 * 0.525 = 0.49875; AC1 = (0.85 - 0.49875) / 0.50125
    """
    ratings = (
        [["in", "in"]] * 40
        + [["out", "out"]] * 45
        + [["in", "out"]] * 10
        + [["out", "in"]] * 5
    )
    result = gwet_ac1(ratings, categories=("in", "out"))
    assert result.pa == pytest.approx(0.85)
    assert result.pe == pytest.approx(0.49875)
    assert result.coefficient == pytest.approx((0.85 - 0.49875) / 0.50125)


def test_unknown_category_is_rejected():
    with pytest.raises(ValueError):
        gwet_ac1([["include", "maybe"]], categories=("include", "exclude"))


def test_no_paired_units_gives_no_coefficient():
    result = gwet_ac1([["include", None], [None, "exclude"]], categories=("include", "exclude"))
    assert result.coefficient is None
    assert result.n_units_paired == 0


def test_quadratic_weights_shape():
    w = weight_matrix([1, 2, 3], "quadratic")
    assert w[0] == pytest.approx([1.0, 0.75, 0.0])
    assert w[1][1] == 1.0


# --------------------------------------------------------------------------
# PABAK
# --------------------------------------------------------------------------


def test_pabak_binary():
    a = ["in"] * 45 + ["out"] * 45 + ["in"] * 5 + ["out"] * 5
    b = ["in"] * 45 + ["out"] * 45 + ["out"] * 5 + ["in"] * 5
    result = pabak(a, b, categories=("in", "out"))
    assert result.pa == pytest.approx(0.9)
    assert result.coefficient == pytest.approx(0.8)


def test_pabak_skips_units_missing_either_rating():
    result = pabak(["in", None, "out"], ["in", "out", None], categories=("in", "out"))
    assert result.n_units == 1
    assert result.coefficient == pytest.approx(1.0)


def test_pabak_rejects_unequal_lengths():
    with pytest.raises(ValueError):
        pabak(["in"], ["in", "out"], categories=("in", "out"))
