"""SQLite-backed store: vectors via sqlite-vec, keyword search via FTS5.

Both halves of the hybrid search live in the same file, so the whole index is
one `.db` you can copy, version or delete. At the corpus size this targets
(~10k chunks) a brute-force KNN scan costs single-digit milliseconds, which is
why no dedicated vector service is involved.
"""

from __future__ import annotations

import functools
import re
import sqlite3
import struct
import threading
from pathlib import Path

import sqlite_vec

from .base import (
    Chunk,
    Document,
    IndexedDocument,
    ProjectInfo,
    SearchHit,
    VectorStore,
)

# Reciprocal Rank Fusion constant. 60 is the value from the original RRF paper
# and behaves well when the two rankers disagree, which is exactly the case
# here: BM25 nails exact symbol names, the vector side nails paraphrases.
RRF_K = 60


def _synchronized(method):
    """Serialise access to the shared connection.

    SQLite tolerates a connection used from several threads, but not two
    overlapping transactions on it. The HTTP transport dispatches tool calls
    from a thread pool, so every public entry point takes this lock; it is
    reentrant because writes call internal helpers that take it too.
    """

    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)

    return wrapper


def _pack(vector: list[float]) -> bytes:
    return struct.pack(f"{len(vector)}f", *vector)


CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")


def _expand_token(token: str) -> str:
    """Expand an identifier so it also matches its spelled-out form.

    Documentation is inconsistent about symbols on purpose: the reference page
    for `TableAttribute` titles its section "Table Attributes parameters",
    while the code samples write `TableAttribute`. Searching one should find
    the other, so a CamelCase token becomes
    `"tableattribute" OR ("table" AND "attribute")` -- the AND keeps the parts
    from matching every page that merely says "table".
    """
    quoted = f'"{token}"'
    parts = [p for p in CAMEL_BOUNDARY.split(token) if len(p) > 1]
    if len(parts) < 2:
        return quoted
    conjunction = " AND ".join(f'"{p}"' for p in parts)
    return f"({quoted} OR ({conjunction}))"


def _fts_query(text: str) -> str:
    """Turn free text into a safe FTS5 MATCH expression.

    User queries contain characters FTS5 treats as operators (``-``, ``"``,
    ``*``, ``:``). Quoting each token individually neutralises them; joining
    with OR lets BM25 rank by how many tokens actually matched instead of
    dropping documents that miss one.
    """
    tokens = [t for t in "".join(c if c.isalnum() else " " for c in text).split() if t]
    return " OR ".join(_expand_token(t) for t in tokens)


