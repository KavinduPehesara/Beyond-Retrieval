"""Chance-corrected agreement: Gwet's AC1/AC2 and prevalence-adjusted kappa.

Used twice in the evaluation plan (proposal, Table 9):

* agreement between the model and the recorded human decisions, and
* inter-run agreement across repeated runs — the *reproducible* property.

Cohen's and Fleiss' kappa are not the headline figure. Under the class
imbalance of screening data (0.8% to 21.9% inclusion in this corpus) they can
sit near zero while raw agreement is near perfect, the paradox AC1 and AC2
were designed to avoid (Gwet, 2008).

There is no scikit-learn implementation of AC2. This one is tested against the
worked example published with the irrCAC package (dataset ``cac.raw4raters``)
before any number it produces is trusted — see ``tests/test_agreement.py``.

Formulae (Gwet, 2014), for n units, q categories and weight matrix w:

    r_ik   raters placing unit i in category k;  r_i = sum_k r_ik
    r*_ik  sum_l w_kl r_il
    pa     mean over units with r_i >= 2 of  sum_k r_ik (r*_ik - 1) / (r_i (r_i - 1))
    pi_k   mean over all rated units of  r_ik / r_i
    pe     sum(w) / (q (q - 1)) * sum_k pi_k (1 - pi_k)
    AC2    (pa - pe) / (1 - pe)

With identity weights AC2 is AC1.
"""

from __future__ import annotations

import math
from collections.abc import Hashable, Sequence
from dataclasses import asdict, dataclass

Weights = str | Sequence[Sequence[float]]


@dataclass(frozen=True)
class Agreement:
    """One agreement coefficient, with the parts it was computed from."""

    coefficient: float | None
    pa: float | None  # observed (weighted) agreement
    pe: float | None  # chance agreement
    n_units: int  # units with at least one rating
    n_units_paired: int  # units rated at least twice — the ones pa is over

    def as_dict(self) -> dict:
        return asdict(self)


def _missing(value) -> bool:
    return value is None or (isinstance(value, float) and math.isnan(value))


def weight_matrix(categories: Sequence[Hashable], weights: Weights = "identity") -> list[list[float]]:
    """Build a q x q weight matrix.

    ``identity`` suits nominal categories such as include/exclude.
    ``linear`` and ``quadratic`` need numeric, ordered categories.
    """
    q = len(categories)
    if not isinstance(weights, str):
        matrix = [list(map(float, row)) for row in weights]
        if len(matrix) != q or any(len(row) != q for row in matrix):
            raise ValueError(f"weight matrix must be {q}x{q}")
        return matrix

    if weights == "identity":
        return [[1.0 if k == l else 0.0 for l in range(q)] for k in range(q)]

    if weights in ("linear", "quadratic"):
        try:
            values = [float(c) for c in categories]
        except (TypeError, ValueError):
            raise ValueError(f"{weights} weights need numeric categories") from None
        span = max(values) - min(values)
        if span == 0:
            raise ValueError(f"{weights} weights need at least two distinct categories")
        power = 1 if weights == "linear" else 2
        return [
            [1.0 - (abs(a - b) / span) ** power for b in values] for a in values
        ]

    raise ValueError(f"Unknown weights {weights!r}")


def gwet_ac2(
    ratings: Sequence[Sequence[Hashable | None]],
    *,
    categories: Sequence[Hashable] | None = None,
    weights: Weights = "identity",
) -> Agreement:
    """Gwet's AC2 for any number of raters, with missing ratings allowed.

    ``ratings[i][j]`` is the category rater j gave unit i, or ``None``.

    Pass ``categories`` whenever the set is known in advance (for screening,
    ``("include", "exclude")``). Inferring it from the data fails when every
    rating is the same, which is exactly what perfect agreement looks like.
    """
    units = [[r for r in row if not _missing(r)] for row in ratings]
    units = [u for u in units if u]

    if categories is None:
        categories = sorted({r for u in units for r in u})
        if len(categories) < 2:
            raise ValueError(
                "Fewer than two categories observed; pass categories explicitly"
            )
    categories = list(categories)
    q = len(categories)
    if q < 2:
        raise ValueError("At least two categories are required")

    index = {c: k for k, c in enumerate(categories)}
    w = weight_matrix(categories, weights)

    counts: list[list[int]] = []
    for u in units:
        row = [0] * q
        for r in u:
            if r not in index:
                raise ValueError(f"Rating {r!r} is not one of {categories}")
            row[index[r]] += 1
        counts.append(row)

    n = len(counts)
    if n == 0:
        return Agreement(None, None, None, 0, 0)

    pi = [0.0] * q
    pa_sum = 0.0
    n_paired = 0
    for row in counts:
        r_i = sum(row)
        for k in range(q):
            pi[k] += row[k] / r_i / n
        if r_i < 2:
            continue
        n_paired += 1
        weighted = [sum(w[k][l] * row[l] for l in range(q)) for k in range(q)]
        pa_sum += sum(row[k] * (weighted[k] - 1) for k in range(q)) / (r_i * (r_i - 1))

    total_weight = sum(sum(row) for row in w)
    pe = total_weight / (q * (q - 1)) * sum(p * (1 - p) for p in pi)

    if n_paired == 0:
        return Agreement(None, None, pe, n, 0)

    pa = pa_sum / n_paired
    coefficient = (pa - pe) / (1 - pe) if pe < 1 else None
    return Agreement(coefficient, pa, pe, n, n_paired)


def gwet_ac1(
    ratings: Sequence[Sequence[Hashable | None]],
    *,
    categories: Sequence[Hashable] | None = None,
) -> Agreement:
    """AC2 with identity weights."""
    return gwet_ac2(ratings, categories=categories, weights="identity")


def pabak(
    rater_a: Sequence[Hashable | None],
    rater_b: Sequence[Hashable | None],
    *,
    categories: Sequence[Hashable],
) -> Agreement:
    """Prevalence-adjusted bias-adjusted kappa for two raters.

    PABAK = (q * po - 1) / (q - 1), over units both raters rated. It fixes
    chance agreement at 1/q, so it is insensitive to prevalence — reported
    beside AC1 so a reader can see the two chance corrections agree.
    """
    if len(rater_a) != len(rater_b):
        raise ValueError("Both raters must rate the same units")
    q = len(categories)
    if q < 2:
        raise ValueError("At least two categories are required")
    allowed = set(categories)

    pairs = [
        (a, b)
        for a, b in zip(rater_a, rater_b)
        if not _missing(a) and not _missing(b)
    ]
    for a, b in pairs:
        if a not in allowed or b not in allowed:
            raise ValueError(f"Rating not in {list(categories)}: {a!r}, {b!r}")

    n = len(pairs)
    if n == 0:
        return Agreement(None, None, 1 / q, 0, 0)
    po = sum(1 for a, b in pairs if a == b) / n
    return Agreement((q * po - 1) / (q - 1), po, 1 / q, n, n)
