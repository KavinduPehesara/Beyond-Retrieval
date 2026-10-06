"""Run a Review -- the product path, end to end, on live literature.

A topic and a set of eligibility criteria go in; what comes back is a
screening decision per paper with the quote it rests on, extracted fields
for the papers that were kept, and any research gap their authors stated.

This is the same pipeline as the evaluation path, not a demo of it: the
same `screen_v1` prompt, the same shape validation, the same span verifier.
What it does *not* have is ground truth, because nobody has published an
answer sheet for a topic typed in a minute ago. So there is no recall,
precision or accuracy here, and this page does not pretend otherwise -- it
reports what was found and what verified, and points at the validation
pages for the question "how often is it right?".

Nothing on this page is written to the `work` table or read by
`report_tables.py`. Discovered records carry review="_discover".
"""

from __future__ import annotations

import httpx
import streamlit as st
from api_client import discover, health

st.set_page_config(page_title="Run a Review", page_icon="\U0001f50d", layout="wide")

st.title("Run a review")
st.caption(
    "Search live literature on your own topic, screen it against your own criteria, "
    "and check every decision against the sentence it was based on."
)

if not health():
    st.error("Can't reach the API. Start it with `uvicorn slr.api.app:app`.")
    st.stop()

# Home writes the topic here when someone searches from the front page, so
# arriving with a topic already typed skips straight to the criteria.
prefill = st.session_state.pop("pending_topic", "")

with st.form("review_form"):
    topic = st.text_input(
        "What are you researching?",
        value=prefill,
        placeholder="e.g. hormone therapy and cardiovascular outcomes",
    )
    criteria = st.text_area(
        "Which papers should be included?",
        height=120,
        placeholder=(
            "e.g. Include randomised controlled trials in post-menopausal women that report "
            "cardiovascular outcomes and include a comparison group of non-users. Exclude "
            "animal studies, reviews, and studies in risk-selected populations."
        ),
        help=(
            "Your eligibility criteria, in plain sentences. Every include or exclude is judged "
            "against this text and nothing else. Leave it empty to search and extract without "
            "screening — the system will not invent an include/exclude with no criteria to "
            "judge against."
        ),
    )
    limit = st.slider("Papers to check", min_value=1, max_value=10, value=5)
    # On its own row rather than beside the slider: in a narrow window a
    # side-by-side column squeezed this off-screen, and an option nobody can
    # see is an option that does not exist.
    fulltext = st.checkbox(
        "Also read the full paper, not just the abstract",
        help=(
            "Looks each paper up in Europe PMC and reads its body text, which makes "
            "effect sizes, statistical methods and the authors' stated limitations "
            "reachable, and pulls tables and equations straight out of the "
            "publisher's file. Slower, and only works for open-access papers — "
            "Europe PMC is life sciences, so coverage outside medicine is thin."
        ),
    )
    st.caption(
        "Full text is opt-in because most papers don't have it: Europe PMC holds the "
        "open-access subset of life-sciences literature, so expect several papers to come "
        "back “paywalled” or “not indexed”. That's the honest coverage limit, not a fault."
    )
    submitted = st.form_submit_button("Run review", type="primary")

if submitted and not topic.strip():
    st.warning("Type a topic to search for.")
    st.stop()

if submitted:
    screening = bool(criteria.strip())
    spinner = (
        f"Searching, then screening up to {limit} papers against your criteria..."
        if screening
        else f"Searching, then checking up to {limit} papers..."
    )
    if fulltext:
        spinner += " Reading full text where it's available, which takes longer."
    with st.spinner(spinner):
        try:
            st.session_state["session"] = discover(
                topic,
                limit=limit,
                criteria=criteria.strip() or None,
                fulltext=fulltext,
            )
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 502:
                st.error("Couldn't reach OpenAlex. Check your internet connection and try again.")
            elif exc.response.status_code == 409:
                st.error(
                    "A cached response didn't match this request, so the run was stopped rather "
                    "than served something stale. This is the cache guard doing its job; "
                    "re-running should resolve it."
                )
            else:
                st.error(f"Request failed: {exc.response.text}")
            st.stop()
        except httpx.HTTPError:
            st.error("The model didn't respond in time. Is Ollama running?")
            st.stop()

session = st.session_state.get("session")

if not session:
    st.info(
        "Searches OpenAlex live — free, no key needed — then runs each result through the local "
        "model for screening, extraction and gap-checking. Needs Ollama running "
        "(`ollama pull qwen2.5:7b-instruct`)."
    )
    st.markdown(
        "**What you'll get back, per paper:** a keep-or-drop decision, the exact sentence it was "
        "based on, whether that sentence was found verbatim in the abstract, and — for the papers "
        "kept — study design, sample size, country, key finding, and any research gap the authors "
        "stated themselves."
    )
    st.stop()

