"""Write a gap-discovery run's precision ratings to ``gap_ratings.json``.

Same reasoning as ``override_report.py``: the week 11 precision number
should trace to a run directory (rule 2), not live only as rows in a
gitignored database.

Usage:
    python -m slr.eval.gap_report --run-id <id> --review Nelson_2002 \\
        --runs-dir runs
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from slr.db import connect
from slr.services.gap import precision


def build_report(conn, run_id: str, review: str) -> dict:
    rows = conn.execute(
        "SELECT work_id, evidence_span, rating, rating_note FROM gap_statement "
        "WHERE run_id = ? AND review = ? AND value = 'gap_stated' ORDER BY work_id",
        (run_id, review),
    ).fetchall()
    summary = precision(conn, run_id, review)
    return {
        "run_id": run_id,
        "review": review,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": summary.as_dict(),
        "records": [
            {
                "work_id": r["work_id"],
                "evidence_span": r["evidence_span"],
                "rating": r["rating"],
                "rating_note": r["rating_note"],
            }
            for r in rows
        ],
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

    if report["summary"]["n_gap_stated"] == 0:
        print(f"error: no gap statements found for run {args.run_id!r}, review {args.review!r}", file=sys.stderr)
        return 2

    out_path = Path(args.runs_dir) / args.run_id / "gap_ratings.json"
    if not out_path.parent.exists():
        print(f"error: run directory not found: {out_path.parent}", file=sys.stderr)
        return 2
    out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")

    s = report["summary"]
    prec = f"{s['precision']:.1%}" if s["precision"] is not None else "n/a"
    print(f"{s['n_gap_stated']} gap statements, {s['n_rated']} rated: {s['n_valid']} valid, "
          f"{s['n_invalid']} invalid (precision {prec})")
    print(f"written -> {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
