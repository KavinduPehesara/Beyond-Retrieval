"""Ranking a review's records: the random and lexical baselines.

These are baselines one and two of four (random, BM25, dense-without-rerank,
ASReview). They are nearly free to build and they make every later number
meaningful — an improvement over nothing is not an improvement.

Dense retrieval, rank fusion and cross-encoder reranking (``dense``,
``hybrid``, ``rerank``) live in ``dense_retrieve.py``, dispatched from
``rank()`` below via a lazy import — that module imports back from this one
(``_SELECT``, ``lexical_rank``), so importing it at the top of this file
would be circular.

Rows returned here go straight to screening, so they carry the columns
screening needs and nothing else. ``label_included`` is not selected: ground
truth is read by ``slr.eval.metrics`` and by nothing else (rule 4), and a row
that carries it is one refactor away from a prompt that does too.
"""

from __future__ import annotations

import random
import re
import sqlite3

SCREENING_COLUMNS = ("review", "work_id", "doi", "title", "abstract", "year")
_SELECT = ", ".join(f"w.{c}" for c in SCREENING_COLUMNS)

# A term is a run of word characters. Everything else — commas, slashes,
# question marks, FTS5 operators — is a separator, never query syntax.
_TERM = re.compile(r"\w+", re.UNICODE)

STRATEGIES = ("random", "bm25", "dense", "hybrid", "rerank")

# Lazy singletons: the embedder and cross-encoder are real models (SPECTER2,
# MiniLM) that are expensive to load. Built once per process on first use,
# not once per review, so a multi-review run doesn't reload them each time.
_embedder = None
_cross_encoder = None


def _get_embedder():
    global _embedder
    if _embedder is None:
        from slr.adapters.embed import Specter2Embedder

        _embedder = Specter2Embedder()
    return _embedder


def _get_cross_encoder():
    global _cross_encoder
    if _cross_encoder is None:
        from slr.adapters.rerank import MiniLMCrossEncoder

        _cross_encoder = MiniLMCrossEncoder()
    return _cross_encoder


def to_match_query(text: str | None) -> str:
    """Turn free text into an FTS5 query that cannot be malformed.

    Each term is quoted, so punctuation and words like ``NOT`` or ``NEAR``
    are matched as text rather than parsed as syntax. Terms are OR-ed rather
    than AND-ed: a screening query is a description of a topic, not a boolean
    filter, and requiring every term returns nothing.
    """
    terms: list[str] = []
    seen: set[str] = set()
    for term in _TERM.findall(text or ""):
        folded = term.casefold()
        if len(folded) <= 2 or folded in seen:
            continue
        seen.add(folded)
        terms.append(f'"{term}"')
    return " OR ".join(terms)


def lexical_rank(
    conn: sqlite3.Connection, query: str, review: str, limit: int | None = None
) -> list[sqlite3.Row]:
    """Rank a review's records against a query by BM25. Best match first.

    Records that match nothing are appended at the end, in work_id order, so
    the full corpus is always returned — screening must consider every record,
    and retrieval only decides the order in which it does so. Ties are broken
    by work_id so the ranking is reproducible.
    """
    match = to_match_query(query)
    ranked: list[sqlite3.Row] = []

    if match:
        ranked = conn.execute(
            f"""
            SELECT {_SELECT}, bm25(work_fts) AS score
            FROM work_fts
            JOIN work w ON w.rowid = work_fts.rowid
            WHERE work_fts MATCH ? AND w.review = ?
            ORDER BY score, w.work_id
            """,
            (match, review),
        ).fetchall()

    seen = {r["work_id"] for r in ranked}
    rest = conn.execute(
        f"SELECT {_SELECT}, NULL AS score FROM work w WHERE w.review = ? ORDER BY w.work_id",
        (review,),
    ).fetchall()
    ranked.extend(r for r in rest if r["work_id"] not in seen)

    return ranked[:limit] if limit else ranked


def random_rank(
    conn: sqlite3.Connection, review: str, seed: int = 42, limit: int | None = None
) -> list[sqlite3.Row]:
    """Baseline one. Seeded, so the baseline itself is reproducible.

    Rows are put in work_id order before shuffling: SQLite does not promise
    an order without ORDER BY, and a shuffle of an unordered list is only
    reproducible by accident.
    """
    rows = conn.execute(
        f"SELECT {_SELECT}, NULL AS score FROM work w WHERE w.review = ? ORDER BY w.work_id",
        (review,),
    ).fetchall()
    random.Random(seed).shuffle(rows)
    return rows[:limit] if limit else rows


def rank(
    conn: sqlite3.Connection,
    strategy: str,
    review: str,
    *,
    seed: int,
    query: str | None = None,
    limit: int | None = None,
    rrf_k: int = 60,
    rerank_top_k: int = 200,
) -> list[sqlite3.Row]:
    """Dispatch on the configured strategy name."""
    if strategy == "random":
        return random_rank(conn, review, seed=seed, limit=limit)
    if strategy == "bm25":
        if not query:
            raise ValueError("bm25 ranking needs a query")
        return lexical_rank(conn, query, review, limit=limit)
    if strategy in ("dense", "hybrid", "rerank"):
        if not query:
            raise ValueError(f"{strategy} ranking needs a query")
        from slr.services import dense_retrieve

        if strategy == "dense":
            return dense_retrieve.dense_rank(
                conn, query, review, embedder=_get_embedder(), limit=limit
            )
        if strategy == "hybrid":
            return dense_retrieve.hybrid_rank(
                conn, query, review, embedder=_get_embedder(), rrf_k=rrf_k, limit=limit
            )
        return dense_retrieve.rerank_rank(
            conn,
            query,
            review,
            embedder=_get_embedder(),
            cross_encoder=_get_cross_encoder(),
            rrf_k=rrf_k,
            top_k=rerank_top_k,
            limit=limit,
        )
    raise ValueError(f"Unknown ranking strategy {strategy!r}. Use one of {STRATEGIES}.")
