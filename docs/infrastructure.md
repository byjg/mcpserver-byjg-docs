# Infrastructure

## Topology

Four containers. Ollama and the MCP server talk over the compose network;
`cloudflared` reaches the MCP server the same way and is the only thing exposed
to the internet.

![Cloudflare edge reaches cloudflared through an outbound tunnel; cloudflared reaches the MCP server, which talks to Ollama. Three Docker volumes hold the model, the repo and the index.](img/infrastructure.svg)

The MCP server is published on `127.0.0.1:2954` so a local client can reach it
without going out to the internet and back. Ollama is not published at all.

## The compose stack

`docker-compose.yml` defines four services:

| Service | What it does | Restarts |
|---|---|---|
| `ollama` | Serves embeddings on `:11434`. Reserves the host GPU. Not published -- only `mcp` reaches it, over the compose network. | always |
| `ollama-init` | Pulls `nomic-embed-text` into the shared volume, then exits. `mcp` waits for it to *complete successfully*. | never |
| `mcp` | The MCP server. Publishes `127.0.0.1:2954` for local clients; the tunnel reaches it internally. | always |
| `cloudflared` | Dials out to Cloudflare and forwards the public hostname to `mcp:8080`. Opt-in: only starts with `--profile tunnel`. | always |

and three named volumes:

| Volume | Holds | Safe to delete? |
|---|---|---|
| `ollama` | Model weights (~274 MB) | Yes -- `ollama-init` re-pulls |
| `index` | `byjg-docs.db` (24 MB) | Yes -- rebuilt in ~60s |

There is no volume for the documentation: each refresh clones it from GitHub
into a temporary directory and deletes the checkout afterwards. Nothing here
holds state that is not reproducible, which is why there is no backup
procedure.

### Running a subset

The services are independent enough to run partially. Without a tunnel token
you can still run everything else and reach it on loopback:

```bash
docker compose up -d ollama mcp      # skip cloudflared
```

To rebuild after changing the code:

```bash
docker compose up -d --build mcp
```

## Configuration

There is **one** file: `.env` in the project root, copied from `.env.example`.
It serves both ways of running -- compose passes the whole file into the
container, and the app reads it directly when you run it on the host.

### What you must fill in

```bash
cp .env.example .env
openssl rand -hex 32     # paste into BYJG_DOCS_AUTH_TOKEN
openssl rand -hex 32     # paste into BYJG_DOCS_WEBHOOK_SECRET
```

| Variable | Value | Required? |
|---|---|---|
| `BYJG_DOCS_AUTH_TOKEN` | `openssl rand -hex 32` | Yes -- compose refuses to start without it |
| `BYJG_DOCS_PUBLIC_URL` | the address clients actually use | Yes -- same reason |
| `BYJG_DOCS_WEBHOOK_SECRET` | a *second*, different `openssl rand -hex 32` | Only for the webhook; empty disables it |
| `CLOUDFLARE_TUNNEL_TOKEN` | from Zero Trust > Networks > Tunnels | Only with `--profile tunnel` |

The two generated values must **differ** -- one authenticates MCP clients, the
other verifies GitHub's signatures. Reusing one for both means a leak of either
compromises the other.

`BYJG_DOCS_PUBLIC_URL` must match what clients type. MCP advertises the
protected resource under this URL, so a mismatch fails authentication even with
the right token. Use the tunnel hostname if you have one, otherwise this
machine's address (e.g. `http://<host-ip>:2954`).

### What compose overrides

Everything in `.env` reaches the container, **except** five values that
describe the inside of it:

| Variable | Forced to | Why |
|---|---|---|
| `BYJG_DOCS_TRANSPORT` | `http` | stdio has no server for the tunnel to reach |
| `BYJG_DOCS_HOST` | `0.0.0.0` | must accept connections from the compose network |
| `BYJG_DOCS_PORT` | `8080` | the port inside the container; the host side is `BYJG_DOCS_LOCAL_PORT` (default `2954`) |
| `BYJG_DOCS_INDEX_PATH` | `/data/index/byjg-docs.db` | the mounted volume |
| `BYJG_DOCS_OLLAMA_URL` | `http://ollama:11434` | the service name, not localhost |

plus `BYJG_DOCS_DOCS_ROOT`, cleared because a host path means nothing inside
the container -- the repository is cloned instead.

Everything else you set takes effect: change `BYJG_DOCS_GIT_BRANCH` and it
clones that branch; change `BYJG_DOCS_DEFAULT_LIMIT` and searches return that
many results.

## Deploying

```bash
docker compose up -d
```

That starts `ollama`, `ollama-init` and `mcp`. The tunnel is **opt-in**:

