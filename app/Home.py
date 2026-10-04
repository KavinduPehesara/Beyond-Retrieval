"""Beyond Retrieval -- dashboard entry point.

Six panels: run a query, review and override decisions, inspect extracted
data, inspect discovered gaps, see the RQ1 trust numbers together, and
search the open web for papers outside the six ingested reviews. Every
number on every panel comes from the API, which in turn reads a run
directory or the live database -- nothing here computes a figure of its
own. Discover is the one exception that isn't a reported figure at all --
see its own page for why.
"""

from __future__ import annotations

import plots
import streamlit as st
from api_client import API_URL, charts_corpus, health, list_reviews

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

# ---------------------------------------------------------------------------
# The corpus, as two pictures. Prevalence first because the spread is a
# deliberate design choice rather than whatever the data happened to be.
# ---------------------------------------------------------------------------

try:
    corpus = charts_corpus()
except Exception as exc:
    st.warning(f"Charts unavailable: {exc}")
else:
    c1, c2 = st.columns([1, 1])
    with c1:
        st.markdown("**Inclusion rate across the corpus**")
        st.caption(
            "A twenty-seven-fold spread, chosen on purpose: screening accuracy is known to "
            "inflate on balanced data, so six reviews spanning 0.8% to 21.9% test more than a "
            "larger corpus at uniform prevalence would."
        )
        st.altair_chart(plots.prevalence_bars(corpus["prevalence"]), use_container_width=True)
    with c2:
        st.markdown("**When these papers were published**")
        years = plots.year_bars(corpus["years"])
        if years is None:
            st.info("No publication years recorded.")
        else:
            span = corpus["years"]["span"]
            st.caption(
                f"All six reviews together, {span[0]}–{span[1]}. Grey is every record screened; "
                "blue is the ones that made it into a review."
            )
            st.altair_chart(years, use_container_width=True)

    missing = [m["column"] for m in corpus["metadata_coverage"] if not m["chartable"]]
    if missing:
        st.caption(
            "Not chartable yet: " + ", ".join(f"`{m}`" for m in missing) + ". These columns exist "
            "in the schema but ingest never populated them, so there is no country map, venue "
            "breakdown or language split — shown as a gap rather than an empty axis."
        )

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
        "overridable) with a live number per review, next to what's a one-off recorded finding.\n\n"
        "**Discover** -- search the open web (OpenAlex) for any topic, not just the six ingested "
        "reviews, and extract + gap-check whatever comes back. Not part of the evaluation corpus."
    )

st.divider()
st.caption(f"API: `{API_URL}` · Local inference only -- every figure on this dashboard is $0.")
