# Kubernetes manifests

The same stack as `docker-compose.yml`, without the Cloudflare tunnel:
`ollama` for embeddings, `mcp` for the server, three volumes, and an Ingress
published by [ByJG EasyHAProxy](https://opensource.byjg.com/docs/devops/docker-easy-haproxy/getting-started/kubernetes).

```bash
# 1. The token and the webhook secret, kept out of git
kubectl create namespace byjg-docs
kubectl -n byjg-docs create secret generic byjg-docs-secrets \
  --from-literal=BYJG_DOCS_AUTH_TOKEN="$(openssl rand -hex 32)" \
  --from-literal=BYJG_DOCS_WEBHOOK_SECRET="$(openssl rand -hex 32)"

# 2. Everything else (delete the Secret document in 10-config.yaml first, or
#    it overwrites what you just created with REPLACE_ME)
kubectl apply -f k8s/

# 3. Watch the first index build -- a clone plus ~4,100 embeddings
kubectl -n byjg-docs logs -f deploy/mcp
```

Set `BYJG_DOCS_PUBLIC_URL` and the Ingress `host` to the same name, or MCP
advertises a resource clients cannot reach.

## What differs from compose

| compose | here |
|---|---|
| `ollama-init` service | `initContainers.pull-embedding-model` on the `mcp` pod -- idempotent, and its retries are the wait for ollama |
| `depends_on: service_healthy` | the readiness probe on `ollama` plus that init container |
| published host port `2954` | `ClusterIP` + Ingress; nothing is published on the nodes |
| `cloudflared` profile | Cloudflare still terminates TLS; it reaches EasyHAProxy over HTTP on port 80 |
| `.env` | `byjg-docs-config` ConfigMap and `byjg-docs-secrets` Secret |
| named volumes | three `ReadWriteOnce` PVCs |

## Things that will bite

- **`replicas` must stay 1.** The index is one SQLite file on a ReadWriteOnce
  volume and the refresh job assumes a single writer. Scaling out means moving
  the store to a server-backed backend first.
- **The rollout overlaps two pods on the same volumes**, for both `mcp` and
  `ollama`. `RollingUpdate` with
  `maxUnavailable: 0` starts the new pod before stopping the old one, so a
  deploy has no downtime. That needs both pods on the same node, since
  ReadWriteOnce is per node: automatic with node-local storage (local-path).
  With network block storage a new pod on another node fails with
  "Multi-Attach error" and the rollout stalls -- the old pod keeps serving;
  switch both to `Recreate` in that case.
- **First boot is slow.** An empty index is built in the background; the server
  answers `/healthz` while it fills, and searches return nothing until it is
  done. On CPU it takes considerably longer than the ~60s a GPU needs.
- **GPU is opt-in.** Uncomment `nvidia.com/gpu` in `30-ollama.yaml` only if the
  device plugin is installed, otherwise the pod stays `Pending`.
- **The origin is HTTP only.** EasyHAProxy has no certificate, so nothing
  listens on 443 -- test the origin with
  `curl -H "Host: mcpdocs.byjg.com" http://<easyhaproxy-ip>/healthz`. Cloudflare
  must reach it over HTTP (Tunnel service `http://...:80`, or SSL mode
  "Flexible") and does the HTTP -> HTTPS redirect ("Always Use HTTPS").
  Adding `easyhaproxy.redirect_ssl` here would loop.
- **No per-ingress timeout annotation exists.** If a long-lived streamable HTTP
  connection gets cut, raise HAProxy's global timeouts on the EasyHAProxy
  deployment, not here.

## Afterwards

```bash
# Deploy a new image. Re-applying the manifests does nothing while the tag is
# still `latest`: the pod template did not change. Restarting makes a new pod,
# and `imagePullPolicy: Always` makes it pull.
kubectl -n byjg-docs rollout restart deployment/mcp
kubectl -n byjg-docs rollout status deployment/mcp

# Point the GitHub webhook at this, with the same secret
#   https://mcpdocs.byjg.com/webhook/github

# Reindex by hand
kubectl -n byjg-docs exec deploy/mcp -- byjg-docs-index build

# What the documentation does not cover
kubectl -n byjg-docs exec deploy/mcp -- byjg-docs-index queries --weak
```
