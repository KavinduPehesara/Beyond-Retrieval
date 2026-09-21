"""Human overrides: the mechanism behind the *overridable* property in RQ1.

The system proposes (``screening_decision``), the reviewer disposes
(``human_decision``). Kept as a separate table, keyed the same way, so an
override never overwrites the model's row -- override rate and agreement are
both computed by comparing the two tables side by side, not by destroying
one of them.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

DECISIONS = ("include", "exclude")


@dataclass(frozen=True)
class ModelDecision:
    """What the system proposed for one record, for the reviewer to see before disposing."""

    decision: str | None  # include | exclude | unverified | error
    confidence: float | None
    span_verified: bool


def model_decision(
    conn: sqlite3.Connection, run_id: str, review: str, work_id: str
) -> ModelDecision | None:
    row = conn.execute(
        "SELECT decision, confidence, span_verified FROM screening_decision "
        "WHERE run_id = ? AND review = ? AND work_id = ?",
        (run_id, review, work_id),
    ).fetchone()
    if row is None:
        return None
    return ModelDecision(row["decision"], row["confidence"], bool(row["span_verified"]))


def record_override(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    review: str,
    work_id: str,
    decision: str,
    rationale: str | None = None,
) -> None:
    """Record a reviewer's disposition for one screened record.

    Raises if the record was never screened in this run: an override without
    a system proposal to override is a data-entry error, not a decision.
    """
    if decision not in DECISIONS:
        raise ValueError(f"decision must be one of {DECISIONS}, got {decision!r}")
    if model_decision(conn, run_id, review, work_id) is None:
        raise ValueError(
            f"{review}/{work_id} was not screened in run {run_id!r} -- nothing to override"
        )
    conn.execute(
        "INSERT OR REPLACE INTO human_decision "
        "(run_id, review, work_id, decision, rationale, created_at) VALUES (?,?,?,?,?,?)",
        (
            run_id,
            review,
            work_id,
            decision,
            rationale,
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    conn.commit()


@dataclass
class OverrideSummary:
    """Every human disposition recorded against one run and review."""

    n_overrides: int
    n_changed: int  # human decision differs from what the system proposed
    n_confirmed: int  # human agreed with the system
    override_rate: float | None  # n_changed / n_overrides
    by_model_decision: dict[str, int]  # system's original decision -> count disposed


def override_summary(conn: sqlite3.Connection, run_id: str, review: str) -> OverrideSummary:
    rows = conn.execute(
        "SELECT h.decision AS human_decision, s.decision AS model_decision "
        "FROM human_decision h "
        "JOIN screening_decision s "
        "  ON h.run_id = s.run_id AND h.review = s.review AND h.work_id = s.work_id "
        "WHERE h.run_id = ? AND h.review = ?",
        (run_id, review),
    ).fetchall()
    n = len(rows)
    changed = sum(1 for r in rows if r["human_decision"] != r["model_decision"])
    by_model: dict[str, int] = {}
    for r in rows:
        by_model[r["model_decision"]] = by_model.get(r["model_decision"], 0) + 1
    return OverrideSummary(
        n_overrides=n,
        n_changed=changed,
        n_confirmed=n - changed,
        override_rate=changed / n if n else None,
        by_model_decision=by_model,
    )
