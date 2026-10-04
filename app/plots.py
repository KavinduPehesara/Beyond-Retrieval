"""Altair chart builders for the panels.

Each function takes the shape ``slr.eval.charts`` returns and gives back a
chart object. Nothing here computes a figure -- if a number appears on an
axis, it came out of the API, which got it from the eval layer, which read
it from a run directory or a harness-written table. Keeping the drawing
here and the arithmetic there means a chart and the table beside it cannot
disagree.

Two conventions worth knowing before changing anything:

* **Prevalence rides along.** Rule 5 says results are reported per review
  with the inclusion rate beside them, never pooled. In a chart that means
  prevalence goes in the axis label or the tooltip of every per-review
  chart, so a bar can't be read without it.
* **A missing number is drawn as missing.** Nothing here substitutes zero
  for ``None``. A field that was never extracted and a field that verified
  zero times look identical on a bar chart and are completely different
  findings, so the former is filtered out and said in words instead.
"""

from __future__ import annotations

import altair as alt
import pandas as pd

# Colour-blind-safe pair, used consistently: blue is the good case
# (verified, included, found), orange the one that needs attention.
VERIFIED = "#2c7fb8"
UNVERIFIED = "#e6833c"
NEUTRAL = "#9aa5b1"
NOT_STATED = "#c7ccd1"

HEIGHT = 280


def _pct(field: str, title: str) -> alt.Y:
    return alt.Y(field, type="quantitative", title=title, axis=alt.Axis(format="%"))


def _review_label(row: dict) -> str:
    """Review name with its inclusion rate, so rule 5 holds on every axis."""
    prevalence = row.get("prevalence")
    if prevalence is None:
        return row["review"]
    return f"{row['review']} ({prevalence * 100:.1f}%)"


# --------------------------------------------------------------------------
# Trust
# --------------------------------------------------------------------------


def verification_bars(rows: list[dict]) -> alt.Chart:
    """Verification rate per review, ordered by prevalence.

    The recorded finding here is that verification does *not* track
    prevalence in any simple direction -- 91.7% at 1.0% prevalence, 51.9%
    at 21.9%, 39.3% at 12.3%. Ordering the bars by prevalence is what lets
    a reader see that there's no trend rather than being told so.
    """
    df = pd.DataFrame(
        [
            {
                "review": _review_label(r),
                "rate": r["verification_rate"],
                "verified": r["verified"],
                "n": r["n"],
                "order": r.get("prevalence") or 0,
            }
            for r in rows
        ]
    )
    return (
        alt.Chart(df)
        .mark_bar(color=VERIFIED)
        .encode(
            x=alt.X("review:N", sort=alt.EncodingSortField("order"), title="Review (inclusion rate)"),
            y=_pct("rate", "Decisions whose quote verified"),
            tooltip=[
                alt.Tooltip("review:N", title="Review"),
                alt.Tooltip("rate:Q", title="Verified", format=".1%"),
                alt.Tooltip("verified:Q", title="Verified decisions"),
                alt.Tooltip("n:Q", title="Decisions"),
            ],
        )
        .properties(height=HEIGHT)
    )


def failure_heatmap(matrix: dict) -> alt.Chart | None:
    """Review x failure type, shaded by share of that review's failures.

    Shares rather than counts: Radjenovic_2013 has sixteen times more
    records than Nelson_2002, so a count heatmap would be one bright row
    and five dark ones. The counts stay in the tooltip.
    """
    if not matrix["rows"]:
        return None
    records = []
    for row in matrix["rows"]:
        for note in matrix["notes"]:
            records.append(
                {
                    "review": row["review"],
                    "note": note,
                    "share": row["shares"][note],
                    "count": row["counts"][note],
                    "total": row["total_failures"],
                }
            )
    df = pd.DataFrame(records)
    return (
        alt.Chart(df)
        .mark_rect()
        .encode(
            x=alt.X("note:N", title="Why verification failed", sort=matrix["notes"]),
            y=alt.Y("review:N", title=None),
            color=alt.Color(
                "share:Q",
                title="Share of failures",
                scale=alt.Scale(scheme="oranges"),
                legend=alt.Legend(format="%"),
            ),
            tooltip=[
                alt.Tooltip("review:N", title="Review"),
                alt.Tooltip("note:N", title="Failure"),
                alt.Tooltip("count:Q", title="Decisions"),
                alt.Tooltip("share:Q", title="Share", format=".1%"),
                alt.Tooltip("total:Q", title="Failures in review"),
            ],
        )
        .properties(height=max(HEIGHT - 60, 28 * len(matrix["rows"])))
    )


