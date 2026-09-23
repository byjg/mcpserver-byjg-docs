---
sidebar_position: 4
---

# Configuration

Every setting is an environment variable prefixed `BYJG_DOCS_`, read from a
single `.env` in the project root. Copy
[.env.example](https://github.com/byjg/mcpserver-byjg-docs/blob/main/.env.example)
to `.env`; it is annotated and covers every setting.

## How .env is read

- **Running from source**: the app loads `.env` itself at startup. A variable
  exported in the shell wins over the same one in `.env`.
- **Under Docker Compose**: compose passes the whole file into the container,
  then overrides the values that describe the inside of it -- see
  [What compose overrides](#what-compose-overrides).

Everything else takes effect in both modes: change `BYJG_DOCS_GIT_BRANCH` and
it clones that branch; change `BYJG_DOCS_DEFAULT_LIMIT` and searches return
that many results.

## Secrets

Only needed when [self-hosting](self-hosting.md). Two values need generating,
each from its own run of `openssl rand -hex 32`, and they must be
**different**:

| Variable | What it is |
|---|---|
| `BYJG_DOCS_AUTH_TOKEN` | the bearer token MCP clients send (only with `BYJG_DOCS_AUTH_TYPE=bearer`) |
| `BYJG_DOCS_WEBHOOK_SECRET` | the secret GitHub signs webhook deliveries with |

Reusing one value for both means leaking either compromises the other.

`CLOUDFLARE_TUNNEL_TOKEN` is *not* generated -- it comes from the Cloudflare
dashboard, and is only needed if you run the tunnel inside the stack.

## Transport and endpoints

Two settings decide what the server exposes. Getting these wrong is the usual
reason an endpoint appears to be missing:

| `TRANSPORT` | `WEBHOOK_SECRET` | MCP tools | `/healthz` | `/webhook/github` |
|---|---|---|---|---|
| `stdio` | *(any)* | yes | no | no |
| `http` | empty | yes (at `/mcp`) | yes | no |
| `http` | set | yes (at `/mcp`) | yes | yes |

`stdio` has no HTTP server at all, so it can serve neither the health check nor
the webhook. The webhook endpoint is only registered when a secret exists --
there is no such thing as an unauthenticated webhook here.

Who may call the MCP endpoint is a separate question, answered by
`BYJG_DOCS_AUTH_TYPE` -- see [Authentication](self-hosting.md#authentication).
The server **refuses to start** when that is `bearer` and no token is set, and
warns on every start when it is `none` on a non-loopback address.

## All settings

### Corpus

| Variable | Default | Purpose |
|---|---|---|
| `BYJG_DOCS_REPO_URL` | `https://github.com/byjg/byjg.github.io` | Source of truth, cloned on each refresh |
| `BYJG_DOCS_GIT_BRANCH` | `master` | Branch to clone |
| `BYJG_DOCS_SOURCES` | docs + blog | Folders of the repository to index, as JSON -- see [Sources](#sources) |
| `BYJG_DOCS_DOCS_ROOT` | *(unset)* | Index this tree instead of cloning -- [development only](local.md#indexing-a-local-checkout) |
| `BYJG_DOCS_SITE_URL` | `https://opensource.byjg.com` | Base of the public URLs attached to results |
| `BYJG_DOCS_DOCS_SUBDIR` | *(unset)* | **Deprecated.** Pins the single indexed folder; ignored when `BYJG_DOCS_SOURCES` is set |
| `BYJG_DOCS_DOCS_ROUTE` | *(unset)* | **Deprecated.** Route for that folder |

### Sources

A source is one folder of the site repository. The default is the reference
documentation and the blog:

```json
[
  {"name": "docs", "subdir": "docs", "route": "docs"},
  {"name": "blog", "subdir": "blog", "route": "blog", "category": "blog"}
]
```

| Key | Purpose |
|---|---|
| `name` | Prefixes every `source_path` from the folder (`docs/php/micro-orm/active-record.md`). It is what keeps two folders from colliding, and what lets a refresh delete only its own documents |
| `subdir` | Folder in the repository. `""` indexes the repository root |
| `route` | Path segment the site publishes it under, so a hit cites the right URL: `/docs/...` or `/blog/...` |
| `category` | Forces the category instead of deriving it from the layout. The docs nest as `category/project/page.md`; the blog is flat, so its posts would otherwise have nothing to filter on |

Both folders land in **one index**, so a single `search_docs` call covers both,
and `category: blog` narrows to the blog. One clone per refresh serves every
source.

URLs follow the site, including the two shapes Docusaurus gives a blog post: a
post that declares a `slug` is cited at `/blog/<slug>`, and one that does not at
`/blog/<YYYY>/<MM>/<DD>/<name>`, taken from the dated file or folder name. The
reference documentation keeps citing its path.

Names must be unique and usable as a path segment -- two sources sharing a name
would share a prefix and prune each other's documents, so that configuration is
refused at startup, as is an empty list.

Renaming a source, or removing one, leaves its documents behind: a refresh only
prunes within a prefix it owns. Nothing is rebuilt or deleted automatically --
the server logs a warning naming them, and you either restore the source or run
`byjg-docs-index build --force`.

### Server

| Variable | Default | Purpose |
|---|---|---|
| `BYJG_DOCS_TRANSPORT` | `stdio` | `stdio` or `http` |
| `BYJG_DOCS_HOST` | `127.0.0.1` | Interface the HTTP server listens on |
| `BYJG_DOCS_PORT` | `2954` | Port the HTTP server listens on |
| `BYJG_DOCS_AUTH_TYPE` | `none` | `none` or `bearer` -- see [Authentication](self-hosting.md#authentication). Compose defaults it to `bearer` |
| `BYJG_DOCS_AUTH_TOKEN` | *(empty)* | The token `bearer` requires; ignored by `none` |
| `BYJG_DOCS_PUBLIC_URL` | `http://127.0.0.1:2954` | The address clients use; must match it exactly |
| `BYJG_DOCS_WEBHOOK_SECRET` | *(empty)* | Enables `/webhook/github`; empty disables it |
| `BYJG_DOCS_QUERY_LOG` | *(empty)* | File that records every tool call -- see [Query log](self-hosting.md#query-log); empty disables it |

`BYJG_DOCS_PUBLIC_URL` must match what clients type. With `bearer`, MCP
advertises the protected resource under this URL, so a mismatch fails
authentication even with the right token. With `none` it is unused.

Authentication belongs to the HTTP transport: under `stdio` both settings are
ignored, because the client spawned the process itself.

### Storage, embeddings and retrieval

| Variable | Default | Purpose |
|---|---|---|
| `BYJG_DOCS_STORE_BACKEND` | `sqlite` | Registered `VectorStore` implementation |
| `BYJG_DOCS_INDEX_PATH` | `./byjg-docs.db` | File path for sqlite; a DSN for a server-backed store |
| `BYJG_DOCS_EMBEDDER_BACKEND` | `ollama` | Registered `Embedder` implementation |
| `BYJG_DOCS_EMBEDDING_MODEL` | `nomic-embed-text` | Changing it needs `build --force` |
| `BYJG_DOCS_OLLAMA_URL` | `http://localhost:11434` | Where Ollama answers |
| `BYJG_DOCS_DEFAULT_LIMIT` | `8` | Results when the caller does not say |
| `BYJG_DOCS_MAX_LIMIT` | `25` | Upper bound on `limit` |

### Docker Compose only

Read by `docker-compose.yml`, not by the app:

| Variable | Default | Purpose |
|---|---|---|
| `BYJG_DOCS_BIND_ADDR` | `0.0.0.0` | Host interface the port is published on -- see [Network exposure](self-hosting.md#network-exposure) |
| `BYJG_DOCS_LOCAL_PORT` | `2954` | Host port mapped to the container's `8080` |
| `CLOUDFLARE_TUNNEL_TOKEN` | *(empty)* | Only with `--profile tunnel` |

## What compose overrides

Everything in `.env` reaches the container, **except** six values that
describe the inside of it:

| Variable | Forced to | Why |
|---|---|---|
| `BYJG_DOCS_TRANSPORT` | `http` | stdio has no server for the tunnel to reach |
| `BYJG_DOCS_HOST` | `0.0.0.0` | must accept connections from the compose network |
| `BYJG_DOCS_PORT` | `8080` | the port inside the container; the host side is `BYJG_DOCS_LOCAL_PORT` |
| `BYJG_DOCS_INDEX_PATH` | `/data/index/byjg-docs.db` | the mounted volume |
| `BYJG_DOCS_OLLAMA_URL` | `http://ollama:11434` | the service name, not localhost |
| `BYJG_DOCS_QUERY_LOG` | `/data/logs/queries.jsonl` | the `logs` volume; the query log is on in every deployment |

plus `BYJG_DOCS_DOCS_ROOT`, cleared because a host path means nothing inside
the container -- the repository is cloned instead.

Compose also *defaults* `BYJG_DOCS_AUTH_TYPE` to `bearer` (a deployment is
reachable from outside the host) and refuses to start while
`BYJG_DOCS_PUBLIC_URL` is empty, rather than booting something
half-configured. The missing-token check lives in the app, so it applies
however you run it.
