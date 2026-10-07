"""How often is full text actually available? Measure it, don't guess.

Testing one paper at a time answers "does the code work". It does not
answer the question the report needs, which is **what fraction of the
literature this feature can actually read**. Those are different, and the
second one is the honest limitation to publish.

Searches OpenAlex for a topic, then puts every result through the Europe
PMC path and classifies the outcome:

``full``          a complete paper: body, sections, usually tables
``fragment``      flagged open access, but a stub was served (see
                  ``FullText.is_fragment`` and the 7 Oct note in CLAUDE.md)
``paywalled``     in Europe PMC, not open access
``no_pmc``        indexed, but no PMC record holds the text
``not_indexed``   Europe PMC does not have the paper at all
``no_doi``        OpenAlex gave no DOI and the title found nothing
``error``         the request failed

Writes a run directory so the figure is reportable under rule 2, and
prints a per-topic table. No model is called and nothing is screened --
this measures the *source*, not the pipeline, so it costs nothing and
takes about a second per paper.

    python scripts/fulltext_coverage.py --topic "vitamin d mortality"
    python scripts/fulltext_coverage.py --topic "hormone therapy" --limit 25
    python scripts/fulltext_coverage.py --topic "fault prediction" --topic "statins"
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402

from slr.adapters.fulltext import (  # noqa: E402
    fetch_full_text,
    find_availability,
)
from slr.services.discover import search_openalex  # noqa: E402

FULL = "full"
FRAGMENT = "fragment"
PAYWALLED = "paywalled"
NO_PMC = "no_pmc"
NOT_INDEXED = "not_indexed"
NO_DOI = "no_doi"
ERROR = "error"

OUTCOMES = (FULL, FRAGMENT, PAYWALLED, NO_PMC, NOT_INDEXED, NO_DOI, ERROR)


def classify(record: dict, *, client: httpx.Client, pause: float) -> dict:
    """One paper's full-text outcome, with the numbers behind it."""
    doi = (record.get("doi") or "").strip() or None
    title = record.get("title")
    out = {
        "work_id": record.get("work_id"),
        "title": (title or "")[:90],
        "doi": doi,
        "outcome": ERROR,
        "pmcid": None,
        "body_chars": 0,
        "sections": 0,
        "tables": 0,
        "figures": 0,
        "equations": 0,
        "reason": "",
    }
    if not doi and not title:
        out["outcome"] = NO_DOI
        out["reason"] = "no DOI or title to look up"
        return out

    try:
        availability = find_availability(doi=doi, title=title, client=client)
    except Exception as exc:
        out["reason"] = f"lookup failed: {exc}"
        return out
    time.sleep(pause)

    out["pmcid"] = availability.pmcid
    out["reason"] = availability.reason
    if not availability.found:
        out["outcome"] = NOT_INDEXED
        return out
    if not availability.pmcid:
        out["outcome"] = NO_PMC
        return out
    if not availability.is_open_access:
        out["outcome"] = PAYWALLED
        return out

    try:
        paper = fetch_full_text(availability.pmcid, client=client)
    except Exception as exc:
        out["reason"] = f"fetch failed: {exc}"
        return out
    time.sleep(pause)

    if paper is None:
        out["outcome"] = NO_PMC
        out["reason"] = "listed open access but full text not served"
        return out

    out.update(
        body_chars=len(paper.body),
        sections=len(paper.sections),
        tables=len(paper.tables),
        figures=len(paper.figures),
        equations=len(paper.equations),
        outcome=FRAGMENT if paper.is_fragment else FULL,
    )
    if paper.is_fragment:
        out["reason"] = "flagged open access but only a stub was served"
    return out


def git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


def format_table(by_topic: dict[str, list[dict]]) -> str:
    lines = [
        "| Topic | Papers | full | fragment | paywalled | no PMC | not indexed | usable |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for topic, rows in by_topic.items():
        counts = Counter(r["outcome"] for r in rows)
        n = len(rows)
        usable = counts[FULL] / n if n else 0.0
        lines.append(
            f"| {topic[:34]} | {n} | {counts[FULL]} | {counts[FRAGMENT]} | "
            f"{counts[PAYWALLED]} | {counts[NO_PMC]} | {counts[NOT_INDEXED]} | "
            f"**{usable:.0%}** |"
        )
    every = [r for rows in by_topic.values() for r in rows]
    counts = Counter(r["outcome"] for r in every)
    n = len(every)
    lines.append(
        f"| **All topics** | **{n}** | {counts[FULL]} | {counts[FRAGMENT]} | "
        f"{counts[PAYWALLED]} | {counts[NO_PMC]} | {counts[NOT_INDEXED]} | "
        f"**{(counts[FULL] / n if n else 0):.0%}** |"
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Measure Europe PMC full-text coverage.")
    parser.add_argument("--topic", action="append", required=True, help="repeatable")
    parser.add_argument("--limit", type=int, default=10, help="papers per topic")
    parser.add_argument("--pause", type=float, default=0.3, help="seconds between requests")
    parser.add_argument("--runs", default="runs")
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)

    by_topic: dict[str, list[dict]] = {}
    client = httpx.Client()
    try:
        for topic in args.topic:
            print(f"\n=== {topic} ===")
            try:
                records = search_openalex(topic, limit=args.limit)
            except Exception as exc:
                print(f"  OpenAlex search failed: {exc}")
                continue
            print(f"  {len(records)} papers with an abstract\n")

            rows = []
            for i, record in enumerate(records, 1):
                row = classify(record, client=client, pause=args.pause)
                rows.append(row)
                detail = (
                    f"{row['body_chars']:,}c {row['sections']}s "
                    f"{row['tables']}t {row['figures']}f"
                    if row["outcome"] in (FULL, FRAGMENT)
                    else row["reason"][:48]
                )
                print(f"  {i:2d}. {row['outcome']:12s} {detail:34s} {row['title'][:46]}")
            by_topic[topic] = rows
    finally:
        client.close()

    if not by_topic:
        print("\nNothing to report.")
        return 1

    every = [r for rows in by_topic.values() for r in rows]
    full = [r for r in every if r["outcome"] == FULL]
    payload = {
        "mode": "fulltext_coverage",
        "topics": args.topic,
        "limit_per_topic": args.limit,
        "n_papers": len(every),
        "outcomes": dict(Counter(r["outcome"] for r in every)),
        "usable_share": round(len(full) / len(every), 4) if every else None,
        "median_body_chars_when_full": (
            sorted(r["body_chars"] for r in full)[len(full) // 2] if full else None
        ),
        "papers_with_tables": sum(1 for r in full if r["tables"]),
        "papers_with_figures": sum(1 for r in full if r["figures"]),
        "by_topic": by_topic,
    }

    digest = hashlib.sha256(
        json.dumps(args.topic, sort_keys=True).encode("utf-8")
    ).hexdigest()[:10]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f") + "Z"
    out = Path(args.out) if args.out else Path(args.runs) / f"{stamp}-ftcoverage-{digest}"
    out.mkdir(parents=True, exist_ok=True)
    (out / "metrics.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    (out / "git_sha.txt").write_text(git_sha() + "\n", encoding="utf-8")
    table = format_table(by_topic)
    (out / "coverage.md").write_text("# Europe PMC full-text coverage\n\n" + table + "\n", "utf-8")

    print(f"\n\nWrote {out}\n")
    print(table)
    if full:
        print(
            f"\nOf the {len(full)} usable papers: {payload['papers_with_tables']} had tables, "
            f"{payload['papers_with_figures']} had figures, median body "
            f"{payload['median_body_chars_when_full']:,} characters."
        )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
