"""Fetching the documentation from GitHub and reindexing it.

GitHub is the source of truth. Each refresh clones the repository into a
temporary directory, indexes it and throws the checkout away -- there is no
permanent working copy to keep in sync, corrupt, or reason about.

That costs a shallow clone (~25s) per refresh instead of a ~2s `git pull`, and
buys the removal of every failure mode a long-lived checkout brings: divergent
local state, ownership mismatches on a mounted volume, and a half-updated tree
after an interrupted fetch. Reindexing stays incremental regardless, because
the indexer keys on the SHA-256 of each file's content, which a fresh clone
reproduces exactly.
"""

from __future__ import annotations

import logging
import subprocess
import tempfile
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from .indexer import IndexReport
from .runtime import Runtime

logger = logging.getLogger(__name__)

CLONE_TIMEOUT = 900


class CloneError(RuntimeError):
    pass


@contextmanager
def clone_docs(repo_url: str, branch: str, subdir: str) -> Iterator[Path]:
    """Shallow-clone `repo_url` and yield the documentation directory.

    The checkout is removed when the block exits, including on failure.
    """
    with tempfile.TemporaryDirectory(prefix="byjg-docs-") as tmp:
        target = Path(tmp) / "repo"
        logger.info("cloning %s (%s)", repo_url, branch)
        result = subprocess.run(
            ["git", "clone", "--depth", "1", "--branch", branch, repo_url, str(target)],
            capture_output=True,
            text=True,
            timeout=CLONE_TIMEOUT,
        )
        if result.returncode != 0:
            raise CloneError(f"git clone failed: {result.stderr.strip()}")

        docs = target / subdir if subdir else target
        if not docs.is_dir():
            raise CloneError(f"{subdir!r} does not exist in {repo_url}")
        yield docs


class ReindexJob:
    """Serialises refreshes.

    A burst of webhook deliveries must not start overlapping clones, so a
    trigger arriving while one is running is dropped rather than queued -- the
    clone already in flight will pick up the newer commits anyway.
    """

    def __init__(self, runtime: Runtime) -> None:
        self.runtime = runtime
        self._lock = threading.Lock()
        self._running = False

    @property
    def running(self) -> bool:
        return self._running

    def trigger(self) -> bool:
        """Start a refresh in the background. False if one is already running."""
        with self._lock:
            if self._running:
                return False
            self._running = True
        threading.Thread(target=self._run, daemon=True).start()
        return True

    def refresh(self, force: bool = False) -> IndexReport:
        """Fetch and reindex, synchronously.

        When `docs_root` is configured explicitly the tree is indexed in place
        and nothing is cloned; that is the local development path.
        """
        settings = self.runtime.settings
        if settings.local_docs:
            logger.info("indexing %s in place", settings.docs_root)
            return self.runtime.indexer(settings.docs_root).run(force=force)

        with clone_docs(
            settings.repo_url, settings.git_branch, settings.docs_subdir
        ) as docs_root:
            return self.runtime.indexer(docs_root).run(force=force)

    def _run(self) -> None:
        try:
            report = self.refresh()
            logger.info("reindex complete: %s", report.summary())
        except Exception:
            logger.exception("reindex failed")
        finally:
            self._running = False
