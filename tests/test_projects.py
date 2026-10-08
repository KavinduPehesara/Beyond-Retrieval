import pytest
from fastapi.testclient import TestClient
from slr.api.app import app
from slr.services import accounts, live_review

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(live_review, "STORE", tmp_path / "projects.sqlite3")
    return TestClient(app)

def login(client, subject):
    ticket, binding = accounts.issue_ticket(dict(sub=subject, email=subject+"@example.test", email_verified=True))
    client.headers["Authorization"] = "Bearer " + accounts.exchange_ticket(ticket,binding)["token"]

def test_projects_create_rename_remove_and_isolation(client):
    assert client.post("/projects", json={"name":"A"}).status_code == 401
    login(client,"owner")
    assert client.post("/projects", json={"name":"   "}).status_code == 400
    project = client.post("/projects", json={"name":"Asthma research"}).json()
    sid = project["session_id"]
    assert project["project_name"] == "Asthma research"
    assert client.patch("/projects/"+sid, json={"name":"Renamed research"}).status_code == 200
    assert client.get("/discover/sessions").json()[0]["name"] == "Renamed research"
    original_header = client.headers["Authorization"]
    login(client,"other")
    assert client.patch("/projects/"+sid, json={"name":"Steal"}).status_code == 404
    assert client.delete("/projects/"+sid).status_code == 404
    client.headers["Authorization"] = original_header
    assert client.delete("/projects/"+sid).status_code == 200
    assert client.get("/discover/sessions").json() == []
    assert client.get("/discover/sessions/"+sid).status_code == 404
    assert live_review.read_session(sid)["project_name"] == "Renamed research"

def test_fulltext_requires_login_and_project(client):
    payload = {"papers":[{"work_id":"W1"}]}
    assert client.post("/discover/fulltext",json=payload).status_code == 401
    login(client,"owner")
    assert client.post("/discover/fulltext",json=payload).status_code == 400
    payload["project_id"] = "missing"
    assert client.post("/discover/fulltext",json=payload).status_code == 404

def test_saves_search_history_and_combines_fulltext(client):
    login(client,"owner")
    project = client.post("/projects",json={"name":"A"}).json()
    sid = project["session_id"]
    owner = accounts.authenticate(client.headers["Authorization"].split()[1])["id"]
    live_review.save_search(sid,owner,dict(query="First",papers=[dict(work_id="W1")]))
    live_review.save_fulltext(sid,owner,dict(papers=[dict(work_id="W1",found=True)]))
    live_review.save_fulltext(sid,owner,dict(papers=[dict(work_id="W2",found=False)]))
    saved = client.get("/discover/sessions/"+sid).json()
    assert saved["fulltext"]["n_requested"] == 2
    assert saved["fulltext"]["n_with_full_text"] == 1
    live_review.save_search(sid,owner,dict(query="Second",papers=[dict(work_id="W3")]))
    saved = client.get("/discover/sessions/"+sid).json()
    assert saved["project_name"] == "A"
    assert saved["search_history"][0]["query"] == "First"
    assert saved["search_history"][0]["fulltext"]["n_requested"] == 2
