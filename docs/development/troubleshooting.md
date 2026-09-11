# Troubleshooting

Problems running or hosting the server. For a client that cannot connect, see
[Connecting a client -- Troubleshooting](../clients.md#troubleshooting) first.

## Indexing and search

**`Ollama does not have model 'nomic-embed-text'`**
Run `ollama pull nomic-embed-text`. Under compose, `ollama-init` does this; check
`docker compose logs ollama-init`.

**Search returns nothing on a fresh install**
The index is empty. Run `uv run byjg-docs-index build` and confirm with
`stats`. Under compose the first build runs in the background -- `/healthz`
shows `"reindexing": true` until it finishes.

**Results look stale after editing docs**
`build` indexes what is on GitHub, not your local edits -- push them first, or
point `BYJG_DOCS_DOCS_ROOT` at your checkout to
[index it in place](local.md#indexing-a-local-checkout). If you changed the
*model* or the chunker instead, run `build --force`.

**`query vector has N dims, index has M`**
The embedding model changed under an existing index. Rebuild with `--force`,
or delete the `.db` and build again.

## Server

**Server exits with "Refusing to serve on a non-loopback address"**
The HTTP transport is bound off loopback without a token. Set
`BYJG_DOCS_AUTH_TOKEN`, or bind `127.0.0.1`.

**`/healthz` returns 404**
The transport is `stdio`. Health and webhook endpoints exist only over HTTP --
see [Transport and endpoints](configuration.md#transport-and-endpoints).

**`/webhook/github` returns 404**
The endpoint is only registered when `BYJG_DOCS_WEBHOOK_SECRET` is set and the
transport is `http`.

**`uv run byjg-docs-mcp` prints one line and hangs**
That is the stdio server waiting for an MCP client on stdin -- correct
behaviour. Register it with a client instead; see
[Connecting a client over stdio](local.md#connecting-a-client-over-stdio).

## Self-hosted clients

**Client gets 401 with the right token**
`BYJG_DOCS_PUBLIC_URL` does not match the hostname the client uses. MCP
advertises the protected resource under that URL, so a mismatch fails
authentication even with the correct token.

**Connection refused or timeout through the tunnel**
The tunnel is down, or `cloudflared` cannot reach `mcp:8080`. Check
`docker compose --profile tunnel ps` and `docker compose logs cloudflared`.

**`docker exec` fails with "No such container"**
The container name comes from the project directory. Run `docker compose ps`
for the actual name, and confirm the stack is up.

## Webhook

**GitHub shows the delivery as 401**
The secret configured on the webhook does not match
`BYJG_DOCS_WEBHOOK_SECRET`. Unsigned and wrongly-signed requests are both
rejected by design.

**Webhook returns 202 but nothing reindexes**
Check `docker compose logs mcp`. The likely causes are a push that touched no
`docs/` path (ignored on purpose), or the clone failing -- look for
`reindex failed` in the log.
