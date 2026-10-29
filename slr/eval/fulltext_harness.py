"""Full-text extraction as a reportable run, not a dashboard demo.

Until this existed, full-text extraction could only be driven through
``POST /discover/fulltext`` and the Run a Review page. That is fine for a
demonstration and useless for a report: rule 2 says every reported number
comes from a run directory containing its config and commit hash, so **no
full-text figure was reportable at all** — not coverage, not per-field
verification, not the truncation share.

That matters now because the supervisor asked for two specific things: keep
full text as future work or a small demonstration, *and* validate it against
a manually annotated reference set with precision, recall and F1 per field.
The second is impossible without an artefact to annotate against. This
harness produces it.

What it records, per paper, beyond the five extracted fields:

* why there is no full text, when there isn't — ``paywalled``,
  ``not_indexed``, ``no_pmc`` are facts about the source, not failures of
  extraction, and the 7 October note explains why conflating them misreads
  the system badly;
* ``fragment``, when Europe PMC flags a paper open access and then serves a
  stub (``FullText.is_fragment``);
* how much of the paper the model actually saw. A field marked
  ``not_stated`` may simply be in the two thirds that were truncated away,
  and ``verify_note`` already distinguishes ``not_stated_possibly_truncated``.

Deliberately outside the evaluation corpus: every record carries
``review="_fulltext"`` (see ``config.FULLTEXT_REVIEW``), never a real review
name, so a full-text row cannot be mistaken for benchmark data — the same
boundary ``_discover`` keeps.

    python -m slr.eval.fulltext_harness --config configs/fulltext_demo.yaml --require-clean
"""

from __future__ import annotations

import argparse
import json
import platform
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import httpx

from slr.adapters.fulltext import fetch_full_text, find_availability, normalise_doi
from slr.adapters.llm import BudgetExceeded, CacheMismatch, Meter, build_provider
from slr.config import FullTextConfig, load_fulltext_config
from slr.db import connect
from slr.eval.harness import DirtyTree, as_run, git_state
from slr.services.extract_fulltext import (
    build_source,
    extract_fulltext_record,
    load_prompt_template,
)

FIELDS = (
    "primary_outcome",
    "effect_size",
    "statistical_methods",
    "sample_characteristics",
    "limitations",
)

# Why a paper produced no prose to read. Each is a fact about the source.
FULL = "full"
FRAGMENT = "fragment"
PAYWALLED = "paywalled"
NO_PMC = "no_pmc"
NOT_INDEXED = "not_indexed"
LOOKUP_FAILED = "lookup_failed"


def _write_json(path: Path, payload) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8", newline="\n")


def resolve(target: str, *, client: httpx.Client) -> tuple[object | None, str, str]:
    """One target -> (FullText or None, availability outcome, human reason)."""
    looks_like_pmcid = target.upper().startswith("PMC") and target[3:].isdigit()
    try:
        if looks_like_pmcid:
            pmcid, reason = target.upper(), "PMCID given directly"
        else:
            availability = find_availability(doi=normalise_doi(target), title=target, client=client)
            reason = availability.reason
            if not availability.found:
                return None, NOT_INDEXED, reason
            if not availability.pmcid:
                return None, NO_PMC, reason
            if not availability.is_open_access:
                return None, PAYWALLED, reason
            pmcid = availability.pmcid
        paper = fetch_full_text(pmcid, client=client)
    except Exception as exc:  # network, parse, anything -- recorded, not raised
        return None, LOOKUP_FAILED, f"{type(exc).__name__}: {exc}"

    if paper is None:
        return None, NO_PMC, "listed open access but full text not served"
    if paper.is_fragment:
        return paper, FRAGMENT, "flagged open access but only a stub was served"
    return paper, FULL, reason


def run(cfg: FullTextConfig, *, require_clean: bool = False) -> Path:
    sha, dirty = git_state(cfg.runs_dir)
    if require_clean and dirty:
        raise DirtyTree(
            "Working tree has uncommitted changes, or git is unavailable. "
            "Commit before a run you intend to report (rule 3)."
        )
    conn = connect(cfg.db_path)
    try:
        return _run(conn, cfg, sha, dirty)
    finally:
        conn.close()


