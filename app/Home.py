"""Beyond Retrieval -- the front door.

Deliberately a search box rather than a table of the six test reviews. The
six reviews are how this project proves its figures; they are not what the
tool is for, and leading with them made the tool look like a report about
six old medical reviews. So the first thing on screen asks the question a
researcher actually arrives with, and the validation evidence sits one
click away under its own clearly-labelled pages.

Nothing here computes a figure. Every number comes from the API, which
reads a run directory or the live database.
"""

from __future__ import annotations

import streamlit as st
from api_client import API_URL, charts_corpus, health, list_reviews

st.set_page_config(page_title="Beyond Retrieval", page_icon="\U0001f4da", layout="wide")

st.title("Beyond Retrieval")
st.markdown("#### Find the papers that matter, and check every decision for yourself.")

if not health():
    st.error(
        f"Can't reach the API at `{API_URL}`. Start it first:\n\n"
        "```\nuvicorn slr.api.app:app\n```"
    )
    st.stop()

# ---------------------------------------------------------------------------
# The front door. Typing a topic here hands it to Run a review, which asks
# for the eligibility criteria -- two short steps rather than one long form,
# because the topic is the thing people arrive already knowing.
# ---------------------------------------------------------------------------

with st.form("start"):
    topic = st.text_input(
        "What are you researching?",
        placeholder="e.g. machine learning for crop disease detection",
        label_visibility="visible",
    )
    started = st.form_submit_button("Start a review", type="primary")

if started:
    if not topic.strip():
        st.warning("Type a topic to get started.")
    else:
        st.session_state["pending_topic"] = topic.strip()
        st.switch_page("pages/1_Run_a_Review.py")

st.caption(
    "Searches live academic literature, screens it against criteria you write, pulls out the "
    "study details, and flags the research gaps authors state themselves — showing you the "
    "exact sentence behind every answer."
)

st.divider()

st.subheader("What it does")
c1, c2, c3 = st.columns(3)
with c1:
    st.markdown(
        "**1 · Searches and sorts**\n\n"
        "Finds candidate papers on your topic and puts the ones most likely to matter first, "
        "so the reading you skip is the reading least likely to be relevant."
    )
with c2:
    st.markdown(
        "**2 · Screens against your criteria**\n\n"
        "You write what counts as relevant, in plain sentences. Every keep-or-drop decision is "
        "judged against that and nothing else."
    )
with c3:
    st.markdown(
        "**3 · Shows its working**\n\n"
        "Each decision comes with the sentence it rests on, checked word-for-word against the "
        "paper's abstract. If that check fails, the decision is withheld rather than shown."
    )

st.divider()

# ---------------------------------------------------------------------------
# The evidence, summarised honestly and in one place. This is the section
# that used to be the whole landing page.
# ---------------------------------------------------------------------------

st.subheader("Why you should believe any of it")
st.markdown(
    "Any tool can produce confident-looking answers. The only reason to trust this one is that "
    "it has been run over literature where the right answers were already known and published — "
    "**six completed systematic reviews, 12,598 papers, 351 of which the original human "
    "reviewers kept.** Every figure in this project comes from that exercise, and the pages "
    "under *Validation* show it, including the parts that went badly."
)

try:
    reviews = list_reviews()
    corpus = charts_corpus()
except Exception as exc:
    st.warning(f"Couldn't load the validation summary: {exc}")
else:
    totals = corpus["prevalence"]
    e1, e2, e3, e4 = st.columns(4)
    e1.metric("Test reviews", len(totals))
    e2.metric("Papers screened", f"{sum(r['n'] for r in totals):,}")
    e3.metric("Correct answers known", f"{sum(r['included'] for r in totals):,}")
    if totals:
        lo = min(r["prevalence"] for r in totals)
        hi = max(r["prevalence"] for r in totals)
        e4.metric(
            "Difficulty range",
            f"{lo * 100:.1f}%–{hi * 100:.1f}%",
            help=(
                "The share of papers actually worth keeping, per review. Chosen to span easy to "
                "very hard on purpose: a screening tool looks far better on a review where one "
                "paper in five is a keeper than on one where it's one in 125."
            ),
        )

    not_screened = [r["review"] for r in reviews if not r["screen_run"]]
    if not_screened:
        st.warning("Not yet screened: " + ", ".join(not_screened))

    st.caption(
        "**The honest headline:** the system reliably refuses to assert what it can't back with a "
        "real quote, and that is the property this project set out to build. It does *not* hit the "
        "99% verification target the proposal set, it finds roughly half the research gaps that "
        "are actually stated, and a dedicated active-learning tool out-ranks it on every review "
        "where the two can be compared. All three are on the validation pages with numbers."
    )

with st.expander("What a “test review” is, if you're not a researcher"):
    st.markdown(
        "A systematic review is what researchers do when they want to answer a question properly: "
        "search the databases, get back a few thousand papers that *might* be relevant, then have "
        "two people read every title and abstract and decide one by one what stays. It takes "
        "weeks, and it is the part this tool is trying to help with.\n\n"
        "The six reviews here were all completed years ago by other research teams, who published "
        "their answer sheets — the exact list of which papers they kept. So the same papers can "
        "be handed to this system, and its answers compared with theirs. **The right answer is "
        "already known, which is what makes the result a measurement rather than a claim.**\n\n"
        "A researcher using the finished tool would never see these six. They'd type their own "
        "topic on this page. The six are the crash-test dummies, not the car."
    )

st.divider()
st.caption(
    f"API: `{API_URL}` · Runs on a local model, so every figure on this dashboard cost $0. "
    "MSE907 capstone — Pehesara Gunawardena."
)
