"""Search & Screen -- run a real query against a review, then watch the
model decide on a handful of records live, with the quote it's staking the
decision on. This is the page the "someone other than the author completes
a query unassisted" exit test runs on.
"""

from __future__ import annotations

import plots
import streamlit as st
from api_client import (
    charts_recall_curve,
    charts_semantic_map,
    health,
    list_reviews,
    query_rank,
    query_screen,
    review_criteria,
)

st.set_page_config(page_title="Validation \u00b7 Screening", page_icon="\U0001f9ea", layout="wide")
from research_style import apply_research_style
apply_research_style()
st.title("Validation \u2014 screening the test reviews")
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

reviews = list_reviews()
review_names = [r["review"] for r in reviews]

STRATEGY_HELP = {
    "bm25": "Lexical match against your query text. Fast, no model needed.",
    "dense": "SPECTER2 embedding similarity. Finds conceptual matches BM25 misses.",
    "hybrid": "BM25 and dense combined by reciprocal rank fusion.",
    "rerank": "Hybrid, then a cross-encoder re-orders the top 200.",
    "random": "No ranking at all -- a baseline to compare the others against.",
}

with st.form("query_form"):
    c1, c2 = st.columns([2, 1])
    with c1:
        review = st.selectbox("Review", review_names, help="Which of the six reviews to search.")
    with c2:
        strategy = st.selectbox("Strategy", list(STRATEGY_HELP), index=0)
    st.caption(STRATEGY_HELP[strategy])

    default_query = ""
    if strategy != "random":
        try:
            default_query = review_criteria(review)["text"]
        except Exception:
            default_query = ""
    query_text = st.text_area(
        "Query",
        value=default_query,
        height=100,
        disabled=strategy == "random",
        help="Defaults to the review's own published inclusion criteria. Edit it to search for something else.",
    )
    top_n = st.slider("Candidates to return", min_value=5, max_value=100, value=20)
    ranked = st.form_submit_button("Rank", type="primary")

if ranked:
    with st.spinner(f"Ranking {review} by {strategy}..."):
        st.session_state["ranked"] = query_rank(review, strategy, query_text or None, top_n)
        st.session_state["ranked_review"] = review
        st.session_state["screened"] = {}

results = st.session_state.get("ranked")
if results and st.session_state.get("ranked_review") == review:
    st.subheader(f"{len(results)} candidates")
    st.dataframe(
        [{"Rank": r["rank"], "Title": r["title"] or "(no title)", "Year": r["year"]} for r in results],
        hide_index=True,
        use_container_width=True,
        height=min(38 * (len(results) + 1), 420),
    )

    st.subheader("Screen a few live")
    st.caption(
        "Pick up to 15 candidates above to screen right now, on the local model. Each one gets a "
        "real decision, a confidence score, and a quote checked against the abstract before it's shown."
    )
    options = {f"#{r['rank']} · {(r['title'] or r['work_id'])[:80]}": r["work_id"] for r in results[:top_n]}
    picked_labels = st.multiselect("Candidates to screen", list(options), max_selections=15)
    go = st.button("Screen selected", disabled=not picked_labels)

    if go:
        work_ids = [options[label] for label in picked_labels]
        with st.spinner(f"Screening {len(work_ids)} record(s) on qwen2.5:7b-instruct..."):
            try:
                st.session_state["screened"] = {
                    r["work_id"]: r for r in query_screen(review, work_ids, "qwen2.5:7b-instruct", "screen_v1")
                }
            except Exception as exc:  # Ollama unreachable, etc. -- surfaced, not swallowed
                st.error(f"Screening failed: {exc}")

    screened = st.session_state.get("screened") or {}
    if screened:
        st.subheader("Decisions")
        for r in results:
            wid = r["work_id"]
            if wid not in screened:
                continue
            s = screened[wid]
            badge = {"include": "\U0001f7e2", "exclude": "\U0001f534", "unverified": "\U0001f7e1", "error": "⚪"}.get(s["decision"], "⚪")
            with st.expander(f"{badge} **{s['decision']}** — {(r['title'] or wid)[:100]}", expanded=True):
                cols = st.columns([1, 1, 2])
                cols[0].metric("Confidence", f"{s['confidence']:.2f}" if s["confidence"] is not None else "n/a")
                cols[1].metric("Quote verified", "Yes" if s["span_verified"] else "No")
                cols[2].caption(f"verify_note: `{s['verify_note']}`" + (" · served from cache" if s["from_cache"] else " · live call"))
                if s["quote"]:
                    st.markdown(f"> {s['quote']}")
                else:
                    st.caption("No quote returned.")
                if not s["span_verified"]:
                    st.caption(
                        "Not found verbatim in the source, so this decision is a referral, not a prediction -- "
                        "see it under Results & Override."
                    )
