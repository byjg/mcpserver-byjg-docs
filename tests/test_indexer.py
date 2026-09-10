from pathlib import Path

import pytest

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
    assert "Completely new body" in store.get_document("php/micro-orm/active-record.md").text


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
    assert store.get_document("php/micro-orm/active-record.md") is None
