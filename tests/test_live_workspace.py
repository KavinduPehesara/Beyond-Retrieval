from pathlib import Path
import sys
from streamlit.testing.v1 import AppTest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))


def test_researcher_decision_controls_fulltext_eligibility():
    from live_workspace import eligible_for_fulltext
    paper = dict(work_id="W1", decision=dict(status="exclude", span_verified=True))
    assert not eligible_for_fulltext(paper, {})
    assert eligible_for_fulltext(paper, {"W1": dict(decision="include")})
    paper["decision"]["status"] = "include"
    assert not eligible_for_fulltext(paper, {"W1": dict(decision="exclude")})


def test_saved_workspace_renders_map_matrix_and_saves_review(monkeypatch):
    import live_workspace as view
    paper = dict(work_id="W1", title="An asthma trial", abstract="Regression in asthma.", source_url=None)
    session = dict(session_id="test", query="Asthma", papers=[paper])
    cell = dict(technique="Regression", domain="Asthma", papers=1, gap_statements=1)
    row = dict(**paper, technique="Regression", domain="Asthma", quote=paper["abstract"], gap_quote="")
    saved = {**session, "reviewer_latest": {}, "coverage_matrix": dict(cells=[cell], evidence=[row])}
    monkeypatch.setattr(view, "read_live_session", lambda sid: saved)
    calls = []
    monkeypatch.setattr(view, "review_live_paper", lambda sid, action: calls.append((sid, action)))
    at = AppTest.from_string("import streamlit as st\nfrom live_workspace import render_workspace,render_reviewer\ns=st.session_state['review']\na=render_workspace(s)\nrender_reviewer(s['papers'][0],s,a)")
    at.session_state["review"] = session
    at.session_state["test-map-result"] = dict(model="SPECTER2", projection="PCA", variance_explained=.8,
                                               points=[dict(**paper, x=0, y=1)])
    at.run()
    assert not at.exception
    assert any(e.label == "Semantic map of these results" for e in at.expander)
    assert any(e.label.startswith("Gap coverage matrix") for e in at.expander)
    next(s for s in at.selectbox if s.label == "Researcher decision").select("include")
    next(b for b in at.button if b.label == "Save researcher review").click().run()
    assert not at.exception
    assert calls[0][1]["decision"] == "include"
