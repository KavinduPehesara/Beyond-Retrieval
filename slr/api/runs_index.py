"""Which run is "current" for a review, for each of the three harnesses.

The dashboard shows one screening run, one extraction run and one gap run
per review by default (a person can still ask for a specific run_id).
"Current" means the most recently started run of that kind whose
metrics.json says it covers that review -- run directory names sort
chronologically because they're timestamp-prefixed, so the last match in
sorted order is the most recent. Nothing here writes anything; it only
reads what the harnesses already wrote (rule 2: every number still traces
to its own run directory).
"""

from __future__ import annotations

import json
from pathlib import Path


def _run_dirs(runs_dir: Path):
    return sorted((p for p in runs_dir.iterdir() if p.is_dir()), key=lambda p: p.name)


def _read_metrics(run_dir: Path) -> dict | None:
    path = run_dir / "metrics.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def latest_screen_run(runs_dir: Path, review: str) -> str | None:
    best = None
    for d in _run_dirs(runs_dir):
        if "-extract-" in d.name or "-gap-" in d.name or "-gaprecall-" in d.name:
            continue
        data = _read_metrics(d)
        if data and data.get("mode") == "screen" and review in (data.get("reviews_completed") or []):
            best = d.name
    return best


def latest_extract_run(runs_dir: Path, review: str) -> str | None:
    best = None
    for d in _run_dirs(runs_dir):
        if "-extract-" not in d.name:
            continue
        data = _read_metrics(d)
        if data and data.get("review") == review:
            best = d.name
    return best


def latest_gap_run(runs_dir: Path, review: str) -> str | None:
    best = None
    for d in _run_dirs(runs_dir):
        if "-gap-" not in d.name or "-gaprecall-" in d.name:
            continue
        data = _read_metrics(d)
        if data and data.get("review") == review:
            best = d.name
    return best


def list_reviews_with_screen_runs(runs_dir: Path) -> dict[str, str]:
    """{review: latest screening run_id} for every review any screening run covers."""
    out: dict[str, str] = {}
    for d in _run_dirs(runs_dir):
        if "-extract-" in d.name or "-gap-" in d.name or "-gaprecall-" in d.name:
            continue
        data = _read_metrics(d)
        if not data or data.get("mode") != "screen":
            continue
        for review in data.get("reviews_completed") or []:
            out[review] = d.name  # later runs overwrite earlier -> latest wins
    return out
