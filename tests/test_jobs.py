"""Long work the browser can watch.

What matters here is that a page is never left guessing: progress reflects
work actually finished, and a failure reaches the page instead of hanging
behind a spinner forever.
"""

from __future__ import annotations

import threading
import time

import pytest

from slr.api import jobs


@pytest.fixture(autouse=True)
def clean_registry():
    jobs.clear()
    yield
    jobs.clear()


def wait_for(job, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if jobs.get(job.id) is None or job.finished:
            return job
        time.sleep(0.01)
    raise AssertionError(f"job did not finish within {timeout}s")


def test_a_finished_job_carries_its_answer():
    job = jobs.start(lambda report: {"papers": 3})
    wait_for(job)
    assert job.finished and job.error is None
    assert job.result == {"papers": 3}
    assert job.percent == 100


def test_progress_is_visible_while_the_work_is_still_running():
    """The whole point: a watcher sees the count move, not just the end."""
    halfway = threading.Event()
    release = threading.Event()

    def work(report):
        report("screening", 2, 4)
        halfway.set()
        release.wait(5)
        report("screening", 4, 4)
        return "done"

    job = jobs.start(work)
    assert halfway.wait(5), "work never reported progress"

    watched = jobs.get(job.id).snapshot()
    assert watched["done"] == 2 and watched["total"] == 4
    assert watched["finished"] is False
    assert 10 < watched["percent"] < 100

    release.set()
    wait_for(job)
    assert job.done == 4 and job.result == "done"


def test_percent_grows_with_papers_judged():
    job = jobs.Job(id="x", stage="screening", done=0, total=20)
    assert job.percent == 10
    job.done = 10
    assert job.percent == 55
    job.done = 20
    # Never 100 until the answer is actually in hand.
    assert job.percent == 99
    job.finished = True
    assert job.percent == 100


def test_the_stages_before_screening_do_not_pretend_to_measure_themselves():
    assert jobs.Job(id="x", stage="searching").percent == 3
    assert jobs.Job(id="x", stage="ranking").percent == 8


def test_a_failure_reaches_the_page_rather_than_hanging():
    def work(report):
        raise RuntimeError("OpenAlex said no")

    job = jobs.start(work)
    wait_for(job)
    assert job.finished and job.result is None
    assert "OpenAlex said no" in job.error


def test_an_http_failure_keeps_its_status_and_message():
    from fastapi import HTTPException

    def work(report):
        raise HTTPException(404, "Project not found")

    job = jobs.start(work)
    wait_for(job)
    assert job.status_code == 404
    assert job.error == "Project not found"


def test_a_progress_report_that_raises_does_not_kill_the_search(tmp_path):
    """The display is the least important thing in the room.

    A page that disconnects mid-search must not take the search with it.
    """
    from slr.adapters.llm import Meter
    from slr.db import connect
    from slr.services.suggest import suggest

    def exploding_report(stage, done, total):
        raise ValueError("nobody is watching")

    conn = connect(tmp_path / "jobs.db")
    try:
        result = suggest(
            conn,
            "does anything work",
            provider=None,
            screen_template="{title}",
            gap_template="{title}",
            meter=Meter(ceiling_usd=0.0, usd_per_1m_input=0.0, usd_per_1m_output=0.0),
            candidates=[],  # no papers, so no provider call is made
            on_progress=exploding_report,
        )
    finally:
        conn.close()

    assert result.suggestions == []


def test_jobs_are_forgotten_once_collected():
    job = jobs.start(lambda report: "answer")
    wait_for(job)
    jobs.forget(job.id)
    assert jobs.get(job.id) is None
