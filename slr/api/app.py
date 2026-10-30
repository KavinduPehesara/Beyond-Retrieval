"""The API behind the dashboard.

One research question, start to finish: ``POST /suggest`` searches live
literature and suggests the papers closest to the question, each with a
relevance verdict and any stated research gap backed by a verified quote;
``POST /discover/fulltext`` reads the papers the researcher picked; and
``POST /projects/{id}/export`` packages them, with their PDFs and categorised
data, as a ZIP. Projects are saved per Google account.

Nothing here touches the evaluation corpus or produces a reported figure:
there is no ground truth for a question typed a minute ago. The evaluation
lives in ``slr/eval`` and its CLI harnesses.
"""

from __future__ import annotations

import json
import sqlite3

import httpx
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from slr.adapters import fulltext_assets
from slr.adapters.llm import BudgetExceeded, CacheMismatch
from slr.api import jobs, providers
from slr.api.auth import current_account, optional_account
from slr.api.auth import router as auth_router
from slr.api.deps import PROMPTS_DIR, get_conn, new_conn
from slr.api.schemas import (
    ArmCostOut,
    DiscoverPaperOut,
    StatedGapOut,
    DiscoverSessionOut,
    FieldValue,
    FigureOut,
    FullTextPaperOut,
    FullTextRequest,
    FullTextSessionOut,
    GapValue,
    ModelVerdictOut,
    ProjectName,
    ScreenDecisionOut,
    SuggestRequest,
    TableOut,
)
from slr.services import live_review
from slr.services.extract_fulltext import build_source as build_fulltext_source
from slr.services.extract_fulltext import load_prompt_template as load_fulltext_prompt
from slr.services.fulltext_categories import enrich_fulltext, unavailable_categories
from slr.services.screen import load_prompt_template

app = FastAPI(title="Beyond Retrieval API")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)


app.include_router(auth_router)


@app.get("/fulltext/assets/{pmcid}/{asset_id}")
def fulltext_asset(pmcid: str, asset_id: str):
    """Serve only a known cached file, never a caller-supplied URL or path."""
    import re
    if not fulltext_assets.valid_pmcid(pmcid) or not re.fullmatch(r"[0-9a-f]{64}", asset_id):
        raise HTTPException(404, "Unknown asset")
    directory = fulltext_assets.ASSETS_DIR / pmcid
    try:
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        asset = next(a for a in manifest["files"] if a.get("asset_id") == asset_id)
    except (OSError, ValueError, KeyError, StopIteration):
        raise HTTPException(404, "Unknown asset")
    path = directory / asset_id
    if not path.is_file():
        raise HTTPException(404, "Asset no longer cached")
    image = asset.get("media_type", "").startswith("image/")
    return FileResponse(path, media_type=asset.get("media_type", "application/octet-stream"),
                        filename=asset["name"], content_disposition_type="inline" if image else "attachment",
                        headers={"X-Content-Type-Options": "nosniff"})


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/providers")
def list_providers():
    """The models the product answers with, and which are usable now.

    Both are listed even when one has no key, with the reason: a reader of
    the report should be able to see that the second vendor is wired, not
    merely described, and someone whose key expired needs to be told which
    one went missing rather than quietly getting half a cross-check.

    The local model is deliberately absent. It is still in the catalogue for
    the evaluation harnesses, which is where its figures come from, but the
    product asks the two vendors and compares them.
    """
    return {"default": None, "providers": providers.product_catalogue()}


@app.post("/projects")
def create_project(req: ProjectName, account=Depends(current_account)):
    name = req.name.strip()
    if not name:
        raise HTTPException(400, "Enter a project name")
    return live_review.create_session(dict(project_name=name, query="", papers=[], criteria=None), account["id"])


@app.post("/projects/{session_id}/import")
def import_project(session_id: str, payload: DiscoverSessionOut, account=Depends(current_account)):
    try:
        return live_review.save_search(session_id, account["id"], payload.model_dump())
    except KeyError as exc:
        raise HTTPException(404, "Project not found") from exc


@app.patch("/projects/{session_id}")
def rename_project(session_id: str, req: ProjectName, account=Depends(current_account)):
    if not req.name.strip():
        raise HTTPException(400, "Enter a project name")
    try:
        return live_review.update_project(session_id, account["id"], project_name=req.name.strip())
    except KeyError as exc:
        raise HTTPException(404, "Project not found") from exc


