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
