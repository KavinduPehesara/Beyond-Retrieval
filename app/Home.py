"""Beyond Retrieval -- dashboard entry point.

Five panels, one job each: run a query, review and override decisions,
inspect extracted data, inspect discovered gaps, and see the RQ1 trust
numbers together. Every number on every panel comes from the API, which in
turn reads a run directory or the live database -- nothing here computes a
figure of its own.
"""

from __future__ import annotations

import streamlit as st
from api_client import API_URL, health, list_reviews

st.set_page_config(page_title="Beyond Retrieval", page_icon="\U0001f4da", layout="wide")

st.title("Beyond Retrieval")
st.caption(
    "An LLM-supported dashboard for literature review and research gap detection. "
    "Every screening decision, extracted field and gap statement here carries a "
    "quote checked against the source paper -- an unverifiable claim is not shown as a fact."
)

if not health():
    st.error(
        f"Can't reach the API at `{API_URL}`. Start it first:\n\n"
        "```\nuvicorn slr.api.app:app\n```"
    )
    st.stop()

reviews = list_reviews()

st.subheader("Six reviews")
st.caption("Prevalence sits beside every count -- results are never pooled across reviews of different prevalence.")

cols = ["review", "domain", "n_records", "n_included", "prevalence", "criteria_status"]
rows = [{c: r[c] for c in cols} for r in sorted(reviews, key=lambda r: r["prevalence"])]
for row in rows:
    row["prevalence"] = row["prevalence"] * 100  # column format below appends "%"
st.dataframe(
    rows,
    hide_index=True,
    use_container_width=True,
    column_config={
        "review": "Review",
        "domain": "Domain",
        "n_records": st.column_config.NumberColumn("Records", format="%d"),
        "n_included": st.column_config.NumberColumn("Included", format="%d"),
        "prevalence": st.column_config.NumberColumn("Prevalence", format="%.1f%%"),
        "criteria_status": "Criteria",
    },
)

not_screened = [r["review"] for r in reviews if not r["screen_run"]]
if not_screened:
    st.warning("Not yet screened: " + ", ".join(not_screened))

st.divider()
st.subheader("Panels")
p1, p2 = st.columns(2)
with p1:
    st.markdown(
        "**Search & Screen** -- pick a review, rank candidates with any of the five "
        "retrieval strategies, screen a handful live and watch the verified quotes come back.\n\n"
        "**Results & Override** -- browse a run's decisions, filter to what needs a human, "
        "and record a disposition against any of them.\n\n"
        "**Extraction** -- the four structured fields for every included paper, with coverage "
        "by field and by review."
    )
with p2:
    st.markdown(
        "**Gap Discovery** -- the research-gap statements the model found, with the rating on each.\n\n"
        "**Trust Dashboard** -- the RQ1 property table (verifiable, accurate, reproducible, "
        "overridable) with a live number per review, next to what's a one-off recorded finding."
    )

st.divider()
st.caption(f"API: `{API_URL}` · Local inference only -- every figure on this dashboard is $0.")
