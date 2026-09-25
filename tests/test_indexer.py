from pathlib import Path

import pytest

from byjg_docs_mcp.config import Source
from byjg_docs_mcp.indexer import DocsIndexer


@pytest.fixture
def docs_root(tmp_path):
    root = tmp_path / "docs"
    (root / "php" / "micro-orm").mkdir(parents=True)
    (root / "images").mkdir()
    (root / "php" / "micro-orm" / "README.md").write_text(
        "# MicroORM\n\n" + "Overview of the library. " * 10
    )
    (root / "php" / "micro-orm" / "active-record.md").write_text(
        "---\ntitle: Active Record\n---\n\n" + "The active record pattern. " * 10
    )
    (root / "php" / "README.md").write_text("# PHP\n\n" + "All PHP components. " * 10)
    (root / "images" / "ignored.md").write_text("# Ignored\n\n" + "x " * 60)
    (root / "php" / "stub.md").write_text("# Stub\n\nTBD")
    return root


@pytest.fixture
def indexer(docs_root, store, embedder):
    return DocsIndexer(
        docs_root=docs_root,
        store=store,
        embedder=embedder,
        site_url="https://opensource.byjg.com",
    )


def test_image_directories_are_skipped(indexer):
    names = {p.name for p in indexer.iter_files()}
    assert "ignored.md" not in names
    assert "active-record.md" in names


def test_url_for_a_regular_page_drops_the_extension(indexer):
    doc = indexer.build_document(indexer.docs_root / "php/micro-orm/active-record.md")
    assert doc.url == "https://opensource.byjg.com/docs/php/micro-orm/active-record"


def test_url_for_a_readme_is_the_folder_index(indexer):
    doc = indexer.build_document(indexer.docs_root / "php/micro-orm/README.md")
    assert doc.url == "https://opensource.byjg.com/docs/php/micro-orm/"


def test_frontmatter_slug_overrides_the_path(indexer, docs_root):
    target = docs_root / "php/micro-orm/custom.md"
    target.write_text("---\nslug: /custom-place\n---\n\n# Custom\n\n" + "body text. " * 20)
    assert indexer.build_document(target).url == "https://opensource.byjg.com/docs/custom-place"


def test_title_comes_from_frontmatter_then_h1(indexer, docs_root):
    assert indexer.build_document(docs_root / "php/micro-orm/active-record.md").title == "Active Record"
    assert indexer.build_document(docs_root / "php/micro-orm/README.md").title == "MicroORM"


def test_scope_is_derived_from_the_folder_layout(indexer, docs_root):
    doc = indexer.build_document(docs_root / "php/micro-orm/active-record.md")
    assert (doc.category, doc.project) == ("php", "micro-orm")
    top = indexer.build_document(docs_root / "php/README.md")
    assert (top.category, top.project) == ("php", "")


def test_placeholder_documents_are_not_indexed(indexer, docs_root):
    assert indexer.build_document(docs_root / "php/stub.md") is None


def test_full_run_reports_what_it_did(indexer):
    report = indexer.run()
    assert report.indexed == 3
    assert report.skipped_empty == 1
    assert report.chunks > 0


def test_second_run_skips_unchanged_documents(indexer):
    indexer.run()
    report = indexer.run()
    assert report.indexed == 0
    assert report.skipped_unchanged == 3


def test_modified_document_is_reindexed_in_place(indexer, docs_root, store):
    """Regression: replacing an existing document must not hit a UNIQUE constraint."""
    indexer.run()
    before = store.stats()["documents"]

    target = docs_root / "php/micro-orm/active-record.md"
    target.write_text("---\ntitle: Active Record\n---\n\n" + "Completely new body text. " * 20)

    report = indexer.run()
    assert report.indexed == 1
    assert store.stats()["documents"] == before
    assert "Completely new body" in store.get_document("docs/php/micro-orm/active-record.md").text


def test_force_reindexes_everything(indexer):
    indexer.run()
    report = indexer.run(force=True)
    assert report.indexed == 3
    assert report.skipped_unchanged == 0


def test_deleted_files_are_dropped_from_the_index(indexer, docs_root, store):
    indexer.run()
    (docs_root / "php/micro-orm/active-record.md").unlink()

    report = indexer.run()
    assert report.deleted == 1
    assert store.get_document("docs/php/micro-orm/active-record.md") is None


# -- several sources in one index ---------------------------------------------

BLOG = Source(name="blog", subdir="blog", route="blog", category="blog")