def _run(conn, cfg: FullTextConfig, sha: str, dirty: bool) -> Path:
    targets = cfg.targets[: cfg.max_records] if cfg.max_records else list(cfg.targets)

    started = datetime.now(timezone.utc)
    run_id = f"{started:%Y%m%dT%H%M%S%fZ}-fulltext-{cfg.config_hash}"
    run_dir = cfg.runs_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=False)

    provider = build_provider(
        cfg.provider, cfg.model, api_key=cfg.api_key(), max_retries=cfg.max_retries
    )
    template = load_prompt_template(cfg.prompt_path)
    meter = Meter(
        ceiling_usd=cfg.ceiling_usd,
        usd_per_1m_input=cfg.usd_per_1m_input,
        usd_per_1m_output=cfg.usd_per_1m_output,
    )

    print(f"run {run_id}")
    print("  mode       fulltext")
    print(f"  targets    {len(targets)}")
    print(f"  provider   {provider.name} / {provider.model}")
    print(f"  prompt     {cfg.prompt_version}  (<= {cfg.max_prompt_chars:,} chars shown)")
    print(f"  ceiling    ${cfg.ceiling_usd:.2f}")
    print(f"  commit     {sha}{' (dirty)' if dirty else ''}\n")
    if dirty:
        print("  ! working tree is dirty — commit before a run you intend to report (rule 3)\n")

    availability = Counter()
    field_status: dict[str, Counter] = {f: Counter() for f in FIELDS}
    papers: list[dict] = []
    aborted: str | None = None
    client = httpx.Client()
    log = (run_dir / "fulltext.jsonl").open("w", encoding="utf-8", newline="\n")
    try:
        for i, target in enumerate(targets, 1):
            paper, outcome, reason = resolve(target, client=client)
            availability[outcome] += 1
            entry = {
                "target": target,
                "availability": outcome,
                "reason": reason,
                "pmcid": getattr(paper, "pmcid", None),
                "title": getattr(paper, "title", None),
                "body_chars": len(paper.body) if paper else 0,
                "sections": len(paper.sections) if paper else 0,
                "tables": len(paper.tables) if paper else 0,
                "figures": len(paper.figures) if paper else 0,
                "equations": len(paper.equations) if paper else 0,
                "fields": {},
            }

            if paper is None:
                print(f"  {i:3d}. {outcome:13s} -- {reason[:60]}")
                papers.append(entry)
                log.write(json.dumps(entry) + "\n")
                continue

            source = build_source(paper, max_chars=cfg.max_prompt_chars)
            entry["chars_available"] = source.chars_available
            entry["chars_shown"] = len(source.text)
            entry["truncated"] = source.truncated
            entry["share_shown"] = (
                round(len(source.text) / source.chars_available, 4)
                if source.chars_available
                else None
            )

            try:
                rows = extract_fulltext_record(
                    paper,
                    work_id=getattr(paper, "pmcid", None) or target,
                    review=cfg.review,
                    provider=provider,
                    template=template,
                    meter=meter,
                    conn=conn,
                    prompt_version=cfg.prompt_version,
                    temperature=cfg.temperature,
                    max_tokens=cfg.max_output_tokens,
                    seed=cfg.seed,
                    use_cache=cfg.cache_enabled,
                    max_chars=cfg.max_prompt_chars,
                )
            except BudgetExceeded as exc:
                aborted = str(exc)
                print(f"\n  ABORTED: {exc}")
                papers.append(entry)
                log.write(json.dumps(entry) + "\n")
                break

            for row in rows:
                status = (
                    "verified"
                    if row.span_verified
                    else ("not_stated" if (row.verify_note or "").startswith("not_stated") else "unverified")
                )
                field_status.setdefault(row.field_name, Counter())[status] += 1
                entry["fields"][row.field_name] = {
                    "status": status,
                    "value": row.value,
                    "evidence_span": row.evidence_span,
                    "verify_note": row.verify_note,
                    "error": row.error,
                }
            verified = sum(1 for r in rows if r.span_verified)
            print(
                f"  {i:3d}. {outcome:13s} {entry['body_chars']:7,d}c "
                f"{entry['tables']:2d}t {entry['figures']:2d}f  "
                f"{verified}/{len(rows)} verified  "
                f"{(entry['share_shown'] or 0) * 100:3.0f}% shown"
            )
            papers.append(entry)
            log.write(json.dumps(entry) + "\n")
        conn.commit()
    finally:
        log.close()
        client.close()

    finished = datetime.now(timezone.utc)
    read = [p for p in papers if p["availability"] in (FULL, FRAGMENT)]
    results = {
        "config_name": cfg.name,
        "config_hash": cfg.config_hash,
        "review": cfg.review,
        "targets": len(targets),
        "aborted": aborted is not None,
        "availability": dict(availability),
        "usable_share": round(availability[FULL] / len(targets), 4) if targets else None,
        "field_status": {f: dict(c) for f, c in field_status.items() if c},
        "truncation": {
            "papers_read": len(read),
            "papers_truncated": sum(1 for p in read if p.get("truncated")),
            "median_share_shown": (
                sorted(p["share_shown"] for p in read if p.get("share_shown") is not None)[
                    len([p for p in read if p.get("share_shown") is not None]) // 2
                ]
                if any(p.get("share_shown") is not None for p in read)
                else None
            ),
            "max_prompt_chars": cfg.max_prompt_chars,
        },
        "note": (
            "paywalled / not_indexed / no_pmc are facts about Europe PMC's holdings, "
            "not extraction failures. 'fragment' means a paper flagged open access "
            "returned only a stub. A field marked not_stated may be in the portion "
            "of a long paper that was truncated away -- see truncation.median_share_shown."
        ),
    }
    run_info = {
        "run_id": run_id,
        "git_sha": sha,
        "git_dirty": dirty,
        "started_at": started.isoformat(),
        "finished_at": finished.isoformat(),
        "duration_s": round((finished - started).total_seconds(), 2),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "calls": meter.calls,
        "cached_calls": meter.cached_calls,
        "live_tokens_in": meter.tokens_in,
        "live_tokens_out": meter.tokens_out,
        "live_spend_usd": round(meter.spend_usd, 6),
        "ceiling_usd": cfg.ceiling_usd,
        "aborted_reason": aborted,
    }

    _write_text(run_dir / "config.yaml", cfg.source_text or "")
    _write_json(
        run_dir / "resolved_config.json",
        as_run(cfg.model_dump(mode="json", exclude={"source_path", "source_text"}), provider),
    )
    _write_text(run_dir / "git_sha.txt", f"{sha}{'-dirty' if dirty else ''}\n")
    _write_json(run_dir / "metrics.json", results)
    _write_json(run_dir / "run.json", run_info)

    print()
    print("availability: " + "  ".join(f"{k} {v}" for k, v in sorted(availability.items())))
    for field, counts in field_status.items():
        if counts:
            print(f"  {field:24s} " + "  ".join(f"{k} {v}" for k, v in sorted(counts.items())))
    print(f"\nspend ${meter.spend_usd:.4f} of ${cfg.ceiling_usd:.2f} "
          f"({meter.cached_calls} of {meter.calls} calls cached)")
    print(f"artefacts -> {run_dir}")
    return run_dir


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run full-text extraction over named papers.")
    parser.add_argument("--config", required=True, help="Path to a config YAML")
    parser.add_argument(
        "--require-clean", action="store_true", help="Refuse to run with uncommitted changes."
    )
    args = parser.parse_args(argv)
    try:
        run(load_fulltext_config(args.config), require_clean=args.require_clean)
    except (DirtyTree, CacheMismatch, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
