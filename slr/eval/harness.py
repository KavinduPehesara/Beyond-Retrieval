"""Command-line harness. The only entry point that produces reportable numbers.

Takes a config file, runs the pipeline headlessly, and writes a run directory:

    runs/<timestamp>-<config hash>/
        config.yaml           the config exactly as written
        resolved_config.json  the config after defaults were applied
        metrics.json          results only — a pure function of config and corpus
        run.json              this execution: commit, timings, live spend, cache hits
        git_sha.txt           the commit the code was at
        responses.jsonl       every decision (not committed; can be large)

metrics.json deliberately holds nothing that varies between executions of the
same configuration — no timestamps, no latency, no cache state, no commit
hash. A stored configuration run twice must produce a byte-identical
metrics.json (proposal, Table 5, weeks 7–8 exit test). Everything that does
vary goes in run.json.

It calls the services directly and never passes through an API or interface.
That is deliberate: every result must be reproducible from a config file
without a browser, and the demonstrated system must not be able to diverge
from the measured one.

Usage:
    python -m slr.eval.harness --config configs/smoke.yaml
    python -m slr.eval.harness --config configs/baseline_bm25.yaml --require-clean
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from slr.adapters.llm import BudgetExceeded, CacheMismatch, Meter, build_provider
from slr.config import Config, load_config
from slr.db import connect
from slr.eval import metrics
from slr.services import criteria as criteria_service
from slr.services import retrieve
from slr.services.screen import (
    load_prompt_template,
    persist,
    screen_record,
    to_jsonl,
)

METRICS_SCHEMA = 2


class DirtyTree(RuntimeError):
    """A reportable run was requested with uncommitted changes."""


class MissingCorpus(RuntimeError):
    """A configured review has no records in the database."""


def git_state(runs_dir: Path | None = None) -> tuple[str, bool]:
    """The commit HEAD is at, and whether the tree differs from it.

    Untracked files under ``runs_dir`` do not count: they are the outputs of
    earlier runs waiting for their ``eval:`` commit, not code, and counting
    them would make every second run in a session "dirty". Anything else — a
    modified tracked file, including a committed run artefact, or a new
    source file — does count.

    If git is unavailable the state is ("unknown", True): a run whose code
    cannot be identified is treated as uncommitted.
    """

    def git(*args: str) -> str:
        return subprocess.check_output(["git", *args], stderr=subprocess.DEVNULL, text=True)

    try:
        sha = git("rev-parse", "HEAD").strip()
        lines = git("status", "--porcelain=v1", "--untracked-files=all").splitlines()
        prefix = None
        if runs_dir is not None:
            top = Path(git("rev-parse", "--show-toplevel").strip()).resolve()
            try:
                prefix = Path(runs_dir).resolve().relative_to(top).as_posix().rstrip("/") + "/"
            except ValueError:
                prefix = None  # runs outside the repository never show up here
        changes = [
            line
            for line in lines
            if not (prefix and line.startswith("?? ") and line[3:].strip('"').startswith(prefix))
        ]
        return sha, bool(changes)
    except Exception:
        return "unknown", True


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _write_text(path: Path, text: str) -> None:
    """Always LF, on every platform.

    Two runs of one configuration must produce byte-identical artefacts, and
    "identical" has to survive the week 13 test of a fresh clone on a second
    machine. Left alone, Python translates newlines on Windows.
    """
    path.write_text(text, encoding="utf-8", newline="\n")


def _write_json(path: Path, payload: dict) -> None:
    _write_text(path, json.dumps(payload, indent=2, ensure_ascii=False) + "\n")


def run(cfg: Config, *, require_clean: bool = False) -> Path:
    """Execute one configuration. Returns the run directory."""
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


def _run(conn, cfg: Config, sha: str, dirty: bool) -> Path:
    reviews = cfg.dataset.reviews
    empty = [
        r
        for r in reviews
        if conn.execute("SELECT 1 FROM work WHERE review = ? LIMIT 1", (r,)).fetchone() is None
    ]
    if empty:
        raise MissingCorpus(
            f"No records for {empty} in {cfg.db_path}. Run "
            f"`python -m slr.services.ingest --config <config>` first."
        )

    started = datetime.now(timezone.utc)
    run_id = f"{started:%Y%m%dT%H%M%S%fZ}-{cfg.config_hash}"
    run_dir = cfg.runs_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=False)

    screening = cfg.screening.enabled
    provider = None
    template = None
    if screening:
        provider = build_provider(
            cfg.screening.provider,
            cfg.screening.model,
            api_key=cfg.api_key(),
            max_retries=cfg.screening.max_retries,
        )
        template = load_prompt_template(cfg.prompt_path)

    meter = Meter(
        ceiling_usd=cfg.budget.ceiling_usd,
        usd_per_1m_input=cfg.budget.usd_per_1m_input,
        usd_per_1m_output=cfg.budget.usd_per_1m_output,
    )

    conn.execute(
        "INSERT INTO run "
        "(run_id, config_hash, config_name, git_sha, provider, model, "
        " prompt_version, temperature, started_at) VALUES (?,?,?,?,?,?,?,?,?)",
        (
            run_id,
            cfg.config_hash,
            cfg.name,
            f"{sha}{'-dirty' if dirty else ''}",
            provider.name if provider else "none",
            provider.model if provider else None,
            cfg.screening.prompt_version if screening else None,
            cfg.screening.temperature if screening else None,
            started.isoformat(),
        ),
    )
    conn.commit()

    print(f"run {run_id}")
    print(f"  mode       {'screen' if screening else 'baseline'} / {cfg.ranking.strategy}")
    if provider:
        print(f"  provider   {provider.name} / {provider.model}")
        print(f"  prompt     {cfg.screening.prompt_version}")
        print(f"  ceiling    ${cfg.budget.ceiling_usd:.2f}")
    print(f"  commit     {sha}{' (dirty)' if dirty else ''}\n")
    if dirty:
        print("  ! working tree is dirty — commit before a run you intend to report (rule 3)\n")
    review_criteria = {r: criteria_service.for_review(conn, r) for r in reviews}
    drafts = [r for r, c in review_criteria.items() if c.status != criteria_service.PUBLISHED]
    uses_criteria = (provider is not None and provider.name != "mock") or (
        provider is None and cfg.ranking.strategy == "bm25"
    )
    if drafts and uses_criteria:
        print(
            f"  ! draft eligibility criteria for {drafts} — run ingest to load the "
            f"published criteria before any run that gets reported\n"
        )

    aborted: str | None = None
    per_review: list[dict] = []
    log = (
        (run_dir / "responses.jsonl").open("w", encoding="utf-8", newline="\n")
        if screening
        else None
    )

    try:
        for review in reviews:
            criteria = review_criteria[review].text
            order = retrieve.rank(
                conn,
                cfg.ranking.strategy,
                review,
                seed=cfg.dataset.seed,
                query=cfg.ranking.query or criteria,
                rrf_k=cfg.ranking.rrf_k,
                rerank_top_k=cfg.ranking.rerank_top_k,
            )

            if not screening:
                print(f"  {review}: ranked {len(order)} records")
                per_review.append(
                    metrics.baseline_metrics(
                        conn,
                        review,
                        [r["work_id"] for r in order],
                        recall_target=cfg.ranking.recall_target,
                    )
                )
                continue

            rows = order[: cfg.dataset.max_records] if cfg.dataset.max_records else order
            print(f"  {review}: screening {len(rows)} of {len(order)} records")
            for i, row in enumerate(rows, 1):
                try:
                    decision = screen_record(
                        row,
                        provider=provider,
                        template=template,
                        criteria=criteria,
                        meter=meter,
                        conn=conn,
                        prompt_version=cfg.screening.prompt_version,
                        temperature=cfg.screening.temperature,
                        max_tokens=cfg.screening.max_output_tokens,
                        seed=cfg.screening.seed,
                        use_cache=cfg.cache_enabled,
                    )
                except BudgetExceeded as exc:
                    aborted = str(exc)
                    print(f"\n  ABORTED: {exc}")
                    break

                persist(conn, run_id, decision)
                log.write(to_jsonl(decision) + "\n")

                if i % 25 == 0 or i == len(rows):
                    print(
                        f"    {i}/{len(rows)}  {meter.calls - meter.cached_calls} live, "
                        f"{meter.cached_calls} cached, ${meter.spend_usd:.4f}"
                    )
            conn.commit()
            per_review.append(
                metrics.review_metrics(
                    conn,
                    run_id,
                    review,
                    recall_target=cfg.ranking.recall_target,
                    usd_per_1m_input=cfg.budget.usd_per_1m_input,
                    usd_per_1m_output=cfg.budget.usd_per_1m_output,
                ).as_dict()
            )
            if aborted:
                break
    finally:
        if log:
            log.close()

    finished = datetime.now(timezone.utc)
    conn.execute(
        "UPDATE run SET finished_at = ?, total_cost_usd = ? WHERE run_id = ?",
        (finished.isoformat(), meter.spend_usd, run_id),
    )
    conn.commit()

    results = {
        "metrics_schema": METRICS_SCHEMA,
        "config_name": cfg.name,
        "config_hash": cfg.config_hash,
        "mode": "screen" if screening else "baseline",
        "ranking": {
            "strategy": cfg.ranking.strategy,
            "query": cfg.ranking.query,
            "recall_target": cfg.ranking.recall_target,
            "seed": cfg.dataset.seed,
        },
        "screening": (
            {
                "provider": provider.name,
                "model": provider.model,
                "prompt_version": cfg.screening.prompt_version,
                "prompt_sha256": _sha256(template),
                "temperature": cfg.screening.temperature,
                "max_output_tokens": cfg.screening.max_output_tokens,
                "seed": cfg.screening.seed,
                "max_records": cfg.dataset.max_records,
                "cache_enabled": cfg.cache_enabled,
            }
            if screening
            else None
        ),
        "criteria": {
            r: {"status": c.status, "source": c.source, "sha256": c.sha256}
            for r, c in review_criteria.items()
        },
        "aborted": aborted is not None,
        "reviews_completed": [m["review"] for m in per_review],
        "verification_failures": metrics.verification_failures(conn, run_id) if screening else {},
        "per_review": per_review,
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
        "ceiling_usd": cfg.budget.ceiling_usd,
        "aborted_reason": aborted,
    }

    _write_text(run_dir / "config.yaml", cfg.source_text or "")
    _write_json(
        run_dir / "resolved_config.json",
        cfg.model_dump(mode="json", exclude={"source_path", "source_text"}),
    )
    _write_text(run_dir / "git_sha.txt", f"{sha}{'-dirty' if dirty else ''}\n")
    _write_json(run_dir / "metrics.json", results)
    _write_json(run_dir / "run.json", run_info)

    print()
    if screening:
        print(metrics.format_screening_table(per_review))
        if results["verification_failures"]:
            print("\nverification failures:")
            for note, n in results["verification_failures"].items():
                print(f"  {note:36} {n}")
        print(f"\nspend ${meter.spend_usd:.4f} of ${cfg.budget.ceiling_usd:.2f} "
              f"({meter.cached_calls} of {meter.calls} calls cached)")
    else:
        print(metrics.format_ranking_table(per_review))
    print(f"artefacts -> {run_dir}")

    return run_dir


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the screening pipeline.")
    parser.add_argument("--config", required=True, help="Path to a config YAML")
    parser.add_argument(
        "--require-clean",
        action="store_true",
        help="Refuse to run with uncommitted changes. Use for every reported run.",
    )
    args = parser.parse_args(argv)
    try:
        run(load_config(args.config), require_clean=args.require_clean)
    except (DirtyTree, MissingCorpus, CacheMismatch) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
