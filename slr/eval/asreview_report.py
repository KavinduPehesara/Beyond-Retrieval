"""Week 14 — turn a finished ``asreview simulate`` run into a metrics figure
directly comparable to this project's own ranking metrics (TNR@95, WSS@95).

Reuses ``slr.eval.metrics.ranking_metrics`` unchanged -- the same function
every BM25/dense/hybrid/rerank figure in this project is computed with -- so
"ASReview beats/loses to our ranking" is a like-for-like comparison, not two
different formulas that happen to share a name.

ASReview's simulation, run with ``--stop_if min``, stops querying the moment
every relevant record has been found; records after that point were never
scored or ranked at all. To get a figure over the *whole* review (every other
reported TNR@95/WSS@95 in this project ranks 100% of a review), the records
ASReview never reached are appended after it, in their original dataset
order. This is provably inconsequential to the result: the 95%-recall cutoff
``ranking_metrics`` looks for always falls before the 100%-recall point
where ASReview itself stopped, so nothing appended afterward can change
which records are counted as found before the cutoff.

Usage:
    python -m slr.eval.asreview_report --review Nelson_2002 \\
        --project runs/asreview-nelson2002/project.asreview \\
        --export data/asreview/Nelson_2002.csv
"""

from __future__ import annotations

import argparse
import csv
import sqlite3
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from slr.eval.harness import _write_json, _write_text, git_state
from slr.eval.metrics import ranking_metrics


def _asreview_order(project_path: Path) -> list[int]:
    """record_id (0-based row index into the exported CSV), in the order
    ASReview's active learner actually queried them."""
    with zipfile.ZipFile(project_path) as zf:
        review_dirs = [n for n in zf.namelist() if n.startswith("reviews/") and n.endswith("/results.sql")]
        if not review_dirs:
            raise SystemExit(f"no results.sql found in {project_path}")
        with tempfile.TemporaryDirectory() as tmp:
            db_path = zf.extract(review_dirs[0], tmp)
            conn = sqlite3.connect(db_path)
            try:
                rows = conn.execute("SELECT record_id FROM results ORDER BY rowid").fetchall()
            finally:
                conn.close()
    return [r[0] for r in rows]


def build_ranking(export_csv: Path, project_path: Path) -> tuple[list[str], dict[str, int]]:
    with export_csv.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    row_work_id = [r["work_id"] for r in rows]
    labels = {r["work_id"]: int(r["label_included"]) for r in rows}

    queried = _asreview_order(project_path)
    ranked_ids = [row_work_id[i] for i in queried]
    never_queried = [wid for wid in row_work_id if wid not in set(ranked_ids)]
    return ranked_ids + never_queried, labels


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--review", required=True)
    parser.add_argument("--project", required=True, type=Path)
    parser.add_argument("--export", required=True, type=Path)
    parser.add_argument("--runs-dir", default=Path("runs"), type=Path)
    parser.add_argument("--recall-target", default=0.95, type=float)
    args = parser.parse_args(argv)

    full_ranking, labels = build_ranking(args.export, args.project)
    metrics = ranking_metrics(full_ranking, labels, recall_target=args.recall_target)

    sha, dirty = git_state(args.runs_dir)
    run_id = f"asreview-{args.review.lower()}-{datetime.now(timezone.utc):%Y%m%dT%H%M%S%fZ}"
    run_dir = args.runs_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    _write_json(run_dir / "metrics.json", {"review": args.review, "tool": "asreview", **metrics.as_dict()})
    _write_json(
        run_dir / "run.json",
        {
            "run_id": run_id,
            "review": args.review,
            "tool": "asreview (external, simulate -m nb -q max -e tfidf, seed 42)",
            "export_csv": str(args.export),
            "project_file": str(args.project),
            "n_never_queried": metrics.n_ranked - len(_asreview_order(args.project)),
            "started_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    _write_text(run_dir / "git_sha.txt", f"{sha}{'-dirty' if dirty else ''}\n")

    print(f"review          {args.review}")
    print(f"n                {metrics.n_ranked}")
    print(f"included         {metrics.n_included}")
    print(f"recall@cutoff    {metrics.recall_at_cutoff:.3f}")
    print(f"TNR@{metrics.recall_target:.2f}         {metrics.tnr_at_recall:.3f}")
    print(f"WSS@{metrics.recall_target:.2f}         {metrics.wss_at_recall:.3f}")
    print(f"artefacts -> {run_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
