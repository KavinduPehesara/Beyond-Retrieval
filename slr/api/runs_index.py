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


def _is_partial(run_dir: Path) -> bool:
    """Whether this run deliberately covered only part of a review.

    The project's own rule is to set ``max_records`` while developing, so a
    five-record smoke run exists to prove a path works, not to report a
    figure. Without this check the newest such run becomes "current" for
    its review and every number downstream quietly recomputes from five
    records -- which is what happened on 29 October, when two provider
    smoke runs displaced a 114-record one.
    """
    path = run_dir / "resolved_config.json"
    if not path.exists():
        return False
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return config.get("max_records") is not None


def latest_screen_run(runs_dir: Path, review: str) -> str | None:
    best = None
    for d in _run_dirs(runs_dir):
        if "-extract-" in d.name or "-gap-" in d.name or "-gaprecall-" in d.name:
            continue
        if _is_partial(d):
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
        if _is_partial(d):
            continue
        data = _read_metrics(d)
        if data and data.get("review") == review:
            best = d.name
    return best


def _provider_of(run_dir: Path) -> str | None:
    path = run_dir / "resolved_config.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("provider")
    except (OSError, json.JSONDecodeError):
        return None


def latest_gap_run(runs_dir: Path, review: str, provider: str | None = None) -> str | None:
    """The newest gap run for a review, optionally from one arm only.

    Three arms have now run over the same records, so "newest run" and "the
    arm a reported figure came from" are no longer the same directory.
    Anything quoting a specific arm's number passes ``provider``; the
    dashboard, which only wants the most recent result, leaves it out.
    """
    best = None
    for d in _run_dirs(runs_dir):
        if "-gap-" not in d.name or "-gaprecall-" in d.name:
            continue
        if _is_partial(d):
            continue
        if provider is not None and _provider_of(d) != provider:
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
