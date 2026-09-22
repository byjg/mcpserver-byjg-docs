"""The query log records what was asked and how well the index answered."""

import json

import anyio
import pytest
from conftest import make_doc

from byjg_docs_mcp import cli
from byjg_docs_mcp.config import Settings
from byjg_docs_mcp.querylog import read_log, weak_signals
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


# -- reading the log back: `byjg-docs-index queries` ---------------------------


def write_lines(path, *lines):
    path.write_text("".join(line + "\n" for line in lines), encoding="utf-8")


def test_read_log_includes_rotated_files_oldest_first(tmp_path):
    log = tmp_path / "queries.jsonl"
    write_lines(tmp_path / "queries.jsonl.2", '{"n": 1}')
    write_lines(tmp_path / "queries.jsonl.1", '{"n": 2}', "{half written")
    write_lines(log, '{"n": 3}')

    assert [e["n"] for e in read_log(log)] == [1, 2, 3], "a broken line must not hide the rest"


def test_read_log_of_a_file_that_does_not_exist_is_empty(tmp_path):
    assert read_log(tmp_path / "never-written.jsonl") == []


def test_weak_signals_counts_repeats_and_ranks_by_the_lowest_score():
    search = lambda q, hits, score=None, bm25=1: {  # noqa: E731
        "tool": "search_docs", "query": q, "hits": hits, "top_score": score, "top_bm25_rank": bm25
    }
    entries = [
        search("webhook signature", 0),
        search("webhook signature", 0),
        search("soft delete", 3, 0.0325),
        search("branch model", 5, 0.0200),
        search("branch model", 5, 0.0164),  # asked again, answered worse: the lowest counts
        search("MyCustomSymbol", 2, 0.0300, bm25=None),
        {"tool": "get_document", "source_path": "php/x/missing.md", "found": False},
        {"tool": "get_document", "source_path": "php/x/exists.md", "found": True},
    ]

    signals = weak_signals(entries)

    assert signals.no_hits == [("webhook signature", 2)]
    assert signals.weakest == [(0.0164, "branch model"), (0.03, "MyCustomSymbol"), (0.0325, "soft delete")]
    assert signals.vector_only == [("MyCustomSymbol", 1)]
    assert signals.missing_documents == [("php/x/missing.md", 1)]


def test_queries_weak_reports_what_the_server_logged(tmp_path, populated, embedder, capsys):
    """End to end: the report reads exactly what the server writes."""
    log = tmp_path / "logs" / "queries.jsonl"
    server = server_with_log(tmp_path, populated, embedder, log)
    call(server, "search_docs", query="soft delete", limit=3)
    call(server, "search_docs", query="soft delete", limit=3, project="no-such-project")
    call(server, "get_document", source_path="php/micro-orm/missing.md")

    assert cli.main(["queries", "--weak", "--log", str(log)]) == 0

    out = capsys.readouterr().out
    no_hits = out.split("Searches with no hits")[1].split("Weakest searches")[0]
    assert "1x  soft delete" in no_hits, "the filtered search found nothing"
    weakest = out.split("Weakest searches, lowest top_score first")[1].split("Best hit")[0]
    assert "soft delete" in weakest
    assert "1x  php/micro-orm/missing.md" in out.split("Documents requested that do not exist")[1]


def test_queries_summary_counts_calls_per_tool(tmp_path, populated, embedder, capsys):
    log = tmp_path / "queries.jsonl"
    server = server_with_log(tmp_path, populated, embedder, log)
    call(server, "search_docs", query="soft delete", limit=3)
    call(server, "list_projects")

    assert cli.main(["queries", "--log", str(log)]) == 0

    out = capsys.readouterr().out
    assert out.startswith("2 calls, ")
    assert "search_docs: 1" in out
    assert "list_projects: 1" in out


def test_queries_does_not_need_the_index(tmp_path, monkeypatch, capsys):
    """Reporting reads a file: it must work where no index or embedding model exists."""
    def no_runtime():
        raise AssertionError("queries must not build the runtime")

    monkeypatch.setattr(cli, "build_runtime", no_runtime)
    log = tmp_path / "queries.jsonl"
    write_lines(log, '{"tool": "search_docs", "query": "x", "hits": 0}')

    assert cli.main(["queries", "--weak", "--log", str(log)]) == 0
    assert "1x  x" in capsys.readouterr().out


def test_queries_without_a_log_configured_fails(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("BYJG_DOCS_QUERY_LOG", raising=False)
    monkeypatch.chdir(tmp_path)  # no .env file to pick a value up from

    assert cli.main(["queries"]) == 2
    assert "BYJG_DOCS_QUERY_LOG" in capsys.readouterr().err