```bash
docker compose --profile tunnel up -d     # adds cloudflared
```

Skip the profile if you run `cloudflared` on the host, or reach the server over
the LAN only; `CLOUDFLARE_TUNNEL_TOKEN` can stay empty in that case.

Compose refuses to start if a required secret is unset, rather than booting
something half-configured:

```
error while interpolating services.mcp.environment.BYJG_DOCS_AUTH_TOKEN:
required variable BYJG_DOCS_AUTH_TOKEN is missing a value: set it in .env
```

### First boot

Nothing to initialise. The `mcp` container starts with an empty index volume,
notices it is empty, clones `byjg.github.io` into a temporary directory, builds
the index in the background, and serves `/healthz` throughout:

```bash
curl -s http://127.0.0.1:2954/healthz
# {"status":"ok","reindexing":true,"documents":327,"chunks":2361}
# {"status":"ok","reindexing":false,"documents":544,"chunks":4136}
```

Measured on an RTX 2000 Ada: **~90s**, of which ~22s is the clone.

### Startup ordering

`ollama-init` pulls the embedding model into the shared volume and exits;
`mcp` waits for it to complete successfully. Without that gate the server would
come up before the model existed and fail its first embedding call.

## GPU

The `ollama` service reserves the host GPU. This needs
`nvidia-container-toolkit` on the host -- the NVIDIA driver alone is not
enough, because Docker needs a runtime that can pass the device through.

Verify before deploying:

```bash
docker run --rm --gpus all nvidia/cuda:12.4.0-base-ubuntu22.04 nvidia-smi
```

