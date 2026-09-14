"""Lexical retrieval over the FTS5 index.

This is baseline two of four (random, BM25, dense-without-rerank, ASReview).
It is nearly free to build and it makes every later number meaningful — an
improvement over nothing is not an improvement.

Dense retrieval, rank fusion and cross-encoder reranking arrive in week 9. The
harness must exist first (rule 1).
"""

from __future__ import annotations

import random
import re
import sqlite3

# FTS5 treats these as syntax. A research question typed by a human is not
# a query language, so they are stripped rather than escaped.
_FTS_SPECIAL = re.compile(r'["\'\(\)\*\^\-:]')


def to_match_query(text: str) -> str:
    """Turn free text into something FTS5 will accept.

    Terms are OR-ed rather than AND-ed: a screening query is a description of
    a topic, not a boolean filter, and requiring every term returns nothing.
    """
    cleaned = _FTS_SPECIAL.sub(" ", text)
    terms = [t for t in cleaned.split() if len(t) > 2]
    if not terms:
        return ""
    return " OR ".join(terms)


def lexical_rank(
    conn: sqlite3.Connection, query: str, review: str, limit: int | None = None
) -> list[sqlite3.Row]:
    """Rank a review's records against a query. Best match first.

    Records that match nothing are appended at the end with a null score, so
    the full corpus is always returned — screening must consider every record,
    and retrieval only decides the order in which it does so.
    """
    match = to_match_query(query)
    ranked: list[sqlite3.Row] = []
    seen: set[str] = set()

    if match:
        sql = """
            SELECT w.*, bm25(work_fts) AS score
            FROM work_fts
            JOIN work w ON w.rowid = work_fts.rowid
            WHERE work_fts MATCH ? AND w.review = ?
            ORDER BY score
        """
        try:
            ranked = conn.execute(sql, (match, review)).fetchall()
            seen = {r["work_id"] for r in ranked}
        except sqlite3.OperationalError:
            # Malformed query after cleaning — fall through to unranked.
            ranked, seen = [], set()

    rest = conn.execute(
        "SELECT *, NULL AS score FROM work WHERE review = ? AND work_id NOT IN "
        "(SELECT work_id FROM work WHERE review = ?)" if False else
        "SELECT *, NULL AS score FROM work WHERE review = ?",
        (review,),
    ).fetchall()
    ranked.extend(r for r in rest if r["work_id"] not in seen)

    return ranked[:limit] if limit else ranked


def random_rank(
    conn: sqlite3.Connection, review: str, seed: int = 42, limit: int | None = None
) -> list[sqlite3.Row]:
    """Baseline one. Seeded, so the baseline itself is reproducible."""
    rows = conn.execute("SELECT *, NULL AS score FROM work WHERE review = ?", (review,)).fetchall()
    random.Random(seed).shuffle(rows)
    return rows[:limit] if limit else rows
