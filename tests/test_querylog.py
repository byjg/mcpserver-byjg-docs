"""The query log records what was asked and how well the index answered."""

import json

import anyio
import pytest
from conftest import make_doc

from byjg_docs_mcp.config import Settings
from byjg_docs_mcp.runtime import Runtime
from byjg_docs_mcp.server import build_server


@pytest.fixture
def populated(store, embedder):
    store.replace_document(
        make_doc(
            "php/micro-orm/softdelete.md",
            [("Soft Delete", "The DeletedAt trait adds soft delete support to a model")],
            embedder,
        )
    )
    return store


def server_with_log(tmp_path, store, embedder, log_path):
    settings = Settings(
        transport="stdio", index_path=str(tmp_path / "i.db"), query_log=str(log_path)
    )
    return build_server(Runtime(settings=settings, embedder=embedder, store=store))


def call(server, tool, **arguments):
    result = anyio.run(server.call_tool, tool, arguments)
    return result.content[0].text


def entries(log_path):
    return [json.loads(line) for line in log_path.read_text().splitlines()]


def test_search_with_hits_records_the_best_match(tmp_path, populated, embedder):
    log = tmp_path / "logs" / "queries.jsonl"  # parent does not exist yet
    server = server_with_log(tmp_path, populated, embedder, log)

    call(server, "search_docs", query="soft delete", limit=3)

    [entry] = entries(log)
    assert entry["tool"] == "search_docs"
    assert entry["query"] == "soft delete"
    assert entry["limit"] == 3
    assert entry["hits"] == 1
    assert entry["sources"] == ["php/micro-orm/softdelete.md"]
    assert entry["top_score"] > 0
    assert entry["top_bm25_rank"] == 1, "an exact keyword match must show in the BM25 rank"
    assert entry["ts"].endswith("+00:00")


def test_search_without_hits_is_recorded_as_a_miss(tmp_path, populated, embedder):
    """A miss is the signal the log exists for: the docs do not cover it."""
    log = tmp_path / "queries.jsonl"
    server = server_with_log(tmp_path, populated, embedder, log)

    answer = call(server, "search_docs", query="soft delete", category="devops")

    assert answer.startswith("No documentation found")
    [entry] = entries(log)
    assert entry["hits"] == 0
    assert entry["category"] == "devops"
    assert entry["top_score"] is None
    assert entry["sources"] == []


def test_get_document_records_whether_the_page_exists(tmp_path, populated, embedder):
    log = tmp_path / "queries.jsonl"
    server = server_with_log(tmp_path, populated, embedder, log)

    call(server, "get_document", source_path="php/micro-orm/softdelete.md")
    call(server, "get_document", source_path="php/micro-orm/missing.md")

    found, missing = entries(log)
    assert (found["tool"], found["found"]) == ("get_document", True)
    assert (missing["source_path"], missing["found"]) == ("php/micro-orm/missing.md", False)


def test_list_projects_is_recorded(tmp_path, populated, embedder):
    log = tmp_path / "queries.jsonl"
    server = server_with_log(tmp_path, populated, embedder, log)

    call(server, "list_projects")

    assert [e["tool"] for e in entries(log)] == ["list_projects"]


def test_nothing_is_written_when_disabled(tmp_path, populated, embedder):
    server = server_with_log(tmp_path, populated, embedder, "")

    call(server, "search_docs", query="soft delete")

    assert not any(tmp_path.rglob("*.jsonl"))


def test_a_log_that_cannot_be_written_does_not_break_search(tmp_path, populated, embedder):
    """Regression guard: a full disk or a volume with the wrong owner must cost
    the log entry, never the answer."""
    unwritable = tmp_path / "is-a-directory"
    unwritable.mkdir()
    server = server_with_log(tmp_path, populated, embedder, unwritable)

    answer = call(server, "search_docs", query="soft delete")

    assert answer.startswith("Found 1 passage")
