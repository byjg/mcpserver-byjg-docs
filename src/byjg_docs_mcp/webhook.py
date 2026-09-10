"""HTTP endpoints: the GitHub push webhook and the health check.

Registered on the same app as the MCP transport, so one process and one port
serve everything. GitHub gets an immediate 202 because a reindex takes longer
than its delivery timeout; the work itself lives in `sync.ReindexJob`.
"""

from __future__ import annotations

import hashlib
import hmac
import logging

from starlette.requests import Request
from starlette.responses import JSONResponse

from .runtime import Runtime
from .sync import ReindexJob

logger = logging.getLogger(__name__)


def verify_signature(payload: bytes, header: str | None, secret: str) -> bool:
    """Check GitHub's `X-Hub-Signature-256` header.

    Without this the endpoint would let anyone on the internet trigger a
    reindex, so an absent or malformed header is a rejection, never a pass.
    """
    if not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(header[len("sha256=") :], expected)


def register_health(mcp, runtime: Runtime, job: "ReindexJob | None" = None) -> None:
    """Attach `GET /healthz`.

    Registered whenever the HTTP transport is used, independently of the
    webhook: the container HEALTHCHECK probes this endpoint, so tying it to an
    unrelated setting would mark a perfectly healthy server as failing.
    """

    @mcp.custom_route("/healthz", methods=["GET"])
    async def healthz(_: Request) -> JSONResponse:
        stats = runtime.store.stats()
        return JSONResponse(
            {"status": "ok", "reindexing": bool(job and job.running), **stats}
        )


def register_webhook(mcp, job: ReindexJob, secret: str, docs_prefix: str = "docs/") -> None:
    """Attach `POST /webhook/github` to the server's HTTP app."""

    @mcp.custom_route("/webhook/github", methods=["POST"])
    async def github_webhook(request: Request) -> JSONResponse:
        body = await request.body()
        if not verify_signature(body, request.headers.get("X-Hub-Signature-256"), secret):
            return JSONResponse({"error": "invalid signature"}, status_code=401)

        event = request.headers.get("X-GitHub-Event", "")
        if event == "ping":
            return JSONResponse({"status": "pong"})
        if event != "push":
            return JSONResponse({"status": "ignored", "event": event})

        payload = await request.json()
        if not _touches_docs(payload, docs_prefix):
            return JSONResponse({"status": "ignored", "reason": "no docs changed"})

        started = job.trigger()
        return JSONResponse(
            {"status": "reindexing" if started else "already running"},
            status_code=202,
        )


def _touches_docs(payload: dict, prefix: str) -> bool:
    """Skip pushes that changed no documentation.

    The site repo also holds the Docusaurus app, CI config and blog; rebuilding
    the index for a package-lock bump is pure waste.
    """
    for commit in payload.get("commits", []):
        for key in ("added", "modified", "removed"):
            if any(path.startswith(prefix) for path in commit.get(key, [])):
                return True
    return False
