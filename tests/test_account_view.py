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
    assert any("Google sign-in setup is pending" in info.value for info in at.info)
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


def test_welcome_skip_opens_home(monkeypatch):
    import account_view
    monkeypatch.setattr(account_view, "account_request", lambda *a, **kw: {"configured": False})
    at = AppTest.from_string("import streamlit as st\nfrom account_view import render_welcome\nrender_welcome()\nst.write('Home content')")
    at.run()
    # The login page is the whole page until a visitor chooses: the logo and
    # name render, and nothing behind it does.
    assert any("Beyond Retrieval" in m.value for m in at.markdown)
    assert not any(m.value == "Home content" for m in at.markdown)
    next(b for b in at.button if b.label == "Continue as a guest").click().run()
    assert any(m.value == "Home content" for m in at.markdown)


def test_welcome_offers_google_when_configured(monkeypatch):
    import account_view
    monkeypatch.setattr(account_view, "account_request", lambda *a, **kw: {"configured": True})
    at = AppTest.from_string("from account_view import render_welcome\nrender_welcome()")
    at.run()
    assert not at.exception
    # AppTest has no typed accessor for link_button, so read the proto.
    links = at.get("link_button")
    assert any(link.proto.label == "Continue with Google" for link in links)
    assert any(link.proto.url.endswith("/auth/google/start") for link in links)


def test_welcome_says_so_when_google_is_not_configured(monkeypatch):
    import account_view
    monkeypatch.setattr(account_view, "account_request", lambda *a, **kw: {"configured": False})
    at = AppTest.from_string("from account_view import render_welcome\nrender_welcome()")
    at.run()
    assert not at.exception
    assert not at.get("link_button")
    assert any("setup is pending" in i.value for i in at.info)
