"""Store registry.

To plug a different database, implement `VectorStore` and register it here.
Nothing else in the codebase names a concrete backend.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from .base import (
    Chunk,
    Document,
    IndexedDocument,
    ProjectInfo,
    SearchHit,
    VectorStore,
)
from .sqlite_vec_store import SqliteVecStore

#: backend name -> factory(index_path, dimensions) -> VectorStore
#:
#: A Qdrant or pgvector backend registers itself the same way; `index_path` is
#: passed through verbatim, so a DSN string works as well as a file path.
STORE_BACKENDS: dict[str, Callable[[str | Path, int], VectorStore]] = {
    "sqlite": lambda location, dims: SqliteVecStore(location, dimensions=dims),
}


def create_store(backend: str, location: str | Path, dimensions: int) -> VectorStore:
    try:
        factory = STORE_BACKENDS[backend]
    except KeyError:
        known = ", ".join(sorted(STORE_BACKENDS))
        raise ValueError(f"unknown store backend {backend!r}; available: {known}") from None
    return factory(location, dimensions)


__all__ = [
    "STORE_BACKENDS",
    "Chunk",
    "Document",
    "IndexedDocument",
    "ProjectInfo",
    "SearchHit",
    "SqliteVecStore",
    "VectorStore",
    "create_store",
]
