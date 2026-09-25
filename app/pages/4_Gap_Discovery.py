"""Gap Discovery -- statements where a paper's own abstract says something
is unknown, limited, or needs further research, with the rating on each:
whether it's a real gap, and if so, whether it's still open or already
filled by the same paper.
"""

from __future__ import annotations

import streamlit as st
from api_client import health, list_gaps, list_reviews

st.set_page_config(page_title="Gap Discovery", page_icon="\U0001f9e9", layout="wide")
st.title("Gap Discovery")
st.caption(
    "Precision here is one person's rating of what the model flagged, checked against the full "
    "abstract. Recall was separately estimated on a small blind sample and is well below precision -- "
    "see the Trust Dashboard."
)

if not health():
    st.error("Can't reach the API. Start it with `uvicorn slr.api.app:app`.")
    st.stop()

reviews = {r["review"]: r for r in list_reviews()}
review = st.selectbox("Review", list(reviews))
info = reviews[review]

if not info["gap_run"]:
    st.warning(f"{review} has not had gap discovery run yet.")
    st.stop()

gaps = list_gaps(review)
st.caption(f"Run `{info['gap_run']}`")

rated = [g for g in gaps if g["rating"]]
valid = [g for g in rated if g["rating"] == "valid"]
open_gaps = [g for g in valid if g["kind"] == "open"]

m1, m2, m3, m4 = st.columns(4)
m1.metric("Gap statements", len(gaps), help="Out of the review's included papers.")
m2.metric("Rated valid", f"{len(valid)}/{len(rated)}" if rated else "n/a")
m3.metric("Precision", f"{len(valid) / len(rated):.0%}" if rated else "n/a")
m4.metric("Still open", f"{len(open_gaps)}/{len(rated)}" if rated else "n/a", help="Excludes gaps the same paper goes on to fill.")

if not gaps:
    st.info(f"No abstract among {review}'s included papers states a research gap.")
    st.stop()

KIND_LABEL = {"open": "\U0001f7e6 Open gap", "motivating": "\U0001f7e8 Motivating gap"}
for g in gaps:
    if g["rating"] == "invalid":
        label = "\U0001f7e5 Not a gap"
    elif g["rating"] == "valid":
        label = KIND_LABEL.get(g["kind"], "Valid")
    else:
        label = "⚪ Unrated"
    with st.expander(f"{label} — {(g['title'] or g['work_id'])[:100]}"):
        st.markdown(f"> {g['quote']}")