def confidence_histogram(hist: dict) -> alt.Chart:
    """Confidence split by whether the quote verified -- the calibration chart.

    Drawn as two overlaid outlines rather than a stacked bar, because the
    question a reader has is whether the two distributions sit on top of
    each other. Stacking would hide exactly that.
    """
    records = []
    for i, label in enumerate(hist["bin_labels"]):
        records.append({"bin": label, "which": "Quote verified", "n": hist["verified"][i]})
        records.append({"bin": label, "which": "Quote not found", "n": hist["unverified"][i]})
    df = pd.DataFrame(records)
    return (
        alt.Chart(df)
        .mark_bar(opacity=0.75)
        .encode(
            x=alt.X("bin:N", title="Model's stated confidence", sort=hist["bin_labels"]),
            y=alt.Y("n:Q", title="Decisions", stack=None),
            color=alt.Color(
                "which:N",
                title=None,
                scale=alt.Scale(
                    domain=["Quote verified", "Quote not found"], range=[VERIFIED, UNVERIFIED]
                ),
            ),
            tooltip=["bin:N", "which:N", alt.Tooltip("n:Q", title="Decisions")],
        )
        .properties(height=HEIGHT)
    )


def verification_vs_recall_scatter(points: list[dict]) -> alt.Chart:
    """One point per review. Size is prevalence, so the class-balance
    confound is visible rather than argued about."""
    df = pd.DataFrame(
        [
            {
                "review": p["review"],
                "verification": p["verification_rate"],
                "recall": p["recall_verified"],
                "prevalence": p["prevalence"],
            }
            for p in points
            if p["recall_verified"] is not None
        ]
    )
    if df.empty:
        return alt.Chart(pd.DataFrame({"x": []})).mark_point()
    base = alt.Chart(df).encode(
        x=_pct("verification", "Verification rate"),
        y=alt.Y("recall:Q", title="Recall over verified decisions"),
    )
    return (
        base.mark_circle(color=VERIFIED, opacity=0.8).encode(
            size=alt.Size("prevalence:Q", title="Inclusion rate", legend=alt.Legend(format="%")),
            tooltip=[
                alt.Tooltip("review:N", title="Review"),
                alt.Tooltip("verification:Q", title="Verified", format=".1%"),
                alt.Tooltip("recall:Q", title="Recall", format=".3f"),
                alt.Tooltip("prevalence:Q", title="Inclusion rate", format=".1%"),
            ],
        )
        + base.mark_text(dy=-12, fontSize=10, color=NEUTRAL).encode(text="review:N")
    ).properties(height=HEIGHT)


# --------------------------------------------------------------------------
# Screening
# --------------------------------------------------------------------------


