"""Document embeddings for dense retrieval, behind one small interface.

Only one embedding model is in scope for week 9 (SPECTER2), so this is a
``Protocol`` for test injection, not a provider-registry like
``adapters/llm.py`` — that dispatch pattern earns its keep when there is a
real second option to switch between (screening's mock/gemini/ollama);
here it would just be ceremony around a single implementation.
"""

from __future__ import annotations

from typing import Protocol

import numpy as np

MODEL_NAME = "allenai/specter2_base"
ADAPTER_NAME = "allenai/specter2"
ADAPTER_LOAD_AS = "proximity"


class Embedder(Protocol):
    def encode(self, texts: list[str]) -> np.ndarray:
        """Return one row vector per input text, in the same order."""
        ...


class Specter2Embedder:
    """SPECTER2 with its proximity adapter active.

    The base model alone (``AutoAdapterModel.from_pretrained`` with no
    adapter loaded) gives generic scientific-paper embeddings; the
    retrieval-tuned ones need the ``proximity`` adapter explicitly loaded and
    activated. Verified directly (not assumed): embeddings with the adapter
    active differ substantially (max abs diff ~0.8) from the same input
    without it, despite a misleading "none activated" warning the adapters
    library prints during loading.

    Lazy-loaded: the model and tokenizer are only pulled in on first
    ``encode()`` call, so importing this module (and running the test suite,
    which never calls it) costs nothing.
    """

    def __init__(self, batch_size: int = 16, max_length: int = 512) -> None:
        self.batch_size = batch_size
        self.max_length = max_length
        self._model = None
        self._tokenizer = None

    def _load(self) -> None:
        if self._model is not None:
            return
        from adapters import AutoAdapterModel
        from transformers import AutoTokenizer

        self._tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
        model = AutoAdapterModel.from_pretrained(MODEL_NAME)
        model.load_adapter(
            ADAPTER_NAME, source="hf", load_as=ADAPTER_LOAD_AS, set_active=True
        )
        model.eval()
        self._model = model

    def encode(self, texts: list[str]) -> np.ndarray:
        self._load()
        import torch

        sep = self._tokenizer.sep_token
        vectors = []
        for i in range(0, len(texts), self.batch_size):
            batch = texts[i : i + self.batch_size]
            inputs = self._tokenizer(
                batch,
                padding=True,
                truncation=True,
                max_length=self.max_length,
                return_tensors="pt",
            )
            with torch.no_grad():
                output = self._model(**inputs)
            vectors.append(output.last_hidden_state[:, 0, :].numpy())
        return np.concatenate(vectors, axis=0)


def title_abstract_text(title: str | None, abstract: str | None, sep: str = " [SEP] ") -> str:
    """SPECTER2's expected input shape: title and abstract joined by SEP."""
    return f"{(title or '').strip()}{sep}{(abstract or '').strip()}"
