"""Command-line harness for structured data extraction.

Takes a config file, reads a prior screening run's verified-include
decisions, and writes a run directory:

    runs/<ts>-extract-<hash>/
        config.yaml            the config exactly as written
        resolved_config.json   the config after defaults were applied
        extraction.jsonl       every extracted field, one line each
        run.json                this execution: commit, timings, cache hits
        git_sha.txt             the commit the code was at

Reads the source run's ``responses.jsonl`` directly rather than the live
``screening_decision`` table — that file is what the screening harness wrote
as the authoritative record of that run's decisions, and it survives a
schema bump that would otherwise wipe the table. It is not committed to git
(same as all responses.jsonl files); this harness only re-runs against a
source run whose responses.jsonl is still present locally.

Usage:
    python -m slr.eval.extract_harness --config configs/extract_demo.yaml --require-clean
"""

from __future__ import annotations

import argparse
import json
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path

from slr.adapters.llm import BudgetExceeded, CacheMismatch, Meter, build_provider
from slr.config import ExtractConfig, load_extract_config
from slr.db import connect
from slr.eval.harness import DirtyTree, _write_json, _write_text, git_state
from slr.services.extract import (
    FIELDS,
    extract_record,
    load_prompt_template,
    persist,
    to_jsonl,
)


class MissingSourceRun(RuntimeError):
    """The source screening run's responses.jsonl is not present locally."""


def _load_verified_includes(cfg: ExtractConfig) -> list[dict]:
    path = cfg.runs_dir / cfg.source_run_id / "responses.jsonl"
    if not path.exists():
        raise MissingSourceRun(
            f"{path} not found. Extraction reads the source screening run's "
            f"decisions directly from its responses.jsonl, which is not "
            f"committed to git — it must still exist locally from when that "
            f"run executed."
        )
    rows = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            if d["review"] == cfg.review and d["decision"] == "include" and d["span_verified"]:
                rows.append(d)
    return rows


def run(cfg: ExtractConfig, *, require_clean: bool = False) -> Path:
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


def _run(conn, cfg: ExtractConfig, sha: str, dirty: bool) -> Path:
    includes = _load_verified_includes(cfg)
    if cfg.max_records:
        includes = includes[: cfg.max_records]
    if not includes:
        raise MissingSourceRun(
            f"No verified-include decisions found for {cfg.review!r} in "
            f"source run {cfg.source_run_id!r}."
        )

    started = datetime.now(timezone.utc)
    run_id = f"{started:%Y%m%dT%H%M%S%fZ}-extract-{cfg.config_hash}"
    run_dir = cfg.runs_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=False)

    provider = build_provider(cfg.provider, cfg.model, api_key=cfg.api_key(), max_retries=cfg.max_retries)
    template = load_prompt_template(cfg.prompt_path)
    meter = Meter(ceiling_usd=cfg.ceiling_usd, usd_per_1m_input=cfg.usd_per_1m_input, usd_per_1m_output=cfg.usd_per_1m_output)

    print(f"run {run_id}")
    print(f"  mode       extract")
    print(f"  source     {cfg.source_run_id} ({cfg.review}, {len(includes)} verified includes)")
    print(f"  provider   {provider.name} / {provider.model}")
    print(f"  prompt     {cfg.prompt_version}")
    print(f"  ceiling    ${cfg.ceiling_usd:.2f}")
    print(f"  commit     {sha}{' (dirty)' if dirty else ''}\n")
    if dirty:
        print("  ! working tree is dirty — commit before a run you intend to report (rule 3)\n")

    aborted: str | None = None
    field_counts = {field: {"verified": 0, "not_stated": 0, "failed": 0} for field in FIELDS}
    log = (run_dir / "extraction.jsonl").open("w", encoding="utf-8", newline="\n")

    try:
        for i, decision in enumerate(includes, 1):
            row = conn.execute(
                "SELECT * FROM work WHERE review = ? AND work_id = ?",
                (decision["review"], decision["work_id"]),
            ).fetchone()
            if row is None:
                continue
            try:
                fields = extract_record(
                    row,
                    provider=provider,
                    template=template,
                    meter=meter,
                    conn=conn,
                    prompt_version=cfg.prompt_version,
                    temperature=cfg.temperature,
                    max_tokens=cfg.max_output_tokens,
                    seed=cfg.seed,
                    use_cache=cfg.cache_enabled,
                )
            except BudgetExceeded as exc:
                aborted = str(exc)
                print(f"\n  ABORTED: {exc}")
                break

            for f in fields:
                persist(conn, run_id, cfg.source_run_id, f)
                log.write(to_jsonl(f) + "\n")
                if f.verify_note == "not_stated":
                    field_counts[f.field_name]["not_stated"] += 1
                elif f.span_verified:
                    field_counts[f.field_name]["verified"] += 1
                else:
                    field_counts[f.field_name]["failed"] += 1

            if i % 25 == 0 or i == len(includes):
                print(f"    {i}/{len(includes)}  {meter.calls - meter.cached_calls} live, {meter.cached_calls} cached, ${meter.spend_usd:.4f}")
        conn.commit()
    finally:
        log.close()

    finished = datetime.now(timezone.utc)

    results = {
        "config_name": cfg.name,
        "config_hash": cfg.config_hash,
        "source_run_id": cfg.source_run_id,
        "review": cfg.review,
        "records": len(includes),
        "aborted": aborted is not None,
        "field_verification": field_counts,
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
    _write_json(run_dir / "resolved_config.json", cfg.model_dump(mode="json", exclude={"source_path", "source_text"}))
    _write_text(run_dir / "git_sha.txt", f"{sha}{'-dirty' if dirty else ''}\n")
    _write_json(run_dir / "metrics.json", results)
    _write_json(run_dir / "run.json", run_info)

    print()
    print(f"{'field':16}{'verified':>10}{'not_stated':>12}{'failed':>8}")
    for field in FIELDS:
        c = field_counts[field]
        print(f"{field:16}{c['verified']:>10}{c['not_stated']:>12}{c['failed']:>8}")
    print(f"\nspend ${meter.spend_usd:.4f} of ${cfg.ceiling_usd:.2f} ({meter.cached_calls} of {meter.calls} calls cached)")
    print(f"artefacts -> {run_dir}")

    return run_dir


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run structured data extraction.")
    parser.add_argument("--config", required=True, help="Path to a config YAML")
    parser.add_argument("--require-clean", action="store_true", help="Refuse to run with uncommitted changes.")
    args = parser.parse_args(argv)
    try:
        run(load_extract_config(args.config), require_clean=args.require_clean)
    except (DirtyTree, MissingSourceRun, CacheMismatch) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
