"""The API behind the dashboard panels.

Every route reads what a harness already wrote (``screening_decision``,
``extraction``, ``gap_statement``, and the run directories under
``runs/``) or calls a service function directly -- no route computes a
figure a CLI run wouldn't also produce. The one route that writes new data,
``POST /query/screen``, is a small, capped live screening for the "complete
a query" usability test (rule 2/3 don't apply to it the way they do to a
reported run: it's an interactive demo, not a figure for the report, so it
skips ``--require-clean`` and writes to an ``api-*`` run_id that
``report_tables.py`` and the run-index in this module both ignore).
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from slr.adapters.llm import BudgetExceeded, CacheMismatch, Meter, build_provider
from slr.api.deps import DB_PATH, PROMPTS_DIR, RUNS_DIR, get_conn
from slr.api.runs_index import latest_extract_run, latest_gap_run, latest_screen_run
from slr.api.schemas import (
    FieldValue,
    GapStatementOut,
    GapValue,
    OverrideRequest,
    OverrideResult,
    OverrideSummaryOut,
    PaperDetail,
    PaperSummary,
    QueryRequest,
    RankedPaper,
    ReviewSummary,
    ScreenRequest,
    ScreenResult,
)
from slr.eval.metrics import load_labels
from slr.services import criteria as criteria_service
from slr.services import retrieve
from slr.services.override import ModelDecision, model_decision, override_summary, record_override
from slr.services.screen import load_prompt_template, persist as persist_screening, screen_record

# Fixed metadata about the six-review corpus (CLAUDE.md's evaluation-corpus
# table). Not stored in the database -- a review's domain doesn't change --
# same precedent as criteria.DRAFT_CRITERIA's per-review constants.
REVIEW_DOMAINS = {
    "Radjenovic_2013": "Software engineering",
    "Smid_2020": "Computer science",
    "van_der_Waal_2022": "Medicine",
    "Menon_2022": "Medicine",
    "van_der_Valk_2021": "Medicine, psychology",
    "Nelson_2002": "Medicine",
}

app = FastAPI(title="Beyond Retrieval API")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)


@app.get("/health")
def health():
    return {"status": "ok"}


# --------------------------------------------------------------------------
# Reviews
# --------------------------------------------------------------------------


@app.get("/reviews", response_model=list[ReviewSummary])
def list_reviews(conn: sqlite3.Connection = Depends(get_conn)):
    reviews = [r["review"] for r in conn.execute("SELECT DISTINCT review FROM work ORDER BY review")]
    out = []
    for review in reviews:
        labels = load_labels(conn, review)
        n = len(labels)
        n_inc = sum(labels.values())
        crit = criteria_service.for_review(conn, review)
        out.append(
            ReviewSummary(
                review=review,
                domain=REVIEW_DOMAINS.get(review),
                n_records=n,
                n_included=n_inc,
                prevalence=(n_inc / n) if n else 0.0,
                criteria_status=crit.status,
                screen_run=latest_screen_run(RUNS_DIR, review),
                extract_run=latest_extract_run(RUNS_DIR, review),
                gap_run=latest_gap_run(RUNS_DIR, review),
            )
        )
    return out


@app.get("/reviews/{review}/metrics")
def review_metrics(review: str, run_id: str | None = None, conn: sqlite3.Connection = Depends(get_conn)):
    """The latest (or a named) screening run's own per-review metrics -- the RQ1 numbers."""
    rid = run_id or latest_screen_run(RUNS_DIR, review)
    if rid is None:
        raise HTTPException(404, f"no screening run found for {review!r}")
    path = RUNS_DIR / rid / "metrics.json"
    if not path.exists():
        raise HTTPException(404, f"run {rid!r} has no metrics.json")
    data = json.loads(path.read_text(encoding="utf-8"))
    for m in data.get("per_review", []):
        if m["review"] == review:
            return {"run_id": rid, **m}
    raise HTTPException(404, f"run {rid!r} does not cover {review!r}")


