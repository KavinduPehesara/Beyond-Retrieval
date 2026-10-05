"""What does each component actually buy?

An ablation answers a question the headline figures cannot: not "how well
does the system do", but "how much worse would it do without this part".
Without it, every mechanism in the system is justified by argument rather
than by measurement, and a reader has no way to tell which parts are
load-bearing and which are decoration.

Four ablations, all computed from data already on disk. No model is called
and nothing here costs money:

* **The span verifier.** The headline one. When a quote fails to verify,
  ``screen.py`` replaces the model's decision with ``unverified`` and the
  original proposal is gone from ``screening_decision``. It is not gone from
  the response cache: ``cached_response.raw_response`` holds the model's
  literal answer, keyed on (model, prompt_version, review, work_id). So the
  un-verified system can be reconstructed exactly -- every record, the
  decision the model actually proposed -- and scored against the same ground
  truth. This measures the verifier's real cost and its real benefit rather
  than asserting either.
* **Retrieval stages**, from the week 9 run directories: BM25, dense,
  hybrid (RRF fusion), rerank.
* **Prompt version**, from the week 10 runs: screen_v1 against v2 and v3.
* **Model tier**, from the week 10 runs: qwen2.5:7b-instruct against qwen3:8b.

The last three read ``metrics.json`` rather than recomputing, so an ablation
figure and the figure it is compared against cannot disagree.

Rule 4 note: this module reads ``work.label_included``, which is why it
lives in ``slr/eval``. Nothing here builds a prompt.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path

from slr.adapters.llm import cache_key
from slr.eval.metrics import (
    _safe_div,
    load_labels,
    ranking_metrics,
)

# A policy is a rule for turning stored decisions into predictions.
POLICY_VERIFIED = "with_verifier"
POLICY_RAW = "no_verifier"
POLICY_REFERRALS_KEPT = "referrals_to_human"


@dataclass
class PolicyResult:
    """One review scored under one policy.

    **Read ``comparable`` before comparing two of these.** ``with_verifier``
    scores only the records whose quote verified, because the rest were
    referred to a human and the system never claimed them. Its recall is
    therefore over a subset, and setting it beside a policy that scores
    every record is not a like-for-like comparison -- it would credit the
    verifier for the records it declined to answer. The two policies that
    *are* comparable both score all records: ``no_verifier`` and
    ``referrals_to_human``.
    """

    review: str
    policy: str
    n_records: int
    n_included_truth: int
    prevalence: float

    n_predictions: int  # records this policy actually decides
    n_to_human: int  # records a reviewer still has to read

    true_positives: int
    false_positives: int
    false_negatives: int
    true_negatives: int

    recall: float | None
    precision: float | None
    work_saved: float | None
    tnr_at_95: float | None

    # True when recall is over every record in the review, so this policy can
    # be set beside another with the same flag. False means a subset.
    comparable: bool = True

    # Only meaningful for the raw policy: how many of the decisions this
    # policy trusts rested on a quote that was not in the source.
    n_unverifiable_trusted: int = 0
    n_unverifiable_wrong: int = 0

    def as_dict(self) -> dict:
        return asdict(self)


def recover_proposed_decisions(
    conn: sqlite3.Connection, run_id: str, review: str
) -> dict[str, dict]:
    """The decision the model actually proposed, per record.

    ``screening_decision.decision`` is the *post-verification* decision, so a
    record whose quote failed reads ``unverified`` and the model's original
    include/exclude is not there. The response cache still holds the literal
    answer, so the un-verified system can be reconstructed rather than
    guessed at.

    Returns {work_id: {proposed, confidence, span_verified, verify_note,
    recovered}}. ``recovered`` is False when the cached response is missing
    or unparseable -- those records are reported, never silently dropped,
    because an ablation computed over a quietly different set of records
    than the headline figure is not a comparison.
    """
    run = conn.execute(
        "SELECT model, prompt_version FROM run WHERE run_id = ?", (run_id,)
    ).fetchone()
    if run is None:
        raise ValueError(f"no run row for {run_id}")

    rows = conn.execute(
        "SELECT work_id, decision, confidence, span_verified, verify_note "
        "FROM screening_decision WHERE run_id = ? AND review = ?",
        (run_id, review),
    ).fetchall()

    out: dict[str, dict] = {}
    for row in rows:
        key = cache_key(run["model"], run["prompt_version"], review, row["work_id"])
        cached = conn.execute(
            "SELECT raw_response FROM cached_response WHERE cache_key = ?", (key,)
        ).fetchone()

        proposed = None
        confidence = row["confidence"]
        recovered = False
        if cached:
            try:
                payload = json.loads(cached["raw_response"])
                value = payload.get("decision")
                if value in ("include", "exclude"):
                    proposed = value
                    recovered = True
                    if payload.get("confidence") is not None:
                        confidence = float(payload["confidence"])
            except (json.JSONDecodeError, TypeError, ValueError):
                pass

        # A verified decision is already the proposal -- verification does
        # not change an accepted answer, only rejects one.
        if proposed is None and row["span_verified"] and row["decision"] in ("include", "exclude"):
            proposed = row["decision"]
            recovered = True

        out[row["work_id"]] = {
            "proposed": proposed,
            "confidence": confidence,
            "span_verified": bool(row["span_verified"]),
            "verify_note": row["verify_note"],
            "decision": row["decision"],
            "recovered": recovered,
        }
    return out


def _score(
    review: str,
    policy: str,
    labels: dict[str, int],
    predictions: dict[str, bool],
    ranked_ids: list[str],
    *,
    n_to_human: int,
    comparable: bool = True,
    unverifiable_trusted: int = 0,
    unverifiable_wrong: int = 0,
) -> PolicyResult:
    """Confusion matrix and ranking for one policy's predictions."""
    tp = fp = fn = tn = 0
    for work_id, predicted_include in predictions.items():
        actual = labels[work_id] == 1
        if predicted_include and actual:
            tp += 1
        elif predicted_include:
            fp += 1
        elif actual:
            fn += 1
        else:
            tn += 1

    n_records = len(labels)
    included = sum(labels.values())
    ranking = ranking_metrics(ranked_ids, labels, recall_target=0.95)

    return PolicyResult(
        review=review,
        policy=policy,
        n_records=n_records,
        n_included_truth=included,
        prevalence=_safe_div(included, n_records) or 0.0,
        n_predictions=len(predictions),
        n_to_human=n_to_human,
        comparable=comparable,
        true_positives=tp,
        false_positives=fp,
        false_negatives=fn,
        true_negatives=tn,
        recall=_safe_div(tp, tp + fn),
        precision=_safe_div(tp, tp + fp),
        work_saved=_safe_div(len(labels) - n_to_human, len(labels)),
        tnr_at_95=ranking.tnr_at_recall,
        n_unverifiable_trusted=unverifiable_trusted,
        n_unverifiable_wrong=unverifiable_wrong,
    )


