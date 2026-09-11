# Configuration

Every setting is an environment variable prefixed `BYJG_DOCS_`, read from a
single `.env` in the project root. Copy [.env.example](../../.env.example) to
`.env`; it is annotated and covers every setting.

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
| `BYJG_DOCS_AUTH_TOKEN` | the bearer token MCP clients send |
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

The server **refuses to start** over HTTP on a non-loopback address without
`BYJG_DOCS_AUTH_TOKEN`, so it cannot be exposed unauthenticated by accident.

## All settings

### Corpus

| Variable | Default | Purpose |
|---|---|---|
| `BYJG_DOCS_REPO_URL` | `https://github.com/byjg/byjg.github.io` | Source of truth, cloned on each refresh |
| `BYJG_DOCS_GIT_BRANCH` | `master` | Branch to clone |
| `BYJG_DOCS_DOCS_SUBDIR` | `docs` | Folder inside the repository holding the documentation |
| `BYJG_DOCS_DOCS_ROOT` | *(unset)* | Index this tree instead of cloning -- [development only](local.md#indexing-a-local-checkout) |
| `BYJG_DOCS_SITE_URL` | `https://opensource.byjg.com` | Base of the public URLs attached to results |
| `BYJG_DOCS_DOCS_ROUTE` | `docs` | Path segment of the docs on the site |

### Server

| Variable | Default | Purpose |
|---|---|---|
| `BYJG_DOCS_TRANSPORT` | `stdio` | `stdio` or `http` |
| `BYJG_DOCS_HOST` | `127.0.0.1` | Interface the HTTP server listens on |
| `BYJG_DOCS_PORT` | `2954` | Port the HTTP server listens on |
| `BYJG_DOCS_AUTH_TOKEN` | *(empty)* | Bearer token; required off loopback |
| `BYJG_DOCS_PUBLIC_URL` | `http://127.0.0.1:2954` | The address clients use; must match it exactly |
| `BYJG_DOCS_WEBHOOK_SECRET` | *(empty)* | Enables `/webhook/github`; empty disables it |

`BYJG_DOCS_PUBLIC_URL` must match what clients type. MCP advertises the
protected resource under this URL, so a mismatch fails authentication even
with the right token.

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

Everything in `.env` reaches the container, **except** five values that
describe the inside of it:

| Variable | Forced to | Why |
|---|---|---|
| `BYJG_DOCS_TRANSPORT` | `http` | stdio has no server for the tunnel to reach |
| `BYJG_DOCS_HOST` | `0.0.0.0` | must accept connections from the compose network |
| `BYJG_DOCS_PORT` | `8080` | the port inside the container; the host side is `BYJG_DOCS_LOCAL_PORT` |
| `BYJG_DOCS_INDEX_PATH` | `/data/index/byjg-docs.db` | the mounted volume |
| `BYJG_DOCS_OLLAMA_URL` | `http://ollama:11434` | the service name, not localhost |

plus `BYJG_DOCS_DOCS_ROOT`, cleared because a host path means nothing inside
the container -- the repository is cloned instead.

Compose also refuses to start while `BYJG_DOCS_AUTH_TOKEN` or
`BYJG_DOCS_PUBLIC_URL` is empty, rather than booting something
half-configured.