@app.get("/reviews/{review}/criteria")
def review_criteria(review: str, conn: sqlite3.Connection = Depends(get_conn)):
    c = criteria_service.for_review(conn, review)
    return {"review": review, "text": c.text, "status": c.status, "source": c.source}


@app.get("/reviews/{review}/extraction-summary")
def extraction_summary(review: str, run_id: str | None = None, conn: sqlite3.Connection = Depends(get_conn)):
    """Per-field verified/not_stated/unverified counts -- the Extraction panel's coverage bars.

    One aggregate query per field rather than N calls to the per-paper
    detail route; still nothing report_tables.py-style: a straight count
    over the extraction table's own rows.
    """
    rid = run_id or latest_extract_run(RUNS_DIR, review)
    if rid is None:
        raise HTTPException(404, f"no extraction run found for {review!r}")
    fields = {}
    for row in conn.execute(
        "SELECT field_name, "
        " SUM(CASE WHEN verify_note = 'not_stated' THEN 1 ELSE 0 END) AS not_stated,"
        " SUM(CASE WHEN verify_note != 'not_stated' AND span_verified = 1 THEN 1 ELSE 0 END) AS verified,"
        " SUM(CASE WHEN verify_note != 'not_stated' AND span_verified = 0 THEN 1 ELSE 0 END) AS unverified "
        "FROM extraction WHERE run_id = ? AND review = ? GROUP BY field_name",
        (rid, review),
    ):
        fields[row["field_name"]] = {
            "verified": row["verified"],
            "not_stated": row["not_stated"],
            "unverified": row["unverified"],
        }
    return {"run_id": rid, "review": review, "fields": fields}


# --------------------------------------------------------------------------
# Papers
# --------------------------------------------------------------------------


def _paper_summary(row: sqlite3.Row) -> PaperSummary:
    return PaperSummary(
        work_id=row["work_id"],
        title=row["title"],
        year=row["year"],
        venue=row["venue"],
        decision=row["decision"],
        confidence=row["confidence"],
        span_verified=bool(row["span_verified"]) if row["span_verified"] is not None else None,
    )


@app.get("/reviews/{review}/papers", response_model=list[PaperSummary])
def list_papers(
    review: str,
    run_id: str | None = None,
    decision: str | None = Query(default=None, description="include | exclude | unverified | error"),
    verified_only: bool = False,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    conn: sqlite3.Connection = Depends(get_conn),
):
    rid = run_id or latest_screen_run(RUNS_DIR, review)
    if rid is None:
        raise HTTPException(404, f"no screening run found for {review!r}")
    sql = (
        "SELECT w.work_id, w.title, w.year, w.venue, sd.decision, sd.confidence, sd.span_verified "
        "FROM work w LEFT JOIN screening_decision sd "
        "  ON sd.run_id = ? AND sd.review = w.review AND sd.work_id = w.work_id "
        "WHERE w.review = ?"
    )
    params: list = [rid, review]
    if decision:
        sql += " AND sd.decision = ?"
        params.append(decision)
    if verified_only:
        sql += " AND sd.span_verified = 1"
    sql += " ORDER BY w.work_id LIMIT ? OFFSET ?"
    params += [limit, offset]
    rows = conn.execute(sql, params).fetchall()
    return [_paper_summary(r) for r in rows]


def _field_value(row: sqlite3.Row | None) -> FieldValue:
    if row is None:
        return FieldValue(status="missing")
    if row["verify_note"] == "not_stated":
        return FieldValue(status="not_stated")
    if row["span_verified"]:
        return FieldValue(status="verified", value=row["value"], quote=row["evidence_span"], note=row["verify_note"])
    return FieldValue(status="unverified", quote=row["evidence_span"], note=row["verify_note"])


