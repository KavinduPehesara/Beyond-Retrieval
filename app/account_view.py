"""Google account controls and the private review library."""
import base64
from functools import lru_cache
from pathlib import Path

import httpx
import streamlit as st
from api_client import API_URL, account_request, read_live_session

BRANDING = Path(__file__).resolve().parents[1] / "assets" / "branding"


def _google_configured():
    try:
        return account_request("GET", "/auth/config")["configured"]
    except httpx.HTTPError:
        return False


def _google_button():
    """Continue with Google, in this tab.

    ``st.link_button`` always opens a new tab, so sign-in used to leave the
    app open in one window and finish in another. Google's consent page
    refuses to be framed, so it cannot live inside the dialog either; going
    there in this tab and coming straight back is the one way to keep the
    whole thing in a single window.
    """
    st.markdown(
        f"<a class='br-google' href='{API_URL}/auth/google/start' target='_self'>"
        "Continue with Google</a>",
        unsafe_allow_html=True,
    )


def _cookie(name):
    """A cookie the browser sent when this page session opened."""
    try:
        return st.context.cookies.get(name, "")
    except Exception:  # no browser context, e.g. under test
        return ""


def restore_sign_in():
    """Sign back in from the browser-session cookie set at Google sign-in.

    A reload or a new tab starts a new Streamlit session with empty state,
    which used to mean signing in again. The cookie has no expiry, so the
    browser deletes it on close: signed in until the browser closes.
    Tried once per page session; a dead cookie just leaves a guest.
    """
    if st.session_state.get("google_account") or st.session_state.get("resume_tried"):
        return
    st.session_state["resume_tried"] = True
    session = _cookie("br_session")
    if not session:
        return
    try:
        st.session_state["google_account"] = account_request("POST", "/auth/resume", json={"session": session})
        st.session_state["guest_access"] = True
    except httpx.HTTPError:
        pass


def render_account(slot=None):
    """The account control. ``slot`` is the top bar's right-hand corner."""
    restore_sign_in()
    ticket = st.query_params.get("login_ticket")
    if ticket:
        try:
            binding = _cookie("br_login_binding")
            account = account_request("POST", "/auth/exchange", json={"ticket": ticket, "binding": binding})
            st.session_state["google_account"] = account
            st.session_state.pop("session", None)
            st.session_state["guest_access"] = True
        except httpx.HTTPError:
            st.error("Sign-in expired. Please try Google sign-in again.")
        del st.query_params["login_ticket"]
        st.rerun()
    account = st.session_state.get("google_account")
    slot = slot or st.container()
    if not account:
        if slot.button("Sign in", type="primary", use_container_width=True):
            sign_in_dialog()
        return
    # The menu opens where the Sign in button was, so the top-right corner
    # means the same thing before and after signing in.
    with slot.popover(account.get("name") or account.get("email") or "Account",
                      icon=":material/account_circle:", use_container_width=True):
        with st.container(key="br-identity"):
            _menu_identity(account)
        # Above the projects panel rather than under it. The panel is taller
        # than a popover is allowed to be, so anything below it is reachable
        # only by scrolling -- and on a shorter screen, not obviously
        # reachable at all. Sign out is not a control to go looking for.
        if st.button("Sign out", icon=":material/logout:", use_container_width=True):
            _sign_out()
        st.divider()
        render_library()


def _initials(account):
    """Something to show when there is no picture.

    An account created before the picture was stored has none until its
    next sign-in, so this is the ordinary case for a while rather than an
    edge case.
    """
    source = (account.get("name") or account.get("email") or "?").strip()
    parts = [p for p in source.replace(".", " ").split() if p]
    letters = "".join(p[0] for p in parts[:2]) or source[:1]
    return letters.upper()


def _menu_identity(account):
    """Who is signed in: picture, name, address."""
    picture = (account.get("picture") or "").strip()
    avatar, who = st.columns([0.3, 0.7], vertical_alignment="center")
    with avatar:
        if picture.startswith("https://"):
            # Google's own URL, fetched by the browser when the menu opens.
            # Nothing of the image is held by this application.
            st.image(picture, width=56)
        else:
            st.markdown(
                f"<div class='br-avatar'>{_initials(account)}</div>",
                unsafe_allow_html=True)
    with who:
        st.markdown(f"**{account.get('name') or 'Signed in'}**")
        if account.get("email"):
            # Not st.caption: markdown turns a bare address into a mailto
            # link, and a blue underlined email in a menu looks like
            # something to click when there is nowhere to go.
            st.markdown(
                f"<div class='br-account-email'>{account['email']}</div>",
                unsafe_allow_html=True)


def _sign_out():
    try:
        account_request("POST", "/auth/logout",
                        json={"session": _cookie("br_session")} if _cookie("br_session") else None)
    except httpx.HTTPError:
        pass
    for key in list(st.session_state):
        if key not in ("research_theme", "research_mode"):
            del st.session_state[key]
    # Signed out on purpose: don't greet them with the sign-in dialog.
    st.session_state["welcome_shown"] = True
    # The cookie is dead server-side now; don't try it again.
    st.session_state["resume_tried"] = True
    st.rerun()