def recall_curve(curve: dict) -> alt.LayerChart:
    """Recall against records read, with the random diagonal and the 95% line.

    The diagonal is the whole point of the chart: the vertical distance
    between the curve and it is the reading effort the ranking saves, which
    is what TNR@95 puts a single number on.
    """
    df = pd.DataFrame(
        {
            "read": curve["x"],
            "Ranking": curve["y"],
            "Random (no ranking)": curve["random_baseline"],
        }
    ).melt("read", var_name="which", value_name="recall")

    lines = (
        alt.Chart(df)
        .mark_line()
        .encode(
            x=alt.X("read:Q", title="Records read, in ranked order"),
            y=_pct("recall", "Included records found"),
            color=alt.Color(
                "which:N",
                title=None,
                scale=alt.Scale(
                    domain=["Ranking", "Random (no ranking)"], range=[VERIFIED, NEUTRAL]
                ),
            ),
            strokeDash=alt.StrokeDash(
                "which:N",
                legend=None,
                scale=alt.Scale(
                    domain=["Ranking", "Random (no ranking)"], range=[[1, 0], [4, 3]]
                ),
            ),
            tooltip=[
                alt.Tooltip("read:Q", title="Records read"),
                alt.Tooltip("recall:Q", title="Recall", format=".1%"),
                alt.Tooltip("which:N", title=None),
            ],
        )
    )

    layers = [lines, alt.Chart(pd.DataFrame({"y": [0.95]})).mark_rule(
        color=UNVERIFIED, strokeDash=[4, 4]
    ).encode(y="y:Q")]

    if curve.get("cutoff_95"):
        layers.append(
            alt.Chart(pd.DataFrame({"x": [curve["cutoff_95"]]}))
            .mark_rule(color=UNVERIFIED, strokeDash=[4, 4])
            .encode(x="x:Q", tooltip=alt.Tooltip("x:Q", title="Records read to 95% recall"))
        )
    return alt.layer(*layers).properties(height=HEIGHT + 40)


def semantic_scatter(data: dict) -> alt.Chart:
    """Included records drawn over excluded, never under.

    There are 27 includes among 2,627 records in Smid_2020; painted in
    arbitrary order they would simply be invisible.
    """
    df = pd.DataFrame(data["points"])
    df["label"] = df["included"].map({True: "Included", False: "Excluded"})
    excluded = (
        alt.Chart(df[~df["included"]])
        .mark_circle(size=18, opacity=0.25, color=NEUTRAL)
        .encode(x=alt.X("x:Q", axis=None), y=alt.Y("y:Q", axis=None))
    )
    included = (
        alt.Chart(df[df["included"]])
        .mark_circle(size=70, opacity=0.95, color=VERIFIED, stroke="white", strokeWidth=0.6)
        .encode(
            x=alt.X("x:Q", axis=None),
            y=alt.Y("y:Q", axis=None),
            tooltip=[alt.Tooltip("work_id:N", title="Record")],
        )
    )
    return (excluded + included).properties(height=HEIGHT + 90)


# --------------------------------------------------------------------------
# Extraction
# --------------------------------------------------------------------------


def extraction_coverage_heatmap(coverage: dict) -> alt.Chart | None:
    """Review x field, shaded by verified share -- the domain chart.

    Cells for a field that was never extracted in a review are dropped
    rather than drawn as 0%: "never attempted" and "attempted and never
    verified" are different findings and must not share a colour.
    """
    records = []
    for row in coverage["rows"]:
        for field in coverage["fields"]:
            cell = row["fields"][field]
            if not cell["n"]:
                continue
            records.append(
                {
                    "review": _review_label(row),
                    "field": field,
                    "share": cell["share"],
                    "verified": cell["verified"],
                    "n": cell["n"],
                    "order": row.get("prevalence") or 0,
                }
            )
    if not records:
        return None
    df = pd.DataFrame(records)
    return (
        alt.Chart(df)
        .mark_rect()
        .encode(
            x=alt.X("field:N", title=None, sort=list(coverage["fields"])),
            y=alt.Y("review:N", title=None, sort=alt.EncodingSortField("order")),
            color=alt.Color(
                "share:Q",
                title="Verified",
                scale=alt.Scale(scheme="blues", domain=[0, 1]),
                legend=alt.Legend(format="%"),
            ),
            tooltip=[
                alt.Tooltip("review:N", title="Review"),
                alt.Tooltip("field:N", title="Field"),
                alt.Tooltip("share:Q", title="Verified", format=".1%"),
                alt.Tooltip("verified:Q", title="Verified records"),
                alt.Tooltip("n:Q", title="Records attempted"),
            ],
        )
        .properties(height=max(HEIGHT - 60, 30 * len(coverage["rows"])))
    )


