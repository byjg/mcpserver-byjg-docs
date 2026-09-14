"""How BYJG_DOCS_AUTH_TYPE decides who may call the HTTP transport."""

import anyio
import pytest
from conftest import make_doc
from pydantic import ValidationError

from byjg_docs_mcp.config import Settings
from byjg_docs_mcp.runtime import Runtime
from byjg_docs_mcp.server import StaticTokenVerifier, build_server


@pytest.fixture(autouse=True)
def no_real_clone(monkeypatch):
    """An empty index builds itself on boot; keep that off the network here."""
    monkeypatch.setattr("byjg_docs_mcp.sync.ReindexJob.trigger", lambda self: True)


def settings(tmp_path, **overrides):
    # _env_file=None: the developer's own .env must not decide what these
    # tests see -- it carries a real token.
    return Settings(
        _env_file=None,
        transport="http",
        public_url="http://127.0.0.1:2954",
        index_path=str(tmp_path / "i.db"),
        **overrides,
    )


def server(settings, store, embedder):
    return build_server(Runtime(settings=settings, embedder=embedder, store=store))


def test_none_is_the_default(tmp_path):
    assert settings(tmp_path).auth_type == "none"


def test_none_serves_without_authentication(tmp_path, store, embedder):
    built = server(settings(tmp_path, auth_type="none"), store, embedder)
    assert built.settings.auth is None, "no auth settings means no token is required"
    assert built._token_verifier is None


def test_bearer_requires_a_token_from_every_client(tmp_path, store, embedder):
    built = server(
        settings(tmp_path, auth_type="bearer", auth_token="tok"), store, embedder
    )
    assert built.settings.auth is not None
    assert str(built.settings.auth.resource_server_url) == "http://127.0.0.1:2954/"


def test_bearer_without_a_token_refuses_to_start(tmp_path, store, embedder):
    """Fails closed: a typo in the token must not silently open the server."""
    with pytest.raises(SystemExit) as exc:
        server(settings(tmp_path, auth_type="bearer", auth_token=""), store, embedder)
    assert "BYJG_DOCS_AUTH_TOKEN" in str(exc.value)


def test_a_token_is_ignored_under_none(tmp_path, store, embedder, caplog):
    """The combination is a misconfiguration, so it must be visible in the log."""
    built = server(
        settings(tmp_path, auth_type="none", auth_token="tok"), store, embedder
    )
    assert built.settings.auth is None
    assert "ignored" in caplog.text


def test_stdio_ignores_auth_entirely(tmp_path, store, embedder):
    """stdio is a pipe to the process the client spawned: nothing to authenticate,
    so `bearer` without a token is not an error there."""
    built = server(
        Settings(
            _env_file=None,
            transport="stdio",
            auth_type="bearer",
            auth_token="",
            index_path=str(tmp_path / "i.db"),
        ),
        store,
        embedder,
    )
    assert built.settings.auth is None


@pytest.mark.parametrize("value", ["", "basic", "Bearer token", "oauth"])
def test_unknown_auth_types_are_rejected(tmp_path, value):
    with pytest.raises(ValidationError, match="BYJG_DOCS_AUTH_TYPE"):
        settings(tmp_path, auth_type=value)


@pytest.mark.parametrize("value", ["BEARER", " bearer ", "None"])
def test_auth_type_is_case_and_space_insensitive(tmp_path, value):
    assert settings(tmp_path, auth_type=value).auth_type == value.strip().lower()


def test_verifier_accepts_only_the_configured_token(store, embedder):
    verifier = StaticTokenVerifier("right")
    assert anyio.run(verifier.verify_token, "wrong") is None
    granted = anyio.run(verifier.verify_token, "right")
    assert granted is not None and granted.scopes == ["read"]


async def _post_mcp(make_app, authorization=None):
    """One real request through the ASGI stack, inside the app's lifespan.

    The app is built per call: a session manager runs only once per instance.
    """
    import httpx

    app = make_app()

    headers = {
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
    }
    if authorization:
        headers["Authorization"] = authorization
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        # A loopback Host: the transport security layer answers 421 to anything else.
        async with httpx.AsyncClient(
            transport=transport, base_url="http://127.0.0.1:2954"
        ) as client:
            response = await client.post(
                "/mcp",
                json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                headers=headers,
            )
            return response.status_code


def test_bearer_rejects_requests_without_a_valid_token(tmp_path, store, embedder):
    """The end that matters: the HTTP layer, not just the configuration."""

    def app():
        return server(
            settings(tmp_path, auth_type="bearer", auth_token="tok"), store, embedder
        ).streamable_http_app()

    assert anyio.run(_post_mcp, app) == 401, "no Authorization header"
    assert anyio.run(_post_mcp, app, "Bearer wrong") == 401
    # Past the auth layer the MCP protocol takes over, and this bare request
    # has no session yet -- any answer but 401 means the token was accepted.
    assert anyio.run(_post_mcp, app, "Bearer tok") != 401


def test_none_lets_a_request_through_without_a_header(tmp_path, store, embedder):
    def app():
        return server(
            settings(tmp_path, auth_type="none"), store, embedder
        ).streamable_http_app()

    assert anyio.run(_post_mcp, app) != 401


def test_tools_still_answer_when_unauthenticated(tmp_path, store, embedder):
    """`none` changes who may call the tools, not what they return."""
    store.replace_document(make_doc("php/micro-orm/a.md", [("H", "soft delete")], embedder))
    built = server(settings(tmp_path, auth_type="none"), store, embedder)
    result = anyio.run(built.call_tool, "search_docs", {"query": "soft delete"})
    assert "Found 1 passage" in result.content[0].text
