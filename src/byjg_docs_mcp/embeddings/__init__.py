"""Embedder registry -- same swap-in pattern as the stores."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable


class Embedder(ABC):
    """Turns text into vectors.

    Documents and queries get separate methods because several models (the
    default `nomic-embed-text` among them) require a different task prefix for
    each side; collapsing them into one call silently degrades recall.
    """

    dimensions: int

    @abstractmethod
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        ...

    @abstractmethod
    def embed_query(self, text: str) -> list[float]:
        ...


def _ollama_factory(model: str, base_url: str) -> Embedder:
    from .ollama import OllamaEmbedder

    return OllamaEmbedder(model=model, base_url=base_url)


EMBEDDER_BACKENDS: dict[str, Callable[[str, str], Embedder]] = {
    "ollama": _ollama_factory,
}


def create_embedder(backend: str, model: str, base_url: str) -> Embedder:
    try:
        factory = EMBEDDER_BACKENDS[backend]
    except KeyError:
        known = ", ".join(sorted(EMBEDDER_BACKENDS))
        raise ValueError(f"unknown embedder backend {backend!r}; available: {known}") from None
    return factory(model, base_url)


__all__ = ["EMBEDDER_BACKENDS", "Embedder", "create_embedder"]
