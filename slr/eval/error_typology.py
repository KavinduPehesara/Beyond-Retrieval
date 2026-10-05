"""Why does verification fail?

``verify_note`` says *that* a quote was rejected, and across the six reviews
98.6% of rejections carry the same note: ``not_found``. That is a true
statement and a useless one. It does not distinguish a model that reworded
a real sentence from one that invented a sentence outright, and those are
different failures with different fixes -- the first is a prompt problem,
the second is a model problem, and only one of them is dangerous.

This module classifies a failed span against the source it was supposed to
come from, using the *same* normalisation the verifier itself uses, so a
category here cannot disagree with the decision that produced it. The
categories are ordered from least to most alarming:

``no_source_text``      the record has no abstract to quote from at all
``echoed_criteria``     the span is lifted from the eligibility criteria in
                        the prompt rather than from the paper
``quote_from_title``    the span is in the title but not the abstract
``truncated``           the span is a real prefix of source text, cut short
``near_paraphrase``     almost all of the span's words are in the source, in
                        order -- the model reworded a real sentence
``stitched``            two halves each appear in the source, but apart --
                        the model joined two separate sentences
``partial_overlap``     a substantial run of the span appears in the source
``fabricated``          little or none of the span is in the source
``too_short``           below the verifier's minimum span length
``longer_than_source``  the span is longer than the text it claims to quote

``echoed_criteria`` is why this module exists rather than a one-line count
of ``verify_note``. Classified without it, 97% of failures look like
fabrication -- a model inventing quotes, which would be a damning and
largely unfixable result. Checked against the criteria text that was in the
prompt, almost all of that 97% turns out to be the model quoting *the rule
it was asked to apply* instead of the evidence for applying it. That is a
prompt-comprehension failure, not invention: different diagnosis, different
fix, and a far more accurate description of what the verifier is catching.

The distribution over *all* failures is computed mechanically and costs
nothing. A seeded sample is also written out as a blind rating sheet, in the
same shape ``gap_recall.py`` uses, so the automatic labels can be checked by
a person rather than trusted.

Rule 4: this module reads ``work.label_included`` to report whether a failed
decision would also have been wrong, which is why it lives in ``slr/eval``.
Nothing here builds a prompt.
"""

from __future__ import annotations

import json
import random
import sqlite3
from collections import Counter
from dataclasses import asdict, dataclass
from difflib import SequenceMatcher

from slr.services.verify import MIN_SPAN_CHARS, normalise, source_text

# A span this much of which appears in the source, as one run, is a
# near-miss rather than an invention. Tuned to be deliberately generous:
# the point is to avoid calling a reworded real sentence "fabricated".
NEAR_PARAPHRASE_RATIO = 0.85
PARTIAL_OVERLAP_RATIO = 0.50
# Each half of a stitched quote has to be a substantial run in its own right.
STITCH_MIN_RATIO = 0.35

NO_SOURCE = "no_source_text"
ECHOED_CRITERIA = "echoed_criteria"
FROM_TITLE = "quote_from_title"
TRUNCATED = "truncated"
NEAR_PARAPHRASE = "near_paraphrase"
STITCHED = "stitched"
PARTIAL = "partial_overlap"
FABRICATED = "fabricated"
TOO_SHORT = "too_short"
LONGER_THAN_SOURCE = "longer_than_source"

# Ordered least to most alarming, for stable reporting.
CATEGORIES = (
    NO_SOURCE,
    ECHOED_CRITERIA,
    TOO_SHORT,
    LONGER_THAN_SOURCE,
    FROM_TITLE,
    TRUNCATED,
    NEAR_PARAPHRASE,
    STITCHED,
    PARTIAL,
    FABRICATED,
)


@dataclass
class Classification:
    category: str
    best_match_ratio: float
    matched_chars: int
    span_chars: int
    note: str

    def as_dict(self) -> dict:
        return asdict(self)


def _longest_common_run(span: str, source: str) -> tuple[int, int, int]:
    """Longest contiguous run of ``span`` that also appears in ``source``.

    Returns (length, span_start, source_start). SequenceMatcher on
    characters rather than words: the verifier matches characters, so the
    classifier should reason in the same units.
    """
    if not span or not source:
        return (0, 0, 0)
    matcher = SequenceMatcher(None, span, source, autojunk=False)
    block = matcher.find_longest_match(0, len(span), 0, len(source))
    return (block.size, block.a, block.b)


