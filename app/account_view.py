"""Google account controls and the private review library."""
import httpx
import streamlit as st
from api_client import API_URL, account_request, read_live_session


def render_account():
    ticket = st.query_params.get("login_ticket")
    if ticket:
        try:
            binding = st.context.cookies.get("br_login_binding", "")
            account = account_request("POST", "/auth/exchange", json={"ticket": ticket, "binding": binding})
            st.session_state["google_account"] = account
            st.session_state.pop("session", None)
            st.session_state["guest_access"] = True
        except httpx.HTTPError:
            st.error("Sign-in expired. Please try Google sign-in again.")
        del st.query_params["login_ticket"]
        if st.session_state.get("google_account"):
            st.switch_page("Home.py")
        st.rerun()
    account = st.session_state.get("google_account")
    with st.popover(account["name"] if account else "Sign in", use_container_width=False):
        if account:
            st.caption(account["email"])
            if st.button("Sign out"):
                try:
                    account_request("POST", "/auth/logout")
                except httpx.HTTPError:
                    pass
                for key in list(st.session_state):
                    if key not in ("research_theme",):
                        del st.session_state[key]
                st.rerun()
        else:
            st.write("Sign in with Google to save and reopen your reviews.")
            try:
                configured = account_request("GET", "/auth/config")["configured"]
            except httpx.HTTPError:
                configured = False
            if configured:
                st.link_button("Continue with Google", API_URL + "/auth/google/start")
            else:
                st.info("Google sign-in setup is pending. Add OAuth credentials to the local .env file and restart the API.")


#: The mark, drawn here rather than shipped as an image file: an open page
#: with a reading line lifted off it, which is the whole claim of the tool —
#: the sentence is pulled out of the paper and shown to you. Inline SVG so it
#: stays sharp at any size, needs no asset pipeline, and costs no request.
LOGO = """
<svg viewBox="0 0 64 64" width="72" height="72" role="img" aria-label="Beyond Retrieval">
  <rect x="9" y="7" width="34" height="46" rx="3" fill="#ffffff" stroke="#28665f" stroke-width="2.5"/>
  <path d="M17 19h18M17 27h18M17 35h11" stroke="#9fb6ad" stroke-width="2.5" stroke-linecap="round"/>
  <rect x="26" y="31" width="29" height="13" rx="3" fill="#28665f"/>
  <path d="M31 37.5h12" stroke="#ffffff" stroke-width="2.2" stroke-linecap="round"/>
  <circle cx="49.5" cy="37.5" r="2.2" fill="#ffffff"/>
</svg>
"""

WELCOME_POINTS = [
    (
        "Search real literature",
        "Type a topic and it searches OpenAlex live, then screens what it finds against "
        "criteria you write yourself.",
    ),
    (
        "Every answer carries its sentence",
        "A decision is shown only when the quote behind it is found word for word in the "
        "paper. Anything else is handed back to you to read.",
    ),
    (
        "Measured, not asserted",
        "The same pipeline was run over 12,598 papers whose correct answers were already "
        "published. The Validation pages show the results, including the bad ones.",
    ),
]


