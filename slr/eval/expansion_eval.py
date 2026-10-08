"""Does query expansion improve retrieval, measured where it can be measured?

The experiment the expansion service is answerable to.

**Why this ranks a known corpus instead of searching the web.** The obvious
test -- search OpenAlex with and without the extra terms, count how many of
a review's included papers come back -- cannot be run honestly at any budget
this project can afford. Measured 8 October 2026: searching OpenAlex with
each review's own publication title and taking the top 100 results with
abstracts returned 0 of 80 known includes for Nelson_2002, 0 of 48 for
Radjenovic_2013 and 1 of 27 for Smid_2020. Relevance ranking over 250
million works does not reproduce a systematic review's candidate set, so the
difference expansion makes is swamped by a floor of zero. That is a real
limitation of the live product path, not of expansion.

What can be measured is the thing expansion is for: given a query, does
adding the model's terms rank a review's included papers higher? Each review
already has a corpus with published answers, and BM25 over it is baseline
two. So each query is run through ``lexical_rank`` and scored with
``ranking_metrics`` -- the same TNR@95 the week 9 arms are reported with, so
the numbers sit in the same table as everything else.

Four arms per review:

    criteria          the published eligibility criteria (today's baseline)
    criteria+terms    the same, with the model's terms appended
    title             the review's own title, standing in for a user's
                      typed question -- short, which is what people type
    title+terms       the same, expanded

Ground truth is read through ``metrics.load_labels``, so rule 4 holds: one
module reads ``label_included``.

Usage:
    python -m slr.eval.expansion_eval
    python -m slr.eval.expansion_eval --reviews Nelson_2002 Smid_2020
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path

from slr.adapters.llm import Meter, build_provider
from slr.config import SUBSET
from slr.db import connect
from slr.eval import metrics
from slr.eval.harness import git_state
from slr.services import criteria as criteria_service
from slr.services import expand
from slr.services.retrieve import lexical_rank

RESULTS_SCHEMA = 2


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def review_title(review: str) -> str | None:
    """The review's own publication title, as a stand-in for the question.

    A researcher types a topic, not a thousand words of protocol. SYNERGY
    ships the title of the review each dataset came from, which is the
    closest thing in the corpus to the question its authors set out to
    answer. Returns None when the release is not installed, so the run falls
    back to criteria rather than failing.
    """
    try:
        from synergy_dataset.base import Dataset

        title = Dataset(review).metadata["publication"].get("title")
    except Exception:
        return None
    return " ".join(title.split()) if title else None


def rank_with(conn, review: str, query: str, labels: dict[str, int], *, recall_target: float) -> dict:
    """BM25 over one review for one query, scored like any other ranking."""
    ranked = [row["work_id"] for row in lexical_rank(conn, query, review)]
    result = metrics.ranking_metrics(ranked, labels, recall_target=recall_target)
    return {
        "query": query,
        "n_terms": len(query.split()),
        "cutoff": result.cutoff,
        "tnr_at_recall": result.tnr_at_recall,
        "wss_at_recall": result.wss_at_recall,
    }


def run_review(
    conn,
    review: str,
    *,
    provider,
    template: str,
    meter: Meter,
    seed: int | None,
    use_cache: bool,
    recall_target: float,
) -> dict:
    """One review, four arms. Returns a row for the results file."""
    labels = metrics.load_labels(conn, review)
    criteria = criteria_service.for_review(conn, review)
    title = review_title(review) or criteria.text

    def expansion_for(question: str):
        return expand.expand_query(
            question,
            provider=provider,
            template=template,
            meter=meter,
            conn=conn,
            seed=seed,
            use_cache=use_cache,
        )

    criteria_expansion = expansion_for(criteria.text)
    title_expansion = expansion_for(title)

    arms = {
        "criteria": rank_with(conn, review, criteria.text, labels, recall_target=recall_target),
        "criteria_expanded": rank_with(
            conn, review, criteria_expansion.query, labels, recall_target=recall_target
        ),
        "title": rank_with(conn, review, title, labels, recall_target=recall_target),
        "title_expanded": rank_with(
            conn, review, title_expansion.query, labels, recall_target=recall_target
        ),
    }
    return {
        "review": review,
        "n_records": len(labels),
        "n_included_truth": sum(labels.values()),
        "criteria_status": criteria.status,
        "title": title,
        "criteria_terms": criteria_expansion.terms,
        "title_terms": title_expansion.terms,
        "expansion_notes": {
            "criteria": criteria_expansion.note,
            "title": title_expansion.note,
        },
        "arms": arms,
    }


def _delta(row: dict, base: str, expanded: str) -> float | None:
    before, after = row["arms"][base]["tnr_at_recall"], row["arms"][expanded]["tnr_at_recall"]
    return None if before is None or after is None else round(after - before, 4)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Measure what query expansion buys.")
    parser.add_argument("--reviews", nargs="*", default=sorted(SUBSET))
    parser.add_argument("--recall-target", type=float, default=0.95)
    parser.add_argument("--provider", default="ollama")
    parser.add_argument("--model", default="qwen2.5:7b-instruct")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument("--db", default="data/slr.db")
    parser.add_argument("--prompts-dir", default="prompts")
    parser.add_argument("--runs-dir", default="runs")
    args = parser.parse_args(argv)

    unknown = [r for r in args.reviews if r not in SUBSET]
    if unknown:
        print(f"error: not in the evaluation subset: {unknown}", file=sys.stderr)
        return 2

    started = datetime.now(timezone.utc)
    sha, dirty = git_state(Path(args.runs_dir))
    conn = connect(args.db)
    provider = build_provider(args.provider, args.model)
    template = expand.load_prompt_template(Path(args.prompts_dir) / "expand_v1.txt")
    meter = Meter(ceiling_usd=0.0, usd_per_1m_input=0.0, usd_per_1m_output=0.0)

    print(f"query expansion · {provider.name}/{provider.model} · TNR@{args.recall_target:.0%}\n")
    header = f"{'Review':20} {'criteria':>9} {'+terms':>8} {'title':>8} {'+terms':>8}"
    print(header)
    print("-" * len(header))

    rows = []
    for review in args.reviews:
        row = run_review(
            conn,
            review,
            provider=provider,
            template=template,
            meter=meter,
            seed=args.seed,
            use_cache=not args.no_cache,
            recall_target=args.recall_target,
        )
        rows.append(row)

        def cell(name: str) -> str:
            value = row["arms"][name]["tnr_at_recall"]
            return "n/a" if value is None else f"{value:.3f}"

        print(
            f"{review:20} {cell('criteria'):>9} {cell('criteria_expanded'):>8} "
            f"{cell('title'):>8} {cell('title_expanded'):>8}"
        )

    finished = datetime.now(timezone.utc)
    config = {
        "reviews": args.reviews,
        "recall_target": args.recall_target,
        "provider": args.provider,
        "model": args.model,
        "seed": args.seed,
        "prompt_version": "expand_v1",
    }
    config_hash = hashlib.sha256(json.dumps(config, sort_keys=True).encode("utf-8")).hexdigest()[:10]
    run_id = f"{started:%Y%m%dT%H%M%S%fZ}-expand-{config_hash}"
    run_dir = Path(args.runs_dir) / run_id
    run_dir.mkdir(parents=True, exist_ok=False)

    criteria_deltas = [d for d in (_delta(r, "criteria", "criteria_expanded") for r in rows) if d is not None]
    title_deltas = [d for d in (_delta(r, "title", "title_expanded") for r in rows) if d is not None]
    _write_json(
        run_dir / "metrics.json",
        {
            "results_schema": RESULTS_SCHEMA,
            "config": config,
            "config_hash": config_hash,
            "totals": {
                "reviews_improved_from_criteria": sum(1 for d in criteria_deltas if d > 0),
                "reviews_worsened_from_criteria": sum(1 for d in criteria_deltas if d < 0),
                "reviews_improved_from_title": sum(1 for d in title_deltas if d > 0),
                "reviews_worsened_from_title": sum(1 for d in title_deltas if d < 0),
                "mean_delta_from_criteria": (
                    round(sum(criteria_deltas) / len(criteria_deltas), 4) if criteria_deltas else None
                ),
                "mean_delta_from_title": (
                    round(sum(title_deltas) / len(title_deltas), 4) if title_deltas else None
                ),
            },
            "per_review": rows,
        },
    )
    _write_json(
        run_dir / "run.json",
        {
            "run_id": run_id,
            "git_sha": sha,
            "git_dirty": dirty,
            "started_at": started.isoformat(),
            "finished_at": finished.isoformat(),
            "duration_s": round((finished - started).total_seconds(), 2),
            "python": platform.python_version(),
            "platform": platform.platform(),
            "calls": meter.calls,
            "cached_calls": meter.cached_calls,
        },
    )
    (run_dir / "git_sha.txt").write_text(
        f"{sha}{'-dirty' if dirty else ''}\n", encoding="utf-8", newline="\n"
    )

    if criteria_deltas:
        print(f"\nfrom criteria: mean TNR change {sum(criteria_deltas)/len(criteria_deltas):+.4f}")
    if title_deltas:
        print(f"from title:    mean TNR change {sum(title_deltas)/len(title_deltas):+.4f}")
    print(f"artefacts -> {run_dir}")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
