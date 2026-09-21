"""Inter-run Gwet AC1 across repeated runs of one configuration.

The *reproducible* property in RQ1 needs a genuine variance number, not just
"same config, cache hit, byte-identical metrics.json" (already proven by the
weeks 7-8 exit test). This reads each run's own metrics.json to confirm the
supplied run directories really share one config_hash -- the check a human
would otherwise have to do by hand before trusting the AC1 number it
prints -- then delegates to ``slr.eval.metrics.inter_run_agreement``.

Usage:
    python -m slr.eval.inter_run --review Nelson_2002 \\
        runs/<ts1>-<hash> runs/<ts2>-<hash> runs/<ts3>-<hash> ...
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from slr.db import connect
from slr.eval import metrics


def load_run_ids(run_dirs: list[Path]) -> list[str]:
    """Run ids from a set of run directories, after checking they share one config_hash."""
    run_ids = []
    hashes = set()
    for run_dir in run_dirs:
        payload = json.loads((run_dir / "metrics.json").read_text(encoding="utf-8"))
        hashes.add(payload["config_hash"])
        run_ids.append(run_dir.name)
    if len(hashes) != 1:
        raise ValueError(
            f"run directories do not share one config_hash, so they are not "
            f"repeats of the same configuration: {sorted(hashes)}"
        )
    return run_ids


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default="data/slr.db")
    parser.add_argument("--review", required=True)
    parser.add_argument("run_dirs", nargs="+", help="Run directories to treat as repeats")
    args = parser.parse_args(argv)

    run_dirs = [Path(d) for d in args.run_dirs]
    try:
        run_ids = load_run_ids(run_dirs)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    conn = connect(args.db)
    try:
        result = metrics.inter_run_agreement(conn, run_ids, args.review)
    finally:
        conn.close()

    print(f"inter-run Gwet AC1, {args.review}, {len(run_ids)} runs:")
    for run_id in run_ids:
        print(f"  run: {run_id}")
    print(f"  n_units={result.n_units} n_units_paired={result.n_units_paired}")
    print(f"  pa={result.pa} pe={result.pe}")
    print(f"  AC1={result.coefficient}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