If that fails with `failed to discover GPU vendor from CDI`, install the
toolkit ([NVIDIA's guide](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html)):

```bash
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \
  | sudo gpg --yes --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
  | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
  | sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
sudo apt-get update && sudo apt-get install -y nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker
```

### Does it need a GPU?

No. It changes indexing cost, not whether it works:

| | Embedding the full corpus | Single query embedding |
|---|---|---|
| GPU (RTX 2000 Ada) | ~40s | ~15ms |
| CPU only | ~30min | ~100-150ms |

(Add ~22s of clone to get the end-to-end refresh time.)

Query latency is what a user feels, and it survives CPU fine. The 45x gap only
bites on a full rebuild. If you index rarely, drop the `deploy.resources`
block from the `ollama` service and run on CPU.

### Memory

`nomic-embed-text` is 137M parameters -- **595 MB** resident. The index is
24 MB. The whole stack fits comfortably in 2 GB.

## Cloudflare Tunnel

The tunnel dials **out** from the host, so no inbound port is opened and the
host needs no public IP. In Zero Trust > Networks > Tunnels, create a tunnel,
copy its token into `CLOUDFLARE_TUNNEL_TOKEN`, and map a public hostname to
`http://mcp:8080`. Then start it with `docker compose --profile tunnel up -d`;
without the profile the service is not created at all.

Set `BYJG_DOCS_PUBLIC_URL` to that hostname. MCP's auth model advertises the
protected resource under this URL, so a mismatch breaks client authentication.

## Network exposure

Three things are easy to confuse. They are independent:

| Setting | Controls | Value |
|---|---|---|
| `BYJG_DOCS_HOST` | Where the process listens *inside* the container | `0.0.0.0` — must be, or `cloudflared` could not reach it |
| `ports:` in compose | Which host interface publishes the port | `BYJG_DOCS_BIND_ADDR`, default `0.0.0.0` |
| Cloudflare Tunnel | Access from outside the network | Reaches `mcp:8080` over the compose network |

**The tunnel does not use the published port.** `cloudflared` resolves `mcp`
on the compose network, so the tunnel works even with `ports:` removed
entirely. Publishing is purely for clients on this machine or the LAN.

The default publishes on `0.0.0.0`, so other machines on your network connect
directly by IP — faster than going out to Cloudflare and back, and it keeps
working if your internet does not:

```bash
curl -s http://<host-ip>:2954/healthz
```

Set `BYJG_DOCS_BIND_ADDR=127.0.0.1` to restrict it to this machine.

### What actually protects the port

The bearer token, and only the bearer token.

**A host firewall does not.** Docker publishes ports by writing iptables rules
in its own chain, which is evaluated before ufw's. On a machine with ufw
active and denying incoming traffic, a published port is still reachable from
the LAN — verified, not assumed. So:

- Treat `BYJG_DOCS_AUTH_TOKEN` as the only barrier, and generate it with
  `openssl rand -hex 32` rather than picking something memorable.
- Check what can route to this host. If it has a public IP, or a forwarded
  port on the router, `0.0.0.0` means the internet, not just your LAN.
- `/healthz` answers without a token by design, exposing only document and
  chunk counts. The MCP endpoint itself returns 401 without a valid token.

If you want the firewall to be meaningful here, bind to `127.0.0.1` and let
the tunnel be the only way in.

## Authentication

Two independent layers:

1. **Cloudflare Access** (optional, at the edge) -- policies before a request
   ever reaches the host.
2. **Bearer token** (in the app) -- `StaticTokenVerifier`, compared in constant
   time so a wrong token cannot be recovered by timing.

The server refuses to bind a non-loopback address without a token, so the
second layer cannot be forgotten.

This is deliberately minimal: one pre-shared token for a personal, read-only
service. More than one consumer, or per-user revocation, wants real OAuth via
the SDK's `auth_server_provider`.

## Keeping the index fresh

`POST /webhook/github` reindexes when documentation changes. The compose stack
enables it automatically, because it sets both variables the endpoint needs
(`BYJG_DOCS_TRANSPORT=http` in the image, `BYJG_DOCS_WEBHOOK_SECRET` from your
`.env`). Running the server by hand instead? See
[Over HTTP, with the webhook](usage.md#over-http-with-the-webhook).

Configure a webhook on `byjg/byjg.github.io`:

| Field | Value |
|---|---|
| Payload URL | `https://<your-hostname>/webhook/github` |
| Content type | `application/json` |
| Secret | your `BYJG_DOCS_WEBHOOK_SECRET` |
| Events | Just the push event |

What the endpoint does, in order:

1. **Verifies `X-Hub-Signature-256`.** Absent or malformed is a rejection, never
   a pass. Without this, anyone could trigger reindexing.
2. **Filters by path.** The site repo also holds the Docusaurus app, CI config
   and blog. A push touching no `docs/` path is ignored -- rebuilding for a
   `package-lock.json` bump is waste.
3. **Returns 202 immediately** and refreshes in a background thread: the clone
   plus reindex takes longer than GitHub's delivery timeout.
4. **Drops overlapping triggers.** A burst of pushes must not start concurrent
   clones; the run already in flight picks up the newer commits.

Verify a delivery end to end:

```bash
BODY='{"commits":[{"added":[],"modified":["docs/php/micro-orm/a.md"],"removed":[]}]}'
SIG=$(printf '%s' "$BODY" | openssl dgst -sha256 -hmac "$BYJG_DOCS_WEBHOOK_SECRET" -hex | sed 's/^.* //')
curl -s -X POST http://127.0.0.1:2954/webhook/github \
  -H "X-GitHub-Event: push" -H "X-Hub-Signature-256: sha256=$SIG" \
  -H "Content-Type: application/json" -d "$BODY"
# {"status":"reindexing"}
```

## Connecting a client

Through the tunnel, with `--scope user` so the server is available in every
directory rather than only the one you ran the command in:

```bash
claude mcp add --transport http --scope user byjg-docs \
  https://mcp-docs.byjg.com/mcp \
  --header "Authorization: Bearer $BYJG_DOCS_AUTH_TOKEN"
```

Full walkthrough, including what each failure mode means:
[Connecting a client through the tunnel](usage.md#connecting-a-client-through-the-tunnel).

On this machine you can skip the token and the network entirely --
`docker exec` runs a stdio server inside the `mcp` container:

```bash
claude mcp add --scope user byjg-docs -- \
  docker exec -i -e BYJG_DOCS_TRANSPORT=stdio mcpserver-mcp-1 byjg-docs-mcp
```

Details: [Through the compose stack, over stdio](usage.md#through-the-compose-stack-over-stdio).

## Operations

```bash
docker compose ps
docker compose logs -f mcp
curl -s http://127.0.0.1:2954/healthz
docker compose restart mcp
```

`/healthz` reports liveness, whether a reindex is running, and the current
document and chunk counts -- enough to distinguish "empty index" from "still
building" from "healthy".

### Rebuilding from scratch

```bash
docker compose down
docker volume rm mcpserver_index
docker compose up -d      # notices the empty index and rebuilds it
```

### Backup

The index is one file inside the `index` volume, fully derived from a public
git repository, and rebuilt in ~60s. There is nothing here worth backing up
that GitHub does not already hold.

## Data flows

Worth knowing given the tunnel exposes this publicly:

- **Documentation content** is cloned from a public repo on each refresh,
  embedded by a local Ollama, and stored in a local file. The checkout is
  temporary and deleted afterwards.
- **Query text** goes to the local Ollama only. No embedding provider sees it.
- **What crosses the internet** is the MCP request and response through the
  Cloudflare tunnel, and the `git clone`/`fetch` of the public docs repo.