def verifier_ablation(
    conn: sqlite3.Connection, run_id: str, review: str
) -> dict:
    """Score the same run with the verifier on, off, and as a referral gate.

    Three policies over identical model output:

    ``with_verifier`` -- what the system ships. Only decisions whose quote
    verified are predictions; the rest are referred to a human and are not
    scored as predictions at all.

    ``no_verifier`` -- the counterfactual. Every record gets the decision the
    model proposed, whether or not its quote was real. This is what the
    system would be without the mechanism RQ1 is built on.

    ``referrals_to_human`` -- the workflow view. Verified excludes are the
    only records a reviewer never sees; everything else is read. Recall here
    is what a researcher following the tool actually keeps.

    The comparison that matters is not which policy has the better recall. It
    is what ``no_verifier`` is buying that recall *with*: decisions resting
    on quotes that are not in the source.
    """
    labels = load_labels(conn, review)
    proposals = recover_proposed_decisions(conn, run_id, review)
    known = {w: p for w, p in proposals.items() if w in labels}

    unrecovered = [w for w, p in known.items() if not p["recovered"]]

    # --- with verifier: verified decisions only -------------------------
    verified_preds = {
        w: p["decision"] == "include"
        for w, p in known.items()
        if p["span_verified"] and p["decision"] in ("include", "exclude")
    }
    verified_to_human = len(known) - sum(
        1 for w, p in known.items() if p["span_verified"] and p["decision"] == "exclude"
    )

    def order_with_verifier(item):
        w, p = item
        confidence = p["confidence"] if p["confidence"] is not None else 0.0
        if not p["span_verified"]:
            return (1, 0.0, w)
        if p["decision"] == "include":
            return (0, -confidence, w)
        return (2, confidence, w)

    ranked_verified = [w for w, _ in sorted(known.items(), key=order_with_verifier)]

    # --- no verifier: trust every proposal -------------------------------
    raw_preds = {
        w: p["proposed"] == "include" for w, p in known.items() if p["proposed"] is not None
    }
    # Of the decisions this policy trusts, how many had no real quote behind
    # them -- and how many of those were also factually wrong?
    trusted_unverifiable = [
        w for w, p in known.items() if p["proposed"] is not None and not p["span_verified"]
    ]
    wrong_unverifiable = sum(
        1
        for w in trusted_unverifiable
        if (known[w]["proposed"] == "include") != (labels[w] == 1)
    )
    raw_to_human = sum(1 for w, p in known.items() if p["proposed"] != "exclude")

    def order_no_verifier(item):
        w, p = item
        confidence = p["confidence"] if p["confidence"] is not None else 0.0
        if p["proposed"] == "include":
            return (0, -confidence, w)
        if p["proposed"] is None:  # unparseable even in the raw response
            return (1, 0.0, w)
        return (2, confidence, w)

    ranked_raw = [w for w, _ in sorted(known.items(), key=order_no_verifier)]

    # --- referrals kept: a verified exclude is the only thing not read ---
    referral_preds = {
        w: not (p["span_verified"] and p["decision"] == "exclude") for w, p in known.items()
    }

    results = [
        _score(
            review, POLICY_VERIFIED, labels, verified_preds, ranked_verified,
            n_to_human=verified_to_human,
            # Scored over verified records only -- a subset. Not comparable
            # with the two policies below, which score every record.
            comparable=False,
        ),
        _score(
            review, POLICY_RAW, labels, raw_preds, ranked_raw,
            n_to_human=raw_to_human,
            unverifiable_trusted=len(trusted_unverifiable),
            unverifiable_wrong=wrong_unverifiable,
        ),
        _score(
            review, POLICY_REFERRALS_KEPT, labels, referral_preds, ranked_verified,
            n_to_human=verified_to_human,
        ),
    ]

    return {
        "review": review,
        "run_id": run_id,
        "n_records": len(known),
        "n_unrecovered": len(unrecovered),
        "unrecovered_sample": unrecovered[:5],
        "policies": {r.policy: r.as_dict() for r in results},
    }