@app.delete("/projects/{session_id}")
def remove_project(session_id: str, account=Depends(current_account)):
    try:
        live_review.remove_project(session_id, account["id"])
        return {"removed": True}
    except KeyError as exc:
        raise HTTPException(404, "Project not found") from exc


@app.post("/projects/{session_id}/export")
def export_project(session_id: str, account=Depends(current_account)):
    """The papers read in full, with their PDFs and categorised data, as one ZIP."""
    from fastapi.responses import Response
    from slr.services.export import build_export

    try:
        live_review.require_owner(session_id, account["id"])
        name, data = build_export(live_review.read_session(session_id))
    except KeyError as exc:
        raise HTTPException(404, "Project not found") from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return Response(data, media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{name}"',
                             "Cache-Control": "no-store"})


@app.get("/discover/sessions")
def my_live_sessions(account=Depends(current_account)):
    return live_review.list_sessions(account["id"])


@app.get("/discover/sessions/{session_id}")
def get_live_session(session_id: str, account=Depends(current_account)):
    try:
        live_review.require_owner(session_id, account["id"])
        return live_review.read_session(session_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc


def _field_value_from_extraction(f) -> FieldValue:
    if f.verify_note == "not_stated":
        return FieldValue(status="not_stated")
    if f.span_verified:
        return FieldValue(status="verified", value=f.value, quote=f.evidence_span, note=f.verify_note)
    return FieldValue(status="unverified", quote=f.evidence_span, note=f.verify_note)


def _gap_value_from_extraction(g) -> GapValue:
    if g.value not in ("gap_stated", "not_stated"):
        return GapValue(status="failed", note=g.verify_note)
    if g.value == "not_stated":
        return GapValue(status="not_stated")
    return GapValue(status="gap_stated", quote=g.evidence_span)


#: Swapped out in tests so they never load SPECTER2.
suggest_embedder = live_review._embedder


def _suggest_session(req: SuggestRequest, conn, account, report) -> dict:
    """The work behind POST /suggest, shared with the watchable job form.

    ``report(stage, done, total)`` is handed through to the service so a
    caller watching a job can see papers being judged one at a time.
    """
    from slr.services.availability import readability_of_each
    from slr.services.suggest import Arm, relevance_criteria, suggest_cross_checked

    if req.project_id:
        if not account:
            raise HTTPException(401, "Sign in to save research")
        try:
            live_review.require_owner(req.project_id, account["id"])
        except KeyError as exc:
            raise HTTPException(404, "Project not found") from exc

    # A named provider answers alone -- the harnesses and the comparison
    # arms rely on being able to ask one model by name. Everything else gets
    # the cross-check, which is what the product offers.
    note = None
    try:
        if req.provider:
            built = [providers.build(req.provider)]
            missing: list = []
        else:
            built, missing = providers.build_product_arms()
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if not built:
        raise HTTPException(400, "; ".join(c.missing_note for c in missing) or "No model is configured")
    if missing and built:
        absent = ", ".join(c.label for c in missing)
        note = (
            f"Answered by {built[0][2].label} alone: {absent} is not configured, "
            "so nothing on this page was cross-checked against a second model."
        )

    arms = [Arm(label=c.label, model=c.model, provider=p, meter=m) for p, m, c in built]
    try:
        result = suggest_cross_checked(
            conn,
            req.query,
            arms=arms,
            screen_template=load_prompt_template(PROMPTS_DIR / "screen_v1.txt"),
            gap_template=load_prompt_template(PROMPTS_DIR / "gap_v1.txt"),
            n=req.n,
            embedder=suggest_embedder(),
            on_progress=report,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except CacheMismatch as exc:
        raise HTTPException(409, str(exc)) from exc
    except BudgetExceeded as exc:
        raise HTTPException(402, str(exc)) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"OpenAlex request failed: {exc}") from exc

    papers = []
    for s in result.suggestions:
        d = s.decision
        papers.append(
            DiscoverPaperOut(
                work_id=s.row["work_id"],
                abstract=s.row.get("abstract") or "",
                title=s.row.get("title"),
                year=s.row.get("year"),
                source_url=s.row.get("source_url"),
                doi=s.row.get("doi"),
                decision=ScreenDecisionOut(
                    status=d.decision,
                    confidence=d.confidence,
                    quote=d.evidence_span,
                    span_verified=bool(d.span_verified),
                    verify_note=d.verify_note,
                    from_cache=bool(d.from_cache),
                ),
                gap=_gap_value_from_extraction(s.gap),
                relevance=s.similarity,
                gap_match=s.gap_similarity,
                agreement=s.agreement,
                gap_sources=list(s.gap_sources),
                verdicts=[
                    ModelVerdictOut(
                        label=v.label,
                        model=v.model,
                        status=v.decision.decision,
                        span_verified=bool(v.decision.span_verified),
                        quote=v.decision.evidence_span,
                        verify_note=v.decision.verify_note,
                        gap_status=_gap_value_from_extraction(v.gap).status,
                        gap_quote=v.gap.evidence_span if v.gap.value == "gap_stated" else None,
                    )
                    for v in s.verdicts
                ],
            )
        )
    # Whether each paper can be read in full, before the reviewer picks one
    # rather than after. Nothing is removed on this basis: see the note in
    # slr/services/availability.py for why filtering was rejected.
    report("checking", 0, 0)
    try:
        for paper, readable in zip(papers, readability_of_each([p.model_dump() for p in papers])):
            paper.fulltext_status = readable.status
            paper.oa_url, paper.oa_host = readable.url, readable.host
    except Exception:
        # A result list without badges is still a result list.
        pass

    decisions = [p.decision for p in papers]
    split = {p.work_id for p in papers if p.agreement == "split"}
    session = DiscoverSessionOut(
        query=req.query,
        criteria=relevance_criteria(req.query),
        n_found=len(papers),
        n_screened=len(papers),
        # A split paper is not counted as included. Both models answered and
        # they did not match, so the thing the count would be asserting --
        # that this paper addresses the question -- is exactly what is in
        # dispute. It is handed back instead, with the referrals.
        n_included=sum(
            1
            for p in papers
            if p.decision.status == "include"
            and p.decision.span_verified
            and p.work_id not in split
        ),
        n_excluded=sum(1 for d in decisions if d.status == "exclude" and d.span_verified),
        n_referred=sum(1 for d in decisions if not d.span_verified),
        n_split=len(split),
        n_verified_quotes=sum(1 for d in decisions if d.span_verified),
        n_gaps=sum(1 for p in papers if p.gap and p.gap.status == "gap_stated"),
        papers=papers,
        n_candidates=result.n_candidates,
        ranking=result.ranking,
        ranking_note=result.ranking_note,
        answered_by=" and ".join(a.label for a in arms),
        model=", ".join(a.model for a in arms),
        cost_usd=round(sum(m.spend_usd for _p, m, _c in built), 6),
        model_calls=sum(m.calls for _p, m, _c in built),
        cached_calls=sum(m.cached_calls for _p, m, _c in built),
        arms=[
            ArmCostOut(
                label=c.label,
                model=c.model,
                cost_usd=round(m.spend_usd, 6),
                model_calls=m.calls,
                cached_calls=m.cached_calls,
            )
            for _p, m, c in built
        ],
        cross_check_note=note,
    )
    if req.project_id:
        return live_review.save_search(req.project_id, account["id"], session.model_dump())
    return session.model_dump()


def _no_progress(stage: str, done: int, total: int) -> None:
    """For callers that wait on the answer and have nowhere to show progress."""


@app.post("/suggest", response_model=DiscoverSessionOut)
def suggest_route(req: SuggestRequest, conn: sqlite3.Connection = Depends(get_conn), account=Depends(optional_account)):
    """A research question in; the papers most worth reading out.

    Searches OpenAlex, ranks the pool by SPECTER2 similarity to the question,
    then for the top ``n`` checks relevance and stated gaps, each against a
    quote verified in the abstract. The researcher picks from these which to
    read in full (``POST /discover/fulltext``). Nothing here is scored.

    This answers in one request, which means the caller waits with no idea
    how far along it is. ``POST /suggest/start`` does the same work as a job
    that can be watched.
    """
    return _suggest_session(req, conn, account, _no_progress)


@app.post("/suggest/start")
def suggest_start(req: SuggestRequest, account=Depends(optional_account)):
    """The same search, as a job the caller can watch.

    Returns immediately with a job id; ``GET /jobs/{job_id}`` reports how
    many papers have been judged and carries the answer once it is done.
    """

    def work(report):
        # The request that started this job is already over, and its
        # connection with it, so the job opens its own.
        conn = new_conn()
        try:
            return _suggest_session(req, conn, account, report)
        finally:
            conn.close()

    return jobs.start(work).snapshot()


@app.get("/jobs/{job_id}")
def job_status(job_id: str):
    """How far along a job is, and its answer once there is one."""
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(404, "No such job. It may have finished long enough ago to be forgotten.")
    body = job.snapshot()
    if job.finished and job.error:
        raise HTTPException(job.status_code, job.error)
    if job.finished:
        body["result"] = job.result
        jobs.forget(job_id)
    return body


def _fulltext_session(req: FullTextRequest, conn, account, report) -> dict:
    """The work behind POST /discover/fulltext, shared with its job form.

    ``report(stage, done, total)`` is called as each paper is finished, so
    a caller watching a job can say which paper is being read rather than
    showing a spinner for the minutes this can take.
    """
    if not req.project_id:
        raise HTTPException(400, "Create or choose a named research project first")
    try:
        live_review.require_owner(req.project_id, account["id"])
    except KeyError as exc:
        raise HTTPException(404, "Project not found") from exc
    from slr.adapters.fulltext import get_full_text
    from slr.services.discover import DISCOVER_REVIEW, open_access_copy
    from slr.services.extract_fulltext import extract_fulltext_record
    from slr.services.gap_fulltext import find_gaps, load_prompt_template as load_gap_prompt

    try:
        provider, meter, _choice = providers.build(req.provider)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    template = load_fulltext_prompt(PROMPTS_DIR / "extract_fulltext_v1.txt")
    gap_template = load_gap_prompt(PROMPTS_DIR / "gap_fulltext_v2.txt")

    out: list[FullTextPaperOut] = []
    report("reading", 0, len(req.papers))
    for target in req.papers:
        entry = FullTextPaperOut(work_id=target.work_id, title=target.title)
        entry.coverage = unavailable_categories("Full text has not been retrieved.")
        try:
            full_text, availability = get_full_text(doi=target.doi, title=target.title)
        except ValueError as exc:  # no doi and no title
            entry.note = str(exc)
            entry.coverage = unavailable_categories(entry.note)
            out.append(entry)
            report("reading", len(out), len(req.papers))
            continue
        except httpx.HTTPError as exc:
            entry.note = f"Europe PMC request failed: {exc}"
            entry.coverage = unavailable_categories(entry.note)
            out.append(entry)
            report("reading", len(out), len(req.papers))
            continue

        if full_text is None:
            entry.note = availability.reason or "no full text available"
            # Europe PMC holds the biomedical open-access subset, so most
            # papers end here. Say where it can be read instead, when
            # somewhere exists: the researcher's next step is a link, not
            # a dead end.
            elsewhere = open_access_copy(target.work_id)
            if elsewhere:
                entry.oa_url, entry.oa_host = elsewhere.url, elsewhere.host
                entry.note += f". A free copy is held by {elsewhere.host}"
            entry.coverage = unavailable_categories(entry.note)
            out.append(entry)
            report("reading", len(out), len(req.papers))
            continue

        entry.found = True
        entry.pmcid = availability.pmcid
        entry.tables = [TableOut(**t.as_dict()) for t in full_text.tables]
        entry.equations = list(full_text.equations)
        entry.figures = [FigureOut(**f.as_dict()) for f in full_text.figures]
        enriched = enrich_fulltext(full_text, include_assets=req.include_assets)
        entry.figures = [FigureOut(**f) for f in enriched.pop("figures")]
        for name, value in enriched.items():
            setattr(entry, name, value)

        try:
            rows = extract_fulltext_record(
                full_text,
                work_id=target.work_id,
                review=DISCOVER_REVIEW,
                provider=provider,
                template=template,
                meter=meter,
                conn=conn,
            )
        except CacheMismatch as exc:
            raise HTTPException(409, str(exc)) from exc
        except BudgetExceeded as exc:
            raise HTTPException(402, str(exc)) from exc
        # Per paper, not per request: see the same commit in suggest.py.
        conn.commit()

        by_field = {r.field_name: r for r in rows}
        for name in (
            "primary_outcome",
            "effect_size",
            "statistical_methods",
            "sample_characteristics",
            "limitations",
        ):
            if name in by_field:
                setattr(entry, name, _field_value_from_extraction(by_field[name]))

        # The gaps the authors state in the body. A separate call from the
        # five fields above: it asks a different question, returns a list
        # rather than one value per field, and a paper stating none is a
        # real and common answer.
        try:
            gap_result = find_gaps(
                full_text,
                work_id=target.work_id,
                review=DISCOVER_REVIEW,
                provider=provider,
                template=gap_template,
                meter=meter,
                conn=conn,
            )
        except CacheMismatch as exc:
            raise HTTPException(409, str(exc)) from exc
        except BudgetExceeded as exc:
            raise HTTPException(402, str(exc)) from exc
        conn.commit()
        entry.gaps = [
            StatedGapOut(value=g.value, quote=g.evidence_span, section=g.section)
            for g in gap_result.gaps
        ]
        entry.gaps_note = gap_result.note
        entry.gaps_withheld = gap_result.n_withheld
        entry.gaps_unsupported = gap_result.n_unsupported

        verified = sum(1 for r in rows if r.span_verified)
        if full_text.is_fragment:
            # Say this plainly. Without it, every field reads "not stated"
            # and a reader blames the extraction for a stub Europe PMC
            # served while flagging the record open access.
            entry.note = (
                f"Europe PMC returned only a fragment of this paper from "
                f"{availability.pmcid} — {len(full_text.body):,} characters, no section "
                f"headings, no tables or figures. It is flagged open access, but the full "
                f"text is not actually there. Most fields will read “not stated”, and that "
                f"is the system being honest about text it was never given."
            )
        else:
            entry.note = (
                f"full text from {availability.pmcid}: {verified} of {len(rows)} fields "
                f"verified, {len(entry.tables)} tables, {len(entry.equations)} equations, "
                f"{len(entry.figures)} figures"
            )
            # How much of the paper the model actually saw. A long paper is
            # truncated to fit the context window, and a field marked "not
            # stated" may simply live in the part that was cut. Saying so is
            # the difference between an honest gap and a silent one.
            source = build_fulltext_source(full_text)
            if source.truncated:
                shown = source.chars_available and len(source.text) / source.chars_available
                entry.note += (
                    f". The paper is {source.chars_available:,} characters and the model was "
                    f"shown the first {len(source.text):,} ({shown:.0%}), prioritising results, "
                    f"limitations and discussion — a field marked “not stated” may be in the "
                    f"part that was cut"
                )
        out.append(entry)
        report("reading", len(out), len(req.papers))

    result = FullTextSessionOut(
        n_requested=len(req.papers),
        n_with_full_text=sum(1 for p in out if p.found),
        papers=out,
    )

    # Saved merged with anything read earlier, but this call answers with
    # what this call read, which is what the page asked for.
    live_review.save_fulltext(req.project_id, account["id"], result.model_dump())
    return result.model_dump()


@app.post("/discover/fulltext", response_model=FullTextSessionOut)
def discover_fulltext(req: FullTextRequest, conn: sqlite3.Connection = Depends(get_conn), account=Depends(current_account)):
    """Stage two: read the full text of papers the reviewer chose.

    Screening on abstracts is stage one; this is what a systematic review
    does next, and splitting them is not only faster but closer to the
    method. PRISMA defines title/abstract screening and full-text review as
    separate stages for the same reason: a human decides what is worth the
    deeper read.

    Nothing here is scored. There is no ground truth for an extracted
    effect size, so this reports what verified and never how often it was
    right. ``POST /discover/fulltext/start`` does the same work as a job
    that can be watched, which matters because each paper is a lookup, a
    download and two long model calls.
    """
    return _fulltext_session(req, conn, account, _no_progress)


@app.post("/discover/fulltext/start")
def discover_fulltext_start(req: FullTextRequest, account=Depends(current_account)):
    """The same reading, as a job the caller can watch."""

    def work(report):
        conn = new_conn()
        try:
            return _fulltext_session(req, conn, account, report)
        finally:
            conn.close()

    return jobs.start(work).snapshot()
