import time
import pytest
from fastapi.testclient import TestClient
from slr.services import accounts, live_review
from slr.api.app import app
from slr.api import auth

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(live_review, "STORE", tmp_path / "accounts.sqlite3")
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "test-client")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "test-secret")
    return TestClient(app)

def identity(subject="one"):
    ticket, binding = accounts.issue_ticket(dict(sub=subject, email=subject+"@example.test", name=subject, email_verified=True))
    return accounts.exchange_ticket(ticket, binding)

def test_ticket_binding_replay_and_logout(client):
    ticket, binding = accounts.issue_ticket(dict(sub="one", email="a@example.test", email_verified=True))
    assert client.post("/auth/exchange", json=dict(ticket=ticket, binding="wrong")).status_code == 401
    response = client.post("/auth/exchange", json=dict(ticket=ticket, binding=binding))
    assert response.status_code == 200
    assert client.post("/auth/exchange", json=dict(ticket=ticket, binding=binding)).status_code == 401
    token = response.json()["token"]
    assert accounts.authenticate(token)["email"] == "a@example.test"
    assert client.post("/auth/logout", headers={"Authorization": "Bearer "+token}).status_code == 200
    with pytest.raises(ValueError):
        accounts.authenticate(token)

def test_identity_uses_subject_and_expiry(client):
    first, second = identity(), identity()
    assert first["id"] == second["id"]
    with accounts.connect() as conn:
        conn.execute("UPDATE account_tokens SET expires=0")
    with pytest.raises(ValueError):
        accounts.authenticate(first["token"])
    with pytest.raises(ValueError):
        accounts.issue_ticket(dict(sub="bad", email="bad@example.test", email_verified=False))

def test_private_review_library(client):
    one, two = identity("one"), identity("two")
    saved = live_review.create_session(dict(query="Private topic", papers=[]), one["id"])
    sid = saved["session_id"]
    assert client.get("/discover/sessions").status_code == 401
    h1 = {"Authorization": "Bearer "+one["token"]}
    h2 = {"Authorization": "Bearer "+two["token"]}
    assert len(client.get("/discover/sessions", headers=h1).json()) == 1
    assert client.get("/discover/sessions", headers=h2).json() == []
    assert client.get("/discover/sessions/"+sid, headers=h1).status_code == 200
    assert client.get("/discover/sessions/"+sid, headers=h2).status_code == 404
    assert client.post("/discover/sessions/"+sid+"/semantic-map", headers=h2).status_code == 404
    action = dict(work_id="W1", decision="exclude")
    assert client.post("/discover/sessions/"+sid+"/review", headers=h2, json=action).status_code == 404

def test_google_callback_state_and_nonce(client, monkeypatch):
    assert client.get("/auth/google/callback?state=bad&code=bad").status_code == 400
    start = client.get("/auth/google/start", follow_redirects=False)
    from urllib.parse import urlparse, parse_qs
    params = parse_qs(urlparse(start.headers["location"]).query)
    assert params["code_challenge_method"] == ["S256"]
    class Response:
        def raise_for_status(self): pass
        def json(self): return {"id_token": "mock-token"}
    monkeypatch.setattr(auth.httpx, "post", lambda *a, **k: Response())
    claims = dict(sub="google-one", email="a@example.test", email_verified=True, nonce=params["nonce"][0])
    monkeypatch.setattr(auth.id_token, "verify_oauth2_token", lambda *a, **k: claims)
    response = client.get("/auth/google/callback", params=dict(state=params["state"][0], code="test-code"), follow_redirects=False)
    assert response.status_code == 303
    ticket = parse_qs(urlparse(response.headers["location"]).query)["login_ticket"][0]
    binding = client.cookies.get("br_login_binding")
    assert client.post("/auth/exchange", json=dict(ticket=ticket, binding=binding)).status_code == 200
    assert client.get("/auth/google/callback", params=dict(state=params["state"][0], code="test-code")).status_code == 400
    start = client.get("/auth/google/start", follow_redirects=False)
    state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]
    claims["nonce"] = "wrong"
    assert client.get("/auth/google/callback", params=dict(state=state, code="test-code")).status_code == 400

def test_unconfigured(client, monkeypatch):
    monkeypatch.delenv("GOOGLE_CLIENT_ID")
    assert client.get("/auth/config").json() == {"configured": False}
    assert client.get("/auth/google/start").status_code == 503


def test_login_ticket_expiry(client):
    ticket, binding = accounts.issue_ticket(dict(sub="one", email="a@example.test", email_verified=True))
    with accounts.connect() as conn:
        conn.execute("UPDATE login_tickets SET expires=0")
    assert client.post("/auth/exchange", json=dict(ticket=ticket, binding=binding)).status_code == 401


def test_google_state_expiry(client):
    state, nonce, verifier = accounts.begin()
    with accounts.connect() as conn:
        conn.execute("UPDATE oauth_states SET expires=0")
    with pytest.raises(ValueError):
        accounts.consume_state(state)
