"""Metrics. This module, and only this module, reads ground truth.

Two families of measure, both reported per review and never pooled:

* **Operating point** — the decisions as the system made them: verification
  rate; recall and precision over verified decisions; recall once referrals
  to a human are counted; the share of records excluded without a human
  (work saved); and chance-corrected agreement with the human labels
  (Gwet's AC1 and PABAK).
* **Ranking** — an ordering of a review's records, which is what a baseline
  produces and what the model's decisions induce: TNR at 95% recall, the
  normalised work saved over sampling that Kusa et al. (2023) showed is
  comparable across reviews of different prevalence, and WSS at 95% recall.

Kusa et al. (2023) showed the field's default efficiency metric is not
comparable across reviews of differing prevalence, and Khraisha et al. (2024)
showed accuracy inflates on balanced data. A pooled headline number would be,
at best, uninterpretable — so every figure travels with its review's
prevalence.

Everything here is a pure function of stored decisions and labels: no
timings, no cache state, no live spend. That is what lets a stored
configuration reproduce an identical metrics file (proposal, Table 5).
"""

from __future__ import annotations

import hashlib
import math
import sqlite3
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from fractions import Fraction

from slr.eval.agreement import gwet_ac1, pabak

CATEGORIES = ("include", "exclude")


def _safe_div(a: float, b: float) -> float | None:
    return a / b if b else None


# --------------------------------------------------------------------------
# Ground truth
# --------------------------------------------------------------------------


def load_labels(conn: sqlite3.Connection, review: str) -> dict[str, int]:
    """work_id -> label_included for one review. The only ground-truth read."""
    rows = conn.execute(
        "SELECT work_id, label_included FROM work WHERE review = ? ORDER BY work_id",
        (review,),
    ).fetchall()
    return {r["work_id"]: int(r["label_included"]) for r in rows}


def corpus_fingerprint(labels: dict[str, int]) -> str:
    """Hash of the review as stored. Two runs over different corpora differ here."""
    digest = hashlib.sha256()
    for work_id in sorted(labels):
        digest.update(f"{work_id}\x1f{labels[work_id]}\n".encode("utf-8"))
    return digest.hexdigest()


# --------------------------------------------------------------------------
# Ranking metrics
# --------------------------------------------------------------------------


@dataclass
class RankingMetrics:
    """How much reading a ranking saves at a fixed recall."""

    recall_target: float
    n_ranked: int
    n_included: int
    complete: bool  # the ranking covers every record in the review
    cutoff: int | None  # records read, top down, to reach the target
    recall_at_cutoff: float | None
    tnr_at_recall: float | None  # normalised WSS (Kusa et al., 2023)
    wss_at_recall: float | None

    def as_dict(self) -> dict:
        return asdict(self)


def ranking_metrics(
    ranked_ids: Sequence[str],
    labels: dict[str, int],
    *,
    recall_target: float = 0.95,
) -> RankingMetrics:
    """TNR and WSS at a recall target, for records read in ranked order.

    A reviewer reads down the ranking until ``ceil(target * included)``
    included records have been found. Everything below that cutoff is not
    read: included records there are false negatives, excluded ones are true
    negatives.

        TNR@r = TN / (TN + FP)
        WSS@r = (TN + FN) / N - (1 - r)

    When the ranking covers only part of a review (a capped run), both are
    computed over the records ranked and ``complete`` is False.
    """
    if not 0 < recall_target <= 1:
        raise ValueError("recall_target must be in (0, 1]")
    ids = list(ranked_ids)
    if len(set(ids)) != len(ids):
        raise ValueError("ranking contains duplicate records")
    unknown = [i for i in ids if i not in labels]
    if unknown:
        raise ValueError(f"ranking contains records not in the review: {unknown[:3]}")

    n = len(ids)
    included = sum(labels[i] for i in ids)
    excluded = n - included
    complete = n == len(labels)

    if included == 0:
        return RankingMetrics(recall_target, n, 0, complete, None, None, None, None)

    # Fraction avoids 0.95 * 100 = 95.00000000000001 rounding up to 96.
    target = math.ceil(Fraction(str(recall_target)) * included)
    found = 0
    cutoff = n
    for position, work_id in enumerate(ids, 1):
        found += labels[work_id]
        if found >= target:
            cutoff = position
            break

    true_pos = found
    false_neg = included - true_pos
    false_pos = cutoff - true_pos
    true_neg = excluded - false_pos

    return RankingMetrics(
        recall_target=recall_target,
        n_ranked=n,
        n_included=included,
        complete=complete,
        cutoff=cutoff,
        recall_at_cutoff=true_pos / included,
        tnr_at_recall=_safe_div(true_neg, excluded),
        wss_at_recall=(true_neg + false_neg) / n - (1 - recall_target),
    )


