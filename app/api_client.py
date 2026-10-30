"""Thin HTTP client for the dashboard panels.

Every function is a direct call to one API route -- no logic lives here
beyond building the request and raising on a non-2xx response. The panels
never touch the database or a run directory themselves.
"""

from __future__ import annotations

import os
import time

import httpx
import streamlit as st

API_URL = os.environ.get("SLR_API_URL", "http://127.0.0.1:8000")


def read_live_session(session_id):
    r = _client().get(f"/discover/sessions/{session_id}", headers=auth_headers())
    r.raise_for_status()
    return r.json()


@st.cache_resource
def _client() -> httpx.Client:
    return httpx.Client(base_url=API_URL, timeout=120.0)


def health() -> bool:
    try:
        return _client().get("/health").status_code == 200
    except httpx.HTTPError:
        return False


def providers() -> dict:
    """The models this deployment can answer with, and which are usable now."""
    try:
        r = _client().get("/providers", timeout=10.0)
        r.raise_for_status()
        return r.json()
    except httpx.HTTPError:
        return {"default": "", "providers": []}


def _suggest_payload(query: str, n: int) -> dict:
    payload: dict = {"query": query, "n": n}
    if st.session_state.get("active_project"):
        payload["project_id"] = st.session_state["active_project"]
    return payload


def suggest(query: str, n: int = 20) -> dict:
    """Papers most worth reading for one research question, best first.

    Each comes with a relevance verdict and any stated research gap, both
    backed by a quote verified in the abstract.
    """
    r = _client().post(
        "/suggest",
        headers=auth_headers(),
        json=_suggest_payload(query, n),
        # A live OpenAlex search, a SPECTER2 pass, then two model calls per
        # suggested paper.
        timeout=1800.0,
    )
    r.raise_for_status()
    return r.json()


def suggest_watched(query: str, n: int, on_progress) -> dict:
    """The same search, reporting how far along it is while it runs.

    ``on_progress(percent, stage, done, total)`` is called as the job moves.
    Falls back to the single blocking call if this deployment has no job
    route, so an older backend still answers rather than failing.
    """
    started = _client().post(
        "/suggest/start", headers=auth_headers(), json=_suggest_payload(query, n), timeout=30.0
    )
    if started.status_code == 404:
        return suggest(query, n)
    started.raise_for_status()
    job_id = started.json()["job_id"]

    return _watch(job_id, on_progress, "The search")


def _watch(job_id: str, on_progress, what: str) -> dict:
    """Follow a job to its answer, reporting progress as it moves.

    Polled rather than streamed: Streamlit redraws the page top to bottom,
    so a short poll is both simpler and all the page can actually paint.
    """
    deadline = time.time() + 1800
    while time.time() < deadline:
        r = _client().get(f"/jobs/{job_id}", timeout=30.0)
        r.raise_for_status()
        body = r.json()
        on_progress(body["percent"], body["stage"], body["done"], body["total"])
        if body["finished"]:
            return body["result"]
        time.sleep(0.6)
    raise TimeoutError(f"{what} ran longer than half an hour and was abandoned.")

def _fulltext_payload(papers: list[dict]) -> dict:
    return {
        "papers": papers,
        "include_assets": True,
        "project_id": st.session_state.get("active_project"),
    }


def discover_fulltext_watched(papers: list[dict], on_progress) -> dict:
    """Read the chosen papers, reporting which one is being read.

    Each paper is a Europe PMC lookup, a document download and two long
    model calls, so this is the slowest thing the tool does and the one a
    spinner tells you least about.
    """
    started = _client().post(
        "/discover/fulltext/start", headers=auth_headers(), json=_fulltext_payload(papers), timeout=30.0
    )
    if started.status_code == 404:
        return discover_fulltext(papers)
    started.raise_for_status()
    return _watch(started.json()["job_id"], on_progress, "Reading the papers")


def discover_fulltext(papers: list[dict]) -> dict:
    """Stage two: read the full text of the papers the reviewer chose.

    ``papers`` is a list of {work_id, title, doi}. Nothing is stored
    between the two calls, so the page sends back what it got.
    """
    r = _client().post(
        "/discover/fulltext",
        json={
            "papers": papers,
            "include_assets": True,
            "project_id": st.session_state.get("active_project"),
            },
        headers=auth_headers(),
        # A Europe PMC lookup, a document fetch and a long model call per
        # paper, on local inference.
        timeout=1800.0,
    )
    r.raise_for_status()
    return r.json()


def export_project(session_id: str) -> tuple[str, bytes]:
    """The project's selected papers as one ZIP: PDFs, categorised data, tables, figures."""
    r = _client().post(
        f"/projects/{session_id}/export",
        headers=auth_headers(),
        # One OpenAlex lookup and up to four PDF downloads per paper.
        timeout=900.0,
    )
    r.raise_for_status()
    disposition = r.headers.get("content-disposition", "")
    name = disposition.split('filename="')[-1].rstrip('"') if 'filename="' in disposition else "research.zip"
    return name, r.content

def auth_headers():
    token = st.session_state.get("google_account", {}).get("token")
    return {"Authorization": "Bearer " + token} if token else {}


def account_request(method, path, **kwargs):
    response = _client().request(method, path, headers=auth_headers(), **kwargs)
    response.raise_for_status()
    return response.json()
