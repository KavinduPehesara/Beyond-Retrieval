"""Extraction -- the four structured fields for every included paper, and
how much of each is actually verified in this review. Only titles and
abstracts are available, so a field is only ever reported with the sentence
it came from.
"""

from __future__ import annotations

import plots
import streamlit as st
from api_client import (
    charts_extraction,
    extraction_summary,
    health,
    list_papers,
    list_reviews,
    paper_detail,
)

st.set_page_config(page_title="Validation \u00b7 Extraction", page_icon="\U0001f4c4", layout="wide")
from research_style import apply_research_style
apply_research_style()
st.title("Validation \u2014 extracted data")
st.info(
    "**This is validation evidence, not the tool.** These six systematic reviews were completed "
    "years ago by other research teams, and their correct answers were published. Running the "
    "pipeline over them is how every figure in this project is checked \u2014 including where it "
    "does badly. To use the tool on your own topic, go to **Run a review**.",
    icon="\U0001f9ea",
)

if not health():
    st.error("Can't reach the API. Start it with `uvicorn slr.api.app:app`.")
    st.stop()

reviews = {r["review"]: r for r in list_reviews()}
review = st.selectbox("Review", list(reviews))
info = reviews[review]

if not info["extract_run"]:
    st.warning(f"{review} has not been extracted yet.")
    st.stop()

summary = extraction_summary(review)
st.caption(f"Run `{summary['run_id']}`")

FIELDS = ["study_design", "sample_size", "country", "key_finding"]
cols = st.columns(4)
for col, field in zip(cols, FIELDS):
    c = summary["fields"].get(field, {"verified": 0, "not_stated": 0, "unverified": 0})
    total = c["verified"] + c["not_stated"] + c["unverified"]
    pct = (c["verified"] / total * 100) if total else 0
    col.metric(field, f"{pct:.0f}% verified", help=f"{c['verified']} verified · {c['not_stated']} not stated · {c['unverified']} unverified")

# ---------------------------------------------------------------------------
# Two charts: this review's per-field breakdown, and the same measure across
# all six so a reader can see whether a low number is the model struggling
# or the domain simply not reporting that detail.
# ---------------------------------------------------------------------------

try:
    chart_data = charts_extraction(review)
except Exception as exc:
    st.warning(f"Charts unavailable: {exc}")
else:
    st.subheader("What each field found")
    st.caption(
        "**Not stated** is a correct answer, not a failure — the abstract genuinely doesn't say, "
        "and the model said so rather than inventing something. It gets its own band for that "
        "reason. Only the orange band is the model quoting something that isn't there."
    )
    st.altair_chart(plots.extraction_status_bars(chart_data["status"]), use_container_width=True)

    st.subheader("The same four fields, across all six reviews")
    heatmap = plots.extraction_coverage_heatmap(chart_data["coverage"])
    if heatmap is None:
        st.info("Only one review has been extracted so far — nothing to compare against.")
    else:
        st.caption(
            "Rows are ordered by inclusion rate. `key_finding` holds up everywhere (96–100%); "
            "`study_design` and `sample_size` collapse on software-engineering abstracts, which "
            "describe datasets and repositories rather than a study design and a patient count. "
            "That's the extraction schema carrying clinical-trial reporting conventions into a "
            "field that doesn't use them — a finding about the schema, not a model failure. "
            "Blank cells mean the field was never extracted for that review, which is different "
            "from extracted and never verified."
        )
        st.altair_chart(heatmap, use_container_width=True)

st.divider()

if info["screen_run"]:
    papers = list_papers(review, run_id=info["screen_run"], decision="include", verified_only=True, limit=500)
else:
    papers = []

q = st.text_input("Filter by title", placeholder="Type to filter...")
if q:
    papers = [p for p in papers if q.lower() in (p["title"] or "").lower()]
st.caption(f"{len(papers)} included papers")

options = {f"{(p['title'] or p['work_id'])[:90]}": p["work_id"] for p in papers}
if not options:
    st.info("No included papers match.")
    st.stop()

chosen = st.selectbox("Paper", list(options))
detail = paper_detail(review, options[chosen])

st.markdown(f"### {detail['title'] or ''}")
st.caption(f"{detail['venue'] or 'venue not recorded'} · {detail['year'] or ''}" + (f" · [DOI]({detail['doi']})" if detail["doi"] else ""))

STATUS_ICON = {"verified": "✓", "not_stated": "—", "unverified": "!", "missing": "·"}
grid = st.columns(2)
for i, field in enumerate(FIELDS):
    f = detail[field]
    with grid[i % 2].container(border=True):
        st.markdown(f"**{field}** &nbsp; {STATUS_ICON.get(f['status'], '')} {f['status']}")
        if f["status"] == "verified":
            st.write(f["value"])
            st.markdown(f"> {f['quote']}")
        elif f["status"] == "not_stated":
            st.caption("The abstract does not say.")
        elif f["status"] == "unverified":
            st.caption("A value was proposed but its quote wasn't found, so it's withheld.")
        else:
            st.caption("Not extracted.")
