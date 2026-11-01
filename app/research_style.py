"""Shared, locally rendered visual identity for the research workspace."""
from pathlib import Path

import streamlit as st

BRANDING = Path(__file__).resolve().parents[1] / "assets" / "branding"

#: Two files, one per appearance. The source art is dark teal, which is
#: invisible against the dark palette's #141d20, so the dark variant is
#: derived from the same artwork by scripts/branding_assets.py rather than
#: drawn a second time and left to drift.
LOGO = {"Light": BRANDING / "logo-light.png", "Dark": BRANDING / "logo-dark.png"}

#: Drawn at half the file's pixel width, so it stays sharp on a high-density
#: display.
LOGO_WIDTH = 210


def apply_research_style():
    """Theme the page and draw the top bar; return the bar's account slot.

    One row: the wordmark on the left, then the Light/Dark switch and the
    account control (Sign in, or the name with Sign out) together at the
    top right, where people look for them.
    """
    # A permanent session value survives Streamlit's page-widget cleanup.
    mode = st.session_state.get("research_mode", "Light")
    brand, account = st.columns([6.1, 2.1], vertical_alignment="center")
    # Both slots are made here and filled later, in the other order. A
    # container keeps the place it was created in, so the account control
    # stays above the appearance switch however they are written into.
    account_slot = account.container(key="br-account")
    with account.container(key="br-appearance"):
        dark = st.toggle("Dark mode", value=mode == "Dark", key="research_mode_toggle")
    selected = "Dark" if dark else "Light"
    st.session_state["research_mode"] = selected
    # Filled after the toggle, not before, so the mark matches the mode
    # chosen on this run rather than the previous one. A column renders
    # where it sits on the page, not in the order it was written into.
    with brand.container(key="br-brand"):
        logo = LOGO[selected]
        if logo.exists():
            st.image(str(logo), width=LOGO_WIDTH)
        else:
            # st.image raises on a path that is not there, which would take
            # the whole page down over a missing picture. The wordmark this
            # replaced is a fine thing to fall back to.
            st.markdown(
                '<div class="research-wordmark">BEYOND RETRIEVAL / RESEARCH WORKSPACE</div>',
                unsafe_allow_html=True)
    css = """
<style>
.stApp {
    --primary-color: #28665f;
    --background-color: #faf9f6;
    --secondary-background-color: #f0f1ed;
    --text-color: #233331;
    background: #faf9f6; color: #233331;
    font-family: 'Segoe UI', Arial, sans-serif;
}
[data-testid="stHeader"] { background: #faf9f6; border-bottom: 1px solid #e0e3dc; }
[data-testid="stSidebar"] { background: #eef0eb; border-right: 1px solid #d9dfd6; }
[data-testid="stSidebar"] * { color: #344a45; }
.block-container { max-width: 1180px; padding-top: 4.5rem; padding-bottom: 4rem; }
h1, h2, h3, h4 { font-family: Georgia, 'Times New Roman', serif !important; color: #203c36 !important; }
h1 { font-size: 2.7rem !important; font-weight: 500 !important; letter-spacing: -.035em; }
h2, h3 { font-weight: 500 !important; letter-spacing: -.015em; }
h4 { line-height: 1.4 !important; }
p, label, [data-testid="stText"] { line-height: 1.65; }
[data-testid="stMarkdownContainer"], [data-testid="stText"], [data-testid="stExpander"] summary { color: #233331; }
[data-testid="stCaptionContainer"] { color: #63716b; }
[data-testid="stForm"] { background: #fff; border: 1px solid #dce2d9; border-radius: 6px; padding: 1.6rem; }
[data-baseweb="input"], [data-baseweb="textarea"], [data-baseweb="select"] > div {
    background: #f4f5f1 !important; color: #233331 !important; border-color: #d6ded3 !important;
}
input, textarea { background: #f4f5f1 !important; color: #233331 !important; caret-color: #28665f; }
[data-testid="stWidgetLabel"] p { color: #344a45 !important; }
[data-testid="stTextInputRootElement"], [data-testid="stTextAreaRootElement"] { background: #f4f5f1 !important; }
input::placeholder, textarea::placeholder { color: #758079 !important; opacity: 1; }
button[kind="primary"], [data-testid="stBaseButton-primaryFormSubmit"] {
    background: #28665f !important; border-color: #28665f !important; color: white !important;
}
button[kind="primary"] p, [data-testid="stBaseButton-primaryFormSubmit"] p { color: white !important; }
button[kind="secondary"], [data-testid="stPopoverButton"], [data-testid="stBaseButton-secondaryFormSubmit"] {
    background: #fff !important; border-color: #cdd8cf !important; color: #28554b !important; border-radius: 5px;
}
[data-testid="stExpander"] { background: #fff; border-color: #dce2d9; border-radius: 6px; }
[data-testid="stMetric"] { border-top: 2px solid #669385; padding-top: .8rem; }
[data-testid="stMetricValue"] { font-family: Georgia, serif; color: #28554b; }
[data-testid="stAlert"] { border-radius: 4px; }
hr { border-color: #dce2d9 !important; margin: 2rem 0 !important; }
a { color: #28665f; text-underline-offset: 3px; }
[data-testid="stSidebarNav"] a[aria-current="page"] { background: #dce6dc; border-radius: 4px; }
[data-testid="stPopoverBody"] { background: #fff; color: #233331; }
/* The logo is an <img> in a figure; Streamlit's default spacing around one
   would push it out of line with the controls beside it. */
.st-key-br-brand [data-testid="stImage"], .st-key-br-brand figure { margin: 0 !important; }
.st-key-br-brand img { display: block; }
@media (max-width: 700px) { .block-container { padding: 2rem 1.2rem; } h1 { font-size: 2.1rem !important; } }
/* Top bar: switch and account pinned to the right edge of their columns. */
.st-key-br-account > div, .st-key-br-appearance > div { width: 100% !important; display: flex; justify-content: flex-end; }
.st-key-br-account .stButton, .st-key-br-account [data-testid="stPopover"] { width: auto !important; }
/* The toggle sits under the account control, flush with its right edge.
   Streamlit's checkbox wrapper fills the column but leaves its label at the
   left, so the alignment has to happen on the wrapper, not the column. */
.st-key-br-appearance [data-testid="stCheckbox"] { display: flex; justify-content: flex-end; }
.st-key-br-appearance [data-testid="stWidgetLabel"] p { font-size: .78rem; color: #547569; margin: 0; }
.st-key-br-appearance label { gap: .45rem; }
.st-key-br-account button p { white-space: nowrap; }
.st-key-br-brand > div { width: 100% !important; }
/* The account menu holds the whole projects panel, which does not fit in a
   popover's default width. */
[data-testid="stPopoverBody"] { min-width: 23rem; max-height: min(80vh, 44rem); padding: 1.1rem !important; }
/* Initials, for an account signed in before the picture was stored. */
.br-avatar { width: 56px; height: 56px; border-radius: 50%; background: #28665f; color: #ffffff;
             display: flex; align-items: center; justify-content: center;
             font-weight: 600; font-size: 1.1rem; letter-spacing: .02em; }
/* The popover's contents render in a portal outside .st-key-br-account, so
   the avatar has to be reached through the popover body, not the column. */
[data-testid="stPopoverBody"] [data-testid="stImage"] img { border-radius: 50%; }
.st-key-br-identity { margin-bottom: .7rem; }
.br-account-email { font-size: .8rem; color: #63716b; word-break: break-all; line-height: 1.3; }
.research-wordmark { font-size: .72rem; font-weight: 600; letter-spacing: .16em; color: #547569; margin: 0; }
</style>
"""
    if selected == "Dark":
        palette = {
            "#faf9f6": "#141d20", "#f0f1ed": "#202c30",
            "#233331": "#e1e9e5", "#eef0eb": "#19262a",
            "#344a45": "#c9d9d1", "#203c36": "#e1ede4",
            "#63716b": "#a6b9af", "#fff": "#1b282c",
            "#f4f5f1": "#26363b", "#758079": "#a6b9af",
            "#28554b": "#a4d7c3", "#dce6dc": "#30483f",
            "#547569": "#92baa7", "#28665f": "#448b7e",
            "#e0e3dc": "#35474a", "#d9dfd6": "#35474a",
            "#dce2d9": "#35474a", "#d6ded3": "#41575b",
            "#cdd8cf": "#41575b",
        }
        for light, dark in palette.items():
            css = css.replace(light, dark)
    st.markdown(css, unsafe_allow_html=True)
    return account_slot
