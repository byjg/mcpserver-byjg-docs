import pytest

from byjg_docs_mcp.stores import Chunk, IndexedDocument
from conftest import make_doc


def test_roundtrip_document_and_chunks(store, embedder):
    doc = make_doc("a.md", [("H1", "soft delete pattern in the mapper")], embedder)
    store.replace_document(doc)

    assert store.stats() == {"documents": 1, "chunks": 1}
    got = store.get_document("a.md")
    assert got is not None and got.title == "a.md"
    assert store.indexed_hashes() == {"a.md": "h1"}


def test_search_finds_the_matching_chunk(store, embedder):
    store.replace_document(make_doc("a.md", [("H", "soft delete pattern")], embedder))
    store.replace_document(
        make_doc("b.md", [("H", "rabbitmq queue consumer")], embedder, content_hash="h2")
    )

    hits = store.search("soft delete", embedder.embed_query("soft delete"), limit=5)
    assert hits
    assert hits[0].chunk.source_path == "a.md"


def test_keyword_half_matches_exact_symbol_the_vector_half_misses(store, embedder):
    """The point of hybrid search: BM25 carries exact identifiers."""
    store.replace_document(
        make_doc("a.md", [("H", "Use the TableAttribute annotation here")], embedder)
    )
    store.replace_document(
        make_doc("b.md", [("H", "unrelated text about queues")], embedder, content_hash="h2")
    )

    hits = store.search("TableAttribute", embedder.embed_query("TableAttribute"), limit=5)
    top = hits[0]
    assert top.chunk.source_path == "a.md"
    assert top.text_rank == 1


def test_camelcase_query_matches_spaced_out_heading(store, embedder):
    """`TableAttribute` should find a page titled "Table Attributes"."""
    store.replace_document(
        make_doc("a.md", [("Table Attributes parameters", "how to configure them")], embedder)
    )
    hits = store.search("TableAttribute", embedder.embed_query("TableAttribute"), limit=5)
    assert [h.chunk.source_path for h in hits] == ["a.md"]


def test_replace_document_is_idempotent(store, embedder):
    doc = make_doc("a.md", [("H", "first"), ("H2", "second")], embedder)
    store.replace_document(doc)
    store.replace_document(doc)
    assert store.stats() == {"documents": 1, "chunks": 2}


def test_replace_document_drops_removed_chunks(store, embedder):
    store.replace_document(make_doc("a.md", [("H", "one"), ("H", "two")], embedder))
    store.replace_document(make_doc("a.md", [("H", "one")], embedder, content_hash="h2"))

    assert store.stats() == {"documents": 1, "chunks": 1}
    assert store.indexed_hashes()["a.md"] == "h2"
    # the vector and fts shadow tables must shrink too, not just `chunks`
    assert store.db.execute("select count(*) from chunks_vec").fetchone()[0] == 1
    assert store.db.execute("select count(*) from chunks_fts").fetchone()[0] == 1


def test_delete_documents_clears_every_table(store, embedder):
    store.replace_document(make_doc("a.md", [("H", "one"), ("H", "two")], embedder))
    assert store.delete_documents(["a.md"]) == 1
    assert store.stats() == {"documents": 0, "chunks": 0}
    assert store.db.execute("select count(*) from chunks_vec").fetchone()[0] == 0
    assert store.db.execute("select count(*) from chunks_fts").fetchone()[0] == 0


def test_delete_documents_with_empty_list_is_a_noop(store, embedder):
    store.replace_document(make_doc("a.md", [("H", "one")], embedder))
    assert store.delete_documents([]) == 0
    assert store.stats()["documents"] == 1


def test_filters_narrow_results(store, embedder):
    store.replace_document(
        make_doc("a.md", [("H", "shared topic text")], embedder, category="php", project="micro-orm")
    )
    store.replace_document(
        make_doc("b.md", [("H", "shared topic text")], embedder,
                 content_hash="h2", category="devops", project="nimbus")
    )

    vec = embedder.embed_query("shared topic")
    assert {h.chunk.source_path for h in store.search("shared topic", vec)} == {"a.md", "b.md"}
    assert [h.chunk.source_path for h in store.search("shared topic", vec, category="php")] == ["a.md"]
    assert [h.chunk.source_path for h in store.search("shared topic", vec, project="nimbus")] == ["b.md"]


def test_list_projects_groups_and_counts(store, embedder):
    store.replace_document(make_doc("a.md", [("H", "x")], embedder, project="micro-orm"))
    store.replace_document(
        make_doc("b.md", [("H", "y"), ("H", "z")], embedder, content_hash="h2", project="micro-orm")
    )
    store.replace_document(
        make_doc("c.md", [("H", "w")], embedder, content_hash="h3",
                 category="devops", project="nimbus")
    )

    by_key = {(p.category, p.project): p for p in store.list_projects()}
    assert by_key[("php", "micro-orm")].documents == 2
    assert by_key[("php", "micro-orm")].chunks == 3
    assert by_key[("devops", "nimbus")].chunks == 1


def test_missing_document_returns_none(store):
    assert store.get_document("nope.md") is None


def test_search_on_empty_index_returns_nothing(store, embedder):
    assert store.search("anything", embedder.embed_query("anything")) == []


def test_query_with_only_punctuation_does_not_crash(store, embedder):
    """FTS5 would choke on raw operator characters; they must be sanitised."""
    store.replace_document(make_doc("a.md", [("H", "content here")], embedder))
    for weird in ['"', "-", "*", "AND OR", "a:b", "()"]:
        store.search(weird, embedder.embed_query(weird))


def test_vector_dimension_mismatch_is_rejected(store, embedder):
    doc = make_doc("a.md", [("H", "text")], embedder)
    doc.vectors = [[0.1, 0.2]]  # wrong width
    with pytest.raises(ValueError, match="expected"):
        store.replace_document(doc)


def test_chunk_vector_count_mismatch_is_rejected(store, embedder):
    doc = make_doc("a.md", [("H", "a"), ("H", "b")], embedder)
    doc.vectors = doc.vectors[:1]
    with pytest.raises(ValueError, match="chunks but"):
        store.replace_document(doc)


def test_reads_work_on_a_brand_new_index(tmp_path, embedder):
    """Regression: a fresh deployment must answer queries, not crash on a missing table."""
    from byjg_docs_mcp.stores import SqliteVecStore

    store = SqliteVecStore(tmp_path / "fresh.db", dimensions=embedder.dimensions)
    store.setup()
    try:
        assert store.stats() == {"documents": 0, "chunks": 0}
        assert store.list_projects() == []
        assert store.indexed_hashes() == {}
        assert store.search("anything", embedder.embed_query("anything")) == []
    finally:
        store.close()
