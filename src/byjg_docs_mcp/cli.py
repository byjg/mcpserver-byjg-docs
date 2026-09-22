"""Command line entry point: build and inspect the index."""

from __future__ import annotations

import argparse
import sys
from collections import Counter

from .config import load_settings
from .querylog import read_log, weak_signals
from .runtime import build_runtime


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="byjg-docs-index", description="Build and inspect the ByJG docs index."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    build = sub.add_parser("build", help="index the docs tree (incremental by default)")
    build.add_argument(
        "--force", action="store_true", help="re-embed every document, ignoring hashes"
    )
    build.add_argument("--quiet", action="store_true", help="only print the summary")


    query = sub.add_parser("search", help="run a query against the index")
    query.add_argument("query")
    query.add_argument("-n", "--limit", type=int, default=5)
    query.add_argument("--category")
    query.add_argument("--project")

    sub.add_parser("stats", help="show what is indexed")

    queries = sub.add_parser(
        "queries", help="report on the query log (BYJG_DOCS_QUERY_LOG)"
    )
    queries.add_argument(
        "--weak", action="store_true", help="list the searches the documentation answered badly"
    )
    queries.add_argument("-n", "--limit", type=int, default=20)
    queries.add_argument("--log", help="log file to read (default: BYJG_DOCS_QUERY_LOG)")

    args = parser.parse_args(argv)
    if args.command == "queries":
        # Reads a file only: no index and no embedding model are needed.
        return report_queries(args.log or load_settings().query_log, args.weak, args.limit)

    runtime = build_runtime()
    try:
        if args.command == "build":
            report = runtime.sync_job().refresh(force=args.force)
            print(report.summary())
        elif args.command == "search":
            vector = runtime.embedder.embed_query(args.query)
            hits = runtime.store.search(
                args.query,
                vector,
                limit=args.limit,
                category=args.category,
                project=args.project,
            )
            if not hits:
                print("no results")
            for hit in hits:
                c = hit.chunk
                origin = f"vec#{hit.vector_rank or '-'} bm25#{hit.text_rank or '-'}"
                print(f"\n[{hit.score:.4f}] ({origin}) {c.title} > {c.heading_path}")
                print(f"  {c.url}")
                print(f"  {c.text[:200].strip()}...")
        elif args.command == "stats":
            print(runtime.store.stats())
            for p in runtime.store.list_projects():
                print(f"  {p.category}/{p.project or '-'}: {p.documents} docs, {p.chunks} chunks")
    finally:
        runtime.close()
    return 0


def report_queries(path: str, weak: bool, limit: int) -> int:
    if not path:
        print("no query log: set BYJG_DOCS_QUERY_LOG or pass --log", file=sys.stderr)
        return 2
    entries = read_log(path)
    if not entries:
        print(f"no entries in {path}")
        return 0

    if not weak:
        print(f"{len(entries)} calls, {entries[0].get('ts')} to {entries[-1].get('ts')}")
        for tool, count in Counter(e.get("tool") for e in entries).most_common():
            print(f"  {tool}: {count}")
        return 0

    signals = weak_signals(entries, limit)
    sections = [
        ("Searches with no hits", [f"{n}x  {q}" for q, n in signals.no_hits]),
        (
            "Weakest searches, lowest top_score first",
            [f"{score:.4f}  {q}" for score, q in signals.weakest],
        ),
        (
            "Best hit found only by the vector ranker",
            [f"{n}x  {q}" for q, n in signals.vector_only],
        ),
        (
            "Documents requested that do not exist",
            [f"{n}x  {source}" for source, n in signals.missing_documents],
        ),
    ]
    for title, lines in sections:
        print(title)
        for line in lines or ["(none)"]:
            print(f"  {line}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
