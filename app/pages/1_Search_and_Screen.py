"""Search & Screen -- run a real query against a review, then watch the
model decide on a handful of records live, with the quote it's staking the
decision on. This is the page the "someone other than the author completes
a query unassisted" exit test runs on.
"""

from __future__ import annotations

import streamlit as st
from api_client import health, list_reviews, query_rank, query_screen, review_criteria

st.set_page_config(page_title="Search & Screen", page_icon="\U0001f50d", layout="wide")
st.title("Search & Screen")

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
