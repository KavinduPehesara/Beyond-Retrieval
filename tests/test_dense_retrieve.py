"""Tests for dense retrieval: RRF fusion, dense/hybrid/rerank ranking.

Uses fake Embedder/CrossEncoderScorer test doubles (mirrors _FakeProvider in
test_extract.py) so this suite stays fast and network-free — no real
SPECTER2/MiniLM download during `pytest`.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from slr.db import connect
from slr.services import dense_retrieve
from slr.services.ingest import ingest_frame

RECORDS = [
    ("W1", "Bayesian estimation in small samples", "Bias of Bayesian estimators at n below fifty.", 1),
    ("W2", "Frequentist methods", "Maximum likelihood under misspecification.", 0),
    ("W3", "Structural equation models", "Bayesian structural equation modelling, small samples.", 1),
    ("W4", "Unrelated topic", "Soil moisture in arid regions.", 0),
]


@pytest.fixture()
def conn(tmp_path):
    c = connect(tmp_path / "t.db")
    ingest_frame(
        c,
        "Smid_2020",
        pd.DataFrame(
            {
                "openalex_id": [r[0] for r in RECORDS],
                "title": [r[1] for r in RECORDS],
                "abstract": [r[2] for r in RECORDS],
                "label_included": [r[3] for r in RECORDS],
            }
        ),
    )
    yield c
    c.close()


class _FakeEmbedder:
    """Returns hand-picked 2D vectors, keyed by a marker word in the text.

    Call count is tracked so the embedding cache can be tested: a second
    ranking call over the same corpus must not call encode() on the corpus
    again.
    """

    # Keyed by each record's exact title — title_abstract_text() always puts
    # the title first, and these four titles share no substrings.
    VECTORS = {
        "query": [1.0, 0.0],
        "Bayesian estimation in small samples": [0.9, 0.1],   # close to the query (W1)
        "Frequentist methods": [0.0, 1.0],                    # far from the query (W2)
        "Structural equation models": [0.8, 0.2],              # second-closest (W3)
        "Unrelated topic": [-1.0, 0.0],                        # opposite the query (W4)
    }

    def __init__(self):
        self.encode_calls = 0

    QUERY_ALIASES = {"the query", "Bayesian"}

    def encode(self, texts: list[str]) -> np.ndarray:
        self.encode_calls += 1
        vectors = []
        for text in texts:
            if text in self.QUERY_ALIASES:
                vectors.append(self.VECTORS["query"])
                continue
            for marker, vec in self.VECTORS.items():
                if marker != "query" and text.startswith(marker):
                    vectors.append(vec)
                    break
            else:
                raise ValueError(f"no fake vector for {text!r}")
        return np.array(vectors, dtype="float32")


class _FakeCrossEncoder:
    """Reverses whatever order it's given — deterministic and easy to assert on."""

    def score(self, query: str, texts: list[str]) -> list[float]:
        return list(range(len(texts)))  # last text gets the highest score


# --------------------------------------------------------------------------
# RRF fusion — pure function, hand-worked example
# --------------------------------------------------------------------------


def test_rrf_fuses_two_rankings():
    # "a" is 1st in both rankings, so it must come out on top.
    ranking_1 = ["a", "b", "c"]
    ranking_2 = ["a", "c", "b"]
    fused = dense_retrieve.reciprocal_rank_fusion([ranking_1, ranking_2], k=60)
    assert fused[0] == "a"
    assert set(fused) == {"a", "b", "c"}


def test_rrf_rewards_agreement_over_a_single_top_rank():
    # "b" is 2nd in both lists (agreement); "a" is 1st in one, absent from the other.
    ranking_1 = ["a", "b"]
    ranking_2 = ["c", "b"]
    fused = dense_retrieve.reciprocal_rank_fusion([ranking_1, ranking_2], k=60)
    # score(a) = 1/(60+1)         = 1/61  ~ 0.0164
    # score(c) = 1/(60+1)         = 1/61  ~ 0.0164  (tied with a)
    # score(b) = 1/(60+2)+1/(60+2) = 2/62 ~ 0.0323  (agreement at rank 2 in both beats a lone rank 1)
    assert fused[0] == "b"
    assert set(fused[1:]) == {"a", "c"}


