---
sidebar_position: 1
---

import Tabs from '@theme/Tabs';
import TabItem from '@theme/TabItem';

# Connecting a client

Every client needs the same thing: the URL `https://mcpdocs.byjg.com/mcp`, over
streamable HTTP. The documentation is public, so **the ByJG server asks for no
credentials**.

Each section below has two tabs: **No token** for `mcpdocs.byjg.com`, and
**With token** for a server of your own that runs with
[`BYJG_DOCS_AUTH_TYPE=bearer`](development/self-hosting.md#authentication).
Picking a tab switches every section on the page. In the "With token" tabs,
replace `<TOKEN>` with the token of that server.

The examples name the server `byjg-docs`; any name works.

Every client here is configured by hand. The server is published in the
official MCP Registry as `com.byjg/docs`, but no editor installs it from there
-- that entry is for discovery, see [The MCP Registry entry](registry.md).

- [Claude Code](#claude-code)
- [Claude Desktop](#claude-desktop)
- [Codex CLI](#codex-cli)
- [Gemini CLI](#gemini-cli)
- [Cursor](#cursor)
- [VS Code](#vs-code)
- [JetBrains IDEs](#jetbrains-ides)
- [The tools](#the-tools)
- [Troubleshooting](#troubleshooting)

## Claude Code

<Tabs groupId="auth">
<TabItem value="none" label="No token" default>

```bash
claude mcp add --transport http --scope user byjg-docs \
  https://mcpdocs.byjg.com/mcp
```

</TabItem>
<TabItem value="token" label="With token">

```bash
claude mcp add --transport http --scope user byjg-docs \
  https://your-server.example.com/mcp \
  --header "Authorization: Bearer <TOKEN>"
```

</TabItem>
</Tabs>

**Use `--scope user`.** The default scope is `local`, which registers the
server only for the directory you ran the command in -- for a documentation
server you want everywhere, that is almost never what you meant.

Verify:

```bash
claude mcp list
# byjg-docs: https://mcpdocs.byjg.com/mcp (HTTP) - ✔ Connected
```

Remove: `claude mcp remove byjg-docs --scope user`.

## Claude Desktop

Claude Desktop takes a remote server's URL directly, as a **custom connector**.
The same connector works on claude.ai and the mobile apps, and it shows up in
Claude Code when you are signed in to the same account.

<Tabs groupId="auth">
<TabItem value="none" label="No token" default>

Open **Customize > Connectors**, click **+**, then **Add custom connector**,
and paste the URL:

```text
https://mcpdocs.byjg.com/mcp
```

Click **Add**. On a Team or Enterprise plan an owner adds it once under
**Organization settings > Connectors > Add > Custom > Web**; everyone else then
enables it from **Customize > Connectors**.

To use it in a conversation, click **+** in the chat, open **Connectors** and
toggle it on. A Free plan is limited to one custom connector; paid plans are
not.

Claude connects to the server **from Anthropic's cloud, not from your
machine** -- which is why `mcpdocs.byjg.com` works and a server on your laptop
or VPN does not.

</TabItem>
<TabItem value="token" label="With token">

Custom connectors only offer OAuth credentials (client ID and secret) under
**Advanced settings** -- there is no field for a static `Authorization` header,
and Anthropic's cloud cannot reach a server on a private network. For a server
of your own running with `BYJG_DOCS_AUTH_TYPE=bearer`, bridge it locally with
[`mcp-remote`](https://github.com/geelen/mcp-remote), a small process that
forwards the requests. It needs Node.js 18 or later.

Open **Settings > Developer > Edit Config**, which opens
`claude_desktop_config.json`, and add:

```json
{
  "mcpServers": {
    "byjg-docs": {
      "command": "npx",
      "args": [
        "-y",
        "mcp-remote",
        "https://your-server.example.com/mcp",
        "--header",
        "Authorization:${AUTH_HEADER}"
      ],
      "env": {
        "AUTH_HEADER": "Bearer <TOKEN>"
      }
    }
  }
}
```

Write `"Authorization:${AUTH_HEADER}"` exactly like that -- colon, no spaces.
On Windows, Claude Desktop does not escape spaces inside `args`, so the space
in `Bearer <TOKEN>` has to live in the `env` value instead.

Restart Claude Desktop completely, then check **Settings > Developer** for the
server status.

</TabItem>
</Tabs>

## Codex CLI

Add to `~/.codex/config.toml`:

<Tabs groupId="auth">
<TabItem value="none" label="No token" default>

```toml
[mcp_servers.byjg-docs]
url = "https://mcpdocs.byjg.com/mcp"
```

</TabItem>
<TabItem value="token" label="With token">

```toml
[mcp_servers.byjg-docs]
url = "https://your-server.example.com/mcp"
http_headers = { "Authorization" = "Bearer <TOKEN>" }
```

To keep the token out of the file, read it from an environment variable
instead:

```bash
export BYJG_DOCS_TOKEN=<TOKEN>
codex mcp add byjg-docs --url https://your-server.example.com/mcp \
  --bearer-token-env-var BYJG_DOCS_TOKEN
```

</TabItem>
</Tabs>

Verify: `codex mcp list`.

## Gemini CLI

<Tabs groupId="auth">
<TabItem value="none" label="No token" default>

```bash
gemini mcp add --transport http --scope user \
  byjg-docs https://mcpdocs.byjg.com/mcp
```

Or edit `~/.gemini/settings.json` directly. Note the key is **`httpUrl`**;
`url` means the older SSE transport in Gemini CLI:

```json
{
  "mcpServers": {
    "byjg-docs": {
      "httpUrl": "https://mcpdocs.byjg.com/mcp"
    }
  }
}
```

</TabItem>
<TabItem value="token" label="With token">

```bash
gemini mcp add --transport http --scope user \
  --header "Authorization: Bearer <TOKEN>" \
  byjg-docs https://your-server.example.com/mcp
```

Or edit `~/.gemini/settings.json` directly. Note the key is **`httpUrl`**;
`url` means the older SSE transport in Gemini CLI:

```json
{
  "mcpServers": {
    "byjg-docs": {
      "httpUrl": "https://your-server.example.com/mcp",
      "headers": {
        "Authorization": "Bearer <TOKEN>"
      }
    }
  }
}
```

</TabItem>
</Tabs>

Verify: `gemini mcp list`.

## Cursor

Click the **gear icon** at the top of the chat panel, open **Tools & MCP**,
and click **Add Custom MCP**. That opens `~/.cursor/mcp.json` (available in
every project; use `<project-root>/.cursor/mcp.json` for one project only):

<Tabs groupId="auth">
<TabItem value="none" label="No token" default>

```json
{
  "mcpServers": {
    "byjg-docs": {
      "url": "https://mcpdocs.byjg.com/mcp"
    }
  }
}
```

</TabItem>
<TabItem value="token" label="With token">

```json
{
  "mcpServers": {
    "byjg-docs": {
      "url": "https://your-server.example.com/mcp",
      "headers": {
        "Authorization": "Bearer ${env:BYJG_DOCS_TOKEN}"
      }
    }
  }
}
```

`${env:BYJG_DOCS_TOKEN}` keeps the token out of the file: export it before
starting Cursor. A literal `"Bearer <TOKEN>"` works too.

</TabItem>
</Tabs>

The server shows up under **Tools & MCP** with a green dot once connected.

## VS Code

Click the **gear icon** at the top of the Chat view, open **MCP Servers**, and
click **Add Server** -- or run **MCP: Open User Configuration** from the
Command Palette. Either way you edit `mcp.json` in your user profile.

VS Code's format differs from the others: the top-level key is `servers`, and
each entry declares its `type`:

<Tabs groupId="auth">
<TabItem value="none" label="No token" default>

```json
{
  "servers": {
    "byjg-docs": {
      "type": "http",
      "url": "https://mcpdocs.byjg.com/mcp"
    }
  }
}
```

</TabItem>
<TabItem value="token" label="With token">

```json
{
  "servers": {
    "byjg-docs": {
      "type": "http",
      "url": "https://your-server.example.com/mcp",
      "headers": {
        "Authorization": "Bearer <TOKEN>"
      }
    }
  }
}
```

For a single workspace the same content goes in `.vscode/mcp.json` -- but that
file is usually committed, so keep the token out of it and use an
[input variable](https://code.visualstudio.com/docs/agents/reference/mcp-configuration)
instead.

</TabItem>
</Tabs>

The server appears under **Installed** in the MCP Servers view.

## JetBrains IDEs

Applies to IntelliJ IDEA, PhpStorm, PyCharm, WebStorm and the rest, through
AI Assistant. Remote HTTP servers need version 2025.3 or later.

Open **Settings > Tools > AI Assistant > Model Context Protocol (MCP)**, click
**+** (Add server), select the **HTTP** tab and paste:

<Tabs groupId="auth">
<TabItem value="none" label="No token" default>

```json
{
  "mcpServers": {
    "byjg-docs": {
      "url": "https://mcpdocs.byjg.com/mcp"
    }
  }
}
```

</TabItem>
<TabItem value="token" label="With token">

```json
{
  "mcpServers": {
    "byjg-docs": {
      "url": "https://your-server.example.com/mcp",
      "headers": {
        "Authorization": "Bearer <TOKEN>"
      }
    }
  }
}
```

If your version does not send the header (the status shows an authentication
error), use the **STDIO** tab with the same `mcp-remote` bridge as
[Claude Desktop](#claude-desktop).

</TabItem>
</Tabs>

Leave **Server level** on **Global** so it is available in every project
(saved to `~/.ai/mcp/mcp.json`), and click **OK**. The **Status** column turns
green once connected.

## The tools

### `search_docs(query, limit, category, project)`

The main entry point. Returns ranked passages, each with its source path,
public URL and project.

- `query` -- natural language or an exact symbol name; both work
- `limit` -- defaults to 8, capped at 25
- `category` -- `php`, `devops`, `js`, `ai`, `helm`, or `blog` for blog posts
- `project` -- `micro-orm`, `restserver`, `docker-easy-haproxy`, ...

### `get_document(source_path)`

Full markdown of one page, addressed by the `source` a search result reports
(`php/micro-orm/active-record.md`). Use when a hit is relevant but truncated.

### `list_projects()`

Inventory grouped by category and project, with counts. Lets the model
discover what exists before searching.

## Troubleshooting

| Symptom | Cause |
|---|---|
| `401 Unauthorized` | The server you pointed at requires a token (`BYJG_DOCS_AUTH_TYPE=bearer`); `mcpdocs.byjg.com` does not. Use the **With token** tabs, and check the header is `Authorization: Bearer <TOKEN>` |
| `404 Not Found` | The URL is missing the `/mcp` path |
| Timeout / connection refused | The server is unreachable; check `https://mcpdocs.byjg.com/healthz` in a browser |
| Works in one directory only (Claude Code) | Registered with the default `local` scope; re-add with `--scope user` |
| `npx: command not found` (Claude Desktop, JetBrains STDIO) | Node.js is not installed, or not on the `PATH` the app sees |
