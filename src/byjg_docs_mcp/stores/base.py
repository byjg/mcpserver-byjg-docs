"""Storage contract for the documentation index.

Everything the server needs from persistence lives behind `VectorStore`.
Swapping SQLite for Qdrant, pgvector or anything else means writing one new
implementation of this class and registering it in `stores.create_store` --
no changes in the indexer, the chunker or the MCP tools.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Chunk:
    """A retrievable slice of a document, carrying enough metadata to cite it."""

    source_path: str  # repo-relative, e.g. "docs/php/micro-orm/active-record.md"
    ordinal: int  # position within the document, 0-based
    text: str  # the chunk body as written in the source
    title: str  # document title
    heading_path: str  # e.g. "Active Record > Pattern Overview"
    url: str  # public docs URL
    category: str  # top-level docs folder, e.g. "php"
    project: str  # second-level folder, e.g. "micro-orm"

    @property
    def chunk_id(self) -> str:
        return f"{self.source_path}#{self.ordinal}"

    def embedding_text(self) -> str:
        """Text handed to the embedder.

        The heading path is prepended so an isolated chunk still carries the
        context it was written under; without it, a passage like "Usage" loses
        every clue about which library it documents.
        """
        header = " > ".join(p for p in (self.title, self.heading_path) if p)
        return f"{header}\n\n{self.text}" if header else self.text


@dataclass(frozen=True)
class SearchHit:
    chunk: Chunk
    score: float
    # Populated by hybrid backends so callers can see *why* something matched.
    vector_rank: int | None = None
    text_rank: int | None = None


@dataclass(frozen=True)
class Document:
    source_path: str
    title: str
    url: str
    category: str
    project: str
    text: str


@dataclass(frozen=True)
class ProjectInfo:
    category: str
    project: str
    documents: int
    chunks: int


@dataclass
class IndexedDocument:
    """A document plus its embedded chunks, ready to be persisted."""

    source_path: str
    content_hash: str
    text: str
    title: str
    url: str
    category: str
    project: str
    chunks: list[Chunk] = field(default_factory=list)
    vectors: list[list[float]] = field(default_factory=list)


class VectorStore(ABC):
    """Persistence + retrieval contract.

    Implementations must be safe to construct cheaply; expensive setup belongs
    in `setup()`, which the indexer calls before writing.
    """

    #: Dimensionality the store was created with. Implementations should refuse
    #: to mix vectors of different sizes rather than corrupt the index silently.
    dimensions: int

    @abstractmethod
    def setup(self) -> None:
        """Create schema/collections if absent. Must be idempotent."""

    @abstractmethod
    def indexed_hashes(self) -> dict[str, str]:
        """Map of source_path -> content_hash already stored.

        Drives incremental reindexing: unchanged files are skipped entirely.
        """

    @abstractmethod
    def replace_document(self, doc: IndexedDocument) -> None:
        """Atomically replace every chunk of `doc.source_path` with the new set."""

    @abstractmethod
    def delete_documents(self, source_paths: list[str]) -> int:
        """Remove documents (and their chunks). Returns how many were removed."""

    @abstractmethod
    def search(
        self,
        query_text: str,
        query_vector: list[float],
        limit: int = 8,
        category: str | None = None,
        project: str | None = None,
    ) -> list[SearchHit]:
        """Retrieve the best chunks for a query.

        Both the raw text and its embedding are passed so a backend may use
        either or both; a lexical-only or vector-only store is free to ignore
        the half it cannot use.
        """

    @abstractmethod
    def get_document(self, source_path: str) -> Document | None:
        """Return a whole document by its source path."""

    @abstractmethod
    def list_projects(self) -> list[ProjectInfo]:
        """Inventory of what is indexed, for discovery."""

    @abstractmethod
    def stats(self) -> dict[str, int]:
        """Coarse counters (documents, chunks) for health checks."""

    def close(self) -> None:  # pragma: no cover - default no-op
        """Release resources. Safe to call more than once."""

    def __enter__(self) -> "VectorStore":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
