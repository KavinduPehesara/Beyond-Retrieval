"""Chart data, shaped once so every panel can plot it.

One function per chart. Each takes a connection (and sometimes a run id or
the runs directory), returns plain lists and dicts, and plots nothing --
the Streamlit pages and the API layer do that. Keeping the shaping here
means it is testable without a browser, and means a figure that ends up in
the report is computed by the same code the dashboard shows.

This module lives in ``slr.eval`` for a reason, not for tidiness. Four of
these functions read ``work.label_included``: the recall curve, prevalence,
the verification-vs-recall scatter and the extraction/gap denominators that
depend on which records were truly included. Rule 4 permits ground truth to
be read inside ``slr/eval`` and nowhere else, so a chart that needs it has
to be written here. Nothing in this module builds a prompt, and nothing in
it is reachable from ``slr/services/screen.py``.

Nothing here computes a *new* reported figure either. Every number is
either already in a run directory's ``metrics.json`` or a direct count over
the tables a harness wrote; the charts are a view of recorded results, in
the same spirit as ``report_tables.py``.
"""

from __future__ import annotations

import json
import sqlite3
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Sequence

from slr.eval.metrics import decision_order, load_labels

# The four extraction fields, in the order every report in this project
# lists them. Fixed rather than discovered from the data so a field that
# verified zero times still gets a row in the heatmap instead of vanishing.
EXTRACTION_FIELDS = ("study_design", "sample_size", "country", "key_finding")

CONFIDENCE_BINS = 10


# --------------------------------------------------------------------------
# Screening: the recall curve
# --------------------------------------------------------------------------


@dataclass
class RecallCurve:
    """Recall as a reviewer reads down a ranking.

    ``x`` is records read, ``y`` is the fraction of all included records
    found by that point. ``cutoff_95`` is where the curve crosses 95%
    recall -- the same point ``ranking_metrics`` reports TNR at, so the
    chart and the table cannot disagree.
    """

    strategy: str
    review: str
    n_ranked: int
    n_included: int
    x: list[int]
    y: list[float]
    cutoff_95: int | None
    random_baseline: list[float]

    def as_dict(self) -> dict:
        return asdict(self)