else:
    st.info("Choose a review and strategy, then **Rank** to see candidates.")

# ---------------------------------------------------------------------------
# How much reading does the ordering actually save? The live query above
# returns the top N; this is the whole review, from its recorded screening
# run. Shown regardless of whether a query has been submitted, because it's
# the context that makes the ranking above mean something.
# ---------------------------------------------------------------------------

st.divider()
st.subheader("How much reading this saves")
try:
    curve = charts_recall_curve(review)
except Exception as exc:
    st.caption(f"No screening run for {review} yet, so there's no curve to draw. ({exc})")
else:
    st.caption(
        "Read down the ranking and this is how fast you find the papers that belong in the "
        "review. The grey diagonal is what you'd get screening in no particular order — the "
        "gap between the two lines *is* the saving. The dashed lines mark 95% recall, the "
        "point every reported figure in this project is measured at."
    )
    st.altair_chart(plots.recall_curve(curve), use_container_width=True)

    cols = st.columns(4)
    cols[0].metric("Records", f"{curve['n_ranked']:,}")
    cols[1].metric("Included", f"{curve['n_included']:,}")
    if curve["cutoff_95"]:
        read = curve["cutoff_95"]
        cols[2].metric("Read to reach 95%", f"{read:,}")
        cols[3].metric(
            "Of the review",
            f"{read / curve['n_ranked']:.0%}",
            help="Screening in a random order would need about 95% of it.",
        )
    st.caption(
        f"Ordering: {curve['strategy']} — verified includes by confidence, then everything "
        "referred to a human, then verified excludes. The same ordering this review's reported "
        "TNR@95 is computed on, so this curve and that number cannot disagree."
    )

# ---------------------------------------------------------------------------
# The shape of the review, from the embeddings dense retrieval already
# cached. Only available for reviews a dense/hybrid config has been run on.
# ---------------------------------------------------------------------------

with st.expander("See the shape of this review"):
    try:
        smap = charts_semantic_map(review, max_points=1200)
    except Exception as exc:
        st.caption(f"Map unavailable: {exc}")
    else:
        if not smap["available"]:
            st.caption(
                f"No semantic map for {review}: {smap['reason']}. Embeddings are computed and "
                "cached the first time a `dense`, `hybrid` or `rerank` config runs on a review."
            )
        else:
            st.caption(
                "Every paper placed by what it's *about*, not by keyword. Each point is one "
                "record; blue ones belong in the review. This is the SPECTER2 embedding space "
                "flattened to two dimensions by PCA — a linear projection, so distance here is "
                "real distance projected, not a neighbour-preserving distortion. "
                f"Those two dimensions carry {smap['variance_explained']:.0%} of the variation, "
                "so clusters that look separate may overlap in the full 768 dimensions."
            )
            st.altair_chart(plots.semantic_scatter(smap), use_container_width=True)
            note = f"{smap['n_plotted']:,} of {smap['n_total']:,} records plotted"
            if smap["downsampled"]:
                note += " — excluded records sampled to keep the chart readable; every included record is shown"
            st.caption(note + ".")
