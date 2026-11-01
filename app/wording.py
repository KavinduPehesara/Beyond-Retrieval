"""Sentences the page says, kept apart from the page.

Home.py is a Streamlit script: importing it runs it, which means anything
defined there can only be tested by rendering the whole page. These are pure
functions over a session dict, so they live here and are tested directly.
"""

from __future__ import annotations


def screening_message(done: int, total: int, arms: int) -> str:
    """How far through screening the run is, counted in papers.

    The service counts model calls, because that is what it can count as it
    goes and with two arms half a paper's worth of bar moves at a time. Said
    out loud that becomes "checking paper 3 of 20" to someone who asked for
    ten papers, which reads as the tool ignoring the slider. Both models see
    every paper, so the paper count is the call count over the arm count.
    """
    arms = max(1, arms)
    papers = max(1, total // arms)
    if done >= total:
        return f"Checked all {papers} papers; finishing up..."
    return f"Checking paper {min(done // arms + 1, papers)} of {papers}..."


def run_cost_note(session: dict) -> str:
    """What this search cost, and why a repeat costs less.

    An answer already in the cache is not paid for twice, so the figure
    falls on a second run of the same question. Saying how many calls were
    served from cache keeps that from looking like a cheaper model.

    Costs are written "USD 0.0058", never "US$0.0058": Streamlit renders a
    caption as markdown, and a second dollar sign later in the same line
    turns everything between the two into italic maths.
    """
    calls = session.get("model_calls")
    if not calls:
        return ""
    cost = session.get("cost_usd") or 0.0
    cached = session.get("cached_calls") or 0
    if cached >= calls:
        # Every answer was already held. Worth saying outright, or a free
        # repeat reads as a free model.
        return f"{calls} model calls, all answered from an earlier run: nothing new was spent."
    if cost <= 0:
        return f"{calls} model calls: no cost, the model runs on this machine."
    priced = calls - cached
    if cached:
        return f"{calls} model calls, {cached} from an earlier run: USD {cost:.4f} for the other {priced}."
    return f"{calls} model calls: USD {cost:.4f}."
