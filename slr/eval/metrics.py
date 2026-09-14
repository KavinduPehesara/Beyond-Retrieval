"""Metrics. This module, and only this module, reads ground truth.

Week 7 covers what the walking skeleton needs: recall, precision, the
verification rate, cost and timing. Week 8 adds TNR@95%, Gwet's AC2 and
prevalence-adjusted kappa — those are the harness, and the harness is week 8.

Everything here is reported *per review*, never pooled. Kusa et al. (2023)
showed the field's default efficiency metric is not comparable across reviews
of differing prevalence, and Khraisha et al. (2024) showed accuracy inflates
on balanced data. A single pooled headline number would be, at best,
uninterpretable.
"""

from __future__ import annotations

import sqlite3
from dataclasses import asdict, dataclass


@dataclass
class ReviewMetrics:
    """One review's results. Class balance travels with every figure."""

    review: str
    n_records: int
    n_included_truth: int
    prevalence: float

    n_screened: int
    n_verified: int
    n_unverified: int
    n_errors: int
    verification_rate: float

    true_positives: int
    false_positives: int
    false_negatives: int
    true_negatives: int
    recall: float | None
    precision: float | None

    tokens_in: int
    tokens_out: int
    cost_usd: float
    cached_fraction: float
    mean_latency_ms: float

    def as_dict(self) -> dict:
        return asdict(self)


def _safe_div(a: float, b: float) -> float | None:
    return a / b if b else None


def review_metrics(conn: sqlite3.Connection, run_id: str, review: str) -> ReviewMetrics:
    rows = conn.execute(
        """
        SELECT d.decision, d.span_verified, d.tokens_in, d.tokens_out,
               d.cost_usd, d.latency_ms, d.from_cache, w.label_included
        FROM screening_decision d
        JOIN work w ON w.work_id = d.work_id
        WHERE d.run_id = ? AND w.review = ?
        """,
        (run_id, review),
    ).fetchall()

    n_records = conn.execute(
        "SELECT COUNT(*) FROM work WHERE review = ?", (review,)
    ).fetchone()[0]
    n_included_truth = conn.execute(
        "SELECT COUNT(*) FROM work WHERE review = ? AND label_included = 1",
        (review,),
    ).fetchone()[0]

    n_screened = len(rows)
    n_verified = sum(1 for r in rows if r["span_verified"])
    n_errors = sum(1 for r in rows if r["decision"] == "error")
    n_unverified = sum(1 for r in rows if r["decision"] == "unverified")

    # Accuracy is computed over verified decisions only. An unverified
    # decision is a referral to a human, not a prediction, and scoring it as
    # one would flatter the system.
    tp = fp = fn = tn = 0
    for r in rows:
        if not r["span_verified"]:
            continue
        predicted = r["decision"] == "include"
        actual = r["label_included"] == 1
        if predicted and actual:
            tp += 1
        elif predicted and not actual:
            fp += 1
        elif not predicted and actual:
            fn += 1
        else:
            tn += 1

    latencies = [r["latency_ms"] for r in rows] or [0]

    return ReviewMetrics(
        review=review,
        n_records=n_records,
        n_included_truth=n_included_truth,
        prevalence=(n_included_truth / n_records) if n_records else 0.0,
        n_screened=n_screened,
        n_verified=n_verified,
        n_unverified=n_unverified,
        n_errors=n_errors,
        verification_rate=_safe_div(n_verified, n_screened) or 0.0,
        true_positives=tp,
        false_positives=fp,
        false_negatives=fn,
        true_negatives=tn,
        recall=_safe_div(tp, tp + fn),
        precision=_safe_div(tp, tp + fp),
        tokens_in=sum(r["tokens_in"] for r in rows),
        tokens_out=sum(r["tokens_out"] for r in rows),
        cost_usd=round(sum(r["cost_usd"] for r in rows), 6),
        cached_fraction=_safe_div(sum(1 for r in rows if r["from_cache"]), n_screened) or 0.0,
        mean_latency_ms=sum(latencies) / len(latencies),
    )


def verification_failures(conn: sqlite3.Connection, run_id: str) -> dict[str, int]:
    """Why verification failed, and how often.

    The shape of this distribution is a finding in its own right: a model that
    truncates quotes is behaving differently from one that invents them.
    """
    rows = conn.execute(
        "SELECT verify_note, COUNT(*) AS n FROM screening_decision "
        "WHERE run_id = ? AND span_verified = 0 GROUP BY verify_note ORDER BY n DESC",
        (run_id,),
    ).fetchall()
    return {r["verify_note"]: r["n"] for r in rows}


def format_table(metrics: list[ReviewMetrics]) -> str:
    """Per-review results, with prevalence beside every figure."""
    head = (
        f"{'Review':24} {'N':>5} {'Prev':>7} {'Verif':>7} "
        f"{'Recall':>7} {'Prec':>7} {'Cost':>9}"
    )
    lines = [head, "-" * len(head)]
    for m in metrics:
        recall = f"{m.recall:.3f}" if m.recall is not None else "n/a"
        prec = f"{m.precision:.3f}" if m.precision is not None else "n/a"
        lines.append(
            f"{m.review:24} {m.n_screened:>5} {m.prevalence:>6.1%} "
            f"{m.verification_rate:>6.1%} {recall:>7} {prec:>7} ${m.cost_usd:>8.4f}"
        )
    return "\n".join(lines)
