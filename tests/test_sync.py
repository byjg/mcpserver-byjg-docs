"""Fetching from GitHub into a throwaway checkout."""

import subprocess
from pathlib import Path

import pytest

from byjg_docs_mcp.config import Settings, Source
from byjg_docs_mcp.runtime import Runtime
from byjg_docs_mcp.sync import CloneError, ReindexJob, clone_docs


@pytest.fixture
def origin(tmp_path):
    """A real git remote, so clone_docs is exercised against actual git."""
    bare = tmp_path / "origin.git"
    bare.mkdir()
    run = lambda a, c: subprocess.run(a, cwd=c, capture_output=True, check=True)
    run(["git", "init", "--bare", "-b", "master", "."], bare)

    work = tmp_path / "work"
    run(["git", "clone", str(bare), str(work)], tmp_path)
    run(["git", "config", "user.email", "t@t"], work)
    run(["git", "config", "user.name", "t"], work)
    (work / "docs").mkdir()
    (work / "docs" / "a.md").write_text("# A\n\n" + "body of the page. " * 20)
    (work / "blog").mkdir()
    (work / "blog" / "2025-09-09-post.md").write_text(
        "---\nslug: a-post\ntitle: A Post\n---\n\n" + "what I learned. " * 20
    )
    (work / "README.md").write_text("not documentation")
    run(["git", "add", "-A"], work)
    run(["git", "commit", "-m", "init"], work)
    run(["git", "push", "origin", "master"], work)
    return bare, work


class TestCloneDocs:
    def test_yields_the_docs_subdirectory(self, origin):
        bare, _ = origin
        with clone_docs(str(bare), "master", "docs") as docs:
            assert (docs / "a.md").exists()
            assert docs.name == "docs"

    def test_checkout_is_removed_afterwards(self, origin):
        bare, _ = origin
        with clone_docs(str(bare), "master", "docs") as docs:
            captured = docs
            assert captured.exists()
        assert not captured.exists(), "the temporary checkout must not survive"

    def test_checkout_is_removed_when_the_body_raises(self, origin):
        bare, _ = origin
        captured = None
        with pytest.raises(ValueError):
            with clone_docs(str(bare), "master", "docs") as docs:
                captured = docs
                raise ValueError("boom")
        assert captured is not None and not captured.exists()

    def test_unreachable_remote_is_reported(self, tmp_path):
        with pytest.raises(CloneError, match="git clone failed"):
            with clone_docs(str(tmp_path / "nope.git"), "master", "docs"):
                pass

    def test_missing_branch_is_reported(self, origin):
        bare, _ = origin
        with pytest.raises(CloneError, match="git clone failed"):
            with clone_docs(str(bare), "nonexistent-branch", "docs"):
                pass

    def test_missing_subdirectory_is_reported(self, origin):
        bare, _ = origin
        with pytest.raises(CloneError, match="does not exist"):
            with clone_docs(str(bare), "master", "no-such-folder"):
                pass


DOCS = Source(name="docs", subdir="docs", route="docs")
BLOG = Source(name="blog", subdir="blog", route="blog", category="blog")