def recall_curve(
    ranked_ids: Sequence[str],
    labels: dict[str, int],
    *,
    strategy: str = "",
    review: str = "",
    max_points: int = 400,
) -> RecallCurve:
    """The standard screening-prioritisation chart, from a ranking.

    Downsampled to at most ``max_points`` so a 5,935-record review sends a
    few hundred numbers to the browser instead of six thousand. Every
    included record's position is kept regardless of downsampling -- those
    are the points where the curve actually moves, and dropping one would
    flatten a step that really happened. The 95% cutoff is computed on the
    full ranking, never on the downsampled view.
    """
    ids = list(ranked_ids)
    unknown = [i for i in ids if i not in labels]
    if unknown:
        raise ValueError(f"ranking contains records not in the review: {unknown[:3]}")

    included = sum(labels[i] for i in ids)
    if included == 0:
        return RecallCurve(strategy, review, len(ids), 0, [0], [0.0], None, [0.0])

    # Every position where an include sits -- these are the points where
    # the curve actually steps up, and the 95% crossing.
    found = 0
    cutoff_95: int | None = None
    target = 0.95 * included
    step_positions = {0, len(ids)}
    for position, work_id in enumerate(ids, 1):
        if labels[work_id]:
            found += 1
            step_positions.add(position)
            if cutoff_95 is None and found >= target:
                cutoff_95 = position

    # Evenly spaced filler too, so long flat stretches between includes are
    # drawn flat rather than interpolated straight across.
    if len(ids) > max_points:
        stride = max(1, len(ids) // max_points)
        filler = range(0, len(ids), stride)
    else:
        filler = range(0, len(ids) + 1)
    step_positions.update(filler)

    x = sorted(step_positions)
    y = _running_recall_at(ids, labels, x, included)

    baseline = [position / len(ids) for position in x]
    return RecallCurve(
        strategy=strategy,
        review=review,
        n_ranked=len(ids),
        n_included=included,
        x=x,
        y=y,
        cutoff_95=cutoff_95,
        random_baseline=baseline,
    )


def _running_recall_at(
    ids: Sequence[str], labels: dict[str, int], positions: Sequence[int], included: int
) -> list[float]:
    """Recall at each requested position, by one pass over the ranking."""
    wanted = sorted(set(positions))
    out: dict[int, float] = {}
    found = 0
    index = 0
    if wanted and wanted[0] == 0:
        out[0] = 0.0
        index = 1
    for position, work_id in enumerate(ids, 1):
        found += labels[work_id]
        while index < len(wanted) and wanted[index] == position:
            out[position] = found / included
            index += 1
    while index < len(wanted):  # positions past the end of the ranking
        out[wanted[index]] = found / included
        index += 1
    return [out[p] for p in positions]


def screening_recall_curve(conn: sqlite3.Connection, run_id: str, review: str) -> RecallCurve:
    """The recall curve for a screening run's own decision ordering.

    Uses ``decision_order`` -- verified includes by confidence, then
    referrals, then verified excludes -- the same ordering every TNR@95
    figure in this project is computed on.
    """
    rows = conn.execute(
        "SELECT work_id, decision, confidence, span_verified "
        "FROM screening_decision WHERE run_id = ? AND review = ?",
        (run_id, review),
    ).fetchall()
    labels = load_labels(conn, review)
    ranked = [w for w in decision_order(rows) if w in labels]
    return recall_curve(ranked, labels, strategy="screening confidence", review=review)


# --------------------------------------------------------------------------
# Trust: verification, failure shape, confidence calibration
# --------------------------------------------------------------------------


def verification_by_review(conn: sqlite3.Connection, runs: dict[str, str]) -> list[dict]:
    """Verification rate per review, lowest prevalence first.

    ``runs`` is {review: run_id}, normally from
    ``runs_index.list_reviews_with_screen_runs``. Prevalence travels with
    every bar (rule 5), so the chart cannot be read without it.
    """
    out = []
    for review, run_id in runs.items():
        row = conn.execute(
            "SELECT COUNT(*) AS n, SUM(span_verified) AS verified "
            "FROM screening_decision WHERE run_id = ? AND review = ?",
            (run_id, review),
        ).fetchone()
        if not row or not row["n"]:
            continue
        prev = conn.execute(
            "SELECT AVG(label_included) AS p FROM work WHERE review = ?", (review,)
        ).fetchone()
        out.append(
            {
                "review": review,
                "run_id": run_id,
                "n": row["n"],
                "verified": row["verified"] or 0,
                "verification_rate": (row["verified"] or 0) / row["n"],
                "prevalence": prev["p"] if prev else None,
            }
        )
    return sorted(out, key=lambda r: r["prevalence"] if r["prevalence"] is not None else 0)


def failure_type_matrix(conn: sqlite3.Connection, runs: dict[str, str]) -> dict:
    """Review x verify_note counts, for a heatmap of *how* verification fails.

    Only failures are counted -- a verified decision's note says it
    verified, which is not a failure type. Returns the note columns sorted by
    total so the dominant mode is leftmost, plus row-normalised shares,
    because the reviews differ in size by a factor of sixteen and raw
    counts would show nothing but Radjenovic_2013.
    """
    per_review: dict[str, Counter] = {}
    for review, run_id in runs.items():
        rows = conn.execute(
            "SELECT verify_note, COUNT(*) AS n FROM screening_decision "
            "WHERE run_id = ? AND review = ? AND span_verified = 0 "
            "GROUP BY verify_note",
            (run_id, review),
        ).fetchall()
        counts = Counter({(r["verify_note"] or "unknown"): r["n"] for r in rows})
        if counts:
            per_review[review] = counts

    totals = Counter()
    for counts in per_review.values():
        totals.update(counts)
    notes = [note for note, _ in totals.most_common()]

    rows_out = []
    for review, counts in per_review.items():
        total = sum(counts.values())
        rows_out.append(
            {
                "review": review,
                "total_failures": total,
                "counts": {note: counts.get(note, 0) for note in notes},
                "shares": {note: counts.get(note, 0) / total for note in notes},
            }
        )
    return {
        "notes": notes,
        "rows": sorted(rows_out, key=lambda r: r["review"]),
        "totals": dict(totals),
    }


def confidence_histogram(
    conn: sqlite3.Connection,
    run_id: str,
    review: str | None = None,
    *,
    bins: int = CONFIDENCE_BINS,
) -> dict:
    """Confidence distribution, split by whether the quote verified.

    This is the calibration chart. If the two distributions sit on top of
    each other, the model is as confident when it invents a quote as when
    it copies one correctly -- which is what the recorded figures show
    (0.798 unverified vs 0.813 verified across the whole database), and is
    the single most important thing a reader can learn about trusting a
    confidence score here.
    """
    sql = (
        "SELECT confidence, span_verified FROM screening_decision "
        "WHERE run_id = ? AND confidence IS NOT NULL"
    )
    params: list = [run_id]
    if review:
        sql += " AND review = ?"
        params.append(review)
    rows = conn.execute(sql, params).fetchall()

    edges = [i / bins for i in range(bins + 1)]
    verified = [0] * bins
    unverified = [0] * bins
    sums = {0: 0.0, 1: 0.0}
    counts = {0: 0, 1: 0}
    for row in rows:
        value = max(0.0, min(1.0, float(row["confidence"])))
        index = min(bins - 1, int(value * bins))
        flag = 1 if row["span_verified"] else 0
        (verified if flag else unverified)[index] += 1
        sums[flag] += value
        counts[flag] += 1

    return {
        "run_id": run_id,
        "review": review,
        "bin_edges": edges,
        "bin_labels": [f"{edges[i]:.1f}-{edges[i + 1]:.1f}" for i in range(bins)],
        "verified": verified,
        "unverified": unverified,
        "mean_verified": (sums[1] / counts[1]) if counts[1] else None,
        "mean_unverified": (sums[0] / counts[0]) if counts[0] else None,
        "n_verified": counts[1],
        "n_unverified": counts[0],
    }


def verification_vs_recall(conn: sqlite3.Connection, runs_dir: Path) -> list[dict]:
    """One point per review: verification rate against recall over verified.

    Read from each review's recorded ``metrics.json``, not recomputed, so
    the scatter cannot drift from the table beside it.
    """
    out = []
    for run_dir in sorted(p for p in Path(runs_dir).iterdir() if p.is_dir()):
        if "-extract-" in run_dir.name or "-gap-" in run_dir.name:
            continue
        path = run_dir / "metrics.json"
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if data.get("mode") != "screen":
            continue
        for entry in data.get("per_review") or []:
            if entry.get("verification_rate") is None:
                continue
            out.append(
                {
                    "review": entry.get("review"),
                    "run_id": run_dir.name,
                    "prevalence": entry.get("prevalence"),
                    "verification_rate": entry.get("verification_rate"),
                    "recall_verified": entry.get("recall_verified"),
                    "recall_with_referrals": entry.get("recall_with_referrals"),
                    "agreement_ac1": entry.get("agreement_ac1"),
                }
            )
    # Latest run per review wins, same rule as runs_index.
    latest: dict[str, dict] = {}
    for point in out:
        latest[point["review"]] = point
    return sorted(latest.values(), key=lambda p: p["prevalence"] or 0)


def override_outcomes(conn: sqlite3.Connection, review: str | None = None) -> dict:
    """Recorded human dispositions: how many changed the system's proposal.

    Compares ``human_decision.decision`` with the screening decision it was
    recorded against. Deliberately does *not* join ground truth -- that join
    belongs to ``override_report.py`` and stays there.
    """
    sql = (
        "SELECT h.review, h.decision AS human, s.decision AS system, s.span_verified "
        "FROM human_decision h "
        "JOIN screening_decision s "
        "  ON s.run_id = h.run_id AND s.review = h.review AND s.work_id = h.work_id"
    )
    params: list = []
    if review:
        sql += " WHERE h.review = ?"
        params.append(review)
    rows = conn.execute(sql, params).fetchall()

    changed = sum(1 for r in rows if r["human"] != r["system"])
    from_referral = sum(1 for r in rows if not r["span_verified"])
    return {
        "n": len(rows),
        "changed": changed,
        "confirmed": len(rows) - changed,
        "override_rate": (changed / len(rows)) if rows else None,
        "disposed_referrals": from_referral,
        "disposed_verified": len(rows) - from_referral,
        "by_review": dict(Counter(r["review"] for r in rows)),
    }


# --------------------------------------------------------------------------
# Extraction
# --------------------------------------------------------------------------


def extraction_coverage(conn: sqlite3.Connection, runs: dict[str, str]) -> dict:
    """Review x field verified share -- the domain-generalisation heatmap.

    ``runs`` is {review: extraction run_id}. This is the chart that shows
    ``key_finding`` holding up everywhere while ``study_design`` and
    ``sample_size`` collapse on software-engineering abstracts: the finding
    is already recorded per review in CLAUDE.md, but as six separate
    tables nobody compares by eye.
    """
    rows_out = []
    for review, run_id in runs.items():
        counts = {}
        for field in EXTRACTION_FIELDS:
            row = conn.execute(
                "SELECT COUNT(*) AS n, SUM(span_verified) AS verified "
                "FROM extraction WHERE run_id = ? AND review = ? AND field_name = ?",
                (run_id, review, field),
            ).fetchone()
            n = row["n"] if row else 0
            counts[field] = {
                "n": n,
                "verified": (row["verified"] or 0) if row else 0,
                "share": ((row["verified"] or 0) / n) if n else None,
            }
        if any(c["n"] for c in counts.values()):
            prev = conn.execute(
                "SELECT AVG(label_included) AS p FROM work WHERE review = ?", (review,)
            ).fetchone()
            rows_out.append(
                {
                    "review": review,
                    "run_id": run_id,
                    "prevalence": prev["p"] if prev else None,
                    "fields": counts,
                }
            )
    return {
        "fields": list(EXTRACTION_FIELDS),
        "rows": sorted(rows_out, key=lambda r: r["prevalence"] or 0),
    }


def extraction_status(conn: sqlite3.Connection, run_id: str, review: str) -> list[dict]:
    """Per field: verified / not_stated / unverified, for a stacked bar.

    ``not_stated`` is an honest answer, not a failure, so it gets its own
    band rather than being folded into either side. The verifier records it
    in ``verify_note``.
    """
    out = []
    for field in EXTRACTION_FIELDS:
        rows = conn.execute(
            "SELECT span_verified, verify_note FROM extraction "
            "WHERE run_id = ? AND review = ? AND field_name = ?",
            (run_id, review, field),
        ).fetchall()
        verified = sum(1 for r in rows if r["span_verified"])
        not_stated = sum(
            1 for r in rows if not r["span_verified"] and (r["verify_note"] or "") == "not_stated"
        )
        out.append(
            {
                "field": field,
                "n": len(rows),
                "verified": verified,
                "not_stated": not_stated,
                "unverified": len(rows) - verified - not_stated,
            }
        )
    return out


# --------------------------------------------------------------------------
# Gap discovery
# --------------------------------------------------------------------------


def gap_rate_by_review(conn: sqlite3.Connection, runs: dict[str, str]) -> list[dict]:
    """Share of verified-includes stating a gap, plus the rating split.

    The recorded finding this chart carries is that the rate swings from
    3.8% to 52% and does *not* track prevalence -- it tracks the genre of
    the abstract. Prevalence rides along on every bar so a reader can see
    that for themselves.
    """
    out = []
    for review, run_id in runs.items():
        rows = conn.execute(
            "SELECT value, rating FROM gap_statement WHERE run_id = ? AND review = ?",
            (run_id, review),
        ).fetchall()
        if not rows:
            continue
        stated = [r for r in rows if r["value"] == "gap_stated"]
        valid = sum(1 for r in stated if r["rating"] == "valid")
        invalid = sum(1 for r in stated if r["rating"] == "invalid")
        prev = conn.execute(
            "SELECT AVG(label_included) AS p FROM work WHERE review = ?", (review,)
        ).fetchone()
        out.append(
            {
                "review": review,
                "run_id": run_id,
                "prevalence": prev["p"] if prev else None,
                "n_records": len(rows),
                "gap_stated": len(stated),
                "gap_rate": len(stated) / len(rows),
                "valid": valid,
                "invalid": invalid,
                "unrated": len(stated) - valid - invalid,
                "precision": (valid / (valid + invalid)) if (valid + invalid) else None,
            }
        )
    return sorted(out, key=lambda r: r["prevalence"] or 0)


# The blind-labelled recall estimates from week 11's gap_recall pass. These
# are a one-off measurement (a seeded sample, hand-labelled before any model
# output was consulted), not something a live query can recompute -- the same
# reason the Trust Dashboard shows reproducibility as a recorded finding.
# Point estimates only; read them with the Wilson intervals in CLAUDE.md.
RECORDED_GAP_RECALL = {
    "Radjenovic_2013": {"recall": 1.00, "worst_case": 0.10, "sampled": 10, "misses": 0},
    "van_der_Waal_2022": {"recall": 0.40, "worst_case": 0.25, "sampled": 10, "misses": 3},
    "Menon_2022": {"recall": 0.67, "worst_case": 0.57, "sampled": 10, "misses": 5},
    "Nelson_2002": {"recall": 0.52, "worst_case": 0.21, "sampled": 10, "misses": 1},
}
GAP_RECALL_RUN = "runs/20260924T120813705057Z-gaprecall-d6901cb0a0"


def gap_precision_vs_recall(conn: sqlite3.Connection, runs: dict[str, str]) -> list[dict]:
    """Precision (live, per review) beside the recorded recall estimate.

    The pair is the point: precision is high and recall is not, and showing
    either alone misrepresents what gap discovery does. Reviews with no
    recall measurement get ``None`` rather than a borrowed number.
    """
    out = []
    for entry in gap_rate_by_review(conn, runs):
        recorded = RECORDED_GAP_RECALL.get(entry["review"])
        out.append(
            {
                "review": entry["review"],
                "prevalence": entry["prevalence"],
                "precision": entry["precision"],
                "n_rated": entry["valid"] + entry["invalid"],
                "recall_estimate": recorded["recall"] if recorded else None,
                "recall_worst_case": recorded["worst_case"] if recorded else None,
                "recall_sampled": recorded["sampled"] if recorded else None,
                "recall_source": GAP_RECALL_RUN if recorded else None,
            }
        )
    return out


# --------------------------------------------------------------------------
# Corpus
# --------------------------------------------------------------------------


def prevalence_by_review(conn: sqlite3.Connection) -> list[dict]:
    """Records and inclusion rate per review -- the corpus-design chart.

    The spread from 0.8% to 21.9% is a deliberate design choice, argued in
    the proposal as a stronger test than a larger corpus at uniform
    prevalence. Worth being the first thing anyone sees.
    """
    rows = conn.execute(
        "SELECT review, COUNT(*) AS n, SUM(label_included) AS included, "
        "       SUM(CASE WHEN abstract IS NULL OR abstract = '' THEN 1 ELSE 0 END) AS no_abstract "
        "FROM work WHERE review != '_discover' GROUP BY review"
    ).fetchall()
    out = [
        {
            "review": r["review"],
            "n": r["n"],
            "included": r["included"] or 0,
            "prevalence": (r["included"] or 0) / r["n"],
            "without_abstract": r["no_abstract"] or 0,
        }
        for r in rows
        if r["n"]
    ]
    return sorted(out, key=lambda r: r["prevalence"])


def year_histogram(conn: sqlite3.Connection, review: str | None = None) -> dict:
    """Publication years, included records counted separately.

    Shows the span a review actually covers (Smid_2020 reaches back to
    1879) and whether its included papers cluster in time.
    """
    sql = (
        "SELECT year, COUNT(*) AS n, SUM(label_included) AS included "
        "FROM work WHERE review != '_discover' AND year IS NOT NULL"
    )
    params: list = []
    if review:
        sql += " AND review = ?"
        params.append(review)
    sql += " GROUP BY year ORDER BY year"
    rows = conn.execute(sql, params).fetchall()
    return {
        "review": review,
        "years": [r["year"] for r in rows],
        "counts": [r["n"] for r in rows],
        "included": [r["included"] or 0 for r in rows],
        "span": (rows[0]["year"], rows[-1]["year"]) if rows else None,
    }


def metadata_coverage(conn: sqlite3.Connection) -> list[dict]:
    """Non-null share of each optional metadata column.

    Here so the three charts that *cannot* be built yet -- country map,
    venue breakdown, language split -- fail visibly with a reason instead
    of rendering an empty axis. Every one of these columns is currently
    0/12,598, because ingest never populated them.
    """
    columns = ("venue", "publisher", "country", "language", "doi")
    total = conn.execute("SELECT COUNT(*) AS n FROM work WHERE review != '_discover'").fetchone()["n"]
    out = []
    for column in columns:
        row = conn.execute(
            f"SELECT COUNT({column}) AS filled FROM work WHERE review != '_discover'"  # noqa: S608
        ).fetchone()
        out.append(
            {
                "column": column,
                "filled": row["filled"],
                "total": total,
                "share": (row["filled"] / total) if total else None,
                "chartable": bool(row["filled"]),
            }
        )
    return out


# --------------------------------------------------------------------------
# Performance (RQ2's cost and time arm)
# --------------------------------------------------------------------------


def latency_summary(conn: sqlite3.Connection, run_id: str, review: str | None = None) -> dict:
    """Per-record latency distribution for live (non-cached) calls only.

    Cache hits return in microseconds and would otherwise dominate the
    distribution with a spike that says nothing about the model.
    """
    sql = (
        "SELECT latency_ms FROM screening_decision "
        "WHERE run_id = ? AND from_cache = 0 AND latency_ms > 0"
    )
    params: list = [run_id]
    if review:
        sql += " AND review = ?"
        params.append(review)
    values = sorted(r["latency_ms"] for r in conn.execute(sql, params).fetchall())
    if not values:
        return {"run_id": run_id, "review": review, "n": 0}

    def percentile(p: float) -> float:
        index = min(len(values) - 1, int(p * len(values)))
        return float(values[index])

    return {
        "run_id": run_id,
        "review": review,
        "n": len(values),
        "values": values,
        "mean_ms": sum(values) / len(values),
        "p50_ms": percentile(0.50),
        "p90_ms": percentile(0.90),
        "p99_ms": percentile(0.99),
        "total_hours": sum(values) / 1000 / 3600,
    }


def cache_savings(conn: sqlite3.Connection, run_id: str | None = None) -> dict:
    """Calls served from cache against calls made, with tokens and cost.

    The budget section's first rule is that the cache is checked before
    every call; this is that rule with a number on it.
    """
    sql = (
        "SELECT from_cache, COUNT(*) AS n, SUM(tokens_in) AS tin, "
        "       SUM(tokens_out) AS tout, SUM(cost_usd) AS cost, SUM(latency_ms) AS ms "
        "FROM screening_decision"
    )
    params: list = []
    if run_id:
        sql += " WHERE run_id = ?"
        params.append(run_id)
    sql += " GROUP BY from_cache"
    rows = {bool(r["from_cache"]): r for r in conn.execute(sql, params).fetchall()}

    def field(cached: bool, key: str):
        row = rows.get(cached)
        return (row[key] or 0) if row else 0

    live_n = field(False, "n")
    cached_n = field(True, "n")
    live_ms = field(False, "ms")
    return {
        "run_id": run_id,
        "live_calls": live_n,
        "cached_calls": cached_n,
        "cache_hit_rate": (cached_n / (live_n + cached_n)) if (live_n + cached_n) else None,
        "tokens_in": field(False, "tin") + field(True, "tin"),
        "tokens_out": field(False, "tout") + field(True, "tout"),
        "cost_usd": field(False, "cost") + field(True, "cost"),
        # What the cached calls would have cost in time, at the live mean.
        "hours_saved": (cached_n * (live_ms / live_n) / 1000 / 3600) if live_n else None,
    }


# --------------------------------------------------------------------------
# Semantic map
# --------------------------------------------------------------------------


def semantic_map(
    conn: sqlite3.Connection,
    review: str,
    embeddings_dir: Path,
    *,
    max_points: int = 1500,
    seed: int = 42,
) -> dict:
    """SPECTER2 vectors projected to 2D, coloured by ground-truth label.

    Projection is PCA by hand (centre, then the top two right-singular
    vectors) rather than t-SNE or UMAP: no new pinned dependency, it is
    deterministic, and it is linear, so a reader can be told honestly that
    distance on the plot is distance in the embedding space projected --
    not a neighbour-preserving distortion whose axes mean nothing.

    Returns ``{"available": False, ...}`` when a review's embeddings have
    not been computed, rather than raising -- a missing cache is a normal
    state for a review week 9 never ran dense retrieval on.
    """
    try:
        import numpy as np
    except ImportError:  # pragma: no cover - numpy is pinned
        return {"available": False, "reason": "numpy not installed", "review": review}

    # Imported lazily and by name: dense_retrieve pulls in faiss, which has
    # no wheel on some platforms, and a missing semantic map must not make
    # the other thirteen charts unimportable.
    try:
        from slr.services.dense_retrieve import embedding_cache_path
    except ImportError:
        def embedding_cache_path(review: str, cache_dir: Path) -> Path:
            return Path(cache_dir) / f"{review}__specter2.npz"

    path = embedding_cache_path(review, Path(embeddings_dir))
    if not path.exists():
        return {
            "available": False,
            "reason": f"no cached embeddings for {review}; run a dense/hybrid config first",
            "review": review,
        }

    with np.load(path, allow_pickle=False) as data:
        work_ids = [str(w) for w in data["work_ids"]]
        vectors = np.asarray(data["vectors"], dtype="float32")

    if vectors.shape[0] != len(work_ids):
        return {"available": False, "reason": "embedding/id length mismatch", "review": review}

    labels = load_labels(conn, review)
    keep = [i for i, w in enumerate(work_ids) if w in labels]

    # Downsample excludes only. Every included record is kept -- there are
    # 27 of them in Smid_2020 and they are the whole point of the picture.
    included = [i for i in keep if labels[work_ids[i]]]
    excluded = [i for i in keep if not labels[work_ids[i]]]
    budget = max(0, max_points - len(included))
    if len(excluded) > budget:
        rng = np.random.default_rng(seed)
        excluded = sorted(rng.choice(excluded, size=budget, replace=False).tolist())
    chosen = sorted(included + excluded)
    if len(chosen) < 3:
        return {"available": False, "reason": "too few records to project", "review": review}

    matrix = vectors[chosen]
    centred = matrix - matrix.mean(axis=0, keepdims=True)
    _, singular, components = np.linalg.svd(centred, full_matrices=False)
    coords = centred @ components[:2].T
    variance = float((singular[:2] ** 2).sum() / (singular**2).sum()) if singular.size else None

    return {
        "available": True,
        "review": review,
        "n_plotted": len(chosen),
        "n_total": len(keep),
        "downsampled": len(chosen) < len(keep),
        "variance_explained": variance,
        "points": [
            {
                "work_id": work_ids[i],
                "x": float(coords[row, 0]),
                "y": float(coords[row, 1]),
                "included": bool(labels[work_ids[i]]),
            }
            for row, i in enumerate(chosen)
        ],
    }