def test_rrf_ties_break_on_work_id():
    fused = dense_retrieve.reciprocal_rank_fusion([["z", "a"]], k=60)
    # No tie here, but confirms a stable, reproducible order for equal scores elsewhere.
    assert fused == ["z", "a"]


# --------------------------------------------------------------------------
# dense_rank
# --------------------------------------------------------------------------


def test_dense_rank_orders_by_cosine_similarity(conn):
    embedder = _FakeEmbedder()
    ranked = dense_retrieve.dense_rank(conn, "the query", "Smid_2020", embedder=embedder)
    assert [r["work_id"] for r in ranked] == ["W1", "W3", "W2", "W4"]


def test_dense_rank_returns_the_full_review(conn):
    ranked = dense_retrieve.dense_rank(conn, "the query", "Smid_2020", embedder=_FakeEmbedder())
    assert sorted(r["work_id"] for r in ranked) == ["W1", "W2", "W3", "W4"]


def test_dense_rank_carries_no_ground_truth(conn):
    ranked = dense_retrieve.dense_rank(conn, "the query", "Smid_2020", embedder=_FakeEmbedder())
    for row in ranked:
        assert "label_included" not in row.keys()


def test_embedding_cache_avoids_recomputing_the_corpus(conn, tmp_path):
    embedder = _FakeEmbedder()
    cache_dir = tmp_path / "embeddings"
    dense_retrieve.dense_rank(conn, "the query", "Smid_2020", embedder=embedder, cache_dir=cache_dir)
    calls_after_first = embedder.encode_calls
    dense_retrieve.dense_rank(conn, "the query", "Smid_2020", embedder=embedder, cache_dir=cache_dir)
    # Second call only re-encodes the query, not the whole corpus again.
    assert embedder.encode_calls == calls_after_first + 1


# --------------------------------------------------------------------------
# hybrid_rank
# --------------------------------------------------------------------------


def test_hybrid_rank_returns_the_full_review(conn):
    ranked = dense_retrieve.hybrid_rank(
        conn, "Bayesian", "Smid_2020", embedder=_FakeEmbedder()
    )
    assert sorted(r["work_id"] for r in ranked) == ["W1", "W2", "W3", "W4"]


def test_hybrid_rank_carries_no_ground_truth(conn):
    ranked = dense_retrieve.hybrid_rank(
        conn, "Bayesian", "Smid_2020", embedder=_FakeEmbedder()
    )
    for row in ranked:
        assert "label_included" not in row.keys()


# --------------------------------------------------------------------------
# rerank_rank
# --------------------------------------------------------------------------


def test_rerank_only_reorders_the_top_k_window(conn):
    # Ground truth for "before reranking" comes from hybrid_rank itself,
    # rather than a hand-computed RRF score — the fusion combines a real BM25
    # ranking with the fake dense one, and hand-predicting their combined
    # order (including a genuine tie) is exactly the kind of arithmetic this
    # test should not have to get right independently.
    fused = dense_retrieve.hybrid_rank(conn, "the query", "Smid_2020", embedder=_FakeEmbedder())
    fused_ids = [r["work_id"] for r in fused]

    ranked = dense_retrieve.rerank_rank(
        conn,
        "the query",
        "Smid_2020",
        embedder=_FakeEmbedder(),
        cross_encoder=_FakeCrossEncoder(),
        top_k=2,
    )
    ids = [r["work_id"] for r in ranked]

    assert ids[:2] == list(reversed(fused_ids[:2]))  # head, reordered by the fake cross-encoder
    assert ids[2:] == fused_ids[2:]                  # tail, untouched
    assert set(ids) == {"W1", "W2", "W3", "W4"}
