"""Command line entry point: build and inspect the index."""

from __future__ import annotations

import argparse
import sys

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

    args = parser.parse_args(argv)
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


if __name__ == "__main__":
    raise SystemExit(main())
