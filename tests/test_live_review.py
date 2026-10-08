import numpy as np
import pytest
from slr.services import live_review as live


@pytest.fixture
def session(tmp_path, monkeypatch):
    monkeypatch.setattr(live, "STORE", tmp_path / "live.sqlite3")
    return live.create_session(dict(query="test", papers=[
        dict(work_id=f"W{i}", title=f"Paper {i}", abstract="We used regression in asthma. Further trials are needed.",
             decision=dict(status="include", span_verified=True), source_url=None,
             gap=dict(status="gap_stated", quote="Further trials are needed.")) for i in range(3)]))


def action(**kwargs):
    return dict(decision="include", rationale="Reviewed", technique="Regression", domain="Asthma",
                quote="We used regression in asthma.", **kwargs)


def test_audit_preserves_original_and_excludes_reviewer_rejections(session):
    sid = session["session_id"]
    live.record_action(sid, "W0", action())
    change = action()
    change["decision"] = "exclude"
    saved = live.record_action(sid, "W0", change)
    assert len(saved["reviewer_actions"]) == 2
    assert saved["papers"][0]["decision"]["status"] == "include"
    assert saved["reviewer_latest"]["W0"]["decision"] == "exclude"
    assert live.coverage(saved)["n_coded"] == 0


def test_coding_requires_actual_evidence_and_both_axes(session):
    bad = action()
    bad["quote"] = "Invented sentence"
    with pytest.raises(ValueError, match="match"):
        live.record_action(session["session_id"], "W0", bad)
    bad = action()
    bad["domain"] = ""
    with pytest.raises(ValueError, match="both"):
        live.record_action(session["session_id"], "W0", bad)
    with pytest.raises(KeyError):
        live.record_action(session["session_id"], "unknown", action())


def test_matrix_contains_zero_cells_and_traceable_gaps(session):
    sid = session["session_id"]
    live.record_action(sid, "W0", action())
    other = action()
    other.update(technique="Trial", domain="Children")
    saved = live.record_action(sid, "W1", other)
    matrix = live.coverage(saved)
    assert len(matrix["cells"]) == 4
    assert sum(c["papers"] == 0 for c in matrix["cells"]) == 2
    assert sum(c["gap_statements"] for c in matrix["cells"]) == 2
    assert matrix["evidence"][0]["quote"] in saved["papers"][0]["abstract"]


def test_semantic_map_uses_abstracts_and_cache(session):
    class Embed:
        def encode(self, texts):
            assert len(texts) == 3 and "regression" in texts[0]
            return np.eye(3)
    result = live.semantic_map(session["session_id"], Embed())
    assert len(result["points"]) == 3
    assert 0 <= result["variance_explained"] <= 1.000001
    assert live.semantic_map(session["session_id"], object()) == result


def test_missing_session_and_insufficient_papers(session):
    with pytest.raises(KeyError):
        live.read_session("../../other")
    small = live.create_session(dict(papers=session["papers"][:1]))
    with pytest.raises(ValueError, match="three"):
        live.semantic_map(small["session_id"])
