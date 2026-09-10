# byjg-docs-mcp

MCP server for semantic search over the [ByJG documentation](https://opensource.byjg.com).

Turns the ~550 markdown files in `byjg.github.io/docs` into ~4,100 searchable
passages and exposes them to an LLM through three MCP tools, so it can answer
questions about the ByJG libraries and cite the page it got the answer from.

![Data flow: the write path indexes markdown into the store; the read path answers MCP queries. Both meet at the embedder and the store.](docs/img/data-flow.svg)

## Documentation

| | |
|---|---|
| [Usage](docs/usage.md) | Building the index, running the server, the MCP tools, configuration |
| [Infrastructure](docs/infrastructure.md) | Docker deployment, GPU, Cloudflare Tunnel, the GitHub webhook |
| [Architecture](docs/architecture.md) | How it works and why it is built this way |

## Quick start

```bash
uv sync
ollama serve &
ollama pull nomic-embed-text

cp .env.example .env          # defaults already point at byjg.github.io
uv run byjg-docs-index build  # clones from GitHub and indexes, ~60s
```

```bash
uv run byjg-docs-index search "how do I map a table to a class"
```

Register with Claude Code, running it locally over stdio:

```bash
claude mcp add byjg-docs -- \
  uv --directory ~/Projects/ByJG/McpServer run byjg-docs-mcp
```

Or run it as a service and reach it over the network — this is also the mode
that serves the GitHub webhook and the health check. It needs two secrets in
`.env`, each from its own `openssl rand -hex 32`:

```bash
# .env:  BYJG_DOCS_AUTH_TOKEN, BYJG_DOCS_WEBHOOK_SECRET, BYJG_DOCS_PUBLIC_URL
docker compose up -d                       # ollama + mcp
docker compose --profile tunnel up -d      # ... plus a Cloudflare tunnel

claude mcp add --transport http --scope user byjg-docs \
  https://mcp.example.com/mcp \
  --header "Authorization: Bearer $BYJG_DOCS_AUTH_TOKEN"
```

On the same machine as the stack, skip the token and the network: `docker exec`
runs a stdio server inside the `mcp` container, sharing its index and Ollama:

```bash
claude mcp add --scope user byjg-docs -- \
  docker exec -i -e BYJG_DOCS_TRANSPORT=stdio mcpserver-mcp-1 byjg-docs-mcp
```

See [Infrastructure](docs/infrastructure.md) for the compose stack and
[Running the server](docs/usage.md#running-the-server) for what each mode
exposes.

## What it does

**Hybrid retrieval.** Vector similarity answers natural-language questions;
BM25 catches exact symbol names like `TableAttribute`, which pure vector search
is notably bad at. Results are fused with Reciprocal Rank Fusion.

**Heading-aware chunking.** Passages are split on markdown headings rather than
fixed-size windows, so each one is a coherent section that arrives with its
heading path and public URL attached.

**GitHub is the source of truth.** Each refresh clones the docs repository into
a temporary directory and discards it afterwards — there is no working copy to
initialise, keep in sync or back up. Indexing stays incremental anyway, because
it keys on content hashes a fresh clone reproduces exactly: a rebuild after an
unrelated push re-embeds nothing.

**One file.** The whole index is a 24 MB SQLite database -- `sqlite-vec` for
vectors, FTS5 for keywords. At this corpus size a brute-force scan takes
milliseconds, so a dedicated vector service would be infrastructure without a
payoff. See [Architecture](docs/architecture.md#the-shape-of-the-problem).

**Swappable backends.** Storage sits behind a `VectorStore` interface and
embedding behind an `Embedder` interface; nothing outside `stores/` and
`embeddings/` names a concrete backend. See
[Swapping the store](docs/architecture.md#swapping-the-store).

## Tools

| Tool | Purpose |
|---|---|
| `search_docs(query, limit, category, project)` | Ranked passages, each with its public URL |
| `get_document(source_path)` | Full markdown of one page |
| `list_projects()` | Inventory of what is indexed |

## Tests

```bash
uv run pytest
```

73 tests, fully offline -- a deterministic hash-based embedder stands in for
Ollama, so no model server is needed.
