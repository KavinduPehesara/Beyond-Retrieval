"""Write a run directory's human overrides to ``overrides.json``.

Every other reportable number in this project traces to a run directory
(rule 2); the override demonstration should too, not live only as rows in a
gitignored database. Combines ``slr.services.override.override_summary``
(blind to ground truth) with ``slr.eval.metrics.override_accuracy`` (the one
join allowed to compare a human decision with the label) into one file.

Usage:
    python -m slr.eval.override_report --run-id <id> --review Nelson_2002 \\
        --runs-dir runs
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from slr.db import connect
from slr.eval import metrics
from slr.services.override import override_summary


def build_report(conn, run_id: str, review: str) -> dict:
    summary = override_summary(conn, run_id, review)
    records = metrics.override_accuracy(conn, run_id, review)
    return {
        "run_id": run_id,
        "review": review,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "n_overrides": summary.n_overrides,
            "n_changed": summary.n_changed,
            "n_confirmed": summary.n_confirmed,
            "override_rate": summary.override_rate,
            "by_model_decision": summary.by_model_decision,
        },
        "records": [r.as_dict() for r in records],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default="data/slr.db")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--review", required=True)
    parser.add_argument("--runs-dir", default="runs")
    args = parser.parse_args(argv)

    conn = connect(args.db)
    try:
        report = build_report(conn, args.run_id, args.review)
    finally:
        conn.close()

    if report["summary"]["n_overrides"] == 0:
        print(f"error: no overrides recorded for run {args.run_id!r}, review {args.review!r}", file=sys.stderr)
        return 2

    out_path = Path(args.runs_dir) / args.run_id / "overrides.json"
    if not out_path.parent.exists():
        print(f"error: run directory not found: {out_path.parent}", file=sys.stderr)
        return 2
    out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")

    s = report["summary"]
    print(f"{s['n_overrides']} overrides: {s['n_changed']} changed, {s['n_confirmed']} confirmed "
          f"(rate {s['override_rate']:.1%})")
    print(f"written -> {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
