"""Long requests the browser can watch, instead of a spinner that says nothing.

A search is two model calls per paper, so twenty papers is half a minute on a
hosted model and several minutes on the local one. Held in one HTTP request,
all a page can show is that something is happening. A job runs the same work
on a worker thread and reports what it has finished, so the page can say
"checked 7 of 20" and be telling the truth.

Jobs live in memory and die with the process. That is the right lifetime: a
job is one person's one question, worth nothing after the answer is read, and
a restart during a search is a failed search either way.
"""

from __future__ import annotations

import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

# A finished job is kept this long so a page that polls slowly, or reloads,
# can still collect its answer.
KEEP_FINISHED_SECONDS = 15 * 60
MAX_JOBS = 64


@dataclass
class Job:
    """One unit of work, and how far through it is."""

    id: str
    stage: str = "starting"
    done: int = 0
    total: int = 0
    finished: bool = False
    result: Any = None
    error: str | None = None
    status_code: int = 500
    started_at: float = field(default_factory=time.time)
    ended_at: float | None = None

    @property
    def percent(self) -> int:
        """How much of the work is done, as a whole number.

        Only the screening stage knows its own size; the stages before it are
        single steps of unpredictable length, so they report as a small fixed
        share rather than pretending to measure themselves.
        """
        if self.finished:
            return 100
        if self.total <= 0:
            return {"starting": 0, "searching": 3, "ranking": 8}.get(self.stage, 5)
        # The search and ranking before screening are worth about a tenth of
        # the wait; the rest scales with papers actually judged.
        return min(99, 10 + int(90 * self.done / self.total))

    def snapshot(self) -> dict:
        return {
            "job_id": self.id,
            "stage": self.stage,
            "done": self.done,
            "total": self.total,
            "percent": self.percent,
            "finished": self.finished,
            "error": self.error,
            "elapsed_seconds": round((self.ended_at or time.time()) - self.started_at, 1),
        }


_jobs: dict[str, Job] = {}
_lock = threading.Lock()


def _evict() -> None:
    """Drop jobs nobody can still want. Caller holds the lock."""
    cutoff = time.time() - KEEP_FINISHED_SECONDS
    stale = [j.id for j in _jobs.values() if j.finished and (j.ended_at or 0) < cutoff]
    for job_id in stale:
        del _jobs[job_id]
    if len(_jobs) > MAX_JOBS:
        oldest = sorted(_jobs.values(), key=lambda j: j.started_at)[: len(_jobs) - MAX_JOBS]
        for job in oldest:
            del _jobs[job.id]


def start(work: Callable[[Callable[[str, int, int], None]], Any]) -> Job:
    """Run ``work`` on a worker thread, handing it a progress reporter.

    ``work`` is called with one argument: ``report(stage, done, total)``.
    Whatever it returns becomes the job's result; whatever it raises becomes
    the job's error, because a failure a page never hears about is worse
    than one it can show.
    """
    job = Job(id=uuid.uuid4().hex)
    with _lock:
        _evict()
        _jobs[job.id] = job

    def report(stage: str, done: int, total: int) -> None:
        with _lock:
            job.stage, job.done, job.total = stage, done, total

    def run() -> None:
        try:
            result = work(report)
        except Exception as exc:  # reported to the page, not swallowed
            with _lock:
                # HTTPException carries its message in ``detail``; everything
                # else says what it says.
                job.error = str(getattr(exc, "detail", None) or exc) or exc.__class__.__name__
                job.status_code = getattr(exc, "status_code", 500)
                job.finished, job.ended_at = True, time.time()
            return
        with _lock:
            job.result = result
            job.stage = "done"
            job.finished, job.ended_at = True, time.time()

    threading.Thread(target=run, name=f"job-{job.id[:8]}", daemon=True).start()
    return job


def get(job_id: str) -> Job | None:
    with _lock:
        return _jobs.get(job_id)


def forget(job_id: str) -> None:
    """Drop a job once its answer has been collected."""
    with _lock:
        _jobs.pop(job_id, None)


def clear() -> None:
    """Only for tests."""
    with _lock:
        _jobs.clear()
