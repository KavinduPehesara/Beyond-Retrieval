"""Shared, locally rendered visual identity for the research workspace."""
import streamlit as st


def apply_research_style():
    """Theme the page and draw the top bar; return the bar's account slot.

    One row: the wordmark on the left, then the Light/Dark switch and the
    account control (Sign in, or the name with Sign out) together at the
    top right, where people look for them.
    """
    # A permanent session value survives Streamlit's page-widget cleanup.
    mode = st.session_state.get("research_mode", "Light")
    brand, appearance, account = st.columns([4.6, 1.5, 2.1], vertical_alignment="center")
    with brand:
        st.markdown('<div class="research-wordmark">BEYOND RETRIEVAL / RESEARCH WORKSPACE</div>',
                    unsafe_allow_html=True)
    with appearance.container(key="br-appearance"):
        selected = st.radio("Appearance", ("Light", "Dark"),
                            index=0 if mode == "Light" else 1,
                            key="research_mode_picker", horizontal=True,
                            label_visibility="collapsed")
    st.session_state["research_mode"] = selected
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
.research-wordmark { font-size: .72rem; font-weight: 600; letter-spacing: .16em; color: #547569; margin-bottom: .4rem; }
@media (max-width: 700px) { .block-container { padding: 2rem 1.2rem; } h1 { font-size: 2.1rem !important; } }
/* Top bar: switch and account pinned to the right edge of their columns. */
.st-key-br-account > div, .st-key-br-appearance > div { width: 100% !important; display: flex; justify-content: flex-end; }
.st-key-br-account .stButton, .st-key-br-account [data-testid="stPopover"] { width: auto !important; }
.st-key-br-appearance [role="radiogroup"] { justify-content: flex-end; }
.st-key-br-account button p { white-space: nowrap; }
.research-wordmark { margin-bottom: 0; }
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
    return account.container(key="br-account")