def extraction_status_bars(rows: list[dict]) -> alt.Chart:
    """Verified / not stated / unverified per field, as shares of a full bar.

    ``not_stated`` gets its own band because it is a correct answer -- the
    abstract genuinely doesn't say -- and folding it into either neighbour
    would misreport the model.
    """
    order = ["Verified", "Not stated", "Quote not found"]
    records = []
    for row in rows:
        if not row["n"]:
            continue
        for name, value in zip(order, (row["verified"], row["not_stated"], row["unverified"])):
            records.append(
                {"field": row["field"], "status": name, "n": value, "total": row["n"]}
            )
    df = pd.DataFrame(records)
    return (
        alt.Chart(df)
        .mark_bar()
        .encode(
            x=alt.X("n:Q", title="Records", stack="normalize", axis=alt.Axis(format="%")),
            y=alt.Y("field:N", title=None),
            color=alt.Color(
                "status:N",
                title=None,
                sort=order,
                scale=alt.Scale(domain=order, range=[VERIFIED, NOT_STATED, UNVERIFIED]),
            ),
            tooltip=[
                alt.Tooltip("field:N", title="Field"),
                alt.Tooltip("status:N", title=None),
                alt.Tooltip("n:Q", title="Records"),
                alt.Tooltip("total:Q", title="Of"),
            ],
        )
        .properties(height=max(140, 42 * len(rows)))
    )


# --------------------------------------------------------------------------
# Gap discovery
# --------------------------------------------------------------------------


def gap_rate_bars(rows: list[dict]) -> alt.Chart:
    """Share of verified-includes stating a gap, ordered by prevalence.

    Ordered by prevalence so the recorded finding -- the rate swings 3.8%
    to 52% and does *not* track prevalence, it tracks the genre of the
    abstract -- is visible rather than asserted.
    """
    df = pd.DataFrame(
        [
            {
                "review": _review_label(r),
                "rate": r["gap_rate"],
                "stated": r["gap_stated"],
                "n": r["n_records"],
                "order": r.get("prevalence") or 0,
            }
            for r in rows
        ]
    )
    return (
        alt.Chart(df)
        .mark_bar(color=VERIFIED)
        .encode(
            x=alt.X("review:N", sort=alt.EncodingSortField("order"), title="Review (inclusion rate)"),
            y=_pct("rate", "Abstracts stating a gap"),
            tooltip=[
                alt.Tooltip("review:N", title="Review"),
                alt.Tooltip("rate:Q", title="Gap rate", format=".1%"),
                alt.Tooltip("stated:Q", title="Flagged"),
                alt.Tooltip("n:Q", title="Records checked"),
            ],
        )
        .properties(height=HEIGHT)
    )


def gap_precision_recall_bars(rows: list[dict]) -> alt.Chart:
    """Precision beside the recorded recall estimate, per review.

    The pair is the finding: precision is high, recall is not, and either
    number alone misrepresents what gap discovery does. A review with no
    recall measurement shows one bar, not a borrowed second one.
    """
    records = []
    for row in rows:
        if row["precision"] is not None:
            records.append(
                {
                    "review": row["review"],
                    "measure": "Precision (rated)",
                    "value": row["precision"],
                    "detail": f"{row['n_rated']} statements rated",
                }
            )
        if row["recall_estimate"] is not None:
            records.append(
                {
                    "review": row["review"],
                    "measure": "Recall (blind sample)",
                    "value": row["recall_estimate"],
                    "detail": f"{row['recall_sampled']} not_stated records sampled",
                }
            )
    if not records:
        return alt.Chart(pd.DataFrame({"x": []})).mark_bar()
    df = pd.DataFrame(records)
    return (
        alt.Chart(df)
        .mark_bar()
        .encode(
            x=alt.X("review:N", title=None),
            y=_pct("value", None),
            xOffset="measure:N",
            color=alt.Color(
                "measure:N",
                title=None,
                scale=alt.Scale(
                    domain=["Precision (rated)", "Recall (blind sample)"],
                    range=[VERIFIED, UNVERIFIED],
                ),
            ),
            tooltip=[
                alt.Tooltip("review:N", title="Review"),
                alt.Tooltip("measure:N", title=None),
                alt.Tooltip("value:Q", title="Value", format=".1%"),
                alt.Tooltip("detail:N", title="Based on"),
            ],
        )
        .properties(height=HEIGHT)
    )


