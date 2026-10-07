"""Look at what Europe PMC actually returned for one paper.

When a full-text extraction comes back mostly "not stated", there are two
very different explanations and they need telling apart:

* Europe PMC served a thin record -- some PMC entries carry little more
  than the abstract, even when flagged open access. Then the model is
  answering honestly about text it was never shown.
* The parser dropped content that was there. Then it is this project's
  bug, and the "not stated" answers are an artefact.

Guessing between those from the dashboard is impossible, so this prints
the raw shape of what arrived: how much body text, which sections, how
many tables, figures and equations, and the first part of the text the
model would actually have been given.

    python scripts/inspect_fulltext.py --pmcid PMC7508247
    python scripts/inspect_fulltext.py --doi 10.1136/bmj.l4673
    python scripts/inspect_fulltext.py --pmcid PMC7508247 --raw > raw.xml
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Run directly (``python scripts/inspect_fulltext.py``) and Python puts
# scripts/ on the path, not the repository root, so ``import slr`` fails.
# Prepending the root keeps the obvious invocation working.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402

from slr.adapters.fulltext import (  # noqa: E402
    FULLTEXT_URL,
    find_availability,
    parse_jats,
)
from slr.services.extract_fulltext import build_source  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inspect one paper's full text.")
    parser.add_argument("--pmcid")
    parser.add_argument("--doi")
    parser.add_argument("--title")
    parser.add_argument("--raw", action="store_true", help="dump the XML and stop")
    parser.add_argument("--chars", type=int, default=600, help="preview length")
    args = parser.parse_args(argv)

    pmcid = args.pmcid
    if not pmcid:
        if not (args.doi or args.title):
            parser.error("give --pmcid, or --doi/--title to look one up")
        availability = find_availability(doi=args.doi, title=args.title)
        print(f"found={availability.found}  pmcid={availability.pmcid}  "
              f"open_access={availability.is_open_access}")
        if availability.reason:
            print(f"reason: {availability.reason}")
        if not availability.has_full_text:
            return 1
        pmcid = availability.pmcid

    url = FULLTEXT_URL.format(pmcid=pmcid)
    print(f"GET {url}")
    response = httpx.get(url, timeout=30.0)
    print(f"HTTP {response.status_code}, {len(response.text):,} characters of XML\n")
    if response.status_code != 200:
        return 1

    if args.raw:
        sys.stdout.write(response.text)
        return 0

    paper = parse_jats(response.text)
    source = build_source(paper)

    print(f"title    : {paper.title}")
    print(f"doi      : {paper.doi}")
    print(f"abstract : {len(paper.abstract or ''):,} chars")
    print(f"body     : {len(paper.body):,} chars across {len(paper.sections)} sections")
    print(f"tables   : {len(paper.tables)}")
    print(f"figures  : {len(paper.figures)}")
    print(f"equations: {len(paper.equations)}")
    print(f"sent to the model: {len(source.text):,} chars"
          f"{' (TRUNCATED)' if source.truncated else ''}\n")

    print("sections:")
    for section in paper.sections:
        print(f"  - {section.title or '(untitled)'}  [{len(section.text):,} chars]")

    if paper.tables:
        print("\ntables:")
        for table in paper.tables:
            print(f"  - {table.label or '(no label)'}: {table.caption or ''} "
                  f"[{len(table.rows)} rows]")

    if paper.figures:
        print("\nfigures:")
        for figure in paper.figures:
            print(f"  - {figure.label or '(no label)'}: {figure.caption or ''}")
            for mention in figure.mentions:
                print(f"      says: {mention[:120]}")

    # The XML tags actually present, which is how a namespace problem or an
    # unexpected document shape shows itself.
    import re

    tags = sorted(set(re.findall(r"<([a-zA-Z][\w:-]*)", response.text)))
    interesting = [t for t in tags if t in {
        "body", "sec", "p", "table-wrap", "table", "fig", "graphic",
        "disp-formula", "inline-formula", "abstract", "article",
    }]
    print(f"\nrelevant tags present in the XML: {', '.join(interesting) or 'NONE'}")
    if "body" not in interesting:
        print("  !! no <body> element -- Europe PMC served metadata only, not the paper")

    print(f"\nfirst {args.chars} chars the model would see:\n")
    print(source.text[: args.chars] or "(nothing)")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
