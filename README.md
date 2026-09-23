---
sidebar_key: mcpserver-byjg-docs
tags: [ai, python, docker]
---

# ByJG Docs MCP Server

An [MCP](https://modelcontextprotocol.io) server that gives AI assistants
semantic search over the documentation of every ByJG open source project, and
the blog -- the same content published at
[opensource.byjg.com](https://opensource.byjg.com).

Connect your assistant and it can answer questions about the ByJG libraries
(MicroOrm, RestServer, Gluo, EasyHAProxy, ...) and cite the documentation page
each answer came from.

## Endpoint

| | |
|---|---|
| URL | `https://mcpdocs.byjg.com/mcp` |
| Transport | Streamable HTTP |
| Authentication | None -- the documentation is public, so no token is needed |

The URL must end in `/mcp`.

Most clients accept this shape; the exact file and keys vary per client:

```json
{
  "mcpServers": {
    "byjg-docs": {
      "url": "https://mcpdocs.byjg.com/mcp"
    }
  }
}
```

Running your own copy? It can require a bearer token instead --
see [Authentication](docs/development/self-hosting.md#authentication).

## Add it to your client

| Client | Setup | One-click |
|---|---|---|
| Claude Code (CLI) | [instructions](docs/clients.md#claude-code) |  |
| Claude Desktop | [instructions](docs/clients.md#claude-desktop) |  |
| Codex CLI | [instructions](docs/clients.md#codex-cli) |  |
| Gemini CLI | [instructions](docs/clients.md#gemini-cli) |  |
| Cursor | [instructions](docs/clients.md#cursor) | [![Install in Cursor](https://img.shields.io/badge/Install_in-Cursor-000000?style=flat-square&logoColor=white)](https://cursor.com/en/install-mcp?name=byjg-docs&config=eyJ0eXBlIjoiaHR0cCIsInVybCI6Imh0dHBzOi8vbWNwZG9jcy5ieWpnLmNvbS9tY3AifQ==) |
| VS Code | [instructions](docs/clients.md#vs-code) | [![Install in VS Code](https://img.shields.io/badge/Install_in-VS_Code-0098FF?style=flat-square&logo=visualstudiocode&logoColor=white)](https://vscode.dev/redirect/mcp/install?name=byjg-docs&config=%7B%22type%22%3A%22http%22%2C%22url%22%3A%22https%3A%2F%2Fmcpdocs.byjg.com%2Fmcp%22%7D) |
| VS Code Insiders | [instructions](docs/clients.md#vs-code) | [![Install in VS Code Insiders](https://img.shields.io/badge/Install_in-VS_Code_Insiders-24bfa5?style=flat-square&logo=visualstudiocode&logoColor=white)](https://insiders.vscode.dev/redirect/mcp/install?name=byjg-docs&config=%7B%22type%22%3A%22http%22%2C%22url%22%3A%22https%3A%2F%2Fmcpdocs.byjg.com%2Fmcp%22%7D&quality=insiders) |
| Visual Studio |  | [![Install in Visual Studio](https://img.shields.io/badge/Install_in-Visual_Studio-C16FDE?style=flat-square&logo=visualstudio&logoColor=white)](https://vs-open.link/mcp-install?%7B%22type%22%3A%22http%22%2C%22url%22%3A%22https%3A%2F%2Fmcpdocs.byjg.com%2Fmcp%22%7D) |
| JetBrains IDEs | [instructions](docs/clients.md#jetbrains-ides) |  |
| Goose |  | [![Install in Goose](https://goose-docs.ai/img/extension-install-dark.svg)](https://goose-docs.ai/extension?url=https%3A%2F%2Fmcpdocs.byjg.com%2Fmcp&type=streamable_http&id=byjg-docs&name=byjg-docs&description=ByJG%20open%20source%20documentation) |
| LM Studio |  | [![Add MCP Server byjg-docs to LM Studio](https://files.lmstudio.ai/deeplink/mcp-install-light.svg)](https://lmstudio.ai/install-mcp?name=byjg-docs&config=eyJ0eXBlIjoiaHR0cCIsInVybCI6Imh0dHBzOi8vbWNwZG9jcy5ieWpnLmNvbS9tY3AifQ==) |

The one-click badges hand the endpoint straight to the client, which then
asks you to confirm; everything else is the manual configuration on the
[client page](docs/clients.md). Connection problems:
[Troubleshooting](docs/clients.md#troubleshooting).

Neither path installs from a registry. The server *is* published in the
official MCP Registry as `com.byjg/docs`, for discovery and provenance: see
[The MCP Registry entry](docs/registry.md).

## Tools

| Tool | Purpose |
|---|---|
| `search_docs(query, limit, category, project)` | Ranked passages, each with its public URL |
| `get_document(source_path)` | Full markdown of one page |
| `list_projects()` | Inventory of what is indexed |

`query` accepts natural language ("how do I map a table to a class") or an
exact symbol name (`TableAttribute`) -- both work. `category` narrows the
search: the technology areas (`php`, `devops`, `js`, `ai`, `helm`) or `blog`.
See [the tools in detail](docs/clients.md#the-tools).

## Privacy

The server records each tool call -- the query, its filters and how well the
documentation matched -- to find what the docs do not cover yet. The log stays
on the server and is not shared. Do not put secrets in a query.

## Development

To run the server yourself, self-host it, or change the code, see
[Development](docs/development/overview.md).
