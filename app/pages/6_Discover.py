"""Discover -- search the open web (OpenAlex), not just the six ingested
reviews, and run every result through the same verified extraction and
gap-discovery pipeline the rest of this project uses. Explicitly not part
of the evaluation corpus: nothing found here is screened against a
review's eligibility criteria, scored, or counted in any reported figure.
"""

from __future__ import annotations

import httpx
import streamlit as st
from api_client import discover, health

st.set_page_config(page_title="Discover", page_icon="\U0001f310", layout="wide")
st.title("Discover")
st.caption(
    "Search the open web for papers on any topic, then extract and check them for stated gaps -- "
    "live, outside the six ingested reviews. Not a reported figure: see the Trust Dashboard for that."
)

if not health():
    st.error("Can't reach the API. Start it with `uvicorn slr.api.app:app`.")
    st.stop()

with st.form("discover_form"):
    query = st.text_input("Search text", placeholder="e.g. hormone therapy cardiovascular outcomes")
    limit = st.slider("Results", min_value=1, max_value=10, value=5)
    submitted = st.form_submit_button("Search")

if not submitted:
    st.info("Searches OpenAlex live (no key needed), then runs each result through extraction and gap-checking with the local model -- needs Ollama running, same as Search & Screen.")
    st.stop()

if not query.strip():
    st.warning("Type something to search for.")
    st.stop()

with st.spinner(f"Searching OpenAlex and checking up to {limit} results..."):
    try:
        papers = discover(query, limit=limit)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 502:
            st.error("Couldn't reach OpenAlex. Check your internet connection and try again.")
        else:
            st.error(f"Request failed: {exc.response.text}")
        st.stop()
    except httpx.HTTPError:
        st.error("The model didn't respond in time. Is Ollama running?")
        st.stop()

if not papers:
    st.warning("No results had an abstract available to check. OpenAlex only has abstracts for roughly half of indexed papers -- try a different search.")
    st.stop()

st.caption(f"{len(papers)} papers, extracted and gap-checked live")

FIELDS = ["study_design", "sample_size", "country", "key_finding"]
STATUS_ICON = {"verified": "✓", "not_stated": "—", "unverified": "!", "missing": "·"}

for paper in papers:
    with st.container(border=True):
        title = paper["title"] or paper["work_id"]
        if paper["source_url"]:
            st.markdown(f"#### [{title}]({paper['source_url']})")
        else:
            st.markdown(f"#### {title}")
        st.caption(f"{paper['year'] or 'year unknown'} &middot; not in the evaluation corpus")

        grid = st.columns(4)
        for col, field in zip(grid, FIELDS):
            f = paper[field]
            with col:
                st.markdown(f"**{field}** {STATUS_ICON.get(f['status'], '')}")
                if f["status"] == "verified":
                    st.write(f["value"])
                    st.caption(f["quote"])
                elif f["status"] == "not_stated":
                    st.caption("Not stated")
                elif f["status"] == "unverified":
                    st.caption("Proposed but unverified -- withheld")
                else:
                    st.caption("—")

        gap = paper["gap"]
        if gap["status"] == "gap_stated":
            st.markdown(f"**Research gap:** {gap['quote']}")
        elif gap["status"] == "not_stated":
            st.caption("No research gap stated in the abstract.")
        else:
            st.caption("Gap check unverified.")