def decision_order(rows: Sequence[sqlite3.Row | dict]) -> list[str]:
    """The order a reviewer would work through screened records.

    Verified includes first, most confident first; then everything referred
    to a human (unverified or error); then verified excludes, least confident
    first. Ties break on work_id so the order is reproducible.
    """

    def key(row):
        confidence = row["confidence"] if row["confidence"] is not None else 0.0
        if not row["span_verified"]:
            return (1, 0.0, row["work_id"])
        if row["decision"] == "include":
            return (0, -confidence, row["work_id"])
        return (2, confidence, row["work_id"])

    return [row["work_id"] for row in sorted(rows, key=key)]


# --------------------------------------------------------------------------
# Operating-point metrics for a screening run
# --------------------------------------------------------------------------


@dataclass
class ReviewMetrics:
    """One review's results. Class balance travels with every figure."""

    review: str
    corpus_sha256: str
    n_records: int
    n_included_truth: int
    prevalence: float

    n_screened: int
    n_included_screened: int
    screened_prevalence: float | None

    n_verified: int
    n_unverified: int
    n_errors: int
    verification_rate: float | None

    true_positives: int
    false_positives: int
    false_negatives: int
    true_negatives: int
    recall_verified: float | None
    precision_verified: float | None

    n_to_human: int
    recall_with_referrals: float | None
    work_saved: float | None

    agreement_ac1: float | None
    agreement_pabak: float | None

    ranking: dict

    tokens_in: int
    tokens_out: int
    cost_usd_at_config_prices: float

    def as_dict(self) -> dict:
        return asdict(self)


def review_metrics(
    conn: sqlite3.Connection,
    run_id: str,
    review: str,
    *,
    recall_target: float = 0.95,
    usd_per_1m_input: float = 0.0,
    usd_per_1m_output: float = 0.0,
) -> ReviewMetrics:
    """Metrics for one review of one screening run."""
    labels = load_labels(conn, review)
    rows = conn.execute(
        """
        SELECT work_id, decision, confidence, span_verified, tokens_in, tokens_out
        FROM screening_decision
        WHERE run_id = ? AND review = ?
        ORDER BY work_id
        """,
        (run_id, review),
    ).fetchall()

    n_records = len(labels)
    n_included_truth = sum(labels.values())
    n_screened = len(rows)
    n_included_screened = sum(labels[r["work_id"]] for r in rows)

    verified = [r for r in rows if r["span_verified"]]
    n_errors = sum(1 for r in rows if r["decision"] == "error")
    n_unverified = sum(1 for r in rows if r["decision"] == "unverified")

    # Accuracy over verified decisions only. An unverified decision is a
    # referral to a human, not a prediction, and scoring it as one would
    # flatter the system.
    tp = fp = fn = tn = 0
    for r in verified:
        predicted = r["decision"] == "include"
        actual = labels[r["work_id"]] == 1
        if predicted and actual:
            tp += 1
        elif predicted:
            fp += 1
        elif actual:
            fn += 1
        else:
            tn += 1

    # The workflow view: a verified exclude is the only record a human never
    # sees. Recall here is what a researcher following the tool keeps.
    to_human = [r for r in rows if not (r["span_verified"] and r["decision"] == "exclude")]
    kept_truth = sum(labels[r["work_id"]] for r in to_human)

    model = [r["decision"] for r in verified]
    human = ["include" if labels[r["work_id"]] else "exclude" for r in verified]
    ac1 = gwet_ac1(list(zip(model, human)), categories=CATEGORIES) if verified else None
    kappa = pabak(model, human, categories=CATEGORIES) if verified else None

    tokens_in = sum(r["tokens_in"] for r in rows)
    tokens_out = sum(r["tokens_out"] for r in rows)
    cost = tokens_in / 1_000_000 * usd_per_1m_input + tokens_out / 1_000_000 * usd_per_1m_output

    ranking = ranking_metrics(decision_order(rows), labels, recall_target=recall_target)

    return ReviewMetrics(
        review=review,
        corpus_sha256=corpus_fingerprint(labels),
        n_records=n_records,
        n_included_truth=n_included_truth,
        prevalence=_safe_div(n_included_truth, n_records) or 0.0,
        n_screened=n_screened,
        n_included_screened=n_included_screened,
        screened_prevalence=_safe_div(n_included_screened, n_screened),
        n_verified=len(verified),
        n_unverified=n_unverified,
        n_errors=n_errors,
        verification_rate=_safe_div(len(verified), n_screened),
        true_positives=tp,
        false_positives=fp,
        false_negatives=fn,
        true_negatives=tn,
        recall_verified=_safe_div(tp, tp + fn),
        precision_verified=_safe_div(tp, tp + fp),
        n_to_human=len(to_human),
        recall_with_referrals=_safe_div(kept_truth, n_included_screened),
        work_saved=_safe_div(n_screened - len(to_human), n_screened),
        agreement_ac1=ac1.coefficient if ac1 else None,
        agreement_pabak=kappa.coefficient if kappa else None,
        ranking=ranking.as_dict(),
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        cost_usd_at_config_prices=round(cost, 6),
    )


