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




def test_a_session_id_cannot_walk_out_of_the_store():
    with pytest.raises(KeyError):
        live.read_session("../../other")
