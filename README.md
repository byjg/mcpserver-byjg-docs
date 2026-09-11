# ByJG Docs MCP Server

An [MCP](https://modelcontextprotocol.io) server that gives AI assistants
semantic search over the documentation of every ByJG open source project --
the same content published at [opensource.byjg.com](https://opensource.byjg.com).

Connect your assistant and it can answer questions about the ByJG libraries
(MicroOrm, RestServer, Gluo, EasyHAProxy, ...) and cite the documentation page
each answer came from.

## Endpoint

| | |
|---|---|
| URL | `https://mcpdocs.byjg.com/mcp` |
| Transport | Streamable HTTP |
| Authentication | `Authorization: Bearer <TOKEN>` |

Replace `<TOKEN>` with the token you were given. The URL must end in `/mcp`.

Most clients accept this shape; the exact file and keys vary per client:

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

## Add it to your client

| Client | |
|---|---|
| Claude Code (CLI) | [instructions](docs/clients.md#claude-code) |
| Claude Desktop | [instructions](docs/clients.md#claude-desktop) |
| Codex CLI | [instructions](docs/clients.md#codex-cli) |
| Gemini CLI | [instructions](docs/clients.md#gemini-cli) |
| Cursor | [instructions](docs/clients.md#cursor) |
| VS Code | [instructions](docs/clients.md#vs-code) |
| JetBrains IDEs | [instructions](docs/clients.md#jetbrains-ides) |

Connection problems: [Troubleshooting](docs/clients.md#troubleshooting).

## Tools

| Tool | Purpose |
|---|---|
| `search_docs(query, limit, category, project)` | Ranked passages, each with its public URL |
| `get_document(source_path)` | Full markdown of one page |
| `list_projects()` | Inventory of what is indexed |

`query` accepts natural language ("how do I map a table to a class") or an
exact symbol name (`TableAttribute`) -- both work. See
[the tools in detail](docs/clients.md#the-tools).

## Privacy

The server records each tool call -- the query, its filters and how well the
documentation matched -- to find what the docs do not cover yet. The log stays
on the server and is not shared. Do not put secrets in a query.

## Development

To run the server yourself, self-host it, or change the code, see
[Development](docs/development/index.md).