def classify_failure(
    span: str | None,
    title: str | None,
    abstract: str | None,
    criteria: str | None = None,
) -> Classification:
    """Categorise one failed span against the record it came from.

    Uses ``verify.normalise`` so the comparison is the one the verifier made
    -- a span this says is "in the source" would have verified.

    ``criteria`` is the eligibility text that was in the prompt. Pass it:
    without it the dominant failure mode is misreported as fabrication.
    """
    source = normalise(source_text(title, abstract))
    abstract_norm = normalise(abstract)
    title_norm = normalise(title)
    text = normalise(span)

    if not text:
        return Classification(FABRICATED, 0.0, 0, 0, "empty span")
    if not source:
        return Classification(NO_SOURCE, 0.0, 0, len(text), "record has no title or abstract")

    # Checked before anything else about the source: a span lifted from the
    # prompt's own criteria is not a failed attempt to quote the paper, it is
    # the model answering a different question.
    criteria_norm = normalise(criteria)
    if criteria_norm and text in criteria_norm:
        return Classification(
            ECHOED_CRITERIA, 0.0, 0, len(text),
            "span was quoted from the eligibility criteria, not the paper",
        )
    if len(text) < MIN_SPAN_CHARS:
        return Classification(TOO_SHORT, 0.0, 0, len(text), "below the verifier's minimum length")
    if len(text) > len(source):
        return Classification(
            LONGER_THAN_SOURCE, 0.0, 0, len(text), "span is longer than the text it quotes"
        )

    size, span_start, _ = _longest_common_run(text, source)
    ratio = size / len(text)

    # In the title but not the abstract: the model quoted the wrong field.
    if abstract_norm and title_norm and text not in abstract_norm and text in title_norm:
        return Classification(FROM_TITLE, 1.0, size, len(text), "span appears in the title only")

    if ratio >= NEAR_PARAPHRASE_RATIO:
        # A near-complete run starting at the span's own beginning that runs
        # to its end is a truncation, not a rewording.
        if span_start == 0 and size == len(text):
            return Classification(TRUNCATED, ratio, size, len(text), "span is a clean prefix")
        return Classification(
            NEAR_PARAPHRASE, ratio, size, len(text),
            f"{ratio:.0%} of the span appears verbatim; the rest was reworded",
        )

    # Two substantial runs that each appear, but not together: the model
    # joined separate sentences into one quote.
    if size:
        head, tail = text[:span_start], text[span_start + size :]
        for other in (head, tail):
            if len(other) < MIN_SPAN_CHARS:
                continue
            other_size, _, _ = _longest_common_run(other, source)
            if other_size / len(other) >= STITCH_MIN_RATIO and ratio >= STITCH_MIN_RATIO:
                return Classification(
                    STITCHED, ratio, size + other_size, len(text),
                    "two parts of the span appear separately in the source",
                )

    if ratio >= PARTIAL_OVERLAP_RATIO:
        return Classification(
            PARTIAL, ratio, size, len(text), f"{ratio:.0%} of the span appears as one run"
        )
    return Classification(
        FABRICATED, ratio, size, len(text),
        f"only {ratio:.0%} of the span appears in the source",
    )


def classify_run(
    conn: sqlite3.Connection, run_id: str, review: str
) -> list[dict]:
    """Classify every failed decision in one review of one run.

    Ground truth rides along so the report can say whether a failure was
    also a *wrong* decision -- an invented quote attached to a correct
    include is a different problem from one attached to a wrong include.
    """
    rows = conn.execute(
        """
        SELECT s.work_id, s.decision, s.confidence, s.evidence_span, s.verify_note,
               w.title, w.abstract, w.label_included
        FROM screening_decision s
        JOIN work w ON w.review = s.review AND w.work_id = s.work_id
        WHERE s.run_id = ? AND s.review = ? AND s.span_verified = 0
        ORDER BY s.work_id
        """,
        (run_id, review),
    ).fetchall()

    # The criteria this review's prompts carried. Read once, not per record.
    criteria_row = conn.execute(
        "SELECT criteria FROM review_criteria WHERE review = ?", (review,)
    ).fetchone()
    criteria = criteria_row["criteria"] if criteria_row else None

    out = []
    for row in rows:
        classification = classify_failure(
            row["evidence_span"], row["title"], row["abstract"], criteria
        )
        out.append(
            {
                "review": review,
                "run_id": run_id,
                "work_id": row["work_id"],
                "decision": row["decision"],
                "confidence": row["confidence"],
                "verify_note": row["verify_note"],
                "span": row["evidence_span"],
                "category": classification.category,
                "match_ratio": round(classification.best_match_ratio, 3),
                "span_chars": classification.span_chars,
                "note": classification.note,
                "truly_included": bool(row["label_included"]),
            }
        )
    return out


