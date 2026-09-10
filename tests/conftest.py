import hashlib

import pytest

from byjg_docs_mcp.embeddings import Embedder
from byjg_docs_mcp.stores import Chunk, IndexedDocument, SqliteVecStore

DIMS = 8


class HashEmbedder(Embedder):
    """Deterministic offline embedder.

    Vectors are derived from the words in the text, so texts sharing words land
    near each other. That is enough to assert ranking behaviour without
    depending on a running Ollama.
    """

    dimensions = DIMS

    def _vector(self, text: str) -> list[float]:
        vec = [0.0] * DIMS
        for word in text.lower().split():
            digest = hashlib.md5(word.encode()).digest()
            vec[digest[0] % DIMS] += 1.0
        norm = sum(v * v for v in vec) ** 0.5
        return [v / norm for v in vec] if norm else [1.0] + [0.0] * (DIMS - 1)

    def embed_documents(self, texts):
        return [self._vector(t) for t in texts]

    def embed_query(self, text):
        return self._vector(text)


@pytest.fixture
def embedder():
    return HashEmbedder()


@pytest.fixture
def store(tmp_path):
    s = SqliteVecStore(tmp_path / "test.db", dimensions=DIMS)
    s.setup()
    yield s
    s.close()


def make_doc(path, chunks, embedder, content_hash="h1", category="php", project="micro-orm"):
    """Build an IndexedDocument with real vectors from the test embedder."""
    chunk_objs = [
        Chunk(
            source_path=path,
            ordinal=i,
            text=text,
            title=path,
            heading_path=heading,
            url=f"https://example.test/{path}",
            category=category,
            project=project,
        )
        for i, (heading, text) in enumerate(chunks)
    ]
    return IndexedDocument(
        source_path=path,
        content_hash=content_hash,
        text="\n".join(t for _, t in chunks),
        title=path,
        url=f"https://example.test/{path}",
        category=category,
        project=project,
        chunks=chunk_objs,
        vectors=embedder.embed_documents([c.embedding_text() for c in chunk_objs]),
    )


@pytest.fixture
def doc_factory():
    return make_doc
