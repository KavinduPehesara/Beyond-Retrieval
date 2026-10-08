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
from api_client import discover, discover_fulltext, health, read_live_session
from fulltext_view import render_categories
from live_workspace import render_workspace, render_reviewer, eligible_for_fulltext

st.set_page_config(page_title="Run a Review", page_icon="\U0001f50d", layout="wide")
from research_style import apply_research_style
apply_research_style()
from account_view import render_account, render_library
render_account()

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
    expand_query = st.checkbox(
        "Let the model add search terms",
        value=False,
        help=(
            "Asks the model for synonyms and technical equivalents of your words, and "
            "searches with those as well. Measured over the six test reviews it helped on "
            "three and hurt on three, so it is off unless you ask for it. The terms it "
            "added are always shown."
        ),
    )
    st.caption(
        "This first pass reads titles and abstracts only, which is how the first stage of "
        "a systematic review works. Once you've seen what came back, you pick the papers "
        "worth reading in full."
    )
    submitted = st.form_submit_button("Screen these papers", type="primary")

if submitted and not topic.strip():
    st.warning("Type a topic to search for.")
    st.stop()

render_library()

if submitted and st.session_state.get("google_account") and not st.session_state.get("active_project"):
    st.warning("Create or open a named research project above before starting your research.")
    st.stop()

if submitted:
    screening = bool(criteria.strip())
    spinner = (
        f"Searching, then screening up to {limit} papers against your criteria..."
        if screening
        else f"Searching, then checking up to {limit} papers..."
    )
    with st.spinner(spinner):
        try:
            st.session_state["session"] = discover(
                topic,
                limit=limit,
                criteria=criteria.strip() or None,
                expand=expand_query,
            )
            # A new screening run invalidates any full text from the last one.
            st.session_state.pop("fulltext", None)
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

# What the model added to the search, if it was asked. Shown rather than
# applied quietly: these are the model's words, not the researcher's, and a
# term that pulled the search into the wrong field should be visible.
_expansion = session.get("expansion")
if _expansion and _expansion.get("terms"):
    st.caption(
        "Searched with your words plus terms the model suggested: "
        + ", ".join(f"*{term}*" for term in _expansion["terms"])
    )
elif _expansion:
    st.caption("The model suggested no extra search terms, so your query was searched as typed.")

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


def _value_repeats_quote(value: str | None, quote: str | None) -> bool:
    """True when the extracted value is just the quoted sentence again.

    Asked for a sample size, the model sometimes answers with the whole
    sentence it quoted rather than the number inside it. Nothing in that is
    false, but printing the sentence as a value and again as its own
    evidence claims a precision the answer does not have. Shown once, as a
    quote, it says exactly as much and claims no more.
    """

    def flat(text: str | None) -> str:
        return " ".join((text or "").split()).casefold().strip(" .“”\"'")

    return bool(value) and flat(value) == flat(quote)


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
    if paper.get("coverage"):
        render_categories(paper)
        return
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
                if _value_repeats_quote(value["value"], value["quote"]):
                    st.markdown(f"**{label}:** stated only as a sentence, not as a value")
                else:
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
                "The images are not fetched or interpreted — reading what a chart or heat map "
                "*shows* would need image analysis, which this system does not do. What you get "
                "instead is the caption, plus the sentences where the authors describe the "
                "figure themselves. Those are real text and can be checked against the paper."
            )
            for figure in figures[:10]:
                bits = " · ".join(
                    x for x in (figure.get("label"), figure.get("caption")) if x
                )
                if bits:
                    st.markdown(f"*{bits}*")
                mentions = figure.get("mentions") or []
                for mention in mentions:
                    st.caption(f"“{mention}”")
                if not mentions and figure.get("label"):
                    st.caption("No sentence in the body cites this figure by name.")
                elif not mentions:
                    st.caption(
                        "This figure has no label in the publisher's file, so sentences citing "
                        "it cannot be matched — a gap in the source, not evidence that the "
                        "authors never mention it."
                    )


def _order(paper: dict) -> tuple:
    """Kept papers first and strongest first, then referrals, then dropped.

    Two levels of sorting, and the second one matters once there are more
    than a handful of results. The first is the order a reviewer actually
    works in: read what the system kept, then deal with what it couldn't
    answer, and only then check what it discarded.

    Within the kept group, order by the model's own confidence, highest
    first. That turns an undifferentiated pile of "kept" into a queue: the
    strongest matches are the ones to read first, and a reviewer running
    out of time has stopped at the right end of the list rather than an
    arbitrary one.

    This is a *predicted* relevance, not a measured one. The system has
    read an abstract, nothing more, and the ranking is only as good as that
    prediction -- which is exactly what the recall curve on the validation
    pages measures. It prioritises; it does not absolve anyone of looking.
    """
    d = paper.get("decision")
    if not d:
        return (0, 0.0, paper["title"] or "")
    confidence = d.get("confidence") or 0.0
    if d["status"] == "include" and d["span_verified"]:
        return (0, -confidence, paper["title"] or "")
    if not d["span_verified"]:
        return (1, -confidence, paper["title"] or "")
    return (2, confidence, paper["title"] or "")


_ranked = sorted(papers, key=_order)
# Rank numbers run over the kept papers only -- numbering a dropped paper
# "7th most relevant" would be meaningless.
_kept_ids = [
    p["work_id"]
    for p in _ranked
    if p.get("decision")
    and p["decision"]["status"] == "include"
    and p["decision"]["span_verified"]
]
_rank_of = {work_id: i + 1 for i, work_id in enumerate(_kept_ids)}

if len(_kept_ids) > 1:
    st.caption(
        f"The {len(_kept_ids)} papers it kept are listed strongest first, by how confident "
        "the model was in its own decision. That is a prediction from an abstract, not a "
        "measurement — it tells you where to start reading, not which papers are definitely "
        "right."
    )