papers = session["papers"]
if not papers:
    st.warning(
        "No results had an abstract available to check. OpenAlex can only redistribute abstracts "
        "for roughly half of what it indexes, so the system filtered out the rest rather than "
        "guessing from a title alone. Try different wording."
    )
    st.stop()

# ---------------------------------------------------------------------------
# What this session produced. Counts, not accuracy -- see the module docstring.
# ---------------------------------------------------------------------------

if session["criteria"]:
    m = st.columns(5)
    m[0].metric("Papers found", session["n_found"])
    m[1].metric("Kept", session["n_included"], help="Include decisions whose quote was verified.")
    m[2].metric("Dropped", session["n_excluded"])
    m[3].metric(
        "Needs your eye",
        session["n_referred"],
        help="The model's quote wasn't found in the abstract, so its decision is a referral, not an answer.",
    )
    m[4].metric("Gaps found", session["n_gaps"])
    if session["n_referred"]:
        st.info(
            f"**{session['n_referred']} of {session['n_screened']} came back as a referral.** "
            "The model proposed a decision but the sentence it quoted wasn't in the abstract, so "
            "the decision was withheld rather than shown to you as an answer. That is the "
            "intended behaviour: a paper you have to read yourself is a better outcome than a "
            "confident decision resting on a sentence nobody wrote."
        )
else:
    m = st.columns(2)
    m[0].metric("Papers found", session["n_found"])
    m[1].metric("Gaps found", session["n_gaps"])
    st.info(
        "No criteria given, so nothing was screened — every paper was extracted and gap-checked "
        "instead. Add criteria above to get keep/drop decisions."
    )

st.divider()

FIELDS = ["study_design", "sample_size", "country", "key_finding"]
FIELD_LABEL = {
    "study_design": "Study design",
    "sample_size": "Sample size",
    "country": "Country",
    "key_finding": "Key finding",
}
DECISION_BADGE = {
    "include": ("\U0001f7e2", "Keep"),
    "exclude": ("\U0001f534", "Drop"),
    "unverified": ("\U0001f7e1", "Needs your eye"),
    "error": ("⚪", "No usable answer"),
}


FULLTEXT_FIELDS = [
    ("primary_outcome", "Main result"),
    ("effect_size", "Effect size"),
    ("statistical_methods", "Statistical method"),
    ("sample_characteristics", "Sample"),
    ("limitations", "Limitations the authors state"),
]


def _render_full_text(paper: dict) -> None:
    """The full-text section, if this paper had one.

    Two blocks, kept visually apart because they are different kinds of
    claim. The five fields are what a model read and are shown with their
    quotes, withheld when the quote didn't verify. Tables and equations
    came out of the publisher's own file with no model involved, so they
    carry no verification badge -- there is nothing to verify.
    """
    note = paper.get("fulltext_note") or ""
    has_fields = any(paper.get(name) for name, _ in FULLTEXT_FIELDS)
    tables = paper.get("tables") or []
    equations = paper.get("equations") or []
    figures = paper.get("figures") or []

    if not (has_fields or tables or equations or figures):
        if note:
            st.caption(f"Full text: {note}")
        return

    with st.expander("From the full paper", expanded=False):
        if note:
            st.caption(note)

        for name, label in FULLTEXT_FIELDS:
            value = paper.get(name)
            if not value:
                continue
            if value["status"] == "verified":
                st.markdown(f"**{label}:** {value['value']}")
                st.caption(f"“{value['quote']}”")
            elif value["status"] == "not_stated":
                st.markdown(f"**{label}:** the paper doesn't state this")
            elif value["status"] == "unverified":
                st.markdown(f"**{label}:** withheld")
                st.caption(
                    "The model proposed an answer but the sentence it quoted wasn't found "
                    "in the paper, so the value isn't shown."
                )

        if tables:
            st.markdown(f"**Tables ({len(tables)})**")
            st.caption(
                "Read straight from the publisher's file. No model was involved, so these "
                "are exact — there is nothing here that could have been invented."
            )
            for table in tables:
                heading = " · ".join(x for x in (table.get("label"), table.get("caption")) if x)
                if heading:
                    st.markdown(f"*{heading}*")
                rows = table.get("rows") or []
                if len(rows) > 1:
                    st.dataframe(rows[1:], hide_index=True, use_container_width=True)
                elif rows:
                    st.dataframe(rows, hide_index=True, use_container_width=True)

        if equations:
            st.markdown(f"**Equations ({len(equations)})**")
            for equation in equations[:10]:
                st.code(equation, language=None)

        if figures:
            st.markdown(f"**Figures ({len(figures)})**")
            st.caption(
                "Captions only. The images themselves are not fetched or interpreted — "
                "reading what a chart or heat map *shows* would need image analysis, which "
                "this system does not do."
            )
            for figure in figures[:10]:
                bits = " · ".join(
                    x for x in (figure.get("label"), figure.get("caption")) if x
                )
                if bits:
                    st.caption(bits)


