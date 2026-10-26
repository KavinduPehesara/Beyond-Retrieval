"""Beyond Retrieval -- one research question, start to finish.

1. The researcher types a question.
2. The system searches OpenAlex, ranks the candidates by closeness to the
   question, and suggests the best ones. Each comes with whether it addresses
   the question and any research gap its authors state, both backed by a
   sentence found word for word in the abstract.
3. The researcher picks the papers worth reading in full.
4. The system reads those papers and lays out what each contains, by
   category, next to how relevant it is to the question.

Nothing here computes a figure. Every value comes from the API.
"""

from __future__ import annotations

import httpx
import streamlit as st
from api_client import (
    API_URL,
    discover_fulltext,
    export_project,
    health,
    providers,
    read_live_session,
    suggest,
)
from fulltext_view import render_categories

st.set_page_config(page_title="Beyond Retrieval", page_icon="\U0001f4da", layout="wide")
from research_style import apply_research_style
top_bar = apply_research_style()
from account_view import render_account, render_library, render_welcome
# Account first: it restores a sign-in from the browser-session cookie,
# and the welcome dialog should not greet someone already signed in.
render_account(top_bar)
render_welcome()

#: The full-text route reads at most this many papers per request.
MAX_FULLTEXT = 10

FULLTEXT_FIELDS = [
    ("primary_outcome", "Main result"),
    ("effect_size", "Effect size"),
    ("statistical_methods", "Method"),
    ("sample_characteristics", "Sample"),
    ("limitations", "Limitations"),
]

RELEVANCE_BADGE = {
    "relevant": ("\U0001f7e2", "Addresses your question"),
    "check": ("\U0001f7e1", "Check it yourself"),
    "not_relevant": ("⚪", "Probably off-topic"),
}


def model_timeout_message() -> str:
    """Why a model call timed out, in terms of the model actually chosen."""
    if st.session_state.get("provider") == "ollama":
        return "The model didn't respond in time. Is Ollama running?"
    return (
        "The model didn't respond in time. Check your connection, or pick a "
        "different AI above and try again."
    )


def relevance_label(paper: dict) -> str:
    """Relevant only when the model said include *and* its quote verified."""
    d = paper.get("decision") or {}
    if not d.get("span_verified"):
        return "check"
    return "relevant" if d.get("status") == "include" else "not_relevant"


def field_text(item: dict | None) -> str:
    """One cell of the comparison table. A withheld value is never shown."""
    if not item:
        return "—"
    if item["status"] == "verified":
        return item.get("value") or "—"
    if item["status"] == "not_stated":
        return "not stated"
    return "withheld (quote not found)"


st.title("Beyond Retrieval")
st.markdown("#### Ask a research question. Get the papers worth reading, and what is in them.")

if not health():
    st.error(f"Can't reach the API at `{API_URL}`. Start it with `uvicorn slr.api.app:app`.")
    st.stop()

render_library()

# ---------------------------------------------------------------------------
# Step 1 -- the question
# ---------------------------------------------------------------------------

catalogue = providers()
usable = [p for p in catalogue.get("providers") or [] if p["configured"]]
blocked = [p for p in catalogue.get("providers") or [] if not p["configured"]]
if usable and not st.session_state.get("provider"):
    default = catalogue.get("default")
    st.session_state["provider"] = next(
        (p["key"] for p in usable if p["key"] == default), usable[0]["key"]
    )

with st.form("question"):
    question = st.text_area(
        "What is your research question?",
        height=90,
        placeholder="e.g. Does vitamin D supplementation reduce the risk of asthma attacks in children?",
    )
    if usable:
        keys = [p["key"] for p in usable]
        labels = {p["key"]: p for p in usable}
        st.session_state["provider"] = st.radio(
            "Which AI answers",
            keys,
            index=keys.index(st.session_state["provider"]) if st.session_state.get("provider") in keys else 0,
            horizontal=True,
            format_func=lambda k: f"{labels[k]['label']} ({labels[k]['model']})",
        )
    if blocked:
        st.caption(
            "Not configured here: "
            + "; ".join(f"{p['label']} — {p['note']}" for p in blocked)
        )
    n = st.slider("Papers to suggest", min_value=5, max_value=25, value=20)
    # Measured: about half a minute for 20 on a hosted model, a few minutes
    # on the local one, which is slower per call but costs nothing.
    pace = (
        "a few minutes for 20"
        if st.session_state.get("provider") == "ollama"
        else "about half a minute for 20"
    )
    st.caption(
        "Searches OpenAlex live, ranks what comes back by how close it is to your question, "
        f"then has the chosen model check the top papers. Expect {pace}."
    )
    asked = st.form_submit_button("Find papers", type="primary")

