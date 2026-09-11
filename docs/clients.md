# Connecting a client

Every client needs the same two things:

| | |
|---|---|
| URL | `https://mcpdocs.byjg.com/mcp` |
| Header | `Authorization: Bearer <TOKEN>` |

Replace `<TOKEN>` with the token you were given. The examples below name the
server `byjg-docs`; any name works.

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

```bash
claude mcp add --transport http --scope user byjg-docs \
  https://mcpdocs.byjg.com/mcp \
  --header "Authorization: Bearer <TOKEN>"
```

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

Claude Desktop's config file only launches local (stdio) servers; it has no
field for a remote URL with a static header. Bridge it with
[`mcp-remote`](https://github.com/geelen/mcp-remote), a small local process
that forwards requests and adds the header. It needs Node.js 18 or later.

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
        "https://mcpdocs.byjg.com/mcp",
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

## Codex CLI

Add to `~/.codex/config.toml`:

```toml
[mcp_servers.byjg-docs]
url = "https://mcpdocs.byjg.com/mcp"
http_headers = { "Authorization" = "Bearer <TOKEN>" }
```

To keep the token out of the file, read it from an environment variable
instead:

```bash
export BYJG_DOCS_TOKEN=<TOKEN>
codex mcp add byjg-docs --url https://mcpdocs.byjg.com/mcp \
  --bearer-token-env-var BYJG_DOCS_TOKEN
```

Verify: `codex mcp list`.

## Gemini CLI

```bash
gemini mcp add --transport http --scope user \
  --header "Authorization: Bearer <TOKEN>" \
  byjg-docs https://mcpdocs.byjg.com/mcp
```

Or edit `~/.gemini/settings.json` directly. Note the key is **`httpUrl`**;
`url` means the older SSE transport in Gemini CLI:

```json
{
  "mcpServers": {
    "byjg-docs": {
      "httpUrl": "https://mcpdocs.byjg.com/mcp",
      "headers": {
        "Authorization": "Bearer <TOKEN>"
      }
    }
  }
}
```

Verify: `gemini mcp list`.

## Cursor

Click the **gear icon** at the top of the chat panel, open **Tools & MCP**,
and click **Add Custom MCP**. That opens `~/.cursor/mcp.json` (available in
every project; use `<project-root>/.cursor/mcp.json` for one project only):

```json
{
  "mcpServers": {
    "byjg-docs": {
      "url": "https://mcpdocs.byjg.com/mcp",
      "headers": {
        "Authorization": "Bearer <TOKEN>"
      }
    }
  }
}
```

To keep the token out of the file, write `"Bearer ${env:BYJG_DOCS_TOKEN}"`
and export `BYJG_DOCS_TOKEN` before starting Cursor.

The server shows up under **Tools & MCP** with a green dot once connected.

## VS Code

Click the **gear icon** at the top of the Chat view, open **MCP Servers**, and
click **Add Server** -- or run **MCP: Open User Configuration** from the
Command Palette. Either way you edit `mcp.json` in your user profile.

VS Code's format differs from the others: the top-level key is `servers`, and
each entry declares its `type`:

```json
{
  "servers": {
    "byjg-docs": {
      "type": "http",
      "url": "https://mcpdocs.byjg.com/mcp",
      "headers": {
        "Authorization": "Bearer <TOKEN>"
      }
    }
  }
}
```

The server appears under **Installed** in the MCP Servers view. For a single
workspace, put the same content in `.vscode/mcp.json` -- but that file is
usually committed, so do not put the token in it.

## JetBrains IDEs

Applies to IntelliJ IDEA, PhpStorm, PyCharm, WebStorm and the rest, through
AI Assistant. Remote HTTP servers need version 2025.3 or later.

1. Open **Settings > Tools > AI Assistant > Model Context Protocol (MCP)**.
2. Click **+** (Add server).
3. Select the **HTTP** tab and paste:

   ```json
   {
     "mcpServers": {
       "byjg-docs": {
         "url": "https://mcpdocs.byjg.com/mcp",
         "headers": {
           "Authorization": "Bearer <TOKEN>"
         }
       }
     }
   }
   ```

4. Leave **Server level** on **Global** so it is available in every project
   (saved to `~/.ai/mcp/mcp.json`), and click **OK**.

The **Status** column turns green once connected.

If your version does not send the header (the status shows an authentication
error), use the **STDIO** tab with the same `mcp-remote` bridge as
[Claude Desktop](#claude-desktop):

```json
{
  "mcpServers": {
    "byjg-docs": {
      "command": "npx",
      "args": [
        "-y",
        "mcp-remote",
        "https://mcpdocs.byjg.com/mcp",
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

## The tools

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

Inventory grouped by category and project, with counts. Lets the model
discover what exists before searching.

## Troubleshooting

| Symptom | Cause |
|---|---|
| `401 Unauthorized` | Token missing or wrong, or the header is malformed -- it must be `Authorization: Bearer <TOKEN>` |
| `404 Not Found` | The URL is missing the `/mcp` path |
| Timeout / connection refused | The server is unreachable; check `https://mcpdocs.byjg.com/healthz` in a browser |
| Works in one directory only (Claude Code) | Registered with the default `local` scope; re-add with `--scope user` |
| `npx: command not found` (Claude Desktop, JetBrains STDIO) | Node.js is not installed, or not on the `PATH` the app sees |