def baseline_metrics(
    conn: sqlite3.Connection,
    review: str,
    ranked_ids: Sequence[str],
    *,
    recall_target: float = 0.95,
) -> dict:
    """Metrics for a ranking-only baseline over one review."""
    labels = load_labels(conn, review)
    n = len(labels)
    included = sum(labels.values())
    return {
        "review": review,
        "corpus_sha256": corpus_fingerprint(labels),
        "n_records": n,
        "n_included_truth": included,
        "prevalence": _safe_div(included, n) or 0.0,
        "ranking": ranking_metrics(ranked_ids, labels, recall_target=recall_target).as_dict(),
    }


# --------------------------------------------------------------------------
# Reproducibility across runs — reads decisions only, never labels
# --------------------------------------------------------------------------


def inter_run_agreement(conn: sqlite3.Connection, run_ids: Sequence[str], review: str):
    """Gwet's AC1 across repeated runs of the same configuration.

    Each run is a rater. Unverified and error decisions are missing ratings:
    they are not predictions, so they cannot agree or disagree.
    """
    units: dict[str, list[str | None]] = {}
    for j, run_id in enumerate(run_ids):
        rows = conn.execute(
            "SELECT work_id, decision, span_verified FROM screening_decision "
            "WHERE run_id = ? AND review = ?",
            (run_id, review),
        ).fetchall()
        for r in rows:
            ratings = units.setdefault(r["work_id"], [None] * len(run_ids))
            ratings[j] = r["decision"] if r["span_verified"] else None
    return gwet_ac1([units[w] for w in sorted(units)], categories=CATEGORIES)


def verification_failures(conn: sqlite3.Connection, run_id: str) -> dict[str, int]:
    """Why verification failed, and how often.

    The shape of this distribution is a finding in its own right: a model that
    truncates quotes is behaving differently from one that invents them.
    """
    rows = conn.execute(
        "SELECT verify_note, COUNT(*) AS n FROM screening_decision "
        "WHERE run_id = ? AND span_verified = 0 "
        "GROUP BY verify_note ORDER BY n DESC, verify_note",
        (run_id,),
    ).fetchall()
    return {r["verify_note"]: r["n"] for r in rows}


# --------------------------------------------------------------------------
# Console tables
# --------------------------------------------------------------------------


def _fmt(value: float | None, spec: str = ".3f") -> str:
    return "n/a" if value is None else format(value, spec)


def format_screening_table(per_review: Sequence[dict]) -> str:
    """Per-review results, with prevalence beside every figure."""
    head = (
        f"{'Review':20} {'N':>5} {'Prev':>6} {'Verif':>6} {'Rec(v)':>7} "
        f"{'Rec(+h)':>7} {'Saved':>6} {'AC1':>6} {'TNR@r':>6} {'Cost':>9}"
    )
    lines = [head, "-" * len(head)]
    for m in per_review:
        lines.append(
            f"{m['review']:20} {m['n_screened']:>5} {_fmt(m['prevalence'], '.1%'):>6} "
            f"{_fmt(m['verification_rate'], '.1%'):>6} {_fmt(m['recall_verified']):>7} "
            f"{_fmt(m['recall_with_referrals']):>7} {_fmt(m['work_saved'], '.1%'):>6} "
            f"{_fmt(m['agreement_ac1']):>6} {_fmt(m['ranking']['tnr_at_recall']):>6} "
            f"${m['cost_usd_at_config_prices']:>8.4f}"
        )
    return "\n".join(lines)


def format_ranking_table(per_review: Sequence[dict]) -> str:
    head = f"{'Review':20} {'N':>5} {'Prev':>6} {'Cutoff':>7} {'TNR@r':>6} {'WSS@r':>6}"
    lines = [head, "-" * len(head)]
    for m in per_review:
        r = m["ranking"]
        lines.append(
            f"{m['review']:20} {m['n_records']:>5} {_fmt(m['prevalence'], '.1%'):>6} "
            f"{r['cutoff'] if r['cutoff'] is not None else 'n/a':>7} "
            f"{_fmt(r['tnr_at_recall']):>6} {_fmt(r['wss_at_recall']):>6}"
        )
    return "\n".join(lines)
