"""Append-only log of tool calls, for finding the gaps in the documentation.

One JSON object per line. A search that returns nothing, or only weak matches,
points at something the documentation does not cover yet -- which is why the
query and the quality of its best hit are recorded together.

Off unless `BYJG_DOCS_QUERY_LOG` names a file.
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .stores import SearchHit

MAX_BYTES = 10 * 1024 * 1024
BACKUP_COUNT = 5


class QueryLog:
    def __init__(self, path: str) -> None:
        self._handler: RotatingFileHandler | None = None
        if not path:
            return
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        # The handler alone, with no Logger in front: a logger would join the
        # global logging tree, echo every query to the root handler (stdout)
        # and be shared by every server built in the same process. The handler
        # brings rotation and thread safety on its own.
        self._handler = RotatingFileHandler(
            path, maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT, encoding="utf-8", delay=True
        )
        self._handler.setFormatter(logging.Formatter("%(message)s"))

    def search(
        self,
        query: str,
        limit: int,
        category: str | None,
        project: str | None,
        hits: list[SearchHit],
    ) -> None:
        top = hits[0] if hits else None
        self._write(
            "search_docs",
            query=query,
            limit=limit,
            category=category,
            project=project,
            hits=len(hits),
            top_score=round(top.score, 4) if top else None,
            top_vec_rank=top.vector_rank if top else None,
            top_bm25_rank=top.text_rank if top else None,
            sources=[h.chunk.source_path for h in hits],
        )

    def document(self, source_path: str, found: bool) -> None:
        self._write("get_document", source_path=source_path, found=found)

    def projects(self) -> None:
        self._write("list_projects")

    def _write(self, tool: str, **fields: object) -> None:
        if self._handler is None:
            return
        entry = {
            "ts": datetime.now(UTC).isoformat(timespec="seconds"),
            "tool": tool,
            **fields,
        }
        # A write failure (full disk, wrong permissions) is reported on stderr
        # by the handler and never reaches the caller: a broken log must not
        # break a search.
        self._handler.handle(logging.makeLogRecord({"msg": json.dumps(entry, ensure_ascii=False)}))


def read_log(path: str | Path) -> list[dict]:
    """Every entry in the log, oldest first, including the rotated files.

    A line that is not valid JSON -- half written when the process died -- is
    skipped: one broken line must not hide the rest of the report.
    """
    base = Path(path)
    files = [base.with_name(f"{base.name}.{n}") for n in range(BACKUP_COUNT, 0, -1)]
    entries: list[dict] = []
    for file in [*files, base]:
        if not file.exists():
            continue
        for line in file.read_text(encoding="utf-8").splitlines():
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return entries


@dataclass
class WeakSignals:
    """The four signals of a documentation gap, as described in self-hosting.md."""

    no_hits: list[tuple[str, int]]
    weakest: list[tuple[float, str]]
    vector_only: list[tuple[str, int]]
    missing_documents: list[tuple[str, int]]


def weak_signals(entries: list[dict], limit: int = 20) -> WeakSignals:
    """Where the documentation answered badly, repeated queries counted once.

    No threshold decides what "weak" means: the searches are ranked by their
    best score and the reader judges where the gap starts.
    """
    searches = [e for e in entries if e.get("tool") == "search_docs"]
    answered = [e for e in searches if e.get("hits")]

    lowest: dict[str, float] = {}
    for e in answered:
        score = e.get("top_score")
        if score is not None:
            lowest[e["query"]] = min(lowest.get(e["query"], score), score)

    return WeakSignals(
        no_hits=Counter(e["query"] for e in searches if e.get("hits") == 0).most_common(limit),
        weakest=sorted((score, query) for query, score in lowest.items())[:limit],
        vector_only=Counter(
            e["query"] for e in answered if e.get("top_bm25_rank") is None
        ).most_common(limit),
        missing_documents=Counter(
            e["source_path"]
            for e in entries
            if e.get("tool") == "get_document" and e.get("found") is False
        ).most_common(limit),
    )
