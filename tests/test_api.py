"""Tests for the API. Every route either reads what a harness already wrote
or calls the same service functions the CLIs do -- these tests check the
wiring, not the underlying logic (which has its own tests already).
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from slr.api import app as app_module
from slr.api.deps import get_conn
from slr.db import connect


@pytest.fixture()
def conn(tmp_path):
    c = connect(tmp_path / "test.db", check_same_thread=False)
    for wid, title, inc in [("W1", "Trial of X in Y patients", 1), ("W2", "A survey of Z", 0)]:
        c.execute(
            "INSERT INTO work (review, work_id, title, abstract, year, venue, doi, label_included) "
            "VALUES ('R1', ?, ?, 'Randomised trial. Further studies are needed.', 2020, 'J. Testing', NULL, ?)",
            (wid, title, inc),
        )
    c.execute(
        "INSERT INTO review_criteria (review, criteria, source, sha256) VALUES ('R1', 'Include RCTs.', 'test', 'x')"
    )
    c.commit()
    yield c
    c.close()


@pytest.fixture()
def client(conn, monkeypatch, tmp_path):
    monkeypatch.setattr(app_module.live_review, "STORE", tmp_path / "live.sqlite3")
    monkeypatch.setattr(app_module, "PROMPTS_DIR", app_module.PROMPTS_DIR)  # real prompts/ dir, read-only

    def override_get_conn():
        yield conn

    app_module.app.dependency_overrides[get_conn] = override_get_conn
    yield TestClient(app_module.app)
    app_module.app.dependency_overrides.clear()


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def _record_search_query(monkeypatch, seen: dict):
    """Record the query the search actually received, and return nothing."""

    def fake_run_discover(conn, query, **kwargs):
        seen["query"] = query
        return []

    monkeypatch.setattr(app_module, "run_discover", fake_run_discover)


def _discover_paper(work_id, decision_status, verified, *, extracted):
    """Build one DiscoverPaper the way run_discover would."""
    from slr.services.discover import DiscoverPaper
    from slr.services.extract import FieldExtraction
    from slr.services.gap import GapExtraction
    from slr.services.screen import Decision

    fields = gap = None
    if extracted:
        fields = [
            FieldExtraction(
                work_id=work_id, review="_discover", field_name=name, value="v",
                evidence_span="a genuinely long quote here", span_verified=True,
                verify_note="exact_after_normalisation", from_cache=False,
                tokens_in=1, tokens_out=1, cost_usd=0.0, latency_ms=1,
            )
            for name in ("study_design", "sample_size", "country", "key_finding")
        ]
        gap = GapExtraction(
            work_id=work_id, review="_discover", value="gap_stated",
            evidence_span="remains an important open question for future work",
            span_verified=True, verify_note="exact_after_normalisation", from_cache=False,
            tokens_in=1, tokens_out=1, cost_usd=0.0, latency_ms=1,
        )
    return DiscoverPaper(
        work_id=work_id, title=f"Paper {work_id}", year=2020, source_url=None,
        fields=fields, gap=gap,
        decision=Decision(
            work_id=work_id, review="_discover", decision=decision_status, confidence=0.9,
            evidence_span="a genuinely long quote here", span_verified=verified,
            verify_note="exact_after_normalisation" if verified else "not_found",
            from_cache=False, tokens_in=1, tokens_out=1, cost_usd=0.0, latency_ms=1,
        ),
    )


# --------------------------------------------------------------------------
# Chart routes
#
# Wiring only: the shaping has its own tests in test_charts.py against the
# real database. What matters here is that each route finds the right run,
# 404s when there isn't one, and -- for the semantic map -- reports an
# absent embedding cache as a normal state rather than an error.
# --------------------------------------------------------------------------


RUN_DIR_NAME = "20260101T000000Z-aaa"  # run directories sort chronologically


def _screened(conn, run_id=RUN_DIR_NAME, review="R1"):
    """Decisions must be written under the *run directory's* name: the chart
    routes resolve "current run" from runs/, then query the tables with that
    id, so a mismatched run_id silently returns nothing."""
    conn.execute(
        "INSERT OR IGNORE INTO run (run_id, config_hash, model, prompt_version) "
        "VALUES (?, 'h', 'qwen2.5:7b-instruct', 'screen_v1')",
        (run_id,),
    )
    for wid, decision, confidence, verified, note in [
        ("W1", "include", 0.9, 1, "exact_after_normalisation"),
        ("W2", "unverified", 0.8, 0, "not_found"),
    ]:
        conn.execute(
            "INSERT INTO screening_decision (run_id, review, work_id, decision, confidence, "
            "evidence_span, span_verified, verify_note, latency_ms, from_cache) "
            "VALUES (?, ?, ?, ?, ?, 's', ?, ?, 1500, 0)",
            (run_id, review, wid, decision, confidence, verified, note),
        )
    conn.commit()


def test_fulltext_note_says_how_much_of_the_paper_was_read(client, monkeypatch):
    project_id = _fulltext_project(client)
    """Observed on PMC10248995: a 75,211-character paper, of which the model
    sees 24,000. A field marked "not stated" may simply be in the two thirds
    that were cut, and a reader who is not told that will read the gap as a
    failure of the extraction.
    """
    from slr.adapters import fulltext as ftmod
    from slr.adapters.fulltext import Availability, parse_jats

    long_xml = (
        "<article><body>"
        + "".join(
            f"<sec><title>Section {i}</title><p>{'content sentence here. ' * 300}</p></sec>"
            for i in range(12)
        )
        + "</body></article>"
    )
    paper = parse_jats(long_xml)
    monkeypatch.setattr(
        ftmod, "get_full_text",
        lambda doi=None, title=None: (paper, Availability(found=True, pmcid="PMC1", is_open_access=True)),
    )

    class _Provider:
        name, model = "fake", "fake-1"

        def complete(self, prompt, **kw):
            from slr.adapters.llm import Completion

            payload = {
                name: {"value": "not_stated", "evidence_span": ""}
                for name in (
                    "primary_outcome", "effect_size", "statistical_methods",
                    "sample_characteristics", "limitations",
                )
            }
            return Completion(text=json.dumps(payload), tokens_in=1, tokens_out=1)

    monkeypatch.setattr(app_module, "build_provider", lambda *a, **k: _Provider())

    body = client.post(
        "/discover/fulltext",
        json={"project_id": project_id, "papers": [{"work_id": "W1", "title": "A long paper", "doi": "10.1/x"}]},
    ).json()
    note = body["papers"][0]["note"]
    assert "the model was shown the first" in note
    assert "may be in the part that was cut" in note


def test_a_short_paper_does_not_claim_to_be_truncated(client, monkeypatch):
    project_id = _fulltext_project(client)
    from slr.adapters import fulltext as ftmod
    from slr.adapters.fulltext import Availability, parse_jats

    short = parse_jats(
        "<article><body><sec><title>Results</title><p>It worked well.</p></sec></body></article>"
    )
    monkeypatch.setattr(
        ftmod, "get_full_text",
        lambda doi=None, title=None: (short, Availability(found=True, pmcid="PMC1", is_open_access=True)),
    )

    class _Provider:
        name, model = "fake", "fake-1"

        def complete(self, prompt, **kw):
            from slr.adapters.llm import Completion

            payload = {
                name: {"value": "not_stated", "evidence_span": ""}
                for name in (
                    "primary_outcome", "effect_size", "statistical_methods",
                    "sample_characteristics", "limitations",
                )
            }
            return Completion(text=json.dumps(payload), tokens_in=1, tokens_out=1)

    monkeypatch.setattr(app_module, "build_provider", lambda *a, **k: _Provider())
    body = client.post(
        "/discover/fulltext",
        json={"project_id": project_id, "papers": [{"work_id": "W1", "title": "Short", "doi": "10.1/x"}]},
    ).json()
    assert "was shown the first" not in body["papers"][0]["note"]


def test_unavailable_fulltext_returns_all_eight_source_statuses(client, monkeypatch):
    project_id = _fulltext_project(client)
    from slr.adapters import fulltext as ftmod
    from slr.adapters.fulltext import Availability
    monkeypatch.setattr(ftmod, "get_full_text", lambda **kw: (None, Availability(found=True, reason="paywalled")))
    body = client.post("/discover/fulltext", json={"project_id": project_id, "papers": [{"work_id": "W1", "doi": "10.1/x"}]}).json()
    assert len(body["papers"][0]["coverage"]) == 8
    assert all(c["status"] == "source_unavailable" for c in body["papers"][0]["coverage"])


def test_asset_route_only_serves_known_cached_files(client, monkeypatch, tmp_path):
    from slr.adapters import fulltext_assets
    import hashlib
    monkeypatch.setattr(fulltext_assets, "ASSETS_DIR", tmp_path)
    asset_id = hashlib.sha256(b"a,b\n1,2").hexdigest()
    directory = tmp_path / "PMC123"
    directory.mkdir()
    (directory / asset_id).write_bytes(b"a,b\n1,2")
    (directory / "manifest.json").write_text(json.dumps({"files": [{"asset_id": asset_id, "name": "data.csv", "media_type": "application/octet-stream"}]}))
    response = client.get(f"/fulltext/assets/PMC123/{asset_id}")
    assert response.status_code == 200
    assert response.content == b"a,b\n1,2"
    assert "attachment" in response.headers["content-disposition"]
    assert response.headers["x-content-type-options"] == "nosniff"
    assert client.get(f"/fulltext/assets/not-pmc/{asset_id}").status_code == 404
    assert client.get("/fulltext/assets/PMC123/" + "0" * 64).status_code == 404


def _fulltext_project(client):
    from slr.services import accounts
    ticket, binding = accounts.issue_ticket(dict(sub="fulltext-owner", email="ft@example.test", email_verified=True))
    client.headers["Authorization"] = "Bearer " + accounts.exchange_ticket(ticket, binding)["token"]
    return client.post("/projects", json={"name": "Full text research"}).json()["session_id"]


# --------------------------------------------------------------------------
# A retrieval strategy the install or the cache can't actually serve.
# Found walking the dashboard through its own interface: a dense query over a
# review with no cached vectors reached the page as a bare "500 Internal
# Server Error". True, and useless -- the caller could say nothing about why.
# --------------------------------------------------------------------------


def test_suggest_returns_ranked_papers_with_relevance_and_gaps(client, monkeypatch):
    import slr.services.suggest as suggest_module
    from slr.services.gap import GapExtraction
    from slr.services.screen import Decision
    from slr.services.suggest import SuggestResult, Suggestion

    def decision(work_id, status, verified):
        return Decision(work_id=work_id, review="_discover", decision=status, confidence=0.8,
                        evidence_span="a genuinely long quote here", span_verified=verified,
                        verify_note="exact_after_normalisation" if verified else "not_found",
                        from_cache=False, tokens_in=1, tokens_out=1, cost_usd=0.0, latency_ms=1)

    def gap(work_id, stated):
        return GapExtraction(work_id=work_id, review="_discover",
                             value="gap_stated" if stated else "not_stated",
                             evidence_span="effects remain unknown" if stated else None,
                             span_verified=stated, verify_note="exact_after_normalisation",
                             from_cache=False, tokens_in=1, tokens_out=1, cost_usd=0.0, latency_ms=1)

    def fake_suggest(conn, question, **kwargs):
        assert question == "vitamin D and asthma"
        assert kwargs["n"] == 2
        row = lambda i: {"work_id": f"W{i}", "title": f"Paper {i}", "abstract": "abs", "year": 2020,
                         "doi": f"10.1/{i}", "source_url": None}
        return SuggestResult(
            question=question, n_candidates=40, ranking="specter2", ranking_note="Ranked by SPECTER2.",
            suggestions=[
                Suggestion(row(1), 0.9, decision("W1", "include", True), gap("W1", True), 0.7),
                Suggestion(row(2), 0.8, decision("W2", "include", False), gap("W2", False)),
            ],
        )

    monkeypatch.setattr(suggest_module, "suggest", fake_suggest)
    monkeypatch.setattr(app_module, "suggest_embedder", lambda: None)

    resp = client.post("/suggest", json={"query": "vitamin D and asthma", "n": 2})
    assert resp.status_code == 200
    body = resp.json()
    assert body["n_candidates"] == 40 and body["ranking"] == "specter2"
    assert body["n_included"] == 1, "an unverified include is a referral, not a yes"
    assert body["n_referred"] == 1
    assert body["n_gaps"] == 1
    first = body["papers"][0]
    assert first["relevance"] == 0.9 and first["gap_match"] == 0.7
    assert first["doi"] == "10.1/1"
    assert first["gap"]["quote"] == "effects remain unknown"


def test_suggest_rejects_an_empty_question_and_too_many_papers(client):
    assert client.post("/suggest", json={"query": ""}).status_code == 422
    assert client.post("/suggest", json={"query": "q", "n": 100}).status_code == 422


def test_export_needs_a_signed_in_owner(client):
    assert client.post("/projects/someone-elses/export").status_code == 401
