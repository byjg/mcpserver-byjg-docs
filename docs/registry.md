---
sidebar_position: 2
---

# The MCP Registry entry

The server is published in the [official MCP Registry](https://registry.modelcontextprotocol.io)
under the name **`com.byjg/docs`**:

```bash
curl "https://registry.modelcontextprotocol.io/v0.1/servers/com.byjg%2Fdocs/versions/latest"
```

The published metadata is the `server.json` file at the root of the repository --
the endpoint URL, the transport, the repository and the documentation site. The
registry hosts **only that metadata**; the server itself keeps running at
`https://mcpdocs.byjg.com/mcp`.

## What reads it

No IDE reads `server.json` from this repository, and publishing it does not make
the server show up inside your editor by itself. The registry is a discovery
index: by design it is
[not consumed directly by host applications](https://github.com/modelcontextprotocol/registry/blob/main/docs/modelcontextprotocol-io/about.mdx) --
aggregators and marketplaces scrape its REST API (roughly hourly) and the
clients browse those.

| Consumer | What it does with the entry |
|---|---|
| The registry REST API and the browsers built on it (MCP Bench, MCP Registry UI, `mcp-registry-cli`, ...) | List it immediately -- this is where publishing has an instant effect |
| Downstream aggregators and marketplaces | Scrape the API and republish the entry with their own curation, ratings or scanning |
| VS Code | The Extensions view (`@mcp`) browses an MCP registry. By default that is GitHub's *curated* MCP Registry, which is a separate submission -- publishing here does not add it. An organisation can point VS Code at any MCP Registry API with the `McpGalleryServiceUrl` policy, including a private one that mirrors this entry |
| JetBrains IDEs, Claude Code, Claude Desktop, Codex CLI, Gemini CLI, Cursor | No registry browsing at all: the server is added by hand, see [Connecting a client](clients.md) |

In short, the registry entry is for **discovery and provenance**, not
installation. [Connecting a client](clients.md) stays the way to actually use
the server, whichever editor you run.

## Why the name is `com.byjg/docs`

The namespace comes from how the entry is authenticated. The registry supports
GitHub-based names (`io.github.<user>/*`) and domain-based names
(`com.example/*`); this server uses the domain, proved with a DNS TXT record on
the **apex** of `byjg.com`:

```text
byjg.com. IN TXT "v=MCPv1; k=ed25519; p=<public key>"
```

`key.pem` in the working copy is the private half of that record. It is never
committed (`.gitignore` excludes `*.pem`) -- keep it somewhere safe, because
regenerating it means replacing the TXT record before you can publish again.

## Publishing a new version

Registry versions are immutable, like npm: to change anything you publish a new
`version`. Keep it in step with `version` in `pyproject.toml`.

1. Edit `server.json` (at least bump `version`).
2. Validate it: `mcp-publisher validate`.
3. Log in with the domain key:

   ```bash
   PRIVATE_KEY="$(openssl pkey -in key.pem -noout -text | grep -A3 "priv:" | tail -n +2 | tr -d ' :\n')"
   mcp-publisher login dns --domain byjg.com --private-key "${PRIVATE_KEY}"
   ```

4. Publish: `mcp-publisher publish`.
5. Verify with the `curl` command at the top of this page.

`mcp-publisher` is the [official CLI](https://github.com/modelcontextprotocol/registry/releases);
`brew install mcp-publisher` also works.

To take an entry down, mark it deleted rather than trying to remove it -- the
record is preserved, it only stops being listed:

```bash
mcp-publisher status --status deleted --message "..." com.byjg/docs 0.1.0
```
