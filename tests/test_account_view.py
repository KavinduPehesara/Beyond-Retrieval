from pathlib import Path
import sys
from streamlit.testing.v1 import AppTest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))


def test_guest_google_setup_ui(monkeypatch):
    import account_view
    monkeypatch.setattr(account_view, "account_request", lambda *a, **kw: {"configured": False})
    at = AppTest.from_string("from account_view import render_account,render_library\nrender_account()\nrender_library()")
    at.run()
    assert not at.exception
    assert any(b.label == "Sign in" for b in at.button)
    assert not any(e.label == "Saved review ID" for e in at.text_input)


def test_saved_review_dropdown_hides_ids(monkeypatch):
    import account_view
    row = dict(session_id="private-id", query="Asthma study", n_found=2, created_at="2026-10-09")
    monkeypatch.setattr(account_view, "account_request", lambda *a, **kw: [row])
    at = AppTest.from_string("from account_view import render_library\nrender_library()")
    at.session_state["google_account"] = {"name": "Test researcher", "token": "test"}
    at.run()
    assert not at.exception
    assert at.selectbox[0].options == ["Asthma study · 2 papers"]
    assert not any(e.label == "Saved review ID" for e in at.text_input)


def test_welcome_is_a_dialog_over_the_app_not_a_page(monkeypatch):
    import account_view
    monkeypatch.setattr(account_view, "account_request", lambda *a, **kw: {"configured": False})
    at = AppTest.from_string("import streamlit as st\nfrom account_view import render_welcome\nrender_welcome()\nst.write('Home content')")
    at.run()
    assert not at.exception
    # The app renders behind the dialog rather than being replaced by it.
    assert any(m.value == "Home content" for m in at.markdown)
    assert any(b.label == "Continue as a guest" for b in at.button)


def test_welcome_is_shown_once_per_session(monkeypatch):
    import account_view
    monkeypatch.setattr(account_view, "account_request", lambda *a, **kw: {"configured": False})
    at = AppTest.from_string("from account_view import render_welcome\nrender_welcome()")
    at.run()
    assert at.session_state["welcome_shown"]
    at.run()
    assert not any(b.label == "Continue as a guest" for b in at.button)


def test_google_sign_in_stays_in_this_tab(monkeypatch):
    import account_view
    monkeypatch.setattr(account_view, "account_request", lambda *a, **kw: {"configured": True})
    at = AppTest.from_string("from account_view import render_welcome\nrender_welcome()")
    at.run()
    assert not at.exception
    assert not at.get("link_button"), "link_button always opens a new tab"
    link = next(m.value for m in at.markdown if "Continue with Google" in m.value)
    assert "/auth/google/start" in link and "target='_self'" in link


def test_welcome_says_so_when_google_is_not_configured(monkeypatch):
    import account_view
    monkeypatch.setattr(account_view, "account_request", lambda *a, **kw: {"configured": False})
    at = AppTest.from_string("from account_view import render_welcome\nrender_welcome()")
    at.run()
    assert not at.exception
    assert not any("Continue with Google" in m.value for m in at.markdown)
    assert any("setup is pending" in i.value for i in at.info)


def test_a_signed_out_visitor_gets_a_sign_in_button(monkeypatch):
    import account_view
    monkeypatch.setattr(account_view, "account_request", lambda *a, **kw: {"configured": True})
    at = AppTest.from_string("from account_view import render_account\nrender_account()")
    at.run()
    next(b for b in at.button if b.label == "Sign in").click().run()
    assert not at.exception
    assert any("Continue with Google" in m.value for m in at.markdown)


def test_a_reload_signs_back_in_from_the_browser_session_cookie(monkeypatch):
    import account_view
    calls = []

    def fake_request(method, path, **kw):
        calls.append((method, path, kw.get("json")))
        if path == "/auth/resume":
            return {"name": "Researcher", "email": "r@example.org", "token": "fresh"}
        return [] if path == "/discover/sessions" else {"configured": True}

    monkeypatch.setattr(account_view, "account_request", fake_request)
    monkeypatch.setattr(account_view, "_cookie", lambda name: "browser-secret" if name == "br_session" else "")
    at = AppTest.from_string("from account_view import render_account, render_welcome\nrender_account()\nrender_welcome()")
    at.run()
    assert not at.exception
    assert ("POST", "/auth/resume", {"session": "browser-secret"}) in calls
    assert at.session_state["google_account"]["token"] == "fresh"
    assert not any(b.label == "Continue as a guest" for b in at.button), "no welcome dialog for someone signed in"
    at.run()
    assert sum(1 for c in calls if c[1] == "/auth/resume") == 1, "tried once per page session"


def test_an_ended_browser_session_leaves_a_guest(monkeypatch):
    import account_view, httpx

    def fake_request(method, path, **kw):
        if path == "/auth/resume":
            raise httpx.HTTPStatusError("401", request=httpx.Request("POST", "http://x"), response=httpx.Response(401))
        return {"configured": True}

    monkeypatch.setattr(account_view, "account_request", fake_request)
    monkeypatch.setattr(account_view, "_cookie", lambda name: "old" if name == "br_session" else "")
    at = AppTest.from_string("from account_view import render_account\nrender_account()")
    at.run()
    assert not at.exception
    assert "google_account" not in at.session_state
    assert any(b.label == "Sign in" for b in at.button)