#: The mark the welcome card drew before there was any brand artwork: an open
#: page with a reading line lifted off it. Kept as the fallback for a working
#: copy that has no assets/branding, so the card still has a mark rather than
#: a gap where one should be.
FALLBACK_MARK = """
<svg viewBox="0 0 64 64" width="72" height="72" role="img" aria-label="Beyond Retrieval">
  <rect x="9" y="7" width="34" height="46" rx="3" fill="#ffffff" stroke="#28665f" stroke-width="2.5"/>
  <path d="M17 19h18M17 27h18M17 35h11" stroke="#9fb6ad" stroke-width="2.5" stroke-linecap="round"/>
  <rect x="26" y="31" width="29" height="13" rx="3" fill="#28665f"/>
  <path d="M31 37.5h12" stroke="#ffffff" stroke-width="2.2" stroke-linecap="round"/>
  <circle cx="49.5" cy="37.5" r="2.2" fill="#ffffff"/>
</svg>
"""


@lru_cache(maxsize=4)
def brand_mark(mode: str) -> str:
    """The brand mark for one appearance, as an inline data URI.

    The welcome card is assembled as a single HTML string, so the image has
    to travel inside it -- a src pointing at a path on disk is not something
    the browser can fetch from here. Cached because the encoding is the same
    on every rerun and the card is drawn on each one.
    """
    path = BRANDING / ("icon-dark.png" if mode == "Dark" else "icon-light.png")
    if not path.exists():
        return FALLBACK_MARK
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return (f"<img src='data:image/png;base64,{data}' width='76' height='76' "
            "alt='Beyond Retrieval'/>")

WELCOME_POINTS = [
    (
        "Search real literature",
        "Ask a research question and it searches OpenAlex live, then suggests the papers "
        "closest to it, with any research gaps their authors state.",
    ),
    (
        "Every answer carries its sentence",
        "A decision is shown only when the quote behind it is found word for word in the "
        "paper. Anything else is handed back to you to read.",
    ),
    (
        "You choose what to read",
        "Pick the suggestions worth a deeper look and it reads them in full, laying out "
        "methods, results, tables and limitations side by side.",
    ),
]


@st.dialog("Welcome to Beyond Retrieval", width="large")
def sign_in_dialog():
    """Sign in, or carry on as a guest, in a dialog over the app.

    It used to be a full page that hid the app until a visitor chose. A
    dialog says the same thing without standing in the way: closing it is
    the same as choosing to continue as a guest. Nothing here calls the
    model or the database.
    """
    st.markdown(
        """
        <style>
        .br-login { text-align: center; margin: .2rem auto .6rem; }
        .br-login .br-tagline { color: #4a5a54; font-size: 1.02rem; }
        .br-point { background:#ffffff; border:1px solid #dce2d9; border-radius:6px;
                    padding:.8rem .9rem; height:100%; }
        .br-point b { display:block; margin-bottom:.3rem; color:#203c36; }
        .br-point span { color:#4a5a54; font-size:.88rem; line-height:1.5; }
        a.br-google { display:block; text-align:center; padding:.55rem 1rem; border-radius:6px;
                      background:#28665f; color:#ffffff !important; text-decoration:none !important;
                      font-weight:600; margin:.4rem 0; }
        a.br-google:hover { background:#1f524c; }
        </style>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(
        f"<div class='br-login'>{brand_mark(st.session_state.get('research_mode', 'Light'))}"
        "<div class='br-tagline'>Find the papers that matter, and check every decision "
        "for yourself.</div></div>",
        unsafe_allow_html=True,
    )
    columns = st.columns(len(WELCOME_POINTS), gap="small")
    for column, (heading, detail) in zip(columns, WELCOME_POINTS):
        with column:
            st.markdown(
                f"<div class='br-point'><b>{heading}</b><span>{detail}</span></div>",
                unsafe_allow_html=True,
            )
    st.write("")
    if _google_configured():
        _google_button()
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
        "search and see suggestions from abstracts. Every question goes to both "
        "models, and each paper says whether they agreed."
    )


def render_welcome():
    """Greet a visitor who isn't signed in, once per session, with the dialog.

    Once only: a dialog closes on the next interaction outside it, and that
    is taken as "continue as a guest" rather than reopened on every rerun.
    """
    if (
        st.session_state.get("google_account")
        or st.session_state.get("guest_access")
        or st.session_state.get("welcome_shown")
    ):
        return
    st.session_state["welcome_shown"] = True
    sign_in_dialog()


def activate_project(project):
    st.session_state["active_project"] = project["session_id"]
    st.session_state["project_name"] = project.get("project_name", project.get("query", "Research"))
    st.session_state["session"] = project if project.get("papers") else None
    st.session_state["fulltext"] = project.get("fulltext")


def render_library():
    if not st.session_state.get("google_account"):
        return
    st.markdown("**Research projects**")
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
            # Folded away by default. Renaming and removing are rare next to
            # opening, and laid out flat they pushed Sign out below the
            # bottom of the menu -- the one control nobody should have to
            # scroll to find.
            with st.expander("Rename or remove"):
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


def project_note():
    """Which project the page is writing into, said on the page itself.

    Stays out of the account menu on purpose: it answers a question someone
    has while they work ("where is this being saved?"), and an answer that
    needs a menu opened to read it is not much of an answer.
    """
    if st.session_state.get("active_project"):
        st.caption("Current project: " + st.session_state.get("project_name", "Research")
                   + " · Research results and reviewer decisions save automatically.")
