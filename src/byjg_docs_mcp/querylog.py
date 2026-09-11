"""Append-only log of tool calls, for finding the gaps in the documentation.

One JSON object per line. A search that returns nothing, or only weak matches,
points at something the documentation does not cover yet -- which is why the
query and the quality of its best hit are recorded together.

Off unless `BYJG_DOCS_QUERY_LOG` names a file.
"""

from __future__ import annotations

import json
import logging
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
