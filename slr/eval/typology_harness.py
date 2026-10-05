"""CLI for the error typology.

Classifies every verification failure across the current screening runs, and
writes a seeded sample as a blind rating sheet so the automatic labels can
be checked by a person rather than trusted.

Reads recorded data only -- no model is called, so this costs nothing.

    python -m slr.eval.typology_harness
    python -m slr.eval.typology_harness --sample 50 --seed 42
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
from slr.eval.error_typology import (
    classify_run,
    distribution,
    format_distribution,
    sample_for_rating,
)


def git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Why does verification fail?")
    parser.add_argument("--db", default="data/slr.db")
    parser.add_argument("--runs", default="runs")
    parser.add_argument("--sample", type=int, default=50, help="rows in the rating sheet")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)

    runs_dir = Path(args.runs)
    conn = connect(Path(args.db))

    screen_runs = list_reviews_with_screen_runs(runs_dir)
    if not screen_runs:
        print("No screening runs found.")
        return 1

    classified: list[dict] = []
    for review, run_id in screen_runs.items():
        got = classify_run(conn, run_id, review)
        print(f"  {review:22s} {len(got):6,} failures classified")
        classified.extend(got)

    dist = distribution(classified)
    sheet = sample_for_rating(classified, n=args.sample, seed=args.seed)

    # How often a failed decision was also factually wrong, by category. A
    # quote that isn't real attached to a decision that was right is a
    # different problem from one attached to a decision that was wrong.
    wrong_by_category: dict[str, dict] = {}
    for item in classified:
        bucket = wrong_by_category.setdefault(
            item["category"], {"n": 0, "wrong": 0}
        )
        bucket["n"] += 1
        proposed_include = item["decision"] == "include"
        if proposed_include != item["truly_included"]:
            bucket["wrong"] += 1
    for bucket in wrong_by_category.values():
        bucket["share_wrong"] = round(bucket["wrong"] / bucket["n"], 4) if bucket["n"] else None

    payload = {
        "mode": "error_typology",
        "screen_runs": screen_runs,
        "sample_seed": args.seed,
        "sample_size": len(sheet),
        "distribution": dist,
        "wrong_by_category": wrong_by_category,
        "sample": sheet,
    }

    digest = hashlib.sha256(
        json.dumps(screen_runs, sort_keys=True).encode("utf-8")
    ).hexdigest()[:10]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f") + "Z"
    out = Path(args.out) if args.out else runs_dir / f"{stamp}-typology-{digest}"
    out.mkdir(parents=True, exist_ok=True)

    (out / "metrics.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    (out / "git_sha.txt").write_text(git_sha() + "\n", encoding="utf-8")
    (out / "typology.md").write_text(
        "# Why verification fails\n\n" + format_distribution(dist) + "\n",
        encoding="utf-8",
    )
    # The rating sheet, with the automatic label withheld from the columns a
    # rater reads -- the same discipline the gap-recall pass used.
    blind = [
        {k: v for k, v in row.items() if not k.startswith("_")} for row in sheet
    ]
    (out / "rating_sheet.json").write_text(json.dumps(blind, indent=2), encoding="utf-8")

    print(f"\nWrote {out}")
    print()
    print(format_distribution(dist))
    conn.close()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
