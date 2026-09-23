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
from .config import Source
from .embeddings import Embedder
from .stores import Chunk, IndexedDocument, VectorStore

H1_RE = re.compile(r"^#\s+(.*?)\s*#*$", re.MULTILINE)

#: Documents whose body is shorter than this are placeholders ("TBD" stubs).
#: Indexing them adds noise without adding an answer.
MIN_DOCUMENT_CHARS = 50

SKIP_DIRECTORIES = {"images", "img", "assets", "node_modules", ".git"}

#: Docusaurus files blog posts by date -- 2025-10-22-a-post.md, or a folder of
#: the same name holding index.md. A post that declares a `slug` is served at
#: /blog/<slug>; one that does not is served at /blog/2025/10/22/a-post. Both
#: shapes exist in the repository, so both rules are needed.
DATE_PREFIX_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})-(?P<name>.+)$")


@dataclass
class IndexReport:
    scanned: int = 0
    indexed: int = 0
    skipped_unchanged: int = 0
    skipped_empty: int = 0
    deleted: int = 0
    chunks: int = 0

    def __add__(self, other: "IndexReport") -> "IndexReport":
        """Totals across the sources of one refresh."""
        return IndexReport(
            scanned=self.scanned + other.scanned,
            indexed=self.indexed + other.indexed,
            skipped_unchanged=self.skipped_unchanged + other.skipped_unchanged,
            skipped_empty=self.skipped_empty + other.skipped_empty,
            deleted=self.deleted + other.deleted,
            chunks=self.chunks + other.chunks,
        )

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
        source: Source | None = None,
    ) -> None:
        self.docs_root = Path(docs_root).resolve()
        self.store = store
        self.embedder = embedder
        self.site_url = site_url.rstrip("/")
        self.source = source or Source(name="docs", subdir="docs", route="docs")
        self.docs_route = self.source.route.strip("/")

    # -- discovery ------------------------------------------------------

    def iter_files(self) -> Iterator[Path]:
        for path in sorted(self.docs_root.rglob("*")):
            if path.suffix.lower() not in {".md", ".mdx"} or not path.is_file():
                continue
            if SKIP_DIRECTORIES & set(path.relative_to(self.docs_root).parts):
                continue
            yield path

    def _relative(self, path: Path) -> str:
        """Path of a file in the index, prefixed with the source it came from.

        The prefix is what keeps two folders apart: `docs/php/index.md` and
        `blog/php/index.md` are different documents, and a refresh of one
        source can tell which rows are its own.
        """
        return f"{self.source.prefix}{path.relative_to(self.docs_root).as_posix()}"

    def _in_source(self, relative: str) -> str:
        """The part after the source prefix, as it sits in the folder."""
        return relative[len(self.source.prefix):]

    def _scope(self, relative: str) -> tuple[str, str]:
        """Derive (category, project) from the folder layout.

        `docs/php/micro-orm/active-record.md` -> ("php", "micro-orm"); a file
        sitting directly under a category has no project of its own. A source
        that forces a category (the blog) skips the derivation entirely.
        """
        if self.source.category:
            # A flat folder such as the blog: every post shares one category
            # and has no project of its own.
            return self.source.category, ""
        parts = self._in_source(relative).split("/")
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
        path = Path(self._in_source(relative))
        if path.stem.lower() in {"readme", "index"}:
            route = path.parent.as_posix()
            route = "" if route == "." else f"{route}/"
        else:
            route = path.with_suffix("").as_posix()
        return f"{self.site_url}/{self.docs_route}/{self._dated_route(route)}"

    @staticmethod
    def _dated_route(route: str) -> str:
        """Expand a `2025-10-22-a-post` segment into `2025/10/22/a-post`.

        That is where Docusaurus serves a blog post that declared no `slug`.
        Nothing else in the corpus is named after a date, so the shape of the
        name is enough to recognise one -- no per-source flag needed.
        """
        parts = route.split("/")
        for i, part in enumerate(parts):
            if match := DATE_PREFIX_RE.match(part):
                year, month, day, name = match.groups()
                parts[i : i + 1] = [year, month, day, name]
                break
        return "/".join(parts)

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
        # Only this source's rows: another folder's documents are not stale
        # just because they are absent from the tree being walked.
        known = (
            {}
            if force
            else {
                path: digest
                for path, digest in self.store.indexed_hashes().items()
                if path.startswith(self.source.prefix)
            }
        )
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
