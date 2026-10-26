"""Everything the live demonstration depends on, checked before it starts.

A demonstration fails on the things nobody looks at: a model that is not
running, a key that expired, a network that blocks an upstream API. Each
check here is the cheapest call that proves the thing actually works rather
than merely looks configured -- a reachable host is not a working model.

    python scripts/preflight.py            # the usual run
    python scripts/preflight.py --paid     # also spends ~$0.0002 per provider

Exit code 0 when everything a demonstration needs is ready.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
# Run as `python scripts/preflight.py`, so the repository root is not on the
# path: only the script's own directory is.
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

OK, WARN, FAIL = "ok", "warn", "FAIL"

# A prompt shaped like the screening call, because that is what the demo
# makes. The providers answer in JSON mode against their own schema.
PROBE = (
    "You are screening a paper. Criteria: studies of probiotics in adults.\n"
    "Title: A randomised trial of a probiotic in adults.\n"
    "Abstract: We randomised 120 adults to a probiotic or placebo for 12 weeks.\n"
    "Answer with decision, confidence and evidence_span quoted from the abstract."
)


def report(label: str, state: str, detail: str = "") -> bool:
    mark = {OK: "  ok ", WARN: " warn", FAIL: " FAIL"}[state]
    print(f"[{mark}] {label}" + (f" -- {detail}" if detail else ""))
    return state != FAIL


def check_api(base: str) -> bool:
    try:
        r = httpx.get(f"{base}/health", timeout=5)
        if r.status_code == 200:
            return report("API", OK, base)
        return report("API", FAIL, f"{base} answered {r.status_code}")
    except httpx.HTTPError as exc:
        return report("API", FAIL, f"not reachable at {base} ({type(exc).__name__})")


def check_providers(base: str) -> tuple[bool, list[dict]]:
    try:
        r = httpx.get(f"{base}/providers", timeout=5)
        r.raise_for_status()
        body = r.json()
    except (httpx.HTTPError, ValueError) as exc:
        report("Providers", FAIL, f"could not be listed ({type(exc).__name__})")
        return False, []

    rows = body.get("providers") or []
    usable = [p for p in rows if p["configured"]]
    for p in rows:
        state = OK if p["configured"] else WARN
        report(f"  {p['label']} ({p['model']})", state, p["note"] or "configured")
    if not usable:
        report("Providers", FAIL, "none are usable, so nothing can answer")
        return False, []
    report("Providers", OK, f"{len(usable)} of {len(rows)} usable, default {body.get('default')}")
    return True, usable


def check_openalex(mailto: str | None) -> bool:
    """The search every question starts with."""
    url = "https://api.openalex.org/works"
    params = {"search": "probiotics irritable bowel syndrome", "per-page": 5}
    if mailto:
        params["mailto"] = mailto
    try:
        started = time.perf_counter()
        r = httpx.get(url, params=params, timeout=20)
        r.raise_for_status()
        results = r.json().get("results") or []
        with_abstract = sum(1 for w in results if w.get("abstract_inverted_index"))
        elapsed = time.perf_counter() - started
    except (httpx.HTTPError, ValueError) as exc:
        return report("OpenAlex", FAIL, f"search failed ({type(exc).__name__})")

    if not with_abstract:
        return report(
            "OpenAlex",
            WARN,
            "reachable, but none of the sample had a redistributable abstract",
        )
    return report("OpenAlex", OK, f"{with_abstract}/{len(results)} with abstracts in {elapsed:.1f}s")


def check_europe_pmc() -> bool:
    """Full text comes from here, and only for the open-access subset."""
    try:
        r = httpx.get(
            "https://www.ebi.ac.uk/europepmc/webservices/rest/search",
            params={"query": "probiotics AND OPEN_ACCESS:y", "format": "json", "pageSize": 1},
            timeout=20,
        )
        r.raise_for_status()
        hits = (r.json().get("resultList") or {}).get("result") or []
    except (httpx.HTTPError, ValueError) as exc:
        return report("Europe PMC", WARN, f"not reachable ({type(exc).__name__}); full text will fail")
    return report("Europe PMC", OK if hits else WARN, f"{len(hits)} open-access hit(s)")


def check_model_call(key: str, label: str) -> bool:
    """Prove the model answers, not just that a key is present."""
    from slr.api import providers as prov

    try:
        provider, meter, choice = prov.build(key)
    except ValueError as exc:
        return report(f"{label} call", WARN, str(exc))
    try:
        started = time.perf_counter()
        out = provider.complete(PROBE, temperature=0.0, max_tokens=128)
        elapsed = time.perf_counter() - started
    except Exception as exc:  # provider errors are many and all mean "no"
        return report(f"{label} call", FAIL, f"{type(exc).__name__}: {str(exc)[:120]}")

    cost = meter.cost_of(out.tokens_in, out.tokens_out)
    return report(
        f"{label} call",
        OK,
        f"answered in {elapsed:.1f}s, {out.tokens_in}+{out.tokens_out} tokens, ${cost:.6f}",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", default="http://127.0.0.1:8000", help="API base URL")
    parser.add_argument(
        "--paid",
        action="store_true",
        help="also make one real call per usable provider (fractions of a cent)",
    )
    args = parser.parse_args()

    import os

    print("Pre-flight for the live demonstration\n")
    ready = check_api(args.api)
    ok_providers, usable = check_providers(args.api) if ready else (False, [])
    ready = ready and ok_providers
    check_openalex(os.getenv("OPENALEX_MAILTO"))
    check_europe_pmc()

    if args.paid:
        print()
        for p in usable:
            # The local model costs nothing, so it is always worth proving.
            if p["free"] or args.paid:
                ready = check_model_call(p["key"], p["label"]) and ready

    print()
    if ready:
        print("Ready. Open a saved project first, so a network failure on stage")
        print("cannot empty the screen: a saved search renders from the database.")
        return 0
    print("Not ready -- fix the FAIL lines above before presenting.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