if asked:
    if not question.strip():
        st.warning("Type a research question first.")
        st.stop()
    if st.session_state.get("google_account") and not st.session_state.get("active_project"):
        st.warning("Create or open a research project above first, so the results are saved.")
        st.stop()
    with st.spinner(f"Searching and checking the {n} closest papers..."):
        try:
            st.session_state["session"] = suggest(question.strip(), n=n)
            st.session_state.pop("fulltext", None)
            st.session_state.pop("picked", None)
            st.session_state.pop("export", None)
        except httpx.HTTPStatusError as exc:
            code = exc.response.status_code
            if code == 502:
                st.error("Couldn't reach OpenAlex. Check your internet connection and try again.")
            elif code == 409:
                st.error("A cached answer didn't match this request, so the search was stopped. Try again.")
            else:
                st.error(f"Request failed: {exc.response.text}")
            st.stop()
        except httpx.HTTPError:
            st.error(model_timeout_message())
            st.stop()

session = st.session_state.get("session")
if not session:
    st.info(
        "Pick the AI that answers above, then ask a question. "
        "Full-text reading needs you to sign in and open a project."
    )
    st.stop()

papers = session.get("papers") or []
if not papers:
    st.warning(
        "No results had an abstract to check. OpenAlex can only share abstracts for about half "
        "of what it indexes. Try different wording."
    )
    st.stop()

# ---------------------------------------------------------------------------
# Step 2 -- suggestions, and whether other authors name the question as a gap
# ---------------------------------------------------------------------------

st.divider()
st.subheader(f"Suggested papers for: {session['query']}")

relevant = [p for p in papers if relevance_label(p) == "relevant"]
gaps = [p for p in papers if (p.get("gap") or {}).get("status") == "gap_stated"]
m = st.columns(4)
m[0].metric("Candidates ranked", session.get("n_candidates") or len(papers))
m[1].metric("Suggested", len(papers))
m[2].metric("Address your question", len(relevant), help="The model said yes and its quote was found in the abstract.")
m[3].metric("State a research gap", len(gaps))
answered_by = session.get("answered_by")
notes = [session.get("ranking_note") or ""]
if answered_by:
    notes.append(f"Screened by {answered_by} ({session.get('model')}).")
if any(notes):
    st.caption(" ".join(n for n in notes if n))

with st.container(border=True):
    st.markdown("**Is your question an open gap?**")
    if not gaps:
        st.caption(
            "None of the suggested papers states a research gap in its abstract. That does not "
            "mean the question is answered: the gap check finds roughly half of stated gaps, "
            "and reads abstracts only."
        )
    else:
        ordered = sorted(gaps, key=lambda p: -(p.get("gap_match") or 0.0))
        st.caption(
            "Gaps other authors state in their own words, closest to your question first. "
            "Each quote was found word for word in that paper's abstract."
        )
        for p in ordered[:6]:
            match = f" · similarity {p['gap_match']:.2f}" if p.get("gap_match") is not None else ""
            st.markdown(f"> {p['gap']['quote']}")
            st.caption(f"{p['title'] or p['work_id']} ({p.get('year') or 'n.d.'}){match}")

st.markdown(f"**Pick the papers to read in full** (up to {MAX_FULLTEXT})")
picked: set[str] = set(st.session_state.get("picked", []))
for rank, paper in enumerate(papers, 1):
    icon, label = RELEVANCE_BADGE[relevance_label(paper)]
    d = paper.get("decision") or {}
    with st.container(border=True):
        top = st.columns([0.06, 0.94])
        checked = top[0].checkbox(
            "Select", key="pick-" + paper["work_id"], value=paper["work_id"] in picked,
            label_visibility="collapsed",
        )
        if checked:
            picked.add(paper["work_id"])
        else:
            picked.discard(paper["work_id"])
        with top[1]:
            st.markdown(f"**#{rank} · {icon} {label} — {paper['title'] or paper['work_id']}**")
            bits = [str(paper["year"]) if paper.get("year") else "year unknown"]
            if paper.get("relevance") is not None:
                bits.append(f"similarity {paper['relevance']:.2f}")
            if paper.get("source_url"):
                bits.append(f"[view paper]({paper['source_url']})")
            st.caption(" · ".join(bits))
            if d.get("quote") and d.get("span_verified"):
                st.markdown(f"Why: “{d['quote']}”")
            elif d.get("quote"):
                st.caption("The model's reason wasn't found in the abstract, so its call is withheld. Read this one yourself.")
            gap = paper.get("gap") or {}
            if gap.get("status") == "gap_stated":
                st.markdown(f"Gap the authors state: “{gap['quote']}”")
            if paper.get("abstract"):
                with st.expander("Abstract"):
                    st.write(paper["abstract"])
st.session_state["picked"] = sorted(picked)

# ---------------------------------------------------------------------------
# Step 3 -- full text for the papers the researcher chose
# ---------------------------------------------------------------------------

st.divider()
st.subheader("Read the selected papers in full")
chosen = [p for p in papers if p["work_id"] in picked]
too_many = len(chosen) > MAX_FULLTEXT
signed_in = bool(st.session_state.get("google_account"))
has_project = bool(st.session_state.get("active_project"))

