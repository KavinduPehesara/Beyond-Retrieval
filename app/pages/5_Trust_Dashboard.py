"""Trust Dashboard -- the RQ1 property table, live. Verifiable and accurate
are a number per review, read straight from that review's latest screening
run. Overridable is live too: whatever's been recorded on the Results &
Override page. Reproducible is not a per-review number -- it took five
repeated runs to measure once -- so it's shown as the one recorded finding,
not invented for every review.
"""

from __future__ import annotations

import plots
import streamlit as st
from api_client import (
    charts_confidence,
    charts_performance,
    charts_trust,
    health,
    list_reviews,
    override_summary,
    review_metrics,
)

st.set_page_config(page_title="Trust Dashboard", page_icon="\U0001f6e1️", layout="wide")
st.title("Trust Dashboard")
st.caption("RQ1: can this system produce screening decisions a researcher can independently verify and rely on?")

if not health():
    st.error("Can't reach the API. Start it with `uvicorn slr.api.app:app`.")
    st.stop()

reviews = sorted(list_reviews(), key=lambda r: r["prevalence"])

rows = []
for r in reviews:
    review = r["review"]
    if not r["screen_run"]:
        rows.append({"Review": review, "Prevalence": r["prevalence"] * 100, "Verified": None, "Recall (verified)": None, "Agreement (AC1)": None, "Overridden": None})
        continue
    m = review_metrics(review)
    override_pct = None
    try:
        s = override_summary(review, m["run_id"])
        if s["n_overrides"]:
            override_pct = s["override_rate"]
    except Exception:
        pass
    rows.append(
        {
            "Review": review,
            "Prevalence": r["prevalence"] * 100,
            "Verified": m["verification_rate"],
            "Recall (verified)": m["recall_verified"],
            "Agreement (AC1)": m["agreement_ac1"],
            "Overridden": override_pct,
        }
    )

for row in rows:
    if row["Verified"] is not None:
        row["Verified"] *= 100
    if row["Overridden"] is not None:
        row["Overridden"] *= 100

st.subheader("Verifiable and accurate")
st.caption("Verified = share of decisions whose quote was found in the source. Recall and AC1 are computed over verified decisions only.")
st.dataframe(
    rows,
    hide_index=True,
    use_container_width=True,
    column_config={
        "Prevalence": st.column_config.NumberColumn(format="%.1f%%"),
        "Verified": st.column_config.NumberColumn(format="%.1f%%"),
        "Recall (verified)": st.column_config.NumberColumn(format="%.2f"),
        "Agreement (AC1)": st.column_config.NumberColumn(format="%.2f"),
        "Overridden": st.column_config.NumberColumn(format="%.0f%%", help="Share of recorded overrides that changed the system's decision."),
    },
)

st.divider()

# ---------------------------------------------------------------------------
# Charts. Every number here comes from /charts/*, which reads the same run
# directories and tables the table above does -- nothing is recomputed in
# this page.
# ---------------------------------------------------------------------------

try:
    trust = charts_trust()
except Exception as exc:  # API reachable but a chart route failed -- say so
    st.warning(f"Charts unavailable: {exc}")
    trust = None

if trust:
    st.subheader("Verification rate, ordered by inclusion rate")
    st.caption(
        "Bars are ordered left to right by how rare included records are in that review. "
        "If verification tracked class balance there would be a trend here; there isn't one, "
        "which is the finding — 91.7% at 1.0% prevalence, 51.9% at 21.9%, 39.3% at 12.3%."
    )
    st.altair_chart(plots.verification_bars(trust["verification"]), use_container_width=True)

    st.subheader("How verification fails")
    heatmap = plots.failure_heatmap(trust["failures"])
    if heatmap is None:
        st.info("No verification failures recorded — nothing to break down.")
    else:
        st.caption(
            "Shaded by each review's *own* share of failures, not raw counts: Radjenović_2013 "
            "has sixteen times more records than Nelson_2002, so counts would show one bright "
            "row and nothing else. `not_found` means the model's quote isn't in the abstract. "
            "`schema_validation_failed` means it didn't return usable JSON at all — a different "
            "problem with a different fix."
        )
        st.altair_chart(heatmap, use_container_width=True)

    st.subheader("Does the model know when it's inventing?")
    conf_review = st.selectbox(
        "Review", [r["review"] for r in reviews if r["screen_run"]], key="conf_review"
    )
    try:
        hist = charts_confidence(conf_review)
    except Exception as exc:
        st.warning(f"No confidence data: {exc}")
    else:
        st.altair_chart(plots.confidence_histogram(hist), use_container_width=True)
        mv, mu = hist["mean_verified"], hist["mean_unverified"]
        if mv is not None and mu is not None:
            cols = st.columns(3)
            cols[0].metric("Mean confidence, quote verified", f"{mv:.3f}", help=f"n = {hist['n_verified']}")
            cols[1].metric("Mean confidence, quote not found", f"{mu:.3f}", help=f"n = {hist['n_unverified']}")
            cols[2].metric("Difference", f"{mv - mu:+.3f}")
            st.caption(
                "**This is the argument for the verifier, in one chart.** The two distributions sit "
                "almost on top of each other: the model is about as confident when it invents a "
                "quote as when it copies one correctly. A confidence threshold could not have "
                "separated these, which is why a decision is only accepted when its quote is found "
                "verbatim in the source — and why an unverified decision becomes a referral to a "
                "human rather than a prediction."
            )

    st.subheader("Verification against recall")
    st.caption(
        "One point per review, sized by inclusion rate. Read from each review's recorded "
        "`metrics.json`, not recomputed here. Nelson_2002 sits high on recall and low on "
        "verification — strong-looking accuracy resting on barely half its decisions being "
        "verified at all, which is why the two are never reported apart."
    )
    st.altair_chart(
        plots.verification_vs_recall_scatter(trust["verification_vs_recall"]),
        use_container_width=True,
    )

