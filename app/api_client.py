"""Thin HTTP client for the dashboard panels.

Every function is a direct call to one API route -- no logic lives here
beyond building the request and raising on a non-2xx response. The panels
never touch the database or a run directory themselves.
"""

from __future__ import annotations

import os

import httpx
import streamlit as st

API_URL = os.environ.get("SLR_API_URL", "http://127.0.0.1:8000")


def save_live_session(session):
    r = _client().post("/discover/sessions", json=session, headers=auth_headers())
    r.raise_for_status()
    return r.json()


def read_live_session(session_id):
    r = _client().get(f"/discover/sessions/{session_id}", headers=auth_headers())
    r.raise_for_status()
    return r.json()


def review_live_paper(session_id, action):
    r = _client().post(f"/discover/sessions/{session_id}/review", json=action, headers=auth_headers())
    r.raise_for_status()
    return r.json()


def map_live_session(session_id):
    r = _client().post(f"/discover/sessions/{session_id}/semantic-map", timeout=600, headers=auth_headers())
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


def list_reviews() -> list[dict]:
    r = _client().get("/reviews")
    r.raise_for_status()
    return r.json()


def review_metrics(review: str, run_id: str | None = None) -> dict:
    r = _client().get(f"/reviews/{review}/metrics", params={"run_id": run_id} if run_id else None)
    r.raise_for_status()
    return r.json()


def review_criteria(review: str) -> dict:
    r = _client().get(f"/reviews/{review}/criteria")
    r.raise_for_status()
    return r.json()


def extraction_summary(review: str, run_id: str | None = None) -> dict:
    r = _client().get(f"/reviews/{review}/extraction-summary", params={"run_id": run_id} if run_id else None)
    r.raise_for_status()
    return r.json()


def list_papers(review: str, **params) -> list[dict]:
    r = _client().get(f"/reviews/{review}/papers", params={k: v for k, v in params.items() if v is not None})
    r.raise_for_status()
    return r.json()


def paper_detail(review: str, work_id: str, **params) -> dict:
    r = _client().get(f"/reviews/{review}/papers/{work_id}", params={k: v for k, v in params.items() if v is not None})
    r.raise_for_status()
    return r.json()


def list_gaps(review: str, run_id: str | None = None) -> list[dict]:
    r = _client().get(f"/reviews/{review}/gaps", params={"run_id": run_id} if run_id else None)
    r.raise_for_status()
    return r.json()


def create_override(run_id: str, review: str, work_id: str, decision: str, rationale: str | None) -> dict:
    r = _client().post(
        "/overrides",
        json={"run_id": run_id, "review": review, "work_id": work_id, "decision": decision, "rationale": rationale},
    )
    r.raise_for_status()
    return r.json()


def override_summary(review: str, run_id: str) -> dict:
    r = _client().get(f"/reviews/{review}/overrides", params={"run_id": run_id})
    r.raise_for_status()
    return r.json()


def query_rank(review: str, strategy: str, query_text: str | None, top_n: int) -> list[dict]:
    r = _client().post(
        "/query", json={"review": review, "strategy": strategy, "query_text": query_text, "top_n": top_n}
    )
    r.raise_for_status()
    return r.json()


def query_screen(review: str, work_ids: list[str], model: str, prompt_version: str) -> list[dict]:
    r = _client().post(
        "/query/screen",
        json={"review": review, "work_ids": work_ids, "model": model, "prompt_version": prompt_version},
        timeout=600.0,  # live model calls, one per record
    )
    r.raise_for_status()
    return r.json()


def discover(
    query: str,
    limit: int = 5,
    criteria: str | None = None,
    fulltext: bool = False,
    expand: bool = False,
) -> dict:
    """One ad-hoc review session. Returns the session summary, not a bare list.

    ``criteria`` given, every result is screened against it and only verified
    includes are extracted; omitted, nothing is screened.
    """
    payload: dict = {"query": query, "limit": limit, "expand": expand}
    if st.session_state.get("active_project"):
        payload["project_id"] = st.session_state["active_project"]
    if criteria:
        payload["criteria"] = criteria
    if fulltext:
        payload["fulltext"] = True
    r = _client().post(
        "/discover",
        headers=auth_headers(),
        json=payload,
        # Live OpenAlex search, then up to three model calls per result
        # (screen, extract, gap) on local hardware.
        # Full text adds a Europe PMC lookup, a document fetch and another
        # model call per paper, so this can be slow on local inference.
        timeout=1800.0,
    )
    r.raise_for_status()
    return r.json()


# -- charts -----------------------------------------------------------------
# One function per chart route. Same rule as everything above: build the
# request, raise on a bad status, return the JSON. No shaping here -- that
# all happens in slr/eval/charts.py so the panels and the report agree.


def charts_corpus(review: str | None = None) -> dict:
    r = _client().get("/charts/corpus", params={"review": review} if review else None)
    r.raise_for_status()
    return r.json()


def charts_trust() -> dict:
    r = _client().get("/charts/trust")
    r.raise_for_status()
    return r.json()


def charts_confidence(review: str, run_id: str | None = None) -> dict:
    r = _client().get(
        f"/charts/reviews/{review}/confidence", params={"run_id": run_id} if run_id else None
    )
    r.raise_for_status()
    return r.json()


def charts_recall_curve(review: str, run_id: str | None = None) -> dict:
    r = _client().get(
        f"/charts/reviews/{review}/recall-curve", params={"run_id": run_id} if run_id else None
    )
    r.raise_for_status()
    return r.json()


def charts_extraction(review: str, run_id: str | None = None) -> dict:
    r = _client().get(
        f"/charts/reviews/{review}/extraction", params={"run_id": run_id} if run_id else None
    )
    r.raise_for_status()
    return r.json()


def charts_gaps() -> dict:
    r = _client().get("/charts/gaps")
    r.raise_for_status()
    return r.json()


def charts_semantic_map(review: str, max_points: int = 1500) -> dict:
    r = _client().get(
        f"/charts/reviews/{review}/semantic-map", params={"max_points": max_points}
    )
    r.raise_for_status()
    return r.json()


def charts_performance(review: str | None = None, run_id: str | None = None) -> dict:
    params = {k: v for k, v in {"review": review, "run_id": run_id}.items() if v}
    r = _client().get("/charts/performance", params=params or None)
    r.raise_for_status()
    return r.json()


def discover_fulltext(papers: list[dict]) -> dict:
    """Stage two: read the full text of the papers the reviewer chose.

    ``papers`` is a list of {work_id, title, doi}. Nothing is stored
    between the two calls, so the page sends back what it got.
    """
    r = _client().post(
        "/discover/fulltext",
        json={"papers": papers, "include_assets": True, "project_id": st.session_state.get("active_project")},
        headers=auth_headers(),
        # A Europe PMC lookup, a document fetch and a long model call per
        # paper, on local inference.
        timeout=1800.0,
    )
    r.raise_for_status()
    return r.json()


def auth_headers():
    token = st.session_state.get("google_account", {}).get("token")
    return {"Authorization": "Bearer " + token} if token else {}


def account_request(method, path, **kwargs):
    response = _client().request(method, path, headers=auth_headers(), **kwargs)
    response.raise_for_status()
    return response.json()
