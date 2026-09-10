# Usage

## Installing

```bash
cd ~/Projects/ByJG/McpServer
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

One `.env` in the project root serves both ways of running. The defaults
already point at `byjg/byjg.github.io`, so for indexing from the CLI there is
nothing to fill in. Deploying as a service needs two generated secrets --
see [Configuration](#configuration).

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

To index a checkout you are editing locally, without cloning, set
`BYJG_DOCS_DOCS_ROOT` to that tree. That is a development convenience -- leave
it unset in any deployment so GitHub remains the only source.

```bash
uv run byjg-docs-index build --force    # re-embed everything, ignore hashes
uv run byjg-docs-index build --quiet    # summary only, no per-file output
```

Use `--force` after changing the embedding model or the chunking rules -- both
invalidate stored vectors in ways the content hash cannot detect.

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

## Running the server

Two settings decide what the server exposes. Getting these wrong is the usual
reason an endpoint appears to be missing:

| `TRANSPORT` | `WEBHOOK_SECRET` | MCP tools | `/healthz` | `/webhook/github` |
|---|---|---|---|---|
| `stdio` | *(any)* | yes | no | no |
| `http` | empty | yes | yes | no |
| `http` | set | yes | yes | yes |

`stdio` has no HTTP server at all, so it can serve neither the health check nor
the webhook. The webhook endpoint is only registered when a secret exists --
there is no such thing as an unauthenticated webhook here.

### Locally, over stdio

The default: the MCP client spawns the process and talks over pipes. Nothing to
start yourself, and no port is opened.

```bash
claude mcp add byjg-docs -- \
  uv --directory ~/Projects/ByJG/McpServer run byjg-docs-mcp
```

### Through the compose stack, over stdio

When the compose stack is running (see [infrastructure.md](infrastructure.md)),
a client on the same machine can use it with no token and no index on the host:
`docker exec` starts a stdio server inside the running `mcp` container.

```bash
claude mcp add --scope user byjg-docs -- \
  docker exec -i -e BYJG_DOCS_TRANSPORT=stdio mcpserver-mcp-1 byjg-docs-mcp
```

For a client configured through a form rather than a command line:

| Field | Value |
|---|---|
| Command | `/usr/bin/docker` -- the full path, since GUI apps often lack your shell's `PATH` |
| Arguments | `exec -i -e BYJG_DOCS_TRANSPORT=stdio mcpserver-mcp-1 byjg-docs-mcp` |

- `-i` keeps stdin open; the protocol runs over it. Do not add `-t` -- a TTY
  mangles the stream.
- `BYJG_DOCS_TRANSPORT=stdio` overrides the `http` the container runs with.
- The process shares the container's index volume and reaches Ollama at
  `ollama:11434`, so nothing is built on the host. It never triggers a reindex;
  the long-running HTTP server keeps the index fresh.
- No bearer token: stdio does not pass through HTTP authentication, and anyone
  who can run `docker exec` already controls the container.
- The stack must be up. `mcpserver-mcp-1` comes from the project directory
  name -- if you move or rename it, check `docker compose ps`.

Run by hand, it logs one line and then waits silently for an MCP client on
stdin -- that is correct, not a hang. To search from the terminal, run the CLI
in the container instead:

```bash
docker exec mcpserver-mcp-1 byjg-docs-index search "soft delete" -n 3
```

### Over HTTP, with the webhook

This is what you want if GitHub should trigger reindexing. The easy path is the
compose stack, which sets all of this for you --
see [infrastructure.md](infrastructure.md):

```bash
docker compose up -d
```

To run it directly instead, set these in `.env` (or export them):

```bash
BYJG_DOCS_TRANSPORT=http                     # enables the HTTP server
BYJG_DOCS_WEBHOOK_SECRET=<openssl rand -hex 32>   # enables /webhook/github
BYJG_DOCS_AUTH_TOKEN=<openssl rand -hex 32>       # required off loopback
BYJG_DOCS_PUBLIC_URL=https://mcp.example.com      # must match what clients use
```

```bash
uv run byjg-docs-mcp
```

The two generated values must differ: one authenticates clients, the other
verifies GitHub's signatures.

Confirm both endpoints came up:

```bash
curl -s http://127.0.0.1:2954/healthz
# {"status":"ok","reindexing":false,"documents":544,"chunks":4136}

curl -s -o /dev/null -w '%{http_code}\n' -X POST http://127.0.0.1:2954/webhook/github -d '{}'
# 401  -- registered, and rejecting an unsigned request
# 404  -- not registered: BYJG_DOCS_WEBHOOK_SECRET is empty
```

The server **refuses to start** on a non-loopback address without
`BYJG_DOCS_AUTH_TOKEN`, so it cannot be exposed unauthenticated by accident.

### Connecting a client through the tunnel

Point `claude mcp add` at the tunnel hostname with `/mcp` on the end, and pass
the bearer token as a header:

```bash
claude mcp add --transport http --scope user byjg-docs \
  https://mcp-docs.byjg.com/mcp \
  --header "Authorization: Bearer $BYJG_DOCS_AUTH_TOKEN"
