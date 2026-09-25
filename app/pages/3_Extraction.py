"""Extraction -- the four structured fields for every included paper, and
how much of each is actually verified in this review. Only titles and
abstracts are available, so a field is only ever reported with the sentence
it came from.
"""

from __future__ import annotations

import streamlit as st
from api_client import extraction_summary, health, list_papers, list_reviews, paper_detail

st.set_page_config(page_title="Extraction", page_icon="\U0001f4c4", layout="wide")
st.title("Extraction")

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
