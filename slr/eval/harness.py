"""Command-line harness. The only entry point that produces reportable numbers.

Takes a config file, runs the pipeline headlessly, and writes a run directory
containing the config, the raw responses, the metrics, and the commit hash of
the code that produced them.

It calls the services directly and never passes through an API or interface.
That is deliberate: every result must be reproducible from a config file
without a browser, and the demonstrated system must not be able to diverge
from the measured one.

Usage:
    python -m slr.eval.harness --config configs/smoke.yaml
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from slr.adapters.llm import BudgetExceeded, Meter, build_provider
from slr.config import Config, load_config
from slr.db import connect
from slr.eval.metrics import format_table, review_metrics, verification_failures
from slr.services import retrieve
from slr.services.ingest import CRITERIA
from slr.services.screen import (
    load_prompt_template,
    persist,
    screen_record,
    to_jsonl,
)


def git_sha() -> str:
    """The commit the code was at. Rule 3: this goes in every artefact."""
    try:
        sha = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], stderr=subprocess.DEVNULL, text=True
        ).strip()
        dirty = subprocess.check_output(
            ["git", "status", "--porcelain"], stderr=subprocess.DEVNULL, text=True
        ).strip()
        return f"{sha}{'-dirty' if dirty else ''}"
    except Exception:
        return "unknown"


def run(cfg: Config) -> Path:
    started = datetime.now(timezone.utc)
    run_id = f"{started:%Y%m%dT%H%M%SZ}-{cfg.config_hash}"
    run_dir = cfg.runs_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    sha = git_sha()
    if sha.endswith("-dirty"):
        print(
            "  ! working tree is dirty — commit before a run you intend to "
            "report (rule 3)\n"
        )

    conn = connect(cfg.db_path)
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
        "INSERT OR REPLACE INTO run "
        "(run_id, config_hash, config_name, git_sha, provider, model, "
        " prompt_version, temperature, started_at) VALUES (?,?,?,?,?,?,?,?,?)",
        (
            run_id,
            cfg.config_hash,
            cfg.name,
            sha,
            provider.name,
            provider.model,
            cfg.screening.prompt_version,
            cfg.screening.temperature,
            started.isoformat(),
        ),
    )
    conn.commit()

    print(f"run {run_id}")
    print(f"  provider   {provider.name} / {provider.model}")
    print(f"  prompt     {cfg.screening.prompt_version}")
    print(f"  commit     {sha}")
    print(f"  ceiling    ${cfg.budget.ceiling_usd:.2f}\n")

    aborted = None
    responses_path = run_dir / "responses.jsonl"

    with responses_path.open("w", encoding="utf-8") as log:
        for review in cfg.dataset.reviews:
            criteria = CRITERIA.get(review, "See the review's published protocol.")
            rows = retrieve.random_rank(
                conn, review, seed=cfg.dataset.seed, limit=cfg.dataset.max_records
            )
            if not rows:
                print(f"  {review}: no records — run ingest first")
                continue

            print(f"  {review}: screening {len(rows)} records")
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
                        f"    {i}/{len(rows)}  verified "
                        f"{meter.calls - meter.cached_calls} live, "
                        f"{meter.cached_calls} cached, ${meter.spend_usd:.4f}"
                    )
            conn.commit()
            if aborted:
                break

    finished = datetime.now(timezone.utc)
    conn.execute(
        "UPDATE run SET finished_at = ?, total_cost_usd = ? WHERE run_id = ?",
        (finished.isoformat(), meter.spend_usd, run_id),
    )
    conn.commit()

    per_review = [review_metrics(conn, run_id, r) for r in cfg.dataset.reviews]
    failures = verification_failures(conn, run_id)

    metrics = {
        "run_id": run_id,
        "config_name": cfg.name,
        "config_hash": cfg.config_hash,
        "git_sha": sha,
        "provider": provider.name,
        "model": provider.model,
        "prompt_version": cfg.screening.prompt_version,
        "temperature": cfg.screening.temperature,
        "started_at": started.isoformat(),
        "finished_at": finished.isoformat(),
        "duration_s": round((finished - started).total_seconds(), 2),
        "aborted": aborted,
        "totals": {
            "calls": meter.calls,
            "cached_calls": meter.cached_calls,
            "tokens_in": meter.tokens_in,
            "tokens_out": meter.tokens_out,
            "cost_usd": round(meter.spend_usd, 6),
            "ceiling_usd": cfg.budget.ceiling_usd,
        },
        "verification_failures": failures,
        "per_review": [m.as_dict() for m in per_review],
    }

    (run_dir / "config.yaml").write_text(cfg.source_text or "", encoding="utf-8")
    (run_dir / "git_sha.txt").write_text(sha + "\n", encoding="utf-8")
    (run_dir / "metrics.json").write_text(
        json.dumps(metrics, indent=2), encoding="utf-8"
    )

    print("\n" + format_table(per_review))
    if failures:
        print("\nverification failures:")
        for note, n in failures.items():
            print(f"  {note:36} {n}")
    print(f"\nspend ${meter.spend_usd:.4f} of ${cfg.budget.ceiling_usd:.2f}")
    print(f"artefacts -> {run_dir}")

    conn.close()
    return run_dir


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the screening pipeline.")
    parser.add_argument("--config", required=True, help="Path to a config YAML")
    args = parser.parse_args(argv)
    run(load_config(args.config))
    return 0


if __name__ == "__main__":
    sys.exit(main())
