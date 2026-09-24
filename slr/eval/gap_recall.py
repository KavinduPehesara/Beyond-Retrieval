"""Gap-discovery recall: how many stated gaps does the model miss?

Precision (``gap_report.py``) only looks at what the model flagged. Recall
needs a labelled sample drawn from what it did NOT flag. Two steps, so the
labelling can be blind:

    draw   seeded random sample of ``not_stated`` records (where misses hide)
           plus a few already-flagged records as blind controls, shuffled
           together. Writes ``sample.json`` (title + abstract only, what the
           labeller sees) and ``sample_key.json`` (which is which).
    score  reads ``labels.json`` -- {index: true/false, does the abstract
           state a gap} -- and estimates recall per review. An optional
           ``miss_types.json`` ({index: "open" | "motivating"}) also gives
           recall for open gaps only, the ones a future researcher could
           still pursue.

Estimator, per review: the miss rate f among sampled ``not_stated`` records
scales to that review's whole ``not_stated`` pool (FN = f * pool);
TP = flagged records rated valid; recall = TP / (TP + FN). With samples this
small the interval is wide, so the Wilson interval on f is reported and
recall is also given at its two bounds. Results are per review, never
pooled (rule 5).

Usage:
    python -m slr.eval.gap_recall draw --run Menon_2022=<run_id> ... --seed 42
    python -m slr.eval.gap_recall score --dir runs/<ts>-gaprecall-<hash>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import sys
from datetime import datetime, timezone
from pathlib import Path

from slr.db import connect
from slr.eval.harness import git_state


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for k successes in n trials."""
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def estimate_recall(tp: int, pool: int, sampled: int, misses: int) -> dict:
    """Recall for one review from a sample of its not_stated pool."""
    f = misses / sampled if sampled else None
    lo, hi = wilson(misses, sampled)

    def recall(rate: float) -> float | None:
        fn = rate * pool
        return tp / (tp + fn) if (tp + fn) else None

    return {
        "true_positives": tp,
        "not_stated_pool": pool,
        "sampled_not_stated": sampled,
        "misses_in_sample": misses,
        "miss_rate": f,
        "miss_rate_ci95": [lo, hi],
        "estimated_false_negatives": None if f is None else f * pool,
        "recall_estimate": None if f is None else recall(f),
        "recall_at_worst_miss_rate": recall(hi),
        "recall_at_best_miss_rate": recall(lo),
    }


def draw(conn, runs: dict[str, str], *, n_not_stated: int, n_flagged: int, seed: int) -> tuple[list, list]:
    rng = random.Random(seed)
    items = []
    for review in sorted(runs):
        run_id = runs[review]
        for stratum, n in (("not_stated", n_not_stated), ("gap_stated", n_flagged)):
            ids = [
                r["work_id"]
                for r in conn.execute(
                    "SELECT work_id FROM gap_statement WHERE run_id = ? AND review = ? AND value = ? "
                    "ORDER BY work_id",
                    (run_id, review, stratum),
                )
            ]
            for work_id in rng.sample(ids, min(n, len(ids))):
                items.append({"review": review, "work_id": work_id, "stratum": stratum})
    rng.shuffle(items)
    sheet, key = [], []
    for i, it in enumerate(items):
        row = conn.execute(
            "SELECT title, abstract FROM work WHERE review = ? AND work_id = ?",
            (it["review"], it["work_id"]),
        ).fetchone()
        sheet.append({"index": i, "title": row["title"], "abstract": row["abstract"]})
        key.append({"index": i, **it})
    return sheet, key


