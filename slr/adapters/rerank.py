"""Cross-encoder reranking, behind one small interface.

Same reasoning as ``adapters/embed.py``: one model in scope for week 9, so a
``Protocol`` for test injection rather than a provider registry.
"""

from __future__ import annotations

from typing import Protocol

MODEL_NAME = "cross-encoder/ms-marco-MiniLM-L-6-v2"


class CrossEncoderScorer(Protocol):
    def score(self, query: str, texts: list[str]) -> list[float]:
        """One relevance score per text, higher is more relevant."""
        ...


class MiniLMCrossEncoder:
    """Lazy-loaded so importing this module costs nothing in the test suite."""

    def __init__(self) -> None:
        self._model = None

    def _load(self) -> None:
        if self._model is not None:
            return
        from sentence_transformers import CrossEncoder

        self._model = CrossEncoder(MODEL_NAME)

    def score(self, query: str, texts: list[str]) -> list[float]:
        self._load()
        pairs = [(query, text) for text in texts]
        return [float(s) for s in self._model.predict(pairs)]
