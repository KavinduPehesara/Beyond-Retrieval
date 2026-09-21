"""Record a human override against one screened record.

The reviewer's half of "system proposes, reviewer disposes" (RQ1,
overridable). Prints the system's original proposal before writing, so the
reviewer sees exactly what they are confirming or overturning.

Usage:
    python -m slr.eval.override_cli --run-id <id> --review Nelson_2002 \\
        --work-id W123 --decision exclude \\
        --rationale "cohort study, not an RCT; criteria require RCT design"
"""

from __future__ import annotations

import argparse
import sys

from slr.db import connect
from slr.services.override import model_decision, record_override


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default="data/slr.db")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--review", required=True)
    parser.add_argument("--work-id", required=True)
    parser.add_argument("--decision", required=True, choices=["include", "exclude"])
    parser.add_argument("--rationale", default=None)
    args = parser.parse_args(argv)

    conn = connect(args.db)
    try:
        before = model_decision(conn, args.run_id, args.review, args.work_id)
        if before is None:
            print(
                f"error: {args.review}/{args.work_id} was not screened in run "
                f"{args.run_id!r}",
                file=sys.stderr,
            )
            return 2
        record_override(
            conn,
            run_id=args.run_id,
            review=args.review,
            work_id=args.work_id,
            decision=args.decision,
            rationale=args.rationale,
        )
        verb = "confirmed" if before.decision == args.decision else "OVERRODE"
        print(
            f"{verb}: system said {before.decision!r} "
            f"(verified={before.span_verified}, confidence={before.confidence}) "
            f"-> human says {args.decision!r}"
        )
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