def score(conn, runs: dict[str, str], key: list, labels: dict[str, bool], miss_types: dict[str, str] | None = None) -> dict:
    per_review = {}
    control_pairs = []
    for review in sorted(runs):
        run_id = runs[review]
        pool = conn.execute(
            "SELECT COUNT(*) c FROM gap_statement WHERE run_id = ? AND review = ? AND value = 'not_stated'",
            (run_id, review),
        ).fetchone()["c"]
        tp = conn.execute(
            "SELECT COUNT(*) c FROM gap_statement WHERE run_id = ? AND review = ? "
            "AND value = 'gap_stated' AND rating = 'valid'",
            (run_id, review),
        ).fetchone()["c"]
        tp_open = conn.execute(
            "SELECT COUNT(*) c FROM gap_statement WHERE run_id = ? AND review = ? "
            "AND value = 'gap_stated' AND rating = 'valid' AND (rating_note IS NULL OR rating_note NOT LIKE '%motivation%')",
            (run_id, review),
        ).fetchone()["c"]
        sampled = misses = open_misses = 0
        for k in key:
            if k["review"] != review:
                continue
            label = labels[str(k["index"])]
            if k["stratum"] == "not_stated":
                sampled += 1
                misses += int(label)
                if label and miss_types and miss_types.get(str(k["index"])) == "open":
                    open_misses += 1
            else:
                rating = conn.execute(
                    "SELECT rating FROM gap_statement WHERE run_id = ? AND review = ? AND work_id = ?",
                    (run_id, review, k["work_id"]),
                ).fetchone()["rating"]
                control_pairs.append((review, label, rating == "valid"))
        per_review[review] = estimate_recall(tp, pool, sampled, misses)
        if miss_types is not None:
            # A miss is "open" if it states a gap still open to a future
            # researcher, not one that only motivates the paper itself.
            per_review[review]["open_gap"] = estimate_recall(tp_open, pool, sampled, open_misses)
    agree = sum(1 for _, blind, earlier in control_pairs if blind == earlier)
    return {
        "per_review": per_review,
        "blind_control_agreement": {
            "n": len(control_pairs),
            "agree": agree,
            "detail": [{"review": r, "blind_label": b, "earlier_rating_valid": e} for r, b, e in control_pairs],
        },
    }


def _parse_runs(items: list[str]) -> dict[str, str]:
    return dict(i.split("=", 1) for i in items)


def _load_runs_from_dir(d: Path) -> dict[str, str]:
    return json.loads((d / "sample_key.json").read_text(encoding="utf-8"))["runs"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("draw")
    d.add_argument("--run", action="append", required=True, help="Review=gap_run_id (repeatable)")
    d.add_argument("--seed", type=int, default=42)
    d.add_argument("--n-not-stated", type=int, default=10)
    d.add_argument("--n-flagged", type=int, default=3)
    d.add_argument("--db", default="data/slr.db")
    d.add_argument("--runs-dir", default="runs")
    s = sub.add_parser("score")
    s.add_argument("--dir", required=True)
    s.add_argument("--db", default="data/slr.db")
    args = parser.parse_args(argv)

    conn = connect(args.db)
    try:
        if args.cmd == "draw":
            runs = _parse_runs(args.run)
            sheet, key = draw(conn, runs, n_not_stated=args.n_not_stated, n_flagged=args.n_flagged, seed=args.seed)
            cfg = {"runs": runs, "seed": args.seed, "n_not_stated": args.n_not_stated, "n_flagged": args.n_flagged}
            h = hashlib.sha256(json.dumps(cfg, sort_keys=True).encode()).hexdigest()[:10]
            out = Path(args.runs_dir) / f"{datetime.now(timezone.utc):%Y%m%dT%H%M%S%fZ}-gaprecall-{h}"
            out.mkdir(parents=True)
            sha, dirty = git_state(Path(args.runs_dir))
            (out / "git_sha.txt").write_text(f"{sha}{'-dirty' if dirty else ''}\n", encoding="utf-8", newline="\n")
            (out / "sample.json").write_text(json.dumps(sheet, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
            (out / "sample_key.json").write_text(json.dumps({"config": cfg, "runs": runs, "key": key}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
            print(f"{len(sheet)} items -> {out}")
            return 0
        out = Path(args.dir)
        keyfile = json.loads((out / "sample_key.json").read_text(encoding="utf-8"))
        labels = json.loads((out / "labels.json").read_text(encoding="utf-8"))
        missing = [k["index"] for k in keyfile["key"] if str(k["index"]) not in labels]
        if missing:
            print(f"error: unlabelled items: {missing}", file=sys.stderr)
            return 2
        types_path = out / "miss_types.json"
        miss_types = json.loads(types_path.read_text(encoding="utf-8")) if types_path.exists() else None
        result = score(conn, keyfile["runs"], keyfile["key"], labels, miss_types)
        result["config"] = keyfile["config"]
        (out / "metrics.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8", newline="\n")
        for review, m in result["per_review"].items():
            print(f"{review:20} pool {m['not_stated_pool']:3} sampled {m['sampled_not_stated']:2} misses {m['misses_in_sample']} "
                  f"recall~{m['recall_estimate']:.2f} (worst {m['recall_at_worst_miss_rate']:.2f})")
        for review, m in result["per_review"].items():
            if "open_gap" in m:
                o = m["open_gap"]
                print(f"  open-gap only: {review:20} misses {o['misses_in_sample']} recall~{o['recall_estimate']:.2f} (worst {o['recall_at_worst_miss_rate']:.2f})")
        c = result["blind_control_agreement"]
        print(f"blind controls agree with earlier ratings: {c['agree']}/{c['n']}")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
