# Running locally

Run the server from source on your own machine, without Docker. This is the
setup for working on the code: build the index, query it from the terminal,
and let an MCP client spawn the server over stdio.

To host a server other machines connect to, see [Self-hosting](self-hosting.md)
instead.

## Installing

```bash
git clone git@github.com:byjg/mcpserver-byjg-docs.git
cd mcpserver-byjg-docs
uv sync
```

The embedder needs Ollama with the embedding model:

```bash
ollama serve &                  # if not already running
ollama pull nomic-embed-text    # ~274 MB
```

```bash
cp .env.example .env
```

The defaults already point at `byjg/byjg.github.io` and at a local Ollama, so
for local use there is nothing to fill in. The secrets in `.env` only matter
when [self-hosting](self-hosting.md). Every setting is described in
[Configuration](configuration.md).

## Building the index

```bash
uv run byjg-docs-index build
```

This clones the documentation repository from GitHub into a temporary
directory, indexes it, and deletes the checkout. GitHub is the source of truth;
no working copy is kept.

```
scanned=549 indexed=544 unchanged=0 empty=5 deleted=0 chunks=4136
```

Reading the summary:

| Field | Meaning |
|---|---|
| `scanned` | Markdown files found |
| `indexed` | Embedded and written this run |
| `unchanged` | Skipped -- content hash matched what was stored |
| `empty` | Skipped -- body under 50 chars (a "TBD" stub) |
| `deleted` | Removed -- no longer on disk |
| `chunks` | Passages written this run |

Runs are **incremental by default**, and stay incremental despite the fresh
clone: the indexer keys on the SHA-256 of each file's content, which a new
clone reproduces exactly. A first build takes ~60s; a build where nothing
changed takes ~25s, essentially all of it the clone.

```bash
uv run byjg-docs-index build --force    # re-embed everything, ignore hashes
uv run byjg-docs-index build --quiet    # summary only, no per-file output
```

Use `--force` after changing the embedding model or the chunking rules -- both
invalidate stored vectors in ways the content hash cannot detect.

### Indexing a local checkout

To index documentation you are editing, without pushing it first, point
`BYJG_DOCS_DOCS_ROOT` at your checkout of `byjg.github.io/docs`. Nothing is
cloned; that tree is indexed in place. This is a development convenience --
leave it unset in any deployment so GitHub remains the only source.

## Searching from the terminal

Useful for sanity-checking retrieval without an LLM in the loop.

```bash
uv run byjg-docs-index search "how do I map a table to a class"
uv run byjg-docs-index search "TableAttribute" -n 3
uv run byjg-docs-index search "soft delete" --category php --project micro-orm
```

Each hit shows where it came from in both rankers:

```
[0.0325] (vec#1 bm25#2) Soft Deletes > How to Enable Soft Delete
  https://opensource.byjg.com/docs/php/micro-orm/softdelete
  The DeletedAt trait adds support for the soft delete pattern...
```

`vec#1 bm25#2` means the vector ranker put it first and BM25 second. A `-`
means that ranker did not return it at all -- normal, and the reason both run.

## Inspecting what is indexed

```bash
uv run byjg-docs-index stats
```

```
{'documents': 544, 'chunks': 4136}
  php/micro-orm: 24 docs, 289 chunks
  devops/nimbus: 41 docs, 256 chunks
  ...
```

## Connecting a client over stdio

With stdio the MCP client spawns the server process and talks to it over
pipes. There is nothing to start yourself, no port is opened, and no token is
needed.

From the repository root, register it with Claude Code:

```bash
claude mcp add --scope user byjg-docs-dev -- \
  uv --directory "$PWD" run byjg-docs-mcp
```

`$PWD` expands to the absolute path of your checkout when you run the command,
which is what the client needs to find it later from any directory. The name
`byjg-docs-dev` keeps it apart from the public server, if you have both.

For a client configured through a form or a JSON file:

| Field | Value |
|---|---|
| Command | `uv` -- or its full path (`which uv`), since GUI apps often lack your shell's `PATH` |
| Arguments | `--directory /path/to/mcpserver-byjg-docs run byjg-docs-mcp` |

Run by hand, `uv run byjg-docs-mcp` logs one line and then waits silently for
an MCP client on stdin -- that is correct, not a hang.

## Running the HTTP server from source

To try the HTTP endpoints (`/mcp`, `/healthz`, `/webhook/github`) without
Docker, override the transport. On `127.0.0.1` no token is required:

```bash
BYJG_DOCS_TRANSPORT=http uv run byjg-docs-mcp
```

```bash
curl -s http://127.0.0.1:2954/healthz
# {"status":"ok","reindexing":false,"documents":544,"chunks":4136}
```

The webhook endpoint is only registered when `BYJG_DOCS_WEBHOOK_SECRET` is
set. Which settings enable which endpoint is in
[Transport and endpoints](configuration.md#transport-and-endpoints); how the
webhook behaves is in [Keeping the index fresh](self-hosting.md#keeping-the-index-fresh).
