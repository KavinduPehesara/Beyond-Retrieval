"""Week 14 — ASReview comparison. Exports one review to the plain CSV shape
ASReview's own CLI reads natively (``title``, ``abstract``, ``label_included``
are column names ASReview recognises directly; see
``asreview.config.COLUMN_DEFINITIONS``), so ASReview is genuinely run as an
external tool, not reimplemented, per CLAUDE.md's standing decision.

``work_id`` is carried as an extra column ASReview ignores, so the exported
rows still trace back to the same records after simulation -- this is the
one place outside ``eval/metrics.py`` that reads ``label_included``, for the
same reason ``metrics.py`` is allowed to: comparing a baseline against
ground truth is the whole point of this export, not something screening
could ever see.

Usage:
    python -m slr.eval.asreview_baseline --review Nelson_2002 --out data/asreview/Nelson_2002.csv

Then, outside this codebase, ASReview's own simulate command:
    asreview simulate data/asreview/Nelson_2002.csv \\
        -s runs/<ts>-asreview-nelson2002/project.asreview \\
        --seed 42 --init_seed 42 -m nb -q max -e tfidf --stop_if min
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

from slr.db import connect


def export_review(conn, review: str, out_path: Path) -> int:
    rows = conn.execute(
        "SELECT work_id, title, abstract, label_included FROM work "
        "WHERE review = ? ORDER BY work_id",
        (review,),
    ).fetchall()
    if not rows:
        raise SystemExit(f"no records for {review!r} -- has it been ingested?")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["work_id", "title", "abstract", "label_included"])
        for row in rows:
            writer.writerow([row["work_id"], row["title"] or "", row["abstract"] or "", row["label_included"]])
    return len(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--review", required=True)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--db", default="data/slr.db")
    args = parser.parse_args(argv)

    conn = connect(args.db)
    try:
        n = export_review(conn, args.review, args.out)
    finally:
        conn.close()
    print(f"{n} records -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
