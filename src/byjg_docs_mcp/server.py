"""MCP server exposing the ByJG documentation index.

Runs over stdio when a client spawns it locally, or over streamable HTTP when
it is deployed as a shared service.
"""

from __future__ import annotations

import logging
import secrets

from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver import MCPServer
from pydantic import AnyHttpUrl

from .querylog import QueryLog
from .runtime import Runtime, build_runtime
from .stores import SearchHit
from .webhook import register_health, register_webhook

logger = logging.getLogger(__name__)

INSTRUCTIONS = """\
Searches the ByJG open source documentation (PHP libraries, DevOps tooling,
Helm charts, JavaScript components and AI tools) published at
opensource.byjg.com.

Use `search_docs` to answer questions about how a ByJG library works, then cite
the returned URL. Use `get_document` when a search hit looks right but you need
the surrounding context, and `list_projects` to discover what is documented.
"""


class StaticTokenVerifier(TokenVerifier):
    """Accepts a single pre-shared bearer token.

    Deliberately minimal: this protects a personal, read-only service. Anything
    with more than one consumer wants real OAuth via `auth_server_provider`.
    """

    def __init__(self, token: str) -> None:
        self._token = token

    async def verify_token(self, token: str) -> AccessToken | None:
        # Constant-time compare so a wrong token cannot be recovered by timing.
        if secrets.compare_digest(token, self._token):
            return AccessToken(token=token, client_id="byjg-docs", scopes=["read"])
        return None


def _format_hit(hit: SearchHit, index: int) -> str:
    c = hit.chunk
    location = " > ".join(p for p in (c.title, c.heading_path) if p)
    return (
        f"## Result {index}: {location}\n"
        f"- source: `{c.source_path}`\n"
        f"- url: {c.url}\n"
        f"- project: {c.category}/{c.project or '-'}\n\n"
        f"{c.text}\n"
    )


def build_server(runtime: Runtime) -> MCPServer:
    settings = runtime.settings
    # Authentication belongs to the HTTP transport: stdio is a pipe between a
    # client and the process it spawned, with nothing to authenticate.
    # A token verifier is only accepted alongside auth settings, which describe
    # the resource clients are authenticating against.
    verifier = None
    auth = None
    if settings.transport != "stdio" and settings.auth_type == "bearer":
        if not settings.auth_token:
            raise SystemExit(
                "BYJG_DOCS_AUTH_TYPE=bearer needs BYJG_DOCS_AUTH_TOKEN. "
                "Generate one with `openssl rand -hex 32`, or set "
                "BYJG_DOCS_AUTH_TYPE=none to serve without authentication."
            )
        verifier = StaticTokenVerifier(settings.auth_token)
        auth = AuthSettings(
            issuer_url=AnyHttpUrl(settings.public_url),
            resource_server_url=AnyHttpUrl(settings.public_url),
            required_scopes=["read"],
        )
    elif settings.transport != "stdio" and settings.auth_token:
        logger.warning(
            "BYJG_DOCS_AUTH_TOKEN is set but BYJG_DOCS_AUTH_TYPE is 'none': "
            "the token is ignored and every client is served."
        )

    mcp = MCPServer(
        name="byjg-docs",
        title="ByJG Documentation",
        instructions=INSTRUCTIONS,
        website_url=settings.site_url,
        token_verifier=verifier,
        auth=auth,
    )
    query_log = QueryLog(settings.query_log)

    @mcp.tool(
        title="Search ByJG documentation",
        description=(
            "Search the ByJG open source documentation and return the most "
            "relevant passages, each with its public URL. Combines semantic and "
            "keyword matching, so both natural-language questions ('how do I "
            "map a table to a class') and exact symbol names ('TableAttribute') "
            "work. Optionally narrow to a category (php, devops, js, ai, helm) or a "
            "project (micro-orm, restserver, docker-easy-haproxy, ...)."
        ),
    )
    def search_docs(
        query: str,
        limit: int = 0,
        category: str | None = None,
        project: str | None = None,
    ) -> str:
        limit = limit or settings.default_limit
        limit = max(1, min(limit, settings.max_limit))
        vector = runtime.embedder.embed_query(query)
        hits = runtime.store.search(
            query, vector, limit=limit, category=category, project=project
        )
        query_log.search(query, limit, category, project, hits)
        if not hits:
            scope = f" in {category or ''}/{project or ''}" if category or project else ""
            return f"No documentation found for {query!r}{scope}."
        header = f"Found {len(hits)} passage(s) for {query!r}:\n"
        return header + "\n".join(_format_hit(h, i) for i, h in enumerate(hits, 1))

    @mcp.tool(
        title="Read a documentation page",
        description=(
            "Return the full markdown of one documentation page, addressed by "
            "the `source` path reported in a search result (for example "
            "`php/micro-orm/active-record.md`). Use it when a search hit is "
            "relevant but truncated and you need the whole page."
        ),
    )
    def get_document(source_path: str) -> str:
        doc = runtime.store.get_document(source_path)
        query_log.document(source_path, found=doc is not None)
        if doc is None:
            return (
                f"No document at {source_path!r}. "
                "Use search_docs first and pass the `source` value it reports."
            )
        return f"# {doc.title}\n\nurl: {doc.url}\n\n{doc.text}"

    @mcp.tool(
        title="List documented projects",
        description=(
            "Inventory of everything indexed, grouped by category and project, "
            "with document and passage counts. Use it to discover which ByJG "
            "libraries have documentation before searching."
        ),
    )
    def list_projects() -> str:
        query_log.projects()
        projects = runtime.store.list_projects()
        if not projects:
            return "The index is empty. Run `byjg-docs-index build` first."
        stats = runtime.store.stats()
        lines = [
            f"{stats['documents']} documents, {stats['chunks']} passages indexed.\n"
        ]
        current = None
        for p in projects:
            if p.category != current:
                current = p.category
                lines.append(f"\n### {p.category}")
            name = p.project or "(top level)"
            lines.append(f"- {name}: {p.documents} docs, {p.chunks} passages")
        return "\n".join(lines)

    # HTTP-only endpoints. Under stdio there is no server to attach them to,
    # and the operator drives indexing with the CLI instead.
    if settings.transport != "stdio":
        # The job is the ability to (re)index; the webhook is merely one trigger
        # for it. Keeping them separate means a server deployed without a
        # webhook still builds its index instead of serving an empty one.
        job = runtime.sync_job()
        if settings.webhook_secret:
            register_webhook(mcp, job, settings.webhook_secret)
        register_health(mcp, runtime, job)

        # A fresh deployment has an empty volume and an empty index; build it in
        # the background so the service answers /healthz while it fills.
        if runtime.store.stats()["documents"] == 0:
            logger.info("index is empty; cloning and building in the background")
            job.trigger()

    return mcp


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    runtime = build_runtime()
    settings = runtime.settings
    server = build_server(runtime)
    try:
        if settings.transport == "stdio":
            server.run("stdio")
        else:
            if settings.auth_type == "none" and settings.host not in {"127.0.0.1", "localhost"}:
                # A deliberate choice (a trusted LAN, or an edge that
                # authenticates), so it runs -- but never silently.
                logger.warning(
                    "Serving UNAUTHENTICATED on %s:%s: anything that can reach "
                    "this port can read the index. Set BYJG_DOCS_AUTH_TYPE=bearer "
                    "with BYJG_DOCS_AUTH_TOKEN to require a token.",
                    settings.host,
                    settings.port,
                )
            server.run(
                "streamable-http",
                host=settings.host,
                port=settings.port,
                stateless_http=True,
            )
    finally:
        runtime.close()


if __name__ == "__main__":
    main()
