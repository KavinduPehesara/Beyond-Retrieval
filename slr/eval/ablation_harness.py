"""CLI for the ablation study.

Writes ``runs/<ts>-ablation-<hash>/`` with the same discipline as every
other harness here: a resolved config, the figures, and the commit the code
was at. Reads only recorded data -- no model is called, so this costs
nothing and can be re-run freely.

    python -m slr.eval.ablation_harness
    python -m slr.eval.ablation_harness --review Nelson_2002
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from slr.api.runs_index import list_reviews_with_screen_runs
from slr.db import connect
from slr.eval.ablation import (
    format_verifier_table,
    stage_ablation,
    verification_ablation_from_runs,
    verifier_ablation,
)

# The week 9 retrieval runs, re-run under commit 393db15 after the BM25
# corpus-independence fix. Named here rather than discovered, because an
# ablation has to compare the runs it says it compares.
RETRIEVAL_STAGES = {
    "bm25": "20260921T072321083927Z-2ecaa4d8d7",
    "dense": "20260921T072327017657Z-423a543937",
    "hybrid": "20260921T072358111413Z-538ba6a5bc",
    "rerank": "20260921T072421885220Z-da2f69f68d",
}

PROMPT_VARIANTS = {
    "screen_v1": "20260921T122043060429Z-df0fc175b2",
    "screen_v2": "20260922T115430121258Z-33c61120f3",
    "screen_v3": "20260922T123132050251Z-6e54fdd202",
}

MODEL_TIERS = {
    "qwen2.5:7b-instruct": "20260921T122043060429Z-df0fc175b2",
    "qwen3:8b": "20260922T123756418737Z-298d2bcad2",
}


def git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ablation study over recorded runs.")
    parser.add_argument("--db", default="data/slr.db")
    parser.add_argument("--runs", default="runs")
    parser.add_argument("--review", action="append", help="limit to these reviews")
    parser.add_argument("--out", default=None, help="run directory (default: auto)")
    args = parser.parse_args(argv)

    runs_dir = Path(args.runs)
    conn = connect(Path(args.db))

    screen_runs = list_reviews_with_screen_runs(runs_dir)
    if args.review:
        screen_runs = {r: v for r, v in screen_runs.items() if r in args.review}
    if not screen_runs:
        print("No screening runs found. Nothing to ablate.")
        return 1

    verifier = []
    for review, run_id in screen_runs.items():
        print(f"  verifier ablation: {review} ({run_id})")
        verifier.append(verifier_ablation(conn, run_id, review))

    retrieval = stage_ablation(runs_dir, RETRIEVAL_STAGES)
    prompts = verification_ablation_from_runs(runs_dir, PROMPT_VARIANTS)
    models = verification_ablation_from_runs(runs_dir, MODEL_TIERS)

    payload = {
        "mode": "ablation",
        "reviews": list(screen_runs),
        "screen_runs": screen_runs,
        "verifier": verifier,
        "retrieval": retrieval,
        "prompt_variants": prompts,
        "model_tiers": models,
    }

    digest = hashlib.sha256(
        json.dumps(payload["screen_runs"], sort_keys=True).encode("utf-8")
    ).hexdigest()[:10]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f") + "Z"
    out = Path(args.out) if args.out else runs_dir / f"{stamp}-ablation-{digest}"
    out.mkdir(parents=True, exist_ok=True)

    (out / "metrics.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    (out / "git_sha.txt").write_text(git_sha() + "\n", encoding="utf-8")
    (out / "ablation.md").write_text(
        "# Verifier ablation\n\n" + format_verifier_table(verifier) + "\n",
        encoding="utf-8",
    )

    print(f"\nWrote {out}")
    print()
    print(format_verifier_table(verifier))
    conn.close()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
