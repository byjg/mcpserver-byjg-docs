"""Ollama embedder."""

from __future__ import annotations

import httpx

from . import Embedder

#: nomic-embed-text is trained with task prefixes and expects them at inference
#: time: documents and queries land in different regions of the space without
#: them. Models that do not use prefixes are configured with empty strings.
TASK_PREFIXES: dict[str, tuple[str, str]] = {
    "nomic-embed-text": ("search_document: ", "search_query: "),
}
DEFAULT_PREFIXES = ("", "")

#: How much of an oversized input to keep on each retry, and the floor at which
#: shrinking stops and the failure is treated as a misconfiguration.
TRUNCATION_RATIO = 0.75
MIN_TRUNCATION = 200


class OllamaEmbedder(Embedder):
    def __init__(
        self,
        model: str = "nomic-embed-text",
        base_url: str = "http://localhost:11434",
        timeout: float = 120.0,
        batch_size: int = 32,
    ) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.batch_size = batch_size
        self._client = httpx.Client(timeout=timeout)
        family = model.split(":", 1)[0]
        self.doc_prefix, self.query_prefix = TASK_PREFIXES.get(family, DEFAULT_PREFIXES)
        self._dimensions: int | None = None

    @property
    def dimensions(self) -> int:
        """Probe the model rather than hardcoding a size.

        Keeps the index and the embedder from silently disagreeing when the
        configured model changes.
        """
        if self._dimensions is None:
            self._dimensions = len(self.embed_query("dimension probe"))
        return self._dimensions

    def _post(self, inputs: list[str]) -> list[list[float]] | None:
        """Embed a batch, or return None if it overflowed the context window."""
        response = self._client.post(
            f"{self.base_url}/api/embed",
            json={"model": self.model, "input": inputs},
        )
        if response.status_code == 404:
            raise RuntimeError(
                f"Ollama does not have model {self.model!r}. Run: ollama pull {self.model}"
            )
        if response.status_code == 400 and "context length" in response.text:
            return None
        response.raise_for_status()
        return response.json()["embeddings"]

    def _embed(self, inputs: list[str]) -> list[list[float]]:
        """Embed a batch, shrinking whatever does not fit.

        The context limit is counted in tokens, and the token-to-character
        ratio is not predictable from the text: a base64 key blob costs roughly
        one token every two characters, ordinary prose closer to one every
        four. Rather than guess a character budget that some future document
        would violate anyway, oversized input is isolated and truncated here.
        Truncation is safe for retrieval because the title and heading path are
        prepended, so the identifying context survives the cut.
        """
        embeddings = self._post(inputs)
        if embeddings is not None:
            return embeddings

        if len(inputs) > 1:
            # Split to find the offending item instead of punishing the batch.
            middle = len(inputs) // 2
            return self._embed(inputs[:middle]) + self._embed(inputs[middle:])

        text = inputs[0]
        while len(text) > MIN_TRUNCATION:
            text = text[: int(len(text) * TRUNCATION_RATIO)]
            embeddings = self._post([text])
            if embeddings is not None:
                return embeddings
        raise RuntimeError(
            f"could not embed a {len(inputs[0])}-char input even truncated to "
            f"{MIN_TRUNCATION} chars; is {self.model!r} an embedding model?"
        )

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self.batch_size):
            batch = texts[start : start + self.batch_size]
            vectors.extend(self._embed([f"{self.doc_prefix}{t}" for t in batch]))
        return vectors

    def embed_query(self, text: str) -> list[float]:
        return self._embed([f"{self.query_prefix}{text}"])[0]

    def close(self) -> None:
        self._client.close()