class TestRefresh:
    def _runtime(self, store, embedder, **kw):
        kw.setdefault("sources", [DOCS])
        return Runtime(settings=Settings(**kw), embedder=embedder, store=store)

    def test_indexes_what_it_cloned(self, origin, store, embedder):
        bare, _ = origin
        rt = self._runtime(store, embedder, repo_url=str(bare), git_branch="master")
        report = ReindexJob(rt).refresh()

        assert report.indexed == 1
        assert store.stats()["documents"] == 1
        assert store.get_document("docs/a.md") is not None

    def test_second_refresh_is_incremental_despite_a_fresh_clone(
        self, origin, store, embedder
    ):
        """The whole point of discarding the checkout: content hashes, not git
        state, drive incremental indexing."""
        bare, _ = origin
        rt = self._runtime(store, embedder, repo_url=str(bare), git_branch="master")
        ReindexJob(rt).refresh()

        report = ReindexJob(rt).refresh()
        assert report.indexed == 0
        assert report.skipped_unchanged == 1

    def test_new_commit_is_picked_up(self, origin, store, embedder):
        bare, work = origin
        rt = self._runtime(store, embedder, repo_url=str(bare), git_branch="master")
        ReindexJob(rt).refresh()

        run = lambda a: subprocess.run(a, cwd=work, capture_output=True, check=True)
        (work / "docs" / "b.md").write_text("# B\n\n" + "a brand new page. " * 20)
        run(["git", "add", "-A"])
        run(["git", "commit", "-m", "add b"])
        run(["git", "push", "origin", "master"])

        report = ReindexJob(rt).refresh()
        assert report.indexed == 1
        assert store.stats()["documents"] == 2

    def test_force_reindexes_everything(self, origin, store, embedder):
        bare, _ = origin
        rt = self._runtime(store, embedder, repo_url=str(bare), git_branch="master")
        ReindexJob(rt).refresh()
        assert ReindexJob(rt).refresh(force=True).indexed == 1

    def test_local_docs_are_indexed_without_cloning(self, tmp_path, store, embedder):
        tree = tmp_path / "tree"
        tree.mkdir()
        (tree / "x.md").write_text("# X\n\n" + "local content. " * 20)
        rt = self._runtime(
            store, embedder, docs_root=tree, repo_url="https://invalid.invalid/nope"
        )
        # an unreachable repo_url proves nothing was fetched
        assert ReindexJob(rt).refresh().indexed == 1


class TestConcurrency:
    def test_a_second_trigger_is_dropped(self, store, embedder):
        rt = Runtime(settings=Settings(), embedder=embedder, store=store)
        job = ReindexJob(rt)
        job._running = True
        assert job.trigger() is False


class TestDocsRootBlank:
    """An empty BYJG_DOCS_DOCS_ROOT must mean "clone", not "index the cwd"."""

    @pytest.mark.parametrize("blank", ["", "   "])
    def test_blank_is_treated_as_unset(self, blank):
        s = Settings(docs_root=blank)
        assert s.docs_root is None
        assert s.local_docs is False

    def test_a_real_path_still_enables_local_mode(self, tmp_path):
        s = Settings(docs_root=tmp_path)
        assert s.local_docs is True


class TestSeveralSources:
    def _runtime(self, store, embedder, **kw):
        return Runtime(settings=Settings(**kw), embedder=embedder, store=store)

    def test_one_clone_feeds_every_source(self, origin, store, embedder):
        bare, _ = origin
        rt = self._runtime(
            store, embedder, repo_url=str(bare), git_branch="master", sources=[DOCS, BLOG]
        )

        report = ReindexJob(rt).refresh()

        assert report.indexed == 2, "the report totals every source"
        assert store.get_document("docs/a.md") is not None
        assert store.get_document("blog/2025-09-09-post.md") is not None

    def test_refreshing_twice_keeps_both_sources(self, origin, store, embedder):
        """Each source cleans up after itself and leaves the others alone."""
        bare, _ = origin
        rt = self._runtime(
            store, embedder, repo_url=str(bare), git_branch="master", sources=[DOCS, BLOG]
        )
        ReindexJob(rt).refresh()

        report = ReindexJob(rt).refresh()

        assert (report.indexed, report.deleted) == (0, 0)
        assert store.stats()["documents"] == 2

    def test_a_missing_folder_is_skipped_not_fatal(self, origin, store, embedder, caplog):
        bare, _ = origin
        absent = Source(name="guides", subdir="guides", route="guides")
        rt = self._runtime(
            store, embedder, repo_url=str(bare), git_branch="master", sources=[DOCS, absent]
        )

        report = ReindexJob(rt).refresh()

        assert report.indexed == 1, "the folder that exists is still indexed"
        assert "guides" in caplog.text

    def test_no_source_at_all_is_a_misconfiguration(self, origin, store, embedder):
        bare, _ = origin
        absent = Source(name="guides", subdir="guides", route="guides")
        rt = self._runtime(
            store, embedder, repo_url=str(bare), git_branch="master", sources=[absent]
        )

        with pytest.raises(CloneError, match="no configured source"):
            ReindexJob(rt).refresh()