if too_many:
    st.warning(f"{len(chosen)} selected. Full text is read {MAX_FULLTEXT} at a time; untick a few.")
elif not signed_in:
    st.info("Sign in with Google and open a project to read full text.")
elif not has_project:
    st.info("Create or open a research project above to read full text.")
else:
    st.caption(
        "Only open-access papers held by Europe PMC can be read in full, mostly medicine and "
        "life sciences. Each paper takes a lookup, a download and a long model call."
    )

if st.button(
    f"Extract full text from {len(chosen)} paper(s)",
    type="primary",
    disabled=not chosen or too_many or not signed_in or not has_project,
):
    targets = [{"work_id": p["work_id"], "title": p["title"], "doi": p.get("doi")} for p in chosen]
    with st.spinner(f"Fetching and reading {len(targets)} paper(s)..."):
        try:
            discover_fulltext(targets)
            st.session_state.pop("export", None)
            st.session_state["fulltext"] = read_live_session(st.session_state["active_project"]).get("fulltext")
        except httpx.HTTPStatusError as exc:
            st.error(f"Request failed: {exc.response.text}")
        except httpx.HTTPError:
            st.error(model_timeout_message())

ft = st.session_state.get("fulltext")
if ft and ft.get("papers"):
    by_id = {p["work_id"]: p for p in papers}
    rank_of = {p["work_id"]: i for i, p in enumerate(papers, 1)}
    results = sorted(ft["papers"], key=lambda p: rank_of.get(p["work_id"], 999))
    found = sum(1 for p in results if p.get("found"))
    if found:
        st.success(f"Full text found for {found} of {len(results)}.")
    else:
        st.warning(
            f"None of the {len(results)} papers had open-access full text in Europe PMC. "
            "That is a coverage limit; each paper's reason is below."
        )

    with st.container(border=True):
        st.markdown("**Save to your computer**")
        st.caption(
            "One folder per paper: the PDF when an open-access copy can be downloaded, its "
            "categorised data (readable summary.md and data.json), tables as CSV, and figures. "
            "Plus summary.csv comparing them all. Your browser saves it as a .zip; unzip it "
            "wherever you keep your research."
        )
        if st.button("Prepare download", key="prepare-export"):
            with st.spinner("Downloading PDFs and packaging the data..."):
                try:
                    st.session_state["export"] = export_project(st.session_state["active_project"])
                except httpx.HTTPStatusError as exc:
                    st.error(f"Export failed: {exc.response.text}")
                except httpx.HTTPError:
                    st.error("The export took too long. Try again with fewer papers.")
        export = st.session_state.get("export")
        if export:
            name, data = export
            st.download_button("Download folder (.zip)", data, file_name=name,
                               mime="application/zip", type="primary", key="download-export")
            st.caption(f"{len(data) / 1_000_000:.1f} MB")

    st.markdown("**At a glance**")
    rows = []
    for p in results:
        s = by_id.get(p["work_id"], {})
        _, label = RELEVANCE_BADGE[relevance_label(s)] if s else ("", "—")
        rows.append(
            {
                "Paper": (p.get("title") or p["work_id"])[:90],
                "Relevance": label,
                "Similarity": round(s["relevance"], 2) if s.get("relevance") is not None else None,
                "Full text": "yes" if p.get("found") else "no",
                "Gaps stated": len(p.get("gaps") or []) if p.get("found") else None,
                **{name: field_text(p.get(field)) for field, name in FULLTEXT_FIELDS},
            }
        )
    st.dataframe(rows, hide_index=True, use_container_width=True)
    st.caption("A value appears only when its supporting quote was found in the paper. Tables and figures below come straight from the publisher's file.")

    for index, p in enumerate(results):
        s = by_id.get(p["work_id"], {})
        with st.container(border=True):
            st.markdown(f"#### {p.get('title') or p['work_id']}")
            if s:
                icon, label = RELEVANCE_BADGE[relevance_label(s)]
                d = s.get("decision") or {}
                line = f"{icon} **{label}**"
                if s.get("relevance") is not None:
                    line += f" · similarity {s['relevance']:.2f}"
                st.markdown(line)
                if d.get("quote") and d.get("span_verified"):
                    st.caption(f"Why: “{d['quote']}”")
                gap = s.get("gap") or {}
                if gap.get("status") == "gap_stated":
                    st.caption(f"Gap the authors state: “{gap['quote']}”")
            if p.get("coverage"):
                render_categories({**p, "fulltext_ui_key": f"ft-{index}-{p['work_id']}",
                                   "fulltext_note": p.get("note", "")})
            elif p.get("note"):
                st.caption(f"Full text: {p['note']}")

st.divider()
st.caption(
    "Nothing on this page is scored: there is no answer sheet for a question you just typed. "
    "Every claim is shown with the sentence it rests on, so you can check it. "
    "The same question can be put to a second AI, so a suggested gap is not taken on one model's word."
)