@pytest.fixture
def blog_root(tmp_path):
    """A Docusaurus blog folder: flat, dated, mostly with explicit slugs."""
    root = tmp_path / "blog"
    (root / "2025-09-26-simple-principles").mkdir(parents=True)
    (root / "2025-09-09-serializer.md").write_text(
        "---\nslug: serializer-superpowers\ntitle: Serializer\n---\n\n"
        + "What the serializer does. " * 10
    )
    (root / "2025-09-26-simple-principles" / "index.md").write_text(
        "---\nslug: simple-principles\ntitle: Simple Principles\n---\n\n"
        + "If it is hard it is wrong. " * 10
    )
    (root / "2025-10-01-no-slug.md").write_text(
        "# Undeclared\n\n" + "A post that never declared a slug. " * 10
    )
    return root


@pytest.fixture
def blog_indexer(blog_root, store, embedder):
    return DocsIndexer(
        docs_root=blog_root,
        store=store,
        embedder=embedder,
        site_url="https://opensource.byjg.com",
        source=BLOG,
    )


def test_source_paths_carry_their_source(indexer, blog_indexer, store):
    indexer.run()
    blog_indexer.run()

    paths = set(store.indexed_hashes())
    assert "docs/php/micro-orm/active-record.md" in paths
    assert "blog/2025-09-09-serializer.md" in paths
    assert "blog/2025-09-26-simple-principles/index.md" in paths


def test_indexing_a_second_source_keeps_the_first(indexer, blog_indexer, store):
    """Regression: the cleanup used to treat every other source as deleted."""
    indexer.run()
    docs_documents = store.stats()["documents"]

    report = blog_indexer.run()

    assert report.deleted == 0, "the docs are not stale just because the blog was walked"
    assert store.stats()["documents"] == docs_documents + 3
    assert store.get_document("docs/php/micro-orm/active-record.md") is not None


def test_a_refresh_still_removes_what_its_own_source_deleted(
    indexer, blog_indexer, blog_root, store
):
    indexer.run()
    blog_indexer.run()
    before = store.stats()["documents"]

    (blog_root / "2025-09-09-serializer.md").unlink()
    report = blog_indexer.run()

    assert report.deleted == 1
    assert store.stats()["documents"] == before - 1
    assert store.get_document("blog/2025-09-09-serializer.md") is None
    assert store.get_document("docs/php/micro-orm/active-record.md") is not None


def test_blog_posts_are_filed_under_the_blog_category(blog_indexer, store):
    blog_indexer.run()

    doc = store.get_document("blog/2025-09-09-serializer.md")
    assert (doc.category, doc.project) == ("blog", "")


def test_docs_keep_deriving_their_scope_from_the_folders(indexer, store):
    indexer.run()

    doc = store.get_document("docs/php/micro-orm/active-record.md")
    assert (doc.category, doc.project) == ("php", "micro-orm")


def test_each_source_links_to_its_own_route(indexer, blog_indexer, store):
    indexer.run()
    blog_indexer.run()

    assert store.get_document("docs/php/micro-orm/active-record.md").url == (
        "https://opensource.byjg.com/docs/php/micro-orm/active-record"
    )
    # An explicit slug wins, exactly as Docusaurus resolves it.
    assert store.get_document("blog/2025-09-09-serializer.md").url == (
        "https://opensource.byjg.com/blog/serializer-superpowers"
    )
    assert store.get_document("blog/2025-09-26-simple-principles/index.md").url == (
        "https://opensource.byjg.com/blog/simple-principles"
    )


def test_a_post_without_a_slug_is_served_under_its_date(blog_indexer, store):
    """Docusaurus routes an undeclared post as /blog/YYYY/MM/DD/name."""
    blog_indexer.run()

    assert store.get_document("blog/2025-10-01-no-slug.md").url == (
        "https://opensource.byjg.com/blog/2025/10/01/no-slug"
    )


def test_a_dated_folder_without_a_slug_is_served_under_its_date(blog_root, store, embedder):
    """The same rule for a post that is a folder with index.md."""
    post = blog_root / "2025-11-09-undeclared-folder"
    post.mkdir()
    (post / "index.md").write_text("# Undeclared\n\n" + "no slug anywhere here. " * 10)

    DocsIndexer(
        docs_root=blog_root, store=store, embedder=embedder,
        site_url="https://opensource.byjg.com", source=BLOG,
    ).run()

    assert store.get_document("blog/2025-11-09-undeclared-folder/index.md").url == (
        "https://opensource.byjg.com/blog/2025/11/09/undeclared-folder/"
    )


def test_documentation_paths_are_never_treated_as_dates(indexer, store):
    """Only blog posts are named after a date; a docs page must be untouched."""
    indexer.run()

    assert store.get_document("docs/php/micro-orm/active-record.md").url == (
        "https://opensource.byjg.com/docs/php/micro-orm/active-record"
    )