def _gap_value(row: sqlite3.Row | None) -> GapValue:
    if row is None:
        return GapValue(status="missing")
    if row["value"] not in ("gap_stated", "not_stated"):
        return GapValue(status="failed", note=row["verify_note"])
    if row["value"] == "not_stated":
        return GapValue(status="not_stated")
    kind = None
    if row["rating"] == "valid":
        kind = "motivating" if "motivation" in (row["rating_note"] or "") else "open"
    return GapValue(status="gap_stated", quote=row["evidence_span"], rating=row["rating"], kind=kind, note=row["rating_note"])


@app.get("/reviews/{review}/papers/{work_id:path}", response_model=PaperDetail)
def paper_detail(
    review: str,
    work_id: str,
    screen_run: str | None = None,
    extract_run: str | None = None,
    gap_run: str | None = None,
    conn: sqlite3.Connection = Depends(get_conn),
):
    work = conn.execute("SELECT * FROM work WHERE review = ? AND work_id = ?", (review, work_id)).fetchone()
    if work is None:
        raise HTTPException(404, f"{review}/{work_id} not found")

    srid = screen_run or latest_screen_run(RUNS_DIR, review)
    sd = None
    if srid:
        sd = conn.execute(
            "SELECT decision, confidence, evidence_span, span_verified, verify_note "
            "FROM screening_decision WHERE run_id = ? AND review = ? AND work_id = ?",
            (srid, review, work_id),
        ).fetchone()

    erid = extract_run or latest_extract_run(RUNS_DIR, review)
    fields: dict[str, sqlite3.Row] = {}
    if erid:
        for r in conn.execute(
            "SELECT field_name, value, evidence_span, span_verified, verify_note "
            "FROM extraction WHERE run_id = ? AND review = ? AND work_id = ?",
            (erid, review, work_id),
        ):
            fields[r["field_name"]] = r

    grid = gap_run or latest_gap_run(RUNS_DIR, review)
    gap_row = None
    if grid:
        gap_row = conn.execute(
            "SELECT value, evidence_span, rating, rating_note, verify_note "
            "FROM gap_statement WHERE run_id = ? AND review = ? AND work_id = ?",
            (grid, review, work_id),
        ).fetchone()

    return PaperDetail(
        work_id=work_id,
        title=work["title"],
        year=work["year"],
        venue=work["venue"],
        doi=work["doi"],
        decision=sd["decision"] if sd else None,
        confidence=sd["confidence"] if sd else None,
        span_verified=bool(sd["span_verified"]) if sd else None,
        screen_quote=sd["evidence_span"] if sd else None,
        screen_note=sd["verify_note"] if sd else None,
        study_design=_field_value(fields.get("study_design")),
        sample_size=_field_value(fields.get("sample_size")),
        country=_field_value(fields.get("country")),
        key_finding=_field_value(fields.get("key_finding")),
        gap=_gap_value(gap_row),
    )


# --------------------------------------------------------------------------
# Gap statements
# --------------------------------------------------------------------------


@app.get("/reviews/{review}/gaps", response_model=list[GapStatementOut])
def list_gaps(review: str, run_id: str | None = None, conn: sqlite3.Connection = Depends(get_conn)):
    rid = run_id or latest_gap_run(RUNS_DIR, review)
    if rid is None:
        raise HTTPException(404, f"no gap-discovery run found for {review!r}")
    rows = conn.execute(
        "SELECT g.work_id, w.title, g.value, g.evidence_span, g.rating, g.rating_note "
        "FROM gap_statement g JOIN work w ON g.review = w.review AND g.work_id = w.work_id "
        "WHERE g.run_id = ? AND g.review = ? AND g.value = 'gap_stated' ORDER BY g.work_id",
        (rid, review),
    ).fetchall()
    out = []
    for r in rows:
        kind = None
        if r["rating"] == "valid":
            kind = "motivating" if "motivation" in (r["rating_note"] or "") else "open"
        out.append(GapStatementOut(work_id=r["work_id"], title=r["title"], status="gap_stated", quote=r["evidence_span"], rating=r["rating"], kind=kind))
    return out


# --------------------------------------------------------------------------
# Overrides
# --------------------------------------------------------------------------


