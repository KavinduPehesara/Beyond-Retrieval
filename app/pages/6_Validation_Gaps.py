"""Gap Discovery -- statements where a paper's own abstract says something
is unknown, limited, or needs further research, with the rating on each:
whether it's a real gap, and if so, whether it's still open or already
filled by the same paper.
"""

from __future__ import annotations

import plots
import streamlit as st
from api_client import charts_gaps, health, list_gaps, list_reviews

st.set_page_config(page_title="Validation \u00b7 Gaps", page_icon="\U0001f9e9", layout="wide")
from research_style import apply_research_style
apply_research_style()
st.title("Validation \u2014 research gaps")
st.info(
    "**This is validation evidence, not the tool.** These six systematic reviews were completed "
    "years ago by other research teams, and their correct answers were published. Running the "
    "pipeline over them is how every figure in this project is checked \u2014 including where it "
    "does badly. To use the tool on your own topic, go to **Run a review**.",
    icon="\U0001f9ea",
)
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

# ---------------------------------------------------------------------------
# The two charts that keep this feature honestly described: how often a gap
# is stated at all, and precision next to recall rather than instead of it.
# ---------------------------------------------------------------------------

st.divider()
try:
    gap_charts = charts_gaps()
except Exception as exc:
    st.warning(f"Charts unavailable: {exc}")
else:
    st.subheader("How often an abstract states a gap")
    st.caption(
        "Ordered by inclusion rate, and the point is that there's no trend: the rate swings from "
        "3.8% to 52% and tracks the *genre* of the abstract, not the review's class balance. "
        "Menon_2022's records are themselves systematic reviews, whose conclusions nearly always "
        "end \"further studies are needed\"; software-engineering abstracts rarely state a gap at all."
    )
    st.altair_chart(plots.gap_rate_bars(gap_charts["rates"]), use_container_width=True)

    st.subheader("Precision and recall together")
    st.caption(
        "**Read these two bars as a pair — either one alone misrepresents the feature.** "
        "When this system flags a gap it is usually a real one (precision, blue). But it misses "
        "a lot of the gaps that are there (recall, orange), especially *motivating* gaps — "
        "\"little is known about…\" — which the prompt suppresses because they read like the "
        "paper's own aim. So: a usable surfacer of stated gaps, not a claim of coverage."
    )
    st.altair_chart(
        plots.gap_precision_recall_bars(gap_charts["precision_vs_recall"]),
        use_container_width=True,
    )
    st.caption(
        f"Precision is live, from each review's gap run. Recall is a one-off blind-labelling "
        f"measurement (`{gap_charts['recall_source']}`) on a seeded sample of ten `not_stated` "
        "records per review — ten is a small sample and every interval around it is wide, so read "
        "the orange bars as direction, not as figures to quote. Two reviews have too few records "
        "to sample and show no recall bar rather than a borrowed one."
    )

st.divider()

if not gaps:
    st.info(f"No abstract among {review}'s included papers states a research gap.")
    st.stop()

st.subheader(f"Every statement found in {review}")

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
