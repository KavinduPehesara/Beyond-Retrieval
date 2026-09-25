"""Results & Override -- browse a screening run's decisions, and dispose
of any of them yourself. The system proposes; this page is where the
reviewer disposes.
"""

from __future__ import annotations

import streamlit as st
from api_client import create_override, health, list_papers, list_reviews, override_summary, paper_detail

st.set_page_config(page_title="Results & Override", page_icon="⚖️", layout="wide")
st.title("Results & Override")

if not health():
    st.error("Can't reach the API. Start it with `uvicorn slr.api.app:app`.")
    st.stop()

reviews = {r["review"]: r for r in list_reviews()}
review = st.selectbox("Review", list(reviews), help="Which review's decisions to browse.")
info = reviews[review]

if not info["screen_run"]:
    st.warning(f"{review} has not been screened yet.")
    st.stop()

run_id = st.text_input("Run", value=info["screen_run"], help="Defaults to the latest screening run for this review.")

c1, c2, c3 = st.columns([1, 1, 2])
decision_filter = c1.selectbox("Decision", ["(all)", "include", "exclude", "unverified", "error"])
verified_only = c2.checkbox("Verified only")

papers = list_papers(
    review,
    run_id=run_id,
    decision=None if decision_filter == "(all)" else decision_filter,
    verified_only=verified_only,
    limit=200,
)
c3.caption(f"{len(papers)} of {info['n_records']} records" + (" (showing first 200)" if len(papers) == 200 else ""))

st.dataframe(
    [
        {
            "Title": (p["title"] or "(no title)")[:100],
            "Year": p["year"],
            "Decision": p["decision"] or "not screened",
            "Confidence": p["confidence"],
            "Verified": "✓" if p["span_verified"] else ("—" if p["span_verified"] is None else ""),
        }
        for p in papers
    ],
    hide_index=True,
    use_container_width=True,
    height=min(38 * (len(papers) + 1), 480),
)

st.divider()
st.subheader("Dispose of one")

options = {f"{(p['title'] or p['work_id'])[:90]} — {p['decision'] or 'not screened'}": p["work_id"] for p in papers}
if not options:
    st.info("No records match these filters.")
    st.stop()

chosen_label = st.selectbox("Record", list(options))
work_id = options[chosen_label]
detail = paper_detail(review, work_id, screen_run=run_id)

left, right = st.columns([3, 2])
with left:
    st.markdown(f"**{detail['title'] or work_id}**")
    st.caption(f"{detail['venue'] or 'venue not recorded'} · {detail['year'] or 'year not recorded'}")
    st.write(f"System proposed: **{detail['decision'] or 'not screened'}**" + (f" (confidence {detail['confidence']:.2f})" if detail["confidence"] is not None else ""))
    if detail["screen_quote"]:
        st.markdown(f"> {detail['screen_quote']}")
    st.caption(f"Verified: {'yes' if detail['span_verified'] else 'no'} · `{detail['screen_note']}`")

with right:
    with st.form("override_form"):
        human_decision = st.radio("Your decision", ["include", "exclude"], horizontal=True)
        rationale = st.text_area("Rationale", placeholder="Why -- cite what the abstract actually says.")
        submitted = st.form_submit_button("Record disposition", type="primary")
    if submitted:
        try:
            result = create_override(run_id, review, work_id, human_decision, rationale or None)
            if result["changed"]:
                st.success(f"Overrode: system said {result['model_decision']!r}, you said {result['human_decision']!r}.")
            else:
                st.success(f"Confirmed: {result['human_decision']!r}.")
        except Exception as exc:
            st.error(f"Could not record that: {exc}")

st.divider()
try:
    summary = override_summary(review, run_id)
    if summary["n_overrides"]:
        st.subheader("Overrides recorded against this run")
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Total", summary["n_overrides"])
        m2.metric("Changed", summary["n_changed"])
        m3.metric("Confirmed", summary["n_confirmed"])
        m4.metric("Override rate", f"{summary['override_rate']:.0%}" if summary["override_rate"] is not None else "n/a")
except Exception:
    pass