st.divider()
c1, c2 = st.columns(2)
with c1:
    st.subheader("Reproducible")
    st.markdown(
        "Two properties, both measured, neither one a per-review live number:\n\n"
        "- **Same config → same output.** A stored config run twice produces a "
        "byte-identical `metrics.json`, verified on every review screened so far.\n"
        "- **Genuine inter-run agreement.** 5 independent, cache-bypassed runs of "
        "`qwen2.5:7b-instruct` at temperature 0 on Nelson_2002 gave Gwet's "
        "**AC1 = 1.0** across 186 commonly-verified records — perfect agreement, "
        "not near-perfect (week 10, `runs/20260922T124547509237Z-9a8ec8f4db` "
        "through `.../20260923T074803087022Z-9a8ec8f4db`)."
    )
with c2:
    st.subheader("Overridable")
    st.markdown(
        "The mechanism is live — use **Results & Override** on any review; the "
        "table above reflects whatever's been recorded this session.\n\n"
        "It was first demonstrated on 13 real Nelson_2002 records (week 10): **69.2%** "
        "of overrides changed the system's proposal, and all 13 matched ground truth on "
        "review — including one case where a verified quote was real but substantively "
        "wrong, which the span verifier cannot catch and an override can."
    )

if trust:
    overrides = trust["overrides"]
    if overrides["n"]:
        st.divider()
        st.subheader("What human review changed")
        o1, o2, o3, o4 = st.columns(4)
        o1.metric("Dispositions recorded", overrides["n"])
        o2.metric("Changed the system's call", overrides["changed"])
        o3.metric("Confirmed it", overrides["confirmed"])
        o4.metric(
            "Override rate",
            f"{overrides['override_rate']:.0%}" if overrides["override_rate"] is not None else "n/a",
        )
        st.caption(
            f"{overrides['disposed_referrals']} of these were records the system had already "
            f"referred to a human, {overrides['disposed_verified']} were decisions it had made "
            "and verified. The second group matters more: a quote can be real and still be "
            "attached to the wrong criterion, which the verifier cannot catch and a reviewer can."
        )

st.divider()
st.subheader("Cost and speed (RQ2)")
perf_review = st.selectbox(
    "Review", [r["review"] for r in reviews if r["screen_run"]], key="perf_review"
)
try:
    perf = charts_performance(perf_review)
except Exception as exc:
    st.warning(f"Performance data unavailable: {exc}")
else:
    latency, cache = perf["latency"], perf["cache"]
    p1, p2 = st.columns(2)
    with p1:
        st.markdown("**Time per record**")
        histogram = plots.latency_histogram(latency)
        if histogram is None:
            st.info(
                "Every call in this run was served from the cache, so there's no live timing to "
                "show — which is the reproducibility property working, not missing data."
            )
        else:
            st.altair_chart(histogram, use_container_width=True)
            st.caption(
                f"Median {latency['p50_ms']:,.0f} ms, 90th percentile {latency['p90_ms']:,.0f} ms, "
                f"{latency['total_hours']:.1f} hours of local GPU time for {latency['n']:,} records. "
                "Cache hits are excluded — they return in microseconds and would swamp the shape."
            )
    with p2:
        st.markdown("**Cache**")
        st.altair_chart(plots.cache_bars(cache), use_container_width=True)
        bits = []
        if cache["cache_hit_rate"] is not None:
            bits.append(f"{cache['cache_hit_rate']:.0%} of calls served from cache")
        if cache["hours_saved"]:
            bits.append(f"about {cache['hours_saved']:.1f} hours of model time avoided")
        bits.append(f"${cache['cost_usd']:.2f} spent")
        st.caption(
            ", ".join(bits) + ". Local inference is $0 by construction, which is why the cost "
            "figure is what it is — the cache is what makes a re-run free in *time* as well."
        )

st.divider()
st.subheader("Gap discovery (RQ2)")
st.markdown(
    "Not part of the RQ1 table, but the same discipline applies: precision on discovered "
    "gap statements is **87.8%** (74 rated across all six reviews), but recall — measured "
    "separately, on a blind sample of what the model did *not* flag — is far lower, "
    "roughly **40–70%** depending on the review. See **Gap Discovery** for the live figures "
    "per review; the recall estimate is a one-off measurement, not a live number, for the same "
    "reason reproducibility isn't: it took a blind labelling pass to produce."
)