@app.post("/overrides", response_model=OverrideResult)
def create_override(req: OverrideRequest, conn: sqlite3.Connection = Depends(get_conn)):
    before: ModelDecision | None = model_decision(conn, req.run_id, req.review, req.work_id)
    if before is None:
        raise HTTPException(404, f"{req.review}/{req.work_id} was not screened in run {req.run_id!r}")
    record_override(conn, run_id=req.run_id, review=req.review, work_id=req.work_id, decision=req.decision, rationale=req.rationale)
    return OverrideResult(
        work_id=req.work_id,
        model_decision=before.decision,
        model_verified=before.span_verified,
        human_decision=req.decision,
        changed=before.decision != req.decision,
    )


@app.get("/reviews/{review}/overrides", response_model=OverrideSummaryOut)
def get_override_summary(review: str, run_id: str, conn: sqlite3.Connection = Depends(get_conn)):
    s = override_summary(conn, run_id, review)
    return OverrideSummaryOut(
        n_overrides=s.n_overrides,
        n_changed=s.n_changed,
        n_confirmed=s.n_confirmed,
        override_rate=s.override_rate,
        by_model_decision=s.by_model_decision,
    )


# --------------------------------------------------------------------------
# Query: rank (fast, no LLM), then optionally screen a small live batch
# --------------------------------------------------------------------------


@app.post("/query", response_model=list[RankedPaper])
def query(req: QueryRequest, conn: sqlite3.Connection = Depends(get_conn)):
    if req.strategy not in retrieve.STRATEGIES:
        raise HTTPException(400, f"strategy must be one of {retrieve.STRATEGIES}")
    query_text = req.query_text
    if req.strategy != "random" and not query_text:
        query_text = criteria_service.for_review(conn, req.review).text
    try:
        rows = retrieve.rank(conn, req.strategy, req.review, seed=42, query=query_text, limit=req.top_n)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return [RankedPaper(rank=i + 1, work_id=r["work_id"], title=r["title"], year=r["year"]) for i, r in enumerate(rows)]


@app.post("/query/screen", response_model=list[ScreenResult])
def query_screen(req: ScreenRequest, conn: sqlite3.Connection = Depends(get_conn)):
    # req.work_ids is capped at the schema level (ScreenRequest.work_ids, max_length)
    criteria = criteria_service.for_review(conn, req.review).text
    provider = build_provider("ollama", req.model)
    template = load_prompt_template(PROMPTS_DIR / f"{req.prompt_version}.txt")
    meter = Meter(ceiling_usd=0.0, usd_per_1m_input=0.0, usd_per_1m_output=0.0)
    run_id = f"api-{datetime.now(timezone.utc):%Y%m%dT%H%M%S%fZ}"
    conn.execute(
        "INSERT INTO run (run_id, config_hash, config_name, provider, model, prompt_version, started_at) "
        "VALUES (?, 'api', 'interactive query', 'ollama', ?, ?, ?)",
        (run_id, req.model, req.prompt_version, datetime.now(timezone.utc).isoformat()),
    )

    results = []
    for work_id in req.work_ids:
        row = conn.execute("SELECT * FROM work WHERE review = ? AND work_id = ?", (req.review, work_id)).fetchone()
        if row is None:
            continue
        try:
            decision = screen_record(
                row,
                provider=provider,
                template=template,
                criteria=criteria,
                meter=meter,
                conn=conn,
                prompt_version=req.prompt_version,
                temperature=0.0,
                max_tokens=512,
                seed=42,
                use_cache=True,
            )
        except CacheMismatch as exc:
            raise HTTPException(409, str(exc)) from exc
        except BudgetExceeded as exc:
            raise HTTPException(402, str(exc)) from exc
        persist_screening(conn, run_id, decision)
        results.append(
            ScreenResult(
                work_id=work_id,
                decision=decision.decision,
                confidence=decision.confidence,
                quote=decision.evidence_span,
                span_verified=decision.span_verified,
                verify_note=decision.verify_note,
                from_cache=decision.from_cache,
            )
        )
    conn.commit()
    return results
