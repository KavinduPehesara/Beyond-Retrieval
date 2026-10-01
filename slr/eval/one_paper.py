"""Run one paper through the whole pipeline, live: screen it, and if it is
included and the quote verifies, extract the four fields and look for a
stated gap. Built for showing the system actually running, in front of
someone, on one concrete record rather than a batch -- a demo, not a
reported figure, so it doesn't need --require-clean. It still writes real
rows under a real run_id, so the result is inspectable afterward the same
way any other run is.

Usage:
    python -m slr.eval.one_paper --review Nelson_2002 --work-id <id>
    python -m slr.eval.one_paper --review Nelson_2002 --random
    python -m slr.eval.one_paper --review Nelson_2002 --random --no-cache
"""

from __future__ import annotations

import argparse
import random
import sys
from datetime import datetime, timezone
from pathlib import Path

from slr.adapters.llm import BudgetExceeded, CacheMismatch, Meter, build_provider
from slr.db import connect
from slr.services import criteria as criteria_service
from slr.services.extract import FIELDS, extract_record
from slr.services.extract import persist as persist_extraction
from slr.services.gap import extract_gap
from slr.services.gap import persist as persist_gap
from slr.services.screen import load_prompt_template, screen_record
from slr.services.screen import persist as persist_screening

MODEL = "qwen2.5:7b-instruct"


def _rule(char: str = "-", width: int = 72) -> str:
    return char * width


def _pick_work_id(conn, review: str, work_id: str | None, pick_random: bool) -> str:
    if work_id:
        return work_id
    rows = conn.execute("SELECT work_id FROM work WHERE review = ? ORDER BY work_id", (review,)).fetchall()
    if not rows:
        raise SystemExit(f"no records for {review!r} -- has it been ingested?")
    if pick_random:
        return random.choice(rows)["work_id"]
    return rows[0]["work_id"]


def run(conn, *, review: str, work_id: str, use_cache: bool, db_path: str, prompts_dir: Path) -> str:
    row = conn.execute("SELECT * FROM work WHERE review = ? AND work_id = ?", (review, work_id)).fetchone()
    if row is None:
        raise SystemExit(f"{review}/{work_id} not found")

    run_id = f"onepaper-{datetime.now(timezone.utc):%Y%m%dT%H%M%S%fZ}"
    conn.execute(
        "INSERT INTO run (run_id, config_hash, config_name, provider, model, started_at) "
        "VALUES (?, 'onepaper', 'one_paper demo', 'ollama', ?, ?)",
        (run_id, MODEL, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()

    print(_rule("="))
    print(f"ONE PAPER, FULL SYSTEM -- {review}")
    print(_rule("="))
    print(f"run_id   {run_id}")
    print(f"work_id  {work_id}")
    print(f"title    {row['title']}")
    print(f"cache    {'on' if use_cache else 'OFF -- every call below is live'}")
    print()

    provider = build_provider("ollama", MODEL)
    meter = Meter(ceiling_usd=0.0, usd_per_1m_input=0.0, usd_per_1m_output=0.0)
    criteria = criteria_service.for_review(conn, review).text

    print(_rule())
    print("STAGE 1 -- SCREEN")
    print(_rule())
    template = load_prompt_template(prompts_dir / "screen_v1.txt")
    try:
        decision = screen_record(
            row, provider=provider, template=template, criteria=criteria, meter=meter, conn=conn,
            prompt_version="screen_v1", temperature=0.0, max_tokens=512, seed=42, use_cache=use_cache,
        )
    except CacheMismatch as exc:
        raise SystemExit(f"error: {exc}") from exc
    except BudgetExceeded as exc:
        raise SystemExit(f"error: {exc}") from exc
    persist_screening(conn, run_id, decision)
    conn.commit()

    print(f"decision       {decision.decision}")
    print(f"confidence     {decision.confidence}")
    print(f"span_verified  {decision.span_verified}  ({decision.verify_note})")
    print(f"quote          {decision.evidence_span!r}" if decision.evidence_span else "quote          (none)")
    print(f"source         {'cache' if decision.from_cache else 'live model call'}")
    print()

    if not (decision.decision == "include" and decision.span_verified):
        print("Stops here: extraction and gap discovery only run over verified includes.")
        print(f"This record is {decision.decision!r}" + ("" if decision.span_verified else " (unverified)") + ".")
        return run_id

    print(_rule())
    print("STAGE 2 -- EXTRACT")
    print(_rule())
    ext_template = load_prompt_template(prompts_dir / "extract_v1.txt")
    fields = extract_record(
        row, provider=provider, template=ext_template, meter=meter, conn=conn,
        prompt_version="extract_v1", temperature=0.0, max_tokens=512, seed=42, use_cache=use_cache,
    )
    for f in fields:
        persist_extraction(conn, run_id, run_id, f)
    conn.commit()
    for f in sorted(fields, key=lambda f: FIELDS.index(f.field_name)):
        status = "verified" if f.span_verified else ("not_stated" if f.verify_note == "not_stated" else "unverified")
        print(f"{f.field_name:14} [{status:10}] {f.value!r}")
        if f.evidence_span:
            print(f"{'':14}            quote: {f.evidence_span!r}")
    print(f"source         {'cache' if fields[0].from_cache else 'live model call'}")
    print()

    print(_rule())
    print("STAGE 3 -- DISCOVER GAPS")
    print(_rule())
    gap_template = load_prompt_template(prompts_dir / "gap_v1.txt")
    gap = extract_gap(
        row, provider=provider, template=gap_template, meter=meter, conn=conn,
        prompt_version="gap_v1", temperature=0.0, max_tokens=512, seed=42, use_cache=use_cache,
    )
    persist_gap(conn, run_id, run_id, gap)
    conn.commit()
    print(f"result   {gap.value}")
    if gap.evidence_span:
        print(f"quote    {gap.evidence_span!r}")
    print(f"status   {'verified' if gap.span_verified else gap.verify_note}")
    print(f"source   {'cache' if gap.from_cache else 'live model call'}")
    print("(not independently rated here -- rating is a human judgement, done separately)")
    print()

    print(_rule("="))
    print(f"Done. Every row above is in {db_path} under run_id {run_id!r}.")
    print(_rule("="))
    return run_id


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--review", required=True)
    parser.add_argument("--work-id", default=None, help="A specific record. Default: the first record in the review.")
    parser.add_argument("--random", action="store_true", help="Pick a random record instead of the first.")
    parser.add_argument("--no-cache", action="store_true", help="Bypass the cache -- every call is a genuine live request.")
    parser.add_argument("--db", default="data/slr.db")
    parser.add_argument("--prompts-dir", default="prompts")
    args = parser.parse_args(argv)

    conn = connect(args.db)
    try:
        work_id = _pick_work_id(conn, args.review, args.work_id, args.random)
        run(
            conn, review=args.review, work_id=work_id, use_cache=not args.no_cache,
            db_path=args.db, prompts_dir=Path(args.prompts_dir),
        )
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
