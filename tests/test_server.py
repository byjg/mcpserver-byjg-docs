"""Which endpoints exist under which configuration, and when a build kicks off."""

import pytest

from byjg_docs_mcp.config import Settings
from byjg_docs_mcp.runtime import Runtime
from byjg_docs_mcp.server import build_server
from conftest import make_doc


@pytest.fixture(autouse=True)
def no_real_clone(monkeypatch):
    """Record boot-time refreshes instead of cloning from the network."""
    calls = []
    monkeypatch.setattr(
        "byjg_docs_mcp.sync.ReindexJob.trigger",
        lambda self: (calls.append(True), True)[1],
    )
    return calls


@pytest.fixture
def base(tmp_path):
    return Settings(
        _env_file=None,  # the developer's .env must not leak into the tests
        transport="http",
        auth_token="tok",
        public_url="http://127.0.0.1:2954",
        index_path=str(tmp_path / "i.db"),
    )


def routes(settings, store, embedder):
    server = build_server(Runtime(settings=settings, embedder=embedder, store=store))
    return {getattr(r, "path", None) for r in server.streamable_http_app().routes}


def test_health_is_served_without_a_webhook_secret(base, store, embedder):
    """Regression: the container HEALTHCHECK probes /healthz, so it must not
    depend on an unrelated webhook setting."""
    base.webhook_secret = ""
    paths = routes(base, store, embedder)
    assert "/healthz" in paths
    assert "/webhook/github" not in paths


def test_webhook_appears_once_a_secret_is_set(base, store, embedder):
    base.webhook_secret = "s3cr3t"
    paths = routes(base, store, embedder)
    assert {"/healthz", "/webhook/github"} <= paths


def test_tools_are_registered(base, store, embedder):
    import anyio

    server = build_server(Runtime(settings=base, embedder=embedder, store=store))
    names = {t.name for t in anyio.run(server.list_tools)}
    assert names == {"search_docs", "get_document", "list_projects"}


def test_empty_index_builds_on_boot_even_without_a_webhook(
    base, store, embedder, no_real_clone
):
    """Regression: the initial build used to be wired to the webhook, so a
    server deployed without one served an empty index forever."""
    base.webhook_secret = ""
    build_server(Runtime(settings=base, embedder=embedder, store=store))
    assert no_real_clone, "an empty index should start building on boot"


def test_populated_index_is_not_rebuilt_on_boot(base, store, embedder, no_real_clone):
    store.replace_document(make_doc("a.md", [("H", "text")], embedder))
    build_server(Runtime(settings=base, embedder=embedder, store=store))
    assert not no_real_clone, "a restart must not re-embed an index that is already built"


def test_stdio_starts_no_background_work(base, store, embedder, no_real_clone):
    """Under stdio the operator drives indexing with the CLI; a client spawning
    the server must not trigger a clone."""
    base.transport = "stdio"
    build_server(Runtime(settings=base, embedder=embedder, store=store))
    assert not no_real_clone