# --------------------------------------------------------------------------
# Component ablations read from recorded run directories
# --------------------------------------------------------------------------


def _read_metrics(runs_dir: Path, run_id: str) -> dict | None:
    path = Path(runs_dir) / run_id / "metrics.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def stage_ablation(runs_dir: Path, stages: dict[str, str], metric: str = "tnr_at_recall") -> dict:
    """Compare named run directories on one ranking metric, per review.

    ``stages`` maps a label ("bm25", "dense", ...) to a run id. Deltas are
    against the first stage listed, which is the baseline being ablated
    against. Reads each run's recorded ``metrics.json`` rather than
    recomputing, so these figures cannot drift from the ones already
    reported.
    """
    labels = list(stages)
    per_review: dict[str, dict] = {}
    missing = []

    for label, run_id in stages.items():
        data = _read_metrics(runs_dir, run_id)
        if data is None:
            missing.append(label)
            continue
        for entry in data.get("per_review") or []:
            review = entry.get("review")
            ranking = entry.get("ranking") or {}
            value = ranking.get(metric)
            row = per_review.setdefault(
                review, {"review": review, "prevalence": entry.get("prevalence"), "stages": {}}
            )
            row["stages"][label] = value

    baseline = labels[0]
    for row in per_review.values():
        base = row["stages"].get(baseline)
        row["deltas"] = {
            label: (None if (base is None or v is None) else round(v - base, 4))
            for label, v in row["stages"].items()
        }

    return {
        "metric": metric,
        "baseline": baseline,
        "stages": labels,
        "missing_runs": missing,
        "rows": sorted(per_review.values(), key=lambda r: r["prevalence"] or 0),
    }