def _order(paper: dict) -> tuple:
    """Kept papers first, then referrals, then dropped.

    The same priority a reviewer actually works in: read what the system
    kept, then deal with what it couldn't answer, and only then check what
    it discarded.
    """
    d = paper.get("decision")
    if not d:
        return (0, paper["title"] or "")
    if d["status"] == "include" and d["span_verified"]:
        return (0, paper["title"] or "")
    if not d["span_verified"]:
        return (1, paper["title"] or "")
    return (2, paper["title"] or "")


for paper in sorted(papers, key=_order):
    decision = paper.get("decision")
    with st.container(border=True):
        title = paper["title"] or paper["work_id"]
        if decision:
            icon, label = DECISION_BADGE.get(decision["status"], ("⚪", decision["status"]))
            # An include whose quote didn't verify is not a keep.
            if decision["status"] == "include" and not decision["span_verified"]:
                icon, label = DECISION_BADGE["unverified"]
            st.markdown(f"#### {icon} {label} — {title}")
        else:
            st.markdown(f"#### {title}")

        bits = [str(paper["year"]) if paper["year"] else "year unknown"]
        if paper["source_url"]:
            bits.append(f"[view paper]({paper['source_url']})")
        st.caption(" · ".join(bits))

        if decision:
            with st.expander("Why — and how to check it", expanded=bool(decision["span_verified"])):
                cols = st.columns([1, 1, 2])
                cols[0].metric(
                    "Model's confidence",
                    f"{decision['confidence']:.2f}" if decision["confidence"] is not None else "n/a",
                )
                cols[1].metric("Quote found in abstract", "Yes" if decision["span_verified"] else "No")
                cols[2].caption(
                    f"`{decision['verify_note']}`"
                    + (" · served from cache" if decision["from_cache"] else " · fresh model call")
                )
                if decision["quote"]:
                    st.markdown(f"> {decision['quote']}")
                if decision["span_verified"]:
                    st.caption(
                        "This sentence was found word-for-word in the paper's own abstract. "
                        "Open the paper and search for it."
                    )
                else:
                    st.caption(
                        "This sentence was **not** found in the abstract — the model either "
                        "paraphrased or invented it. The decision is withheld for that reason. "
                        "Read this one yourself."
                    )
                st.caption(
                    "Note what verification does and doesn't prove: it confirms the sentence is "
                    "real, not that it supports the criterion it was attached to. A real quote "
                    "can still back the wrong call — which is why you, not the system, decide."
                )

        if paper.get("study_design") is None:
            if decision and not decision["span_verified"]:
                st.caption("Not extracted — the screening decision was referred to you first.")
            elif decision:
                st.caption("Not extracted — this paper doesn't meet your criteria.")
            continue

        grid = st.columns(4)
        for col, field in zip(grid, FIELDS):
            f = paper[field]
            with col:
                st.markdown(f"**{FIELD_LABEL[field]}**")
                if f["status"] == "verified":
                    st.write(f["value"])
                    st.caption(f"“{f['quote']}”")
                elif f["status"] == "not_stated":
                    st.caption("The abstract doesn't say")
                elif f["status"] == "unverified":
                    st.caption("Proposed but not found in the abstract — withheld")
                else:
                    st.caption("—")

        gap = paper.get("gap")
        if gap and gap["status"] == "gap_stated":
            st.markdown(f"**Research gap the authors state:** “{gap['quote']}”")
        elif gap and gap["status"] == "not_stated":
            st.caption("No research gap stated in the abstract.")
        elif gap:
            st.caption("Gap check returned nothing usable.")

        _render_full_text(paper)

st.divider()
st.caption(
    "**How much should you trust this?** Nothing on this page is scored, because there is no "
    "published answer sheet for a topic you just typed. The measured figures live under the "
    "validation pages, where the same pipeline was run over 12,598 papers whose correct answers "
    "*were* already known — including where it does badly."
)
