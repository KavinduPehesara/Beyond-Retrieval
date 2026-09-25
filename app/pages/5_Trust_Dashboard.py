"""Trust Dashboard -- the RQ1 property table, live. Verifiable and accurate
are a number per review, read straight from that review's latest screening
run. Overridable is live too: whatever's been recorded on the Results &
Override page. Reproducible is not a per-review number -- it took five
repeated runs to measure once -- so it's shown as the one recorded finding,
not invented for every review.
"""

from __future__ import annotations

import streamlit as st
from api_client import health, list_reviews, override_summary, review_metrics

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