def verification_ablation_from_runs(runs_dir: Path, variants: dict[str, str]) -> dict:
    """Compare run directories on verification rate and recall.

    Used for the prompt-variant and model-tier ablations, where the thing
    that moves is not a ranking but how often the model produces a quote
    that can be checked at all.
    """
    rows: dict[str, dict] = {}
    missing = []
    for label, run_id in variants.items():
        data = _read_metrics(runs_dir, run_id)
        if data is None:
            missing.append(label)
            continue
        for entry in data.get("per_review") or []:
            review = entry.get("review")
            row = rows.setdefault(review, {"review": review, "variants": {}})
            row["variants"][label] = {
                "verification_rate": entry.get("verification_rate"),
                "recall_verified": entry.get("recall_verified"),
                "n_verified": entry.get("n_verified"),
                "n_errors": entry.get("n_errors"),
                "run_id": run_id,
            }
    return {"variants": list(variants), "missing_runs": missing, "rows": list(rows.values())}


# --------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------


def format_verifier_table(results: list[dict]) -> str:
    """Markdown, per review with prevalence beside it, never pooled (rule 5).

    Two tables on purpose. The first is the only like-for-like comparison --
    both policies score every record in the review. The second reports the
    shipped system's figures, which are over verified decisions only and are
    deliberately kept out of the comparison table so they cannot be read as
    if they belonged in it.
    """
    results = sorted(results, key=lambda r: r["policies"][POLICY_VERIFIED]["prevalence"])

    lines = [
        "## What the verifier costs and buys",
        "",
        "Both policies below score **every record**, so they can be compared.",
        "",
        "| Review | Prev | Recall, trusting the model | Recall, verifier as a gate | Δ recall | Read w/ trust | Read w/ gate |",
        "|---|---|---|---|---|---|---|",
    ]
    for result in results:
        raw = result["policies"][POLICY_RAW]
        gate = result["policies"][POLICY_REFERRALS_KEPT]
        delta = (
            None
            if (raw["recall"] is None or gate["recall"] is None)
            else gate["recall"] - raw["recall"]
        )
        lines.append(
            f"| {raw['review']} | {raw['prevalence'] * 100:.1f}% | "
            f"{_fmt(raw['recall'])} | {_fmt(gate['recall'])} | "
            f"{'n/a' if delta is None else f'{delta:+.3f}'} | "
            f"{raw['n_to_human']:,} | {gate['n_to_human']:,} |"
        )

    lines += [
        "",
        "## What trusting the model would mean",
        "",
        "| Review | Decisions trusted with no real quote | …of which factually wrong |",
        "|---|---|---|",
    ]
    for result in results:
        raw = result["policies"][POLICY_RAW]
        share = (
            f"{raw['n_unverifiable_wrong'] / raw['n_unverifiable_trusted']:.1%}"
            if raw["n_unverifiable_trusted"]
            else "n/a"
        )
        lines.append(
            f"| {raw['review']} | {raw['n_unverifiable_trusted']:,} | "
            f"{raw['n_unverifiable_wrong']:,} ({share}) |"
        )

    lines += [
        "",
        "## Shipped system, for reference",
        "",
        "Scored over verified decisions only, so **not** comparable with the",
        "table above -- the referred records are excluded rather than counted",
        "as misses.",
        "",
        "| Review | Recall (verified only) | Precision | Scored on |",
        "|---|---|---|---|",
    ]
    for result in results:
        p = result["policies"][POLICY_VERIFIED]
        lines.append(
            f"| {p['review']} | {_fmt(p['recall'])} | {_fmt(p['precision'])} | "
            f"{p['n_predictions']:,} of {p['n_records']:,} |"
        )

    return "\n".join(lines)


def _fmt(value: float | None, spec: str = ".3f") -> str:
    return "n/a" if value is None else format(value, spec)