def distribution(classified: list[dict]) -> dict:
    """Category counts per review, with prevalence-independent shares."""
    per_review: dict[str, Counter] = {}
    for item in classified:
        per_review.setdefault(item["review"], Counter())[item["category"]] += 1

    rows = []
    for review, counts in per_review.items():
        total = sum(counts.values())
        rows.append(
            {
                "review": review,
                "n_failures": total,
                "counts": {c: counts.get(c, 0) for c in CATEGORIES if counts.get(c)},
                "shares": {
                    c: round(counts.get(c, 0) / total, 4)
                    for c in CATEGORIES
                    if counts.get(c)
                },
            }
        )
    overall = Counter()
    for item in classified:
        overall[item["category"]] += 1
    return {
        "per_review": sorted(rows, key=lambda r: r["review"]),
        "overall": {c: overall[c] for c in CATEGORIES if overall[c]},
        "n_failures": len(classified),
    }


def sample_for_rating(
    classified: list[dict], *, n: int = 50, seed: int = 42
) -> list[dict]:
    """A seeded sample, stratified across reviews, for a human to check.

    Stratified so one huge review cannot dominate the sheet: Radjenovic_2013
    alone contributes 3,821 of the failures, and an unstratified draw of 50
    would be almost entirely that one review. Each review contributes in
    proportion to its share, with at least one row where it has any.

    The sheet deliberately carries no automatic label -- the point is to
    rate the span against the abstract independently and only then compare,
    the same method the gap-recall pass used.
    """
    by_review: dict[str, list[dict]] = {}
    for item in classified:
        by_review.setdefault(item["review"], []).append(item)
    if not by_review:
        return []

    total = len(classified)
    rng = random.Random(seed)
    quotas = {}
    for review, items in by_review.items():
        quotas[review] = max(1, round(n * len(items) / total))

    # Trim or pad to land on n exactly, largest review first.
    order = sorted(quotas, key=lambda r: -len(by_review[r]))
    while sum(quotas.values()) > n:
        for review in order:
            if sum(quotas.values()) <= n:
                break
            if quotas[review] > 1:
                quotas[review] -= 1
    while sum(quotas.values()) < n:
        for review in order:
            if sum(quotas.values()) >= n:
                break
            if quotas[review] < len(by_review[review]):
                quotas[review] += 1

    sheet = []
    for review in sorted(by_review):
        items = sorted(by_review[review], key=lambda i: i["work_id"])
        take = min(quotas[review], len(items))
        for item in rng.sample(items, take):
            sheet.append(
                {
                    "review": item["review"],
                    "work_id": item["work_id"],
                    "span": item["span"],
                    "decision": item["decision"],
                    # Withheld from the rater on purpose, kept for scoring.
                    "_auto_category": item["category"],
                    "_truly_included": item["truly_included"],
                    "rating": None,
                    "rating_note": None,
                }
            )
    rng.shuffle(sheet)
    return sheet


def format_distribution(dist: dict) -> str:
    """Markdown, per review with counts, never pooled into one claim."""
    categories = [c for c in CATEGORIES if dist["overall"].get(c)]
    header = "| Review | Failures | " + " | ".join(categories) + " |"
    sep = "|---" * (len(categories) + 2) + "|"
    lines = [header, sep]
    for row in dist["per_review"]:
        cells = " | ".join(
            f"{row['counts'].get(c, 0)} ({row['shares'].get(c, 0):.0%})" if row["counts"].get(c)
            else "-"
            for c in categories
        )
        lines.append(f"| {row['review']} | {row['n_failures']:,} | {cells} |")
    totals = " | ".join(
        f"{dist['overall'].get(c, 0):,} ({dist['overall'].get(c, 0) / dist['n_failures']:.0%})"
        for c in categories
    )
    lines.append(f"| **All six** | **{dist['n_failures']:,}** | {totals} |")
    return "\n".join(lines)