```

**Use `--scope user`.** The default scope is `local`, which registers the
server only for the directory you happened to run the command in -- for a
documentation server you want everywhere, that is almost never what you meant.

Verify it connected:

```bash
claude mcp list
# byjg-docs: https://mcp-docs.byjg.com/mcp (HTTP) - ✔ Connected
```

If it says failed rather than connected:

| Symptom | Cause |
|---|---|
| `401` | Token missing or does not match `BYJG_DOCS_AUTH_TOKEN` |
| `404` | URL is missing the `/mcp` path |
| connection refused / timeout | Tunnel is down, or `cloudflared` cannot reach `mcp:8080` |
| connects but auth is rejected | `BYJG_DOCS_PUBLIC_URL` does not match the hostname the client uses |

To remove it: `claude mcp remove byjg-docs -s user`.

## The MCP tools

### `search_docs(query, limit, category, project)`

The main entry point. Returns ranked passages, each with its source path,
public URL and project.

- `query` -- natural language or an exact symbol name; both work
- `limit` -- defaults to 8, capped at 25
- `category` -- `php`, `devops`, `js`, `helm`, ...
- `project` -- `micro-orm`, `restserver`, `docker-easy-haproxy`, ...

### `get_document(source_path)`

Full markdown of one page, addressed by the `source` a search result reports
(`php/micro-orm/active-record.md`). Use when a hit is relevant but truncated.

### `list_projects()`

Inventory grouped by category and project, with counts. Lets the model discover
what exists before searching.

## Configuration

Every setting is an environment variable prefixed `BYJG_DOCS_`, read from a
single `.env` in the project root. Copy [.env.example](../.env.example) to
`.env`; it is annotated and covers every setting.

**Two values need generating**, each from its own run of `openssl rand -hex 32`,
and they must be **different**:

| Variable | What it is |
|---|---|
| `BYJG_DOCS_AUTH_TOKEN` | the bearer token MCP clients send |
| `BYJG_DOCS_WEBHOOK_SECRET` | the secret GitHub signs webhook deliveries with |

Reusing one value for both means leaking either compromises the other.

`CLOUDFLARE_TUNNEL_TOKEN` is *not* generated -- it comes from the Cloudflare
dashboard, and is only needed if you run the tunnel inside the stack.

### How .env is read

- **Running directly**: the app loads `.env` itself at startup.
- **Under docker compose**: compose passes the whole file into the container,
  then overrides five values that describe the inside of it (`TRANSPORT`,
  `HOST`, `PORT`, `INDEX_PATH`, `OLLAMA_URL`) and clears `DOCS_ROOT`, since a
  host path means nothing in there. See
  [What compose overrides](infrastructure.md#what-compose-overrides).

Everything else takes effect in both modes.

### Settings you are most likely to change

| Variable | Default | Purpose |
|---|---|---|
| `BYJG_DOCS_REPO_URL` | `github.com/byjg/byjg.github.io` | Source of truth |
| `BYJG_DOCS_GIT_BRANCH` | `master` | Branch to clone |
| `BYJG_DOCS_DOCS_ROOT` | *(unset)* | Index this tree instead of cloning (dev only) |
| `BYJG_DOCS_INDEX_PATH` | `./byjg-docs.db` | Where the index lives |
| `BYJG_DOCS_TRANSPORT` | `stdio` | `stdio` or `http` |
| `BYJG_DOCS_AUTH_TOKEN` | *(empty)* | Bearer token; required off loopback |
| `BYJG_DOCS_DEFAULT_LIMIT` | `8` | Results when the caller does not say |
| `BYJG_DOCS_EMBEDDING_MODEL` | `nomic-embed-text` | Changing it needs `--force` |

## Tests

```bash
uv run pytest
```

73 tests, fully offline -- `tests/conftest.py` supplies a deterministic
hash-based embedder, so no Ollama instance is needed.

## Troubleshooting

**`Ollama does not have model 'nomic-embed-text'`**
Run `ollama pull nomic-embed-text`.

**Search returns nothing on a fresh install**
The index is empty. Run `byjg-docs-index build`; confirm with `stats`.

**Results look stale after editing docs**
`build` indexes what is on GitHub, not your local edits -- push them first, or
point `BYJG_DOCS_DOCS_ROOT` at your checkout to index it in place. If you
changed the *model* or the chunker instead, run `build --force`.

**`query vector has N dims, index has M`**
The embedding model changed under an existing index. Rebuild with `--force`,
or delete the `.db` and build again.

**Server exits with "Refusing to serve on a non-loopback address"**
Set `BYJG_DOCS_AUTH_TOKEN`, or bind `127.0.0.1`.

**`/webhook/github` returns 404**
The endpoint is only registered when `BYJG_DOCS_WEBHOOK_SECRET` is set and the
transport is `http`. Under `stdio` there is no HTTP server at all. See the
table in [Running the server](#running-the-server).

**`/healthz` returns 404**
The transport is `stdio`. Health and webhook endpoints exist only over HTTP.

**GitHub shows the delivery as 401**
The secret configured on the webhook does not match
`BYJG_DOCS_WEBHOOK_SECRET`. Unsigned and wrongly-signed requests are both
rejected by design.

**Webhook returns 202 but nothing reindexes**
Check `docker compose logs mcp`. The likely causes are a push that touched no
`docs/` path (ignored on purpose), or the `git pull` failing — the log line
says which.