# --------------------------------------------------------------------------
# Corpus
# --------------------------------------------------------------------------


def prevalence_bars(rows: list[dict]) -> alt.Chart:
    """Records and inclusion rate per review -- the corpus-design chart.

    The spread from 0.8% to 21.9% is the deliberate design choice the
    proposal argues for, so it is worth being the first thing anyone sees.
    """
    df = pd.DataFrame(
        [
            {
                "review": r["review"],
                "prevalence": r["prevalence"],
                "n": r["n"],
                "included": r["included"],
            }
            for r in rows
        ]
    )
    return (
        alt.Chart(df)
        .mark_bar(color=VERIFIED)
        .encode(
            x=alt.X("review:N", sort="y", title=None),
            y=_pct("prevalence", "Inclusion rate"),
            tooltip=[
                alt.Tooltip("review:N", title="Review"),
                alt.Tooltip("prevalence:Q", title="Inclusion rate", format=".1%"),
                alt.Tooltip("included:Q", title="Included"),
                alt.Tooltip("n:Q", title="Records"),
            ],
        )
        .properties(height=HEIGHT)
    )


def year_bars(years: dict) -> alt.Chart | None:
    """Publication years, with included records as a darker overlay."""
    if not years["years"]:
        return None
    df = pd.DataFrame(
        {
            "year": years["years"],
            "Records": years["counts"],
            "Included": years["included"],
        }
    )
    base = alt.Chart(df).encode(x=alt.X("year:O", title=None, axis=alt.Axis(labelOverlap=True)))
    return (
        base.mark_bar(color=NEUTRAL, opacity=0.55).encode(
            y=alt.Y("Records:Q", title="Records"),
            tooltip=["year:O", "Records:Q", "Included:Q"],
        )
        + base.mark_bar(color=VERIFIED).encode(y="Included:Q")
    ).properties(height=HEIGHT)


# --------------------------------------------------------------------------
# Performance
# --------------------------------------------------------------------------


def latency_histogram(summary: dict, *, bins: int = 30) -> alt.Chart | None:
    """Live-call latency. Cache hits are already excluded upstream."""
    if not summary.get("n"):
        return None
    df = pd.DataFrame({"ms": summary["values"]})
    return (
        alt.Chart(df)
        .mark_bar(color=VERIFIED)
        .encode(
            x=alt.X("ms:Q", bin=alt.Bin(maxbins=bins), title="Milliseconds per record"),
            y=alt.Y("count():Q", title="Records"),
            tooltip=[alt.Tooltip("count():Q", title="Records")],
        )
        .properties(height=HEIGHT)
    )


def cache_bars(cache: dict) -> alt.Chart:
    """Calls served from cache against calls actually made."""
    df = pd.DataFrame(
        [
            {"which": "Served from cache", "n": cache["cached_calls"]},
            {"which": "Sent to the model", "n": cache["live_calls"]},
        ]
    )
    return (
        alt.Chart(df)
        .mark_bar()
        .encode(
            y=alt.Y("which:N", title=None),
            x=alt.X("n:Q", title="Calls"),
            color=alt.Color(
                "which:N",
                legend=None,
                scale=alt.Scale(
                    domain=["Served from cache", "Sent to the model"], range=[VERIFIED, NEUTRAL]
                ),
            ),
            tooltip=[alt.Tooltip("which:N", title=None), alt.Tooltip("n:Q", title="Calls")],
        )
        .properties(height=120)
    )
