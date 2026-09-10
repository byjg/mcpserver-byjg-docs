"""Walk the docs tree, chunk it, embed it and persist it.

Reindexing is incremental: a document is re-embedded only when its content
hash changes, and documents deleted from disk are dropped from the index.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

from .chunking import chunk_markdown, parse_frontmatter
from .embeddings import Embedder
from .stores import Chunk, IndexedDocument, VectorStore

H1_RE = re.compile(r"^#\s+(.*?)\s*#*$", re.MULTILINE)

#: Documents whose body is shorter than this are placeholders ("TBD" stubs).
#: Indexing them adds noise without adding an answer.
MIN_DOCUMENT_CHARS = 50

SKIP_DIRECTORIES = {"images", "img", "assets", "node_modules", ".git"}


@dataclass
class IndexReport:
    scanned: int = 0
    indexed: int = 0
    skipped_unchanged: int = 0
    skipped_empty: int = 0
    deleted: int = 0
    chunks: int = 0

    def summary(self) -> str:
        return (
            f"scanned={self.scanned} indexed={self.indexed} "
            f"unchanged={self.skipped_unchanged} empty={self.skipped_empty} "
            f"deleted={self.deleted} chunks={self.chunks}"
        )


class DocsIndexer:
    def __init__(
        self,
        docs_root: Path,
        store: VectorStore,
        embedder: Embedder,
        site_url: str = "https://opensource.byjg.com",
        docs_route: str = "docs",
    ) -> None:
        self.docs_root = Path(docs_root).resolve()
        self.store = store
        self.embedder = embedder
        self.site_url = site_url.rstrip("/")
        self.docs_route = docs_route.strip("/")

    # -- discovery ------------------------------------------------------

    def iter_files(self) -> Iterator[Path]:
        for path in sorted(self.docs_root.rglob("*")):
            if path.suffix.lower() not in {".md", ".mdx"} or not path.is_file():
                continue
            if SKIP_DIRECTORIES & set(path.relative_to(self.docs_root).parts):
                continue
            yield path

    def _relative(self, path: Path) -> str:
        return path.relative_to(self.docs_root).as_posix()

    def _scope(self, relative: str) -> tuple[str, str]:
        """Derive (category, project) from the folder layout.

        `php/micro-orm/active-record.md` -> ("php", "micro-orm"); a file sitting
        directly under a category has no project of its own.
        """
        parts = relative.split("/")
        category = parts[0] if len(parts) > 1 else ""
        project = parts[1] if len(parts) > 2 else ""
        return category, project

    def _url(self, relative: str, slug: str | None) -> str:
        """Reproduce the Docusaurus route for a source file.

        README.md/index.md are folder indexes; everything else drops its
        extension. An explicit frontmatter `slug` overrides the whole path.
        """
        if slug:
            return f"{self.site_url}/{self.docs_route}/{slug.strip('/')}"
        path = Path(relative)
        if path.stem.lower() in {"readme", "index"}:
            route = path.parent.as_posix()
            route = "" if route == "." else f"{route}/"
        else:
            route = path.with_suffix("").as_posix()
        return f"{self.site_url}/{self.docs_route}/{route}"

    def _title(self, meta: dict[str, str], body: str, relative: str) -> str:
        if title := meta.get("title"):
            return title
        if match := H1_RE.search(body):
            return match.group(1).strip()
        return Path(relative).stem.replace("-", " ").replace("_", " ").title()

    # -- indexing -------------------------------------------------------

    def build_document(self, path: Path) -> IndexedDocument | None:
        raw = path.read_text(encoding="utf-8", errors="replace")
        meta, body = parse_frontmatter(raw)
        if len(body.strip()) < MIN_DOCUMENT_CHARS:
            return None

        relative = self._relative(path)
        category, project = self._scope(relative)
        title = self._title(meta, body, relative)
        url = self._url(relative, meta.get("slug"))

        chunks = [
            Chunk(
                source_path=relative,
                ordinal=ordinal,
                text=text,
                title=title,
                heading_path=heading_path,
                url=url,
                category=category,
                project=project,
            )
            for ordinal, (heading_path, text) in enumerate(chunk_markdown(body))
        ]
        if not chunks:
            return None

        return IndexedDocument(
            source_path=relative,
            content_hash=hashlib.sha256(raw.encode("utf-8")).hexdigest(),
            text=body.strip(),
            title=title,
            url=url,
            category=category,
            project=project,
            chunks=chunks,
        )

    def run(
        self,
        force: bool = False,
        progress: Callable[[str], None] | None = None,
    ) -> IndexReport:
        report = IndexReport()
        self.store.setup()
        known = {} if force else self.store.indexed_hashes()
        seen: set[str] = set()

        for path in self.iter_files():
            report.scanned += 1
            relative = self._relative(path)
            seen.add(relative)

            doc = self.build_document(path)
            if doc is None:
                report.skipped_empty += 1
                continue
            if known.get(relative) == doc.content_hash:
                report.skipped_unchanged += 1
                continue

            doc.vectors = self.embedder.embed_documents(
                [c.embedding_text() for c in doc.chunks]
            )
            self.store.replace_document(doc)
            report.indexed += 1
            report.chunks += len(doc.chunks)
            if progress:
                progress(f"indexed {relative} ({len(doc.chunks)} chunks)")

        stale = [p for p in known if p not in seen]
        if stale:
            report.deleted = self.store.delete_documents(stale)
            if progress:
                progress(f"removed {report.deleted} document(s) no longer on disk")

        return report
