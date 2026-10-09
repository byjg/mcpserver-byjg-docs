---
sidebar_position: 1
---

# Development

Everything about running, hosting and changing the server. To *use* the
public server, you do not need any of this -- see [Connecting a client](../clients.md).

## What it is

The server turns the ~575 markdown files in
[`byjg/byjg.github.io`](https://github.com/byjg/byjg.github.io) -- the `docs`
folder and the blog -- into ~4,400 searchable passages and exposes them to an
LLM through three MCP tools.

![Data flow: the write path indexes markdown into the store; the read path answers MCP queries. Both meet at the embedder and the store.](../img/data-flow.svg)

**Hybrid retrieval.** Vector similarity answers natural-language questions;
BM25 catches exact symbol names like `TableAttribute`, which pure vector search
is notably bad at. Results are fused with Reciprocal Rank Fusion.

**Heading-aware chunking.** Passages are split on markdown headings rather than
fixed-size windows, so each one is a coherent section that arrives with its
heading path and public URL attached.

**GitHub is the source of truth.** Each refresh clones the docs repository into
a temporary directory and discards it afterwards -- there is no working copy to
initialise, keep in sync or back up. Indexing stays incremental anyway, because
it keys on content hashes a fresh clone reproduces exactly: a rebuild after an
unrelated push re-embeds nothing.

**One file.** The whole index is a 24 MB SQLite database -- `sqlite-vec` for
vectors, FTS5 for keywords. At this corpus size a brute-force scan takes
milliseconds, so a dedicated vector service would be infrastructure without a
payoff.

**Swappable backends.** Storage sits behind a `VectorStore` interface and
embedding behind an `Embedder` interface; nothing outside `stores/` and
`embeddings/` names a concrete backend.

## Pick your path

| You want to | How it runs | Page |
|---|---|---|
| Work on the code, build and query the index | From source with `uv`, stdio | [Running locally](local.md) |
| Host your own server, with the GitHub webhook | Docker Compose, HTTP | [Self-hosting](self-hosting.md) |
| Know what a setting does | -- | [Configuration](configuration.md) |
| Understand how and why it works | -- | [Architecture](architecture.md) |
| Fix something that broke | -- | [Troubleshooting](troubleshooting.md) |

## Tests

```bash
uv run pytest
```

Fully offline -- `tests/conftest.py` supplies a deterministic hash-based
embedder, so no Ollama instance is needed.
