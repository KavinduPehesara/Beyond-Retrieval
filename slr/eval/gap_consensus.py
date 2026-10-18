"""Two (or three) AIs over the same gap-discovery records: how often do they
agree, and does combining them help?

Built in week 14 because the supervisor asked that gap detection be
cross-checked by a second AI. Her reason is the sharpest limitation this
project records about gap discovery: every one of the 74 precision ratings and
52 recall labels was made by one person, once, with no second rater and so no
inter-rater agreement at all.

**What a second model does and does not buy.** It gives a second independent
rater, and therefore an agreement coefficient. It does not establish
correctness. Two models can agree on a wrong answer, and models trained on
overlapping corpora correlate in their errors, so agreement between them reads
higher than true independence warrants. This is the supervisor's own point
about verified quotes -- traceability is not correctness -- one level up. The
human-rated reference set remains the only thing that establishes precision,
and ``agreement`` below is reported separately from ``precision`` for exactly
that reason.

**The two ways to combine them move in opposite directions.** ``both`` (an
intersection: flag only where every arm flags) raises precision and lowers
recall. ``either`` (a union) raises recall and lowers precision. This project's
measured weakness is recall -- 0.40 to 1.00 across four reviews, roughly half
the literal gap statements found, and worse on motivating ones -- so ``either``
is the combination likelier to fix the actual problem. Both are computed here
rather than assumed, because week 10's two prompt variants were both expected
to help and both made things worse.

Reported per review, never pooled (rule 5), with each review's gap rate beside
it. Reads finished run directories only: no model is called, nothing is
written to the evaluation corpus, and it costs nothing.

    python -m slr.eval.gap_consensus --runs runs \\
        --arm qwen2.5:7b-instruct=20260923T102642236622Z-gap-3496ae576f \\
        --arm gemini-3.5-flash-lite=20261018T...Z-gap-... \\
        --arm gpt-5-nano=20261018T...Z-gap-...
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from slr.eval.agreement import gwet_ac1, pabak

STATED = "gap_stated"
NOT_STATED = "not_stated"
CATEGORIES = (STATED, NOT_STATED)


def load_arm(run_dir: Path) -> dict[str, dict]:
    """One arm's verdict per record, from its own ``gap_statements.jsonl``.

    Keyed on (review, work_id) the same way the ``work`` table is: a label
    belongs to a review, not to a paper.
    """
    path = run_dir / "gap_statements.jsonl"
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found. --arm expects a gap harness run directory "
            f"(runs/<ts>-gap-<hash>), not a screening or extraction run."
        )
    out: dict[str, dict] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        # An errored record is a missing rating, not a third category -- the
        # same treatment inter-run agreement already gives unverified decisions.
        value = row.get("value") if not row.get("error") else None
        if value not in CATEGORIES:
            value = None if value is None else NOT_STATED
        out[f"{row['review']}\t{row['work_id']}"] = {
            "review": row["review"],
            "work_id": row["work_id"],
            "value": value,
            "span": row.get("evidence_span"),
            "span_verified": bool(row.get("span_verified")),
        }
    return out


def _combine(values: list[str], policy: str) -> str:
    """``both``: flag only where every arm flags. ``either``: flag where any does."""
    if policy == "both":
        return STATED if all(v == STATED for v in values) else NOT_STATED
    return STATED if any(v == STATED for v in values) else NOT_STATED


def compare(arms: dict[str, dict[str, dict]]) -> dict:
    """Per-review agreement and combination rates across two or more arms."""
    names = list(arms)
    if len(names) < 2:
        raise ValueError("need at least two arms to compare")

    reviews = sorted({r["review"] for arm in arms.values() for r in arm.values()})
    per_review = []
    for review in reviews:
        # Only records every arm actually produced a verdict for. A record one
        # arm never saw is not a disagreement.
        keys = sorted(
            set.intersection(
                *({k for k, v in arm.items() if v["review"] == review} for arm in arms.values())
            )
        )
        rows = [[arms[n][k]["value"] for n in names] for k in keys]
        paired = [r for r in rows if all(v is not None for v in r)]

        ac1 = gwet_ac1(rows, categories=CATEGORIES) if rows else None
        entry = {
            "review": review,
            "n_records": len(keys),
            "n_rated_by_every_arm": len(paired),
            "flagged_by_arm": {
                n: sum(1 for r in rows if r[i] == STATED) for i, n in enumerate(names)
            },
            "agreement_ac1": ac1.as_dict() if ac1 else None,
            "n_unanimous": sum(1 for r in paired if len(set(r)) == 1),
            "n_disagreed": sum(1 for r in paired if len(set(r)) > 1),
            "combined": {
                policy: sum(1 for r in paired if _combine(r, policy) == STATED)
                for policy in ("both", "either")
            },
        }
        if len(names) == 2:
            a = [r[0] for r in paired]
            b = [r[1] for r in paired]
            entry["pabak"] = pabak(a, b, categories=CATEGORIES).as_dict() if paired else None
        # The records worth a human's time: where the arms actually differ.
        entry["disagreements"] = [
            {
                "work_id": arms[names[0]][k]["work_id"],
                **{
                    n: {"value": arms[n][k]["value"], "span": arms[n][k]["span"]}
                    for n in names
                },
            }
            for k in keys
            if len({arms[n][k]["value"] for n in names}) > 1
            and all(arms[n][k]["value"] is not None for n in names)
        ]
        per_review.append(entry)

    return {
        "arms": names,
        "per_review": per_review,
        "note": (
            "Agreement measures consistency between models, not correctness. Two "
            "models can agree on a wrong answer, and models with overlapping "
            "training data correlate in their errors, so this reads higher than "
            "true independence would warrant. Precision and recall against the "
            "human-rated reference set are reported separately and are what "
            "establish whether a flagged statement is really a gap."
        ),
    }


def format_table(result: dict) -> str:
    names = result["arms"]
    head = " | ".join(f"{n} flagged" for n in names)
    lines = [
        f"| Review | Records | {head} | Unanimous | Disagreed | AC1 | both | either |",
        "|---" * (6 + len(names)) + "|",
    ]
    for r in result["per_review"]:
        ac1 = r["agreement_ac1"] or {}
        coef = ac1.get("coefficient")
        flagged = " | ".join(str(r["flagged_by_arm"][n]) for n in names)
        lines.append(
            f"| {r['review']} | {r['n_records']} | {flagged} | {r['n_unanimous']} | "
            f"{r['n_disagreed']} | {coef:.3f} |".replace("None", "--")
            if coef is not None
            else f"| {r['review']} | {r['n_records']} | {flagged} | {r['n_unanimous']} | "
            f"{r['n_disagreed']} | -- |"
        )
        lines[-1] += f" {r['combined']['both']} | {r['combined']['either']} |"
    return "\n".join(lines)


def git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compare gap discovery across models.")
    parser.add_argument(
        "--arm",
        action="append",
        required=True,
        metavar="MODEL=RUN_ID",
        help="repeatable; at least two",
    )
    parser.add_argument("--runs", default="runs")
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)

    runs_dir = Path(args.runs)
    arms: dict[str, dict[str, dict]] = {}
    for spec in args.arm:
        if "=" not in spec:
            print(f"error: --arm wants MODEL=RUN_ID, got {spec!r}", file=sys.stderr)
            return 2
        model, run_id = spec.split("=", 1)
        try:
            arms[model] = load_arm(runs_dir / run_id)
        except FileNotFoundError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        print(f"  {model:24s} {len(arms[model]):4d} records  {run_id}")

    if len(arms) < 2:
        print("error: need at least two --arm", file=sys.stderr)
        return 2

    result = compare(arms)
    result["git_sha"] = git_sha()
    result["source_runs"] = {m: s.split("=", 1)[1] for m, s in zip(arms, args.arm)}

    digest = hashlib.sha256(json.dumps(sorted(args.arm)).encode()).hexdigest()[:10]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f") + "Z"
    out = Path(args.out) if args.out else runs_dir / f"{stamp}-gapconsensus-{digest}"
    out.mkdir(parents=True, exist_ok=True)
    (out / "metrics.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    (out / "git_sha.txt").write_text(result["git_sha"] + "\n", encoding="utf-8")
    table = format_table(result)
    (out / "consensus.md").write_text(
        "# Gap discovery across models\n\n" + table + "\n\n" + result["note"] + "\n",
        encoding="utf-8",
    )

    print(f"\nWrote {out}\n")
    print(table)
    print("\n" + result["note"])
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