_reviewer_latest = render_workspace(session)

for paper in _ranked:
    decision = paper.get("decision")
    with st.container(border=True):
        title = paper["title"] or paper["work_id"]
        if decision:
            icon, label = DECISION_BADGE.get(decision["status"], ("⚪", decision["status"]))
            # An include whose quote didn't verify is not a keep.
            if decision["status"] == "include" and not decision["span_verified"]:
                icon, label = DECISION_BADGE["unverified"]
            rank = _rank_of.get(paper["work_id"])
            prefix = f"#{rank} · " if rank else ""
            st.markdown(f"#### {prefix}{icon} {label} — {title}")
        else:
            st.markdown(f"#### {title}")

        bits = [str(paper["year"]) if paper["year"] else "year unknown"]
        if paper["source_url"]:
            bits.append(f"[view paper]({paper['source_url']})")
        st.caption(" · ".join(bits))
        _human = _reviewer_latest.get(paper["work_id"], {})
        if _human.get("decision") in ("include", "exclude"):
            st.markdown(f"**Researcher decision: {_human['decision'].title()}**")
            if _human.get("rationale"):
                st.text(_human["rationale"])

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

        render_reviewer(paper, session, _reviewer_latest)

        if paper.get("study_design") is None:
            if _human.get("decision") == "include":
                st.caption("Included by the researcher. Abstract extraction was not run after the model's original decision; you can select this paper for full-text review below.")
            elif decision and not decision["span_verified"]:
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
                    if _value_repeats_quote(f["value"], f["quote"]):
                        st.caption("Stated only as a sentence, not as a value:")
                    else:
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

# ---------------------------------------------------------------------------
# Stage two. Screening on abstracts narrows the field; the reviewer decides
# which survivors are worth the deeper read, and only those get fetched.
# That is PRISMA's own two-stage shape, and it is the sensible one here too:
# full text costs a lookup, a download and a long model call per paper, and
# most papers will not have it at all.
# ---------------------------------------------------------------------------

st.divider()
st.subheader("Read the full paper")

_candidates = [
    p
    for p in papers
    if eligible_for_fulltext(p, _reviewer_latest)
]

if not _candidates:
    st.caption(
        "Nothing was kept, so there is nothing to read in full. Loosen your criteria or try "
        "different search terms."
    )
else:
    st.caption(
        "Abstracts rarely carry effect sizes, confidence intervals, statistical methods or the "
        "authors' stated limitations — those live in the body of the paper. Pick the ones "
        "worth a deeper read. Only open-access papers held by Europe PMC can be read this way, "
        "which is mostly medicine and life sciences, so expect some to come back unavailable."
    )
    # Same order as the cards above, so "the top three" means the same
    # thing in both places.
    _candidates = sorted(_candidates, key=_order)
    _labels = {
        f"#{_rank_of[p['work_id']]} · {(p['title'] or p['work_id'])[:85]}"
        if p["work_id"] in _rank_of
        else (p["title"] or p["work_id"])[:90]: p
        for p in _candidates
    }
    _picked = st.multiselect(
        "Papers to read in full",
        list(_labels),
        max_selections=5,
        help="Each one is a lookup, a download and a model call, so start with two or three.",
    )
    if not st.session_state.get("google_account"):
        st.info("Sign in with Google to retrieve full text, then create or open a named research project.")
    elif not st.session_state.get("active_project"):
        st.info("Give this research a project name above to save your full-text results.")
    if st.button("Read these in full", disabled=not _picked or not st.session_state.get("google_account") or not st.session_state.get("active_project"), type="primary"):
        if not st.session_state.get("google_account") or not st.session_state.get("active_project"):
            st.warning("Sign in and choose a named project first.")
            st.stop()
        _targets = [
            {
                "work_id": _labels[label]["work_id"],
                "title": _labels[label]["title"],
                "doi": _labels[label].get("doi"),
            }
            for label in _picked
        ]
        with st.spinner(f"Fetching and reading {len(_targets)} paper(s)..."):
            try:
                discover_fulltext(_targets)
                st.session_state["fulltext"] = read_live_session(st.session_state["active_project"]).get("fulltext")
            except httpx.HTTPStatusError as exc:
                st.error(f"Request failed: {exc.response.text}")
            except httpx.HTTPError:
                st.error("The model didn't respond in time. Is Ollama running?")

_ft = st.session_state.get("fulltext")
if _ft:
    _found, _asked = _ft["n_with_full_text"], _ft["n_requested"]
    if _found:
        st.success(f"Full text found for {_found} of {_asked}.")
    else:
        st.warning(
            f"None of the {_asked} selected papers had open-access full text in Europe PMC. "
            "That is a coverage limit, not a failure — each paper's reason is below."
        )
    for _paper_index, _paper in enumerate(_ft["papers"]):
        with st.container(border=True):
            st.markdown(f"#### {_paper['title'] or _paper['work_id']}")
            _render_full_text(
                {
                    **_paper,
                    "fulltext_ui_key": f"stage2-{_paper_index}-{_paper['work_id']}",
                    **{name: _paper.get(name) for name, _ in FULLTEXT_FIELDS},
                    "tables": _paper.get("tables"),
                    "equations": _paper.get("equations"),
                    "figures": _paper.get("figures"),
                    "fulltext_note": _paper.get("note", ""),
                }
            )

st.divider()
st.caption(
    "**How much should you trust this?** Nothing on this page is scored, because there is no "
    "published answer sheet for a topic you just typed. The measured figures live under the "
    "validation pages, where the same pipeline was run over 12,598 papers whose correct answers "
    "*were* already known — including where it does badly."
)
