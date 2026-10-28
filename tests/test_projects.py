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


def test_a_reopened_project_still_holds_the_gaps_read_from_the_body(client):
    """What the researcher keeps must survive closing the browser.

    The gaps a paper states in its body are the newest thing the tool
    finds, and they arrive after the search that created the project, so
    the round trip through the store is worth pinning.
    """
    login(client, "owner")
    sid = client.post("/projects", json={"name": "Probiotics"}).json()["session_id"]
    owner = accounts.authenticate(client.headers["Authorization"].split()[1])["id"]

    live_review.save_search(sid, owner, dict(query="Do probiotics help?", papers=[dict(work_id="W1")]))
    live_review.save_fulltext(sid, owner, dict(papers=[dict(
        work_id="W1", found=True,
        gaps=[{"value": "Optimal dose unknown", "section": "Conclusion",
               "quote": "Further research should establish the optimal dose."}],
        gaps_note="found", gaps_withheld=0, gaps_unsupported=1,
    )]))

    reopened = client.get("/discover/sessions/" + sid).json()
    paper = reopened["fulltext"]["papers"][0]
    assert paper["gaps"][0]["quote"] == "Further research should establish the optimal dose."
    assert paper["gaps"][0]["section"] == "Conclusion"
    # The counts behind the quotes survive too: a reader of the saved
    # project can still see what was withheld.
    assert paper["gaps_unsupported"] == 1


def test_exporting_a_project_returns_a_zip_a_researcher_can_open(client, monkeypatch):
    """The last thing the tool does, and the only one that leaves the screen.

    PDF fetching is turned off here: whether a publisher serves a file is
    not what this route is responsible for.
    """
    import io
    import zipfile

    from slr.services import export as export_service

    real_build = export_service.build_export
    monkeypatch.setattr(
        export_service, "build_export",
        lambda session, **kw: real_build(session, **{**kw, "fetch_pdfs": False}),
    )

    login(client, "owner")
    sid = client.post("/projects", json={"name": "Probiotics"}).json()["session_id"]
    owner = accounts.authenticate(client.headers["Authorization"].split()[1])["id"]
    live_review.save_search(sid, owner, dict(
        query="Do probiotics help?",
        papers=[dict(work_id="W1", title="A probiotic trial", decision=dict(
            status="include", quote="we randomised 120 adults", span_verified=True))],
    ))
    live_review.save_fulltext(sid, owner, dict(papers=[dict(
        work_id="W1", title="A probiotic trial", found=True, note="full text from PMC1",
        gaps=[{"value": "Optimal dose unknown", "section": "Conclusion",
               "quote": "Further research should establish the optimal dose."}],
    )]))

    r = client.post(f"/projects/{sid}/export")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/zip"

    with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
        assert zf.testzip() is None, "the zip is corrupt"
        names = zf.namelist()
        summary = next(n for n in names if n.endswith("summary.md"))
        assert "Further research should establish the optimal dose." in zf.read(summary).decode()
        assert any(n.endswith("README.txt") for n in names)
        assert any(n.endswith("summary.csv") for n in names)
