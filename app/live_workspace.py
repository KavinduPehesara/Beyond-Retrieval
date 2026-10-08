"""Interactive research views for a saved, ad-hoc review."""
import json
import altair as alt
import httpx
import streamlit as st
from api_client import read_live_session, save_live_session, review_live_paper, map_live_session


def eligible_for_fulltext(paper, latest):
    decision = latest.get(paper["work_id"], {}).get("decision")
    if decision in ("include", "exclude"):
        return decision == "include"
    model = paper.get("decision")
    return not model or (model["status"] == "include" and model["span_verified"])


def _error(exc):
    detail = str(exc)
    if isinstance(exc, httpx.HTTPStatusError):
        try:
            detail = exc.response.json().get("detail", detail)
        except ValueError:
            pass
    st.error(detail)


def render_workspace(session):
    sid = session.get("session_id")
    if not sid:
        st.caption("Sign in and create a named project to save this research and use the research workspace.")
        return {}
    try:
        saved = read_live_session(sid)
    except httpx.HTTPError as exc:
        _error(exc)
        return {}
    st.markdown("**Review topic**")
    st.text(saved["query"])
    st.caption("Saved to your project. Reopen it from My research projects.")
    history = saved.get("search_history", [])
    if history:
        with st.expander("Previous searches in this project"):
            for index, previous in enumerate(history, 1):
                st.write(str(index) + ". " + previous.get("query", "Search") + " · " + str(len(previous.get("papers", []))) + " papers")
                st.download_button("Download saved search " + str(index), json.dumps(previous, indent=2), file_name="research-search-"+str(index)+".json", mime="application/json", key=sid+"-history-"+str(index))
    latest = saved["reviewer_latest"]
    reviewed = [a for a in latest.values() if a["decision"] != "pending"]
    st.caption(f"Researcher decisions: {len(reviewed)} of {len(session['papers'])} papers. Model decisions remain unchanged.")
    with st.expander("Semantic map of these results"):
        st.caption("SPECTER2 scientific-document embeddings projected into two dimensions. Nearby points suggest similar content; axes are not research quality or relevance scores. First use may load the local model.")
        if st.button("Build semantic map", key=sid + "-map"):
            try:
                with st.spinner("Embedding papers and projecting the map…"):
                    st.session_state[sid + "-map-result"] = map_live_session(sid)
            except httpx.HTTPError as exc:
                _error(exc)
        result = st.session_state.get(sid + "-map-result")
        if result:
            points = [{**p, "reviewer_decision": latest.get(p["work_id"], {}).get("decision", "pending")} for p in result["points"]]
            chart = alt.Chart(alt.Data(values=points)).mark_circle(size=130).encode(
                x=alt.X("x:Q", title="Component 1"), y=alt.Y("y:Q", title="Component 2"),
                color=alt.Color("reviewer_decision:N", title="Researcher decision"),
                tooltip=["title:N", "reviewer_decision:N"], href="source_url:N").properties(height=330).interactive()
            st.altair_chart(chart, use_container_width=True)
            st.caption(f"{result['model']} · {result['projection']} · two dimensions retain {result['variance_explained']:.0%} of embedding variation. Click a point to open its source.")
    with st.expander("Gap coverage matrix — technique × domain"):
        matrix = saved["coverage_matrix"]
        st.caption("Reviewer-assigned categories backed by abstract quotes. Counts describe this result set only. Empty cells do not establish a research gap. Excluded papers are omitted; pending coded papers remain provisional.")
        if not matrix["cells"]:
            st.info("Code technique and domain under ‘Researcher review’ on the paper cards to build the matrix.")
        else:
            chart = alt.Chart(alt.Data(values=matrix["cells"])).mark_rect().encode(
                x=alt.X("domain:N", title="Domain"), y=alt.Y("technique:N", title="Technique"),
                color=alt.Color("papers:Q", title="Coded papers", scale=alt.Scale(scheme="tealblues", domainMin=0)),
                tooltip=["technique:N", "domain:N", "papers:Q", "gap_statements:Q"])
            pick = alt.selection_point(name="coverage_cell", fields=["technique", "domain"], empty=False)
            selection = st.altair_chart(chart.add_params(pick), use_container_width=True,
                                       key=sid + "-matrix", on_select="rerun")
            cells = matrix["cells"]
            st.caption("Click a matrix cell to inspect evidence, or use the dropdown below. Clear the chart selection to return to dropdown navigation.")
            index = st.selectbox("Inspect a cell's source evidence", range(len(cells)),
                                 format_func=lambda i: f"{cells[i]['technique']} / {cells[i]['domain']} ({cells[i]['papers']} papers)", key=sid + "-cell")
            cell = cells[index]
            picked = selection.selection.get("coverage_cell", [])
            if picked:
                cell = next((c for c in cells if c["technique"] == picked[0].get("technique") and c["domain"] == picked[0].get("domain")), cell)
                st.caption(f"Selected cell: {cell['technique']} / {cell['domain']}")
            matches = [r for r in matrix["evidence"] if r["technique"] == cell["technique"] and r["domain"] == cell["domain"]]
            if not matches:
                st.info("No coded paper in this cell. Broaden the search before drawing conclusions.")
            for row in matches:
                st.markdown(f"**{row['title']}**")
                st.text(row["quote"])
                if row["gap_quote"]:
                    st.caption("Author-stated gap — quote matched the stored abstract:")
                    st.text(row["gap_quote"])
                if row["source_url"]:
                    st.link_button("Open evidence source", row["source_url"])
    st.download_button("Export review and researcher audit trail", json.dumps(saved, ensure_ascii=False, indent=2),
                       "research-review.json", "application/json", key=sid + "-export")
    return latest


def render_reviewer(paper, session, latest):
    sid = session.get("session_id")
    if not sid:
        return
    previous = latest.get(paper["work_id"], {})
    key = sid + paper["work_id"]
    with st.expander("Researcher review — decision and coverage coding"):
        st.caption("Your decision is stored separately from the model suggestion. A changed decision does not automatically rerun extraction.")
        if previous:
            st.caption(f"Last saved: {previous['decision']} · {previous['saved_at']}")
        if paper.get("abstract"):
            st.text(paper["abstract"])
        else:
            st.info("This older result has no stored abstract. Run a fresh search to enable semantic mapping and verified coding.")
        with st.form(key + "-review"):
            choices = ["pending", "include", "exclude"]
            decision = st.selectbox("Researcher decision", choices, index=choices.index(previous.get("decision", "pending")), key=key + "-decision")
            rationale = st.text_area("Reason for your decision", value=previous.get("rationale", ""), key=key + "-reason")
            technique = st.text_input("Technique (optional)", value=previous.get("technique", ""), key=key + "-technique")
            domain = st.text_input("Domain (optional)", value=previous.get("domain", ""), key=key + "-domain")
            quote = st.text_area("Exact abstract quote supporting the coverage labels", value=previous.get("quote", ""), key=key + "-quote")
            st.caption("Use consistent category names across papers. Both labels and a matching source quote are required for matrix coding; label meaning remains your responsibility.")
            submit = st.form_submit_button("Save researcher review")
        if submit:
            try:
                review_live_paper(sid, dict(work_id=paper["work_id"], decision=decision, rationale=rationale,
                                            technique=technique, domain=domain, quote=quote))
                st.rerun()
            except httpx.HTTPError as exc:
                _error(exc)
