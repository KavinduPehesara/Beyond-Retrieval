"""Dense retrieval: SPECTER2 + FAISS, RRF fusion with BM25, cross-encoder rerank.

Sits beside ``retrieve.py`` rather than inside it — same reasoning as
``extract.py`` sitting beside ``screen.py``: three new, fairly different
ranking strategies, built on the existing random/BM25 baselines without
touching them.
"""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import numpy as np

from slr.adapters.embed import Embedder, title_abstract_text
from slr.adapters.rerank import CrossEncoderScorer
from slr.services.retrieve import _SELECT, lexical_rank

DEFAULT_CACHE_DIR = Path("data/embeddings")


def _corpus_hash(rows: list[sqlite3.Row]) -> str:
    """Fingerprint of the text embeddings were computed from.

    Keyed on work_id/title/abstract only — if any of these change the cached
    vectors are stale and must be recomputed. Unlike the LLM response cache,
    a stale embedding is safe to just regenerate: there is no experiment-
    design bug being masked here, just text that changed.
    """
    digest = hashlib.sha256()
    for r in sorted(rows, key=lambda row: row["work_id"]):
        digest.update(f"{r['work_id']}\x1f{r['title']}\x1f{r['abstract']}\n".encode("utf-8"))
    return digest.hexdigest()


def embedding_cache_path(review: str, cache_dir: Path) -> Path:
    return cache_dir / f"{review}__specter2.npz"


def load_or_build_embeddings(
    conn: sqlite3.Connection,
    review: str,
    embedder: Embedder,
    *,
    cache_dir: Path = DEFAULT_CACHE_DIR,
) -> tuple[list[str], np.ndarray]:
    """work_ids (in a fixed order) and their SPECTER2 vectors, cached to disk."""
    rows = conn.execute(
        "SELECT work_id, title, abstract FROM work WHERE review = ? ORDER BY work_id",
        (review,),
    ).fetchall()
    corpus_sha = _corpus_hash(rows)

    path = embedding_cache_path(review, cache_dir)
    if path.exists():
        cached = np.load(path, allow_pickle=False)
        if str(cached["corpus_sha256"].item()) == corpus_sha:
            return list(cached["work_ids"]), cached["vectors"]
        print(f"  ! {review}: corpus changed since embeddings were cached, recomputing")

    work_ids = [r["work_id"] for r in rows]
    texts = [title_abstract_text(r["title"], r["abstract"]) for r in rows]
    vectors = embedder.encode(texts)

    cache_dir.mkdir(parents=True, exist_ok=True)
    np.savez(
        path,
        work_ids=np.array(work_ids),
        vectors=vectors,
        corpus_sha256=np.array(corpus_sha),
    )
    return work_ids, vectors


def _l2_normalise(vectors: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return vectors / norms


def _rows_in_order(
    conn: sqlite3.Connection, review: str, ranked_ids: list[str], *, limit: int | None = None
) -> list[sqlite3.Row]:
    rows = conn.execute(
        f"SELECT {_SELECT}, NULL AS score FROM work w WHERE w.review = ?", (review,)
    ).fetchall()
    by_id = {r["work_id"]: r for r in rows}
    ordered = [by_id[wid] for wid in ranked_ids if wid in by_id]
    return ordered[:limit] if limit else ordered


def dense_rank(
    conn: sqlite3.Connection,
    query: str,
    review: str,
    *,
    embedder: Embedder,
    cache_dir: Path = DEFAULT_CACHE_DIR,
    limit: int | None = None,
) -> list[sqlite3.Row]:
    """Rank a review's records by cosine similarity to the query. Best match first."""
    import faiss

    work_ids, vectors = load_or_build_embeddings(conn, review, embedder, cache_dir=cache_dir)
    normed = _l2_normalise(np.asarray(vectors, dtype="float32"))
    index = faiss.IndexFlatIP(normed.shape[1])
    index.add(normed)

    query_vec = _l2_normalise(embedder.encode([query]).astype("float32"))
    _, order = index.search(query_vec, len(work_ids))
    ranked_ids = [work_ids[i] for i in order[0]]

    return _rows_in_order(conn, review, ranked_ids, limit=limit)


def reciprocal_rank_fusion(rankings: list[list[str]], *, k: int = 60) -> list[str]:
    """RRF: score(d) = sum over rankers of 1 / (k + rank(d)), 1-indexed rank.

    Ties broken by work_id, same reproducibility rule as the other rankers.
    """
    scores: dict[str, float] = {}
    for ranking in rankings:
        for position, work_id in enumerate(ranking, start=1):
            scores[work_id] = scores.get(work_id, 0.0) + 1.0 / (k + position)
    return sorted(scores, key=lambda wid: (-scores[wid], wid))


def hybrid_rank(
    conn: sqlite3.Connection,
    query: str,
    review: str,
    *,
    embedder: Embedder,
    cache_dir: Path = DEFAULT_CACHE_DIR,
    rrf_k: int = 60,
    limit: int | None = None,
) -> list[sqlite3.Row]:
    """RRF fusion of dense and BM25 rankings, k=60 by default."""
    dense_rows = dense_rank(conn, query, review, embedder=embedder, cache_dir=cache_dir)
    lexical_rows = lexical_rank(conn, query, review)
    fused_ids = reciprocal_rank_fusion(
        [[r["work_id"] for r in dense_rows], [r["work_id"] for r in lexical_rows]], k=rrf_k
    )
    return _rows_in_order(conn, review, fused_ids, limit=limit)


def rerank_rank(
    conn: sqlite3.Connection,
    query: str,
    review: str,
    *,
    embedder: Embedder,
    cross_encoder: CrossEncoderScorer,
    cache_dir: Path = DEFAULT_CACHE_DIR,
    rrf_k: int = 60,
    top_k: int = 200,
    limit: int | None = None,
) -> list[sqlite3.Row]:
    """Hybrid fusion, then a cross-encoder reranks the top ``top_k`` only.

    Everything past position ``top_k`` keeps its fused order — reranking the
    whole review is slow and pointless (same reasoning CLAUDE.md already
    gives for capping reranking at all).
    """
    fused = hybrid_rank(conn, query, review, embedder=embedder, cache_dir=cache_dir, rrf_k=rrf_k)
    head, tail = fused[:top_k], fused[top_k:]

    texts = [title_abstract_text(r["title"], r["abstract"]) for r in head]
    scores = cross_encoder.score(query, texts)
    reranked_head = [row for _, row in sorted(zip(scores, head), key=lambda pair: -pair[0])]

    ordered = reranked_head + list(tail)
    return ordered[:limit] if limit else ordered
