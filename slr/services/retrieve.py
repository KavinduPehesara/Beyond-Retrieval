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

    BM25 is computed over a temporary index holding **only this review**, not
    over the shared ``work_fts``. This is not an optimisation; it is required
    for the number to mean anything. ``bm25()`` derives IDF from the whole
    index it is called on, so querying ``work_fts`` and filtering by review
    afterwards makes a review's score depend on which *other* reviews happen
    to be ingested. Observed 21 September 2026: Smid_2020's TNR@95 read 0.568
    with two reviews in the database and 0.618 with three — same review, same
    code, same criteria, and an identical ``corpus_sha256`` in both metrics
    files, because that fingerprint covers the review's own text and not the
    rest of the index.

    Scoping the index also matches how results are reported. Rule 5 says
    per review, never pooled, because a metric pooled across reviews of
    different prevalence is not comparable (Kusa et al., 2023). An IDF pooled
    across reviews is the same mistake one level further down.

    Cost is rebuilding an index of at most 5,935 rows per review per run,
    which is well under a second.
    """
    match = to_match_query(query)
    ranked: list[sqlite3.Row] = []

    if match:
        try:
            conn.executescript(
                "DROP TABLE IF EXISTS temp.review_fts;"
                "CREATE VIRTUAL TABLE temp.review_fts USING fts5("
                "  work_id UNINDEXED, title, abstract,"
                "  tokenize='porter unicode61');"
            )
            conn.execute(
                "INSERT INTO review_fts (work_id, title, abstract) "
                "SELECT work_id, title, abstract FROM work WHERE review = ?",
                (review,),
            )
            ranked = conn.execute(
                f"""
                SELECT {_SELECT}, bm25(review_fts) AS score
                FROM review_fts
                JOIN work w ON w.work_id = review_fts.work_id AND w.review = ?
                WHERE review_fts MATCH ?
                ORDER BY score, w.work_id
                """,
                (review, match),
            ).fetchall()
        finally:
            conn.executescript("DROP TABLE IF EXISTS temp.review_fts;")

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