def render_welcome():
    """The front door for anyone not signed in.

    Deliberately a sign-in page rather than a wall: the tool is usable as a
    guest, and the page says what signing in adds instead of implying an
    account is required. Nothing here calls the model or the database.
    """
    if st.session_state.get("google_account") or st.session_state.get("guest_access"):
        return

    st.markdown(
        """
        <style>
        .br-login { text-align: center; margin: 1.5rem auto 0.5rem; }
        .br-login h1 { margin: .4rem 0 .2rem; font-size: 2.6rem; letter-spacing: -.035em; }
        .br-login .br-tagline { color: #4a5a54; font-size: 1.08rem; margin-bottom: .2rem; }
        .br-point { background:#ffffff; border:1px solid #dce2d9; border-radius:6px;
                    padding:1rem 1.1rem; height:100%; }
        .br-point b { display:block; margin-bottom:.35rem; color:#203c36; }
        .br-point span { color:#4a5a54; font-size:.93rem; line-height:1.55; }
        </style>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(
        f"<div class='br-login'>{LOGO}"
        "<h1>Beyond Retrieval</h1>"
        "<div class='br-tagline'>Find the papers that matter, and check every decision "
        "for yourself.</div></div>",
        unsafe_allow_html=True,
    )

    columns = st.columns(len(WELCOME_POINTS), gap="medium")
    for column, (heading, detail) in zip(columns, WELCOME_POINTS):
        with column:
            st.markdown(
                f"<div class='br-point'><b>{heading}</b><span>{detail}</span></div>",
                unsafe_allow_html=True,
            )

    st.write("")
    left, middle, right = st.columns([1, 2, 1])
    with middle:
        try:
            configured = account_request("GET", "/auth/config")["configured"]
        except httpx.HTTPError:
            configured = False
        if configured:
            st.link_button(
                "Continue with Google",
                API_URL + "/auth/google/start",
                type="primary",
                use_container_width=True,
            )
        else:
            st.info(
                "Google sign-in setup is pending. Add OAuth credentials to the local .env "
                "file and restart the API."
            )
        if st.button("Continue as a guest", type="secondary", use_container_width=True):
            st.session_state["guest_access"] = True
            st.rerun()
        st.caption(
            "Signing in saves your projects and unlocks full-text retrieval. Guests can "
            "search, screen and extract from abstracts. Your work stays on this machine: "
            "the screening model runs locally, so a review costs nothing to run."
        )
        st.caption("MSE907 capstone · Pehesara Gunawardena")
    st.stop()


def activate_project(project):
    st.session_state["active_project"] = project["session_id"]
    st.session_state["project_name"] = project.get("project_name", project.get("query", "Research"))
    st.session_state["session"] = project if project.get("papers") else None
    st.session_state["fulltext"] = project.get("fulltext")


def render_library():
    if not st.session_state.get("google_account"):
        return
    with st.expander("My research projects", expanded=not st.session_state.get("active_project")):
        try:
            with st.form("create_project"):
                name = st.text_input("New project name", max_chars=120, placeholder="e.g. Vitamin D and childhood asthma")
                create = st.form_submit_button("Create project")
            if create:
                if not name.strip():
                    st.warning("Enter a name for this research project.")
                else:
                    project = account_request("POST", "/projects", json={"name": name.strip()})
                    existing = st.session_state.get("session")
                    if existing and existing.get("papers") and not st.session_state.get("active_project"):
                        project = account_request("POST", "/projects/" + project["session_id"] + "/import", json=existing)
                    activate_project(project)
                    st.rerun()
            reviews = account_request("GET", "/discover/sessions")
            if reviews:
                selected = st.selectbox("Choose a project", reviews, format_func=lambda r: r.get("name", r["query"]) + " · " + str(r["n_found"]) + " papers")
                if st.button("Open project"):
                    activate_project(read_live_session(selected["session_id"]))
                    st.rerun()
                with st.form("rename_project"):
                    new_name = st.text_input("Rename selected project", value=selected.get("name", selected["query"]), max_chars=120)
                    rename = st.form_submit_button("Rename project")
                if rename:
                    updated = account_request("PATCH", "/projects/"+selected["session_id"], json={"name": new_name.strip()})
                    if st.session_state.get("active_project") == selected["session_id"]:
                        st.session_state["project_name"] = updated["project_name"]
                    st.rerun()
                st.caption("Remove hides the project from your library and keeps its saved data archived locally.")
                if st.button("Remove selected project"):
                    account_request("DELETE", "/projects/"+selected["session_id"])
                    if st.session_state.get("active_project") == selected["session_id"]:
                        for key in ("active_project", "project_name", "session", "fulltext"):
                            st.session_state.pop(key, None)
                    st.rerun()
            else:
                st.caption("Create your first project to start saving research.")
        except httpx.HTTPError:
            st.error("Could not update your projects. Check the connection or sign in again.")
    if st.session_state.get("active_project"):
        st.caption("Current project: " + st.session_state.get("project_name", "Research") + " · Research results and reviewer decisions save automatically.")
