"""Wires configuration into concrete components."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .config import Settings, load_settings
from .embeddings import Embedder, create_embedder
from .indexer import DocsIndexer
from .stores import VectorStore, create_store


@dataclass
class Runtime:
    settings: Settings
    embedder: Embedder
    store: VectorStore

    def sync_job(self):
        """The fetch-and-reindex job for this configuration."""
        from .sync import ReindexJob

        return ReindexJob(self)

    def indexer(self, docs_root: Path) -> DocsIndexer:
        """An indexer bound to a specific tree.

        The tree is passed in rather than read from settings because it is
        usually a temporary clone that only exists for the duration of a
        refresh.
        """
        return DocsIndexer(
            docs_root=docs_root,
            store=self.store,
            embedder=self.embedder,
            site_url=self.settings.site_url,
            docs_route=self.settings.docs_route,
        )

    def close(self) -> None:
        self.store.close()


def build_runtime(settings: Settings | None = None) -> Runtime:
    """Assemble the embedder and store described by `settings`.

    The embedder is created first because the store is sized from the model's
    real output width: probing beats hardcoding 768, which would corrupt the
    index the moment the model changes.
    """
    settings = settings or load_settings()
    embedder = create_embedder(
        settings.embedder_backend, settings.embedding_model, settings.ollama_url
    )
    store = create_store(
        settings.store_backend, settings.index_path, embedder.dimensions
    )
    # Idempotent, and required before any read: a fresh deployment starts with
    # no index at all, and every caller (CLI and server alike) expects to be
    # able to query immediately.
    store.setup()
    return Runtime(settings=settings, embedder=embedder, store=store)