class SqliteVecStore(VectorStore):
    def __init__(self, path: Path | str, dimensions: int = 768) -> None:
        self.path = Path(path)
        self.dimensions = dimensions
        self._db: sqlite3.Connection | None = None
        # The HTTP transport serves requests from a thread pool, so the
        # connection is shared across threads and guarded by this lock rather
        # than confined to the one that opened it.
        self._lock = threading.RLock()

    # -- connection -----------------------------------------------------

    @property
    def db(self) -> sqlite3.Connection:
        if self._db is None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            db = sqlite3.connect(self.path, check_same_thread=False)
            db.row_factory = sqlite3.Row
            db.enable_load_extension(True)
            sqlite_vec.load(db)
            db.enable_load_extension(False)
            db.execute("pragma journal_mode=WAL")
            db.execute("pragma foreign_keys=ON")
            self._db = db
        return self._db

    def close(self) -> None:
        if self._db is not None:
            self._db.close()
            self._db = None

    # -- schema ---------------------------------------------------------

    @_synchronized
    def setup(self) -> None:
        db = self.db
        db.executescript(
            f"""
            create table if not exists documents (
                source_path  text primary key,
                content_hash text not null,
                title        text not null,
                url          text not null,
                category     text not null,
                project      text not null,
                text         text not null
            );

            create table if not exists chunks (
                id           integer primary key,
                source_path  text not null references documents(source_path) on delete cascade,
                ordinal      integer not null,
                text         text not null,
                title        text not null,
                heading_path text not null,
                url          text not null,
                category     text not null,
                project      text not null,
                unique(source_path, ordinal)
            );
            create index if not exists chunks_by_source on chunks(source_path);
            create index if not exists chunks_by_scope on chunks(category, project);

            create virtual table if not exists chunks_fts using fts5(
                text, heading_path, title,
                content='chunks', content_rowid='id',
                tokenize='porter unicode61'
            );

            create virtual table if not exists chunks_vec using vec0(
                embedding float[{self.dimensions}] distance_metric=cosine
            );
            """
        )
        db.commit()

    # -- writes ---------------------------------------------------------

    @_synchronized
    def indexed_hashes(self) -> dict[str, str]:
        rows = self.db.execute("select source_path, content_hash from documents").fetchall()
        return {r["source_path"]: r["content_hash"] for r in rows}

    @_synchronized
    def replace_document(self, doc: IndexedDocument) -> None:
        if len(doc.chunks) != len(doc.vectors):
            raise ValueError(
                f"{doc.source_path}: {len(doc.chunks)} chunks but {len(doc.vectors)} vectors"
            )
        for vec in doc.vectors:
            if len(vec) != self.dimensions:
                raise ValueError(
                    f"{doc.source_path}: expected {self.dimensions}-d vectors, got {len(vec)}"
                )

        db = self.db
        with db:  # single transaction: the document is never half-replaced
            self._purge(doc.source_path)
            db.execute("delete from documents where source_path = ?", (doc.source_path,))
            db.execute(
                """insert into documents
                       (source_path, content_hash, title, url, category, project, text)
                   values (?, ?, ?, ?, ?, ?, ?)""",
                (
                    doc.source_path,
                    doc.content_hash,
                    doc.title,
                    doc.url,
                    doc.category,
                    doc.project,
                    doc.text,
                ),
            )
            for chunk, vector in zip(doc.chunks, doc.vectors):
                cur = db.execute(
                    """insert into chunks
                           (source_path, ordinal, text, title, heading_path, url, category, project)
                       values (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        chunk.source_path,
                        chunk.ordinal,
                        chunk.text,
                        chunk.title,
                        chunk.heading_path,
                        chunk.url,
                        chunk.category,
                        chunk.project,
                    ),
                )
                rowid = cur.lastrowid
                db.execute(
                    "insert into chunks_fts(rowid, text, heading_path, title) values (?, ?, ?, ?)",
                    (rowid, chunk.text, chunk.heading_path, chunk.title),
                )
                db.execute(
                    "insert into chunks_vec(rowid, embedding) values (?, ?)",
                    (rowid, _pack(vector)),
                )

    @_synchronized
    def delete_documents(self, source_paths: list[str]) -> int:
        if not source_paths:
            return 0
        db = self.db
        with db:
            removed = 0
            for path in source_paths:
                self._purge(path)
                removed += db.execute(
                    "delete from documents where source_path = ?", (path,)
                ).rowcount
        return removed

    def _purge(self, source_path: str) -> None:
        """Drop a document's chunks from all three tables.

        FTS5 and vec0 are external-content/virtual tables: neither participates
        in the foreign key cascade, so their rows must be deleted explicitly and
        before the `chunks` rows they point at disappear.
        """
        db = self.db
        rowids = [
            r["id"]
            for r in db.execute("select id from chunks where source_path = ?", (source_path,))
        ]
        for rowid in rowids:
            db.execute("delete from chunks_fts where rowid = ?", (rowid,))
            db.execute("delete from chunks_vec where rowid = ?", (rowid,))
        db.execute("delete from chunks where source_path = ?", (source_path,))

    # -- read -----------------------------------------------------------

    @_synchronized
    def search(
        self,
        query_text: str,
        query_vector: list[float],
        limit: int = 8,
        category: str | None = None,
        project: str | None = None,
    ) -> list[SearchHit]:
        # Over-fetch from each ranker: filters are applied after retrieval, and
        # RRF needs a deeper pool than the final cut to fuse meaningfully.
        pool = max(limit * 6, 60)
        vector_ids = self._vector_ranking(query_vector, pool)
        text_ids = self._text_ranking(query_text, pool)

        scores: dict[int, float] = {}
        vpos: dict[int, int] = {}
        tpos: dict[int, int] = {}
        for rank, rowid in enumerate(vector_ids, start=1):
            scores[rowid] = scores.get(rowid, 0.0) + 1.0 / (RRF_K + rank)
            vpos[rowid] = rank
        for rank, rowid in enumerate(text_ids, start=1):
            scores[rowid] = scores.get(rowid, 0.0) + 1.0 / (RRF_K + rank)
            tpos[rowid] = rank

        if not scores:
            return []

        rows = self._load_chunks(list(scores), category=category, project=project)
        hits = [
            SearchHit(
                chunk=chunk,
                score=scores[rowid],
                vector_rank=vpos.get(rowid),
                text_rank=tpos.get(rowid),
            )
            for rowid, chunk in rows.items()
        ]
        hits.sort(key=lambda h: h.score, reverse=True)
        return hits[:limit]

    def _vector_ranking(self, query_vector: list[float], pool: int) -> list[int]:
        if len(query_vector) != self.dimensions:
            raise ValueError(
                f"query vector has {len(query_vector)} dims, index has {self.dimensions}"
            )
        rows = self.db.execute(
            """select rowid from chunks_vec
               where embedding match ? and k = ?
               order by distance""",
            (_pack(query_vector), pool),
        ).fetchall()
        return [r["rowid"] for r in rows]

    def _text_ranking(self, query_text: str, pool: int) -> list[int]:
        match = _fts_query(query_text)
        if not match:
            return []
        rows = self.db.execute(
            """select rowid from chunks_fts
               where chunks_fts match ?
               order by bm25(chunks_fts, 1.0, 2.0, 2.0)
               limit ?""",
            (match, pool),
        ).fetchall()
        return [r["rowid"] for r in rows]

    def _load_chunks(
        self, rowids: list[int], category: str | None, project: str | None
    ) -> dict[int, Chunk]:
        placeholders = ",".join("?" * len(rowids))
        sql = f"select * from chunks where id in ({placeholders})"
        params: list[object] = list(rowids)
        if category:
            sql += " and category = ?"
            params.append(category)
        if project:
            sql += " and project = ?"
            params.append(project)
        return {
            r["id"]: Chunk(
                source_path=r["source_path"],
                ordinal=r["ordinal"],
                text=r["text"],
                title=r["title"],
                heading_path=r["heading_path"],
                url=r["url"],
                category=r["category"],
                project=r["project"],
            )
            for r in self.db.execute(sql, params)
        }

    @_synchronized
    def get_document(self, source_path: str) -> Document | None:
        row = self.db.execute(
            "select * from documents where source_path = ?", (source_path,)
        ).fetchone()
        if row is None:
            return None
        return Document(
            source_path=row["source_path"],
            title=row["title"],
            url=row["url"],
            category=row["category"],
            project=row["project"],
            text=row["text"],
        )

    @_synchronized
    def list_projects(self) -> list[ProjectInfo]:
        rows = self.db.execute(
            """select c.category,
                      c.project,
                      count(distinct c.source_path) as documents,
                      count(*)                      as chunks
               from chunks c
               group by c.category, c.project
               order by c.category, c.project"""
        ).fetchall()
        return [
            ProjectInfo(
                category=r["category"],
                project=r["project"],
                documents=r["documents"],
                chunks=r["chunks"],
            )
            for r in rows
        ]

    @_synchronized
    def stats(self) -> dict[str, int]:
        docs = self.db.execute("select count(*) from documents").fetchone()[0]
        chunks = self.db.execute("select count(*) from chunks").fetchone()[0]
        return {"documents": docs, "chunks": chunks}
