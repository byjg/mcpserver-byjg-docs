from byjg_docs_mcp.chunking import (
    HARD_MAX_CHARS,
    chunk_markdown,
    parse_frontmatter,
    split_sections,
)


def test_frontmatter_is_separated_from_body():
    meta, body = parse_frontmatter("---\ntitle: Active Record\nsidebar_position: 5\n---\n\n# Doc\n")
    assert meta == {"title": "Active Record", "sidebar_position": "5"}
    assert body.strip() == "# Doc"


def test_body_without_frontmatter_is_untouched():
    meta, body = parse_frontmatter("# Doc\n\ntext")
    assert meta == {}
    assert body == "# Doc\n\ntext"


def test_quoted_frontmatter_values_are_unwrapped():
    meta, _ = parse_frontmatter('---\ntitle: "My Title"\n---\nbody')
    assert meta["title"] == "My Title"


def test_headings_build_a_nested_path():
    body = "# Top\n\nintro\n\n## Middle\n\nmid text\n\n### Leaf\n\nleaf text\n"
    paths = [s.heading_path for s in split_sections(body)]
    assert ["Top"] in paths
    assert ["Top", "Middle"] in paths
    assert ["Top", "Middle", "Leaf"] in paths


def test_hash_inside_fenced_code_is_not_a_heading():
    """A shell comment must not split the document."""
    body = "# Real\n\n```bash\n# this is a comment\n## and this one too\n```\n\ntail\n"
    sections = split_sections(body)
    assert len(sections) == 1
    assert sections[0].heading_path == ["Real"]
    assert "# this is a comment" in sections[0].text


def test_tilde_fences_are_honoured():
    body = "# Real\n\n~~~\n# not a heading\n~~~\n"
    assert len(split_sections(body)) == 1


def test_oversized_paragraph_is_split_below_the_hard_limit():
    """A single unbroken block (a table, a generated diagram) must still be cut."""
    body = "# Big\n\n" + ("x" * (HARD_MAX_CHARS * 3))
    chunks = chunk_markdown(body)
    assert len(chunks) > 1
    assert all(len(text) <= HARD_MAX_CHARS for _, text in chunks)


def test_long_prose_splits_on_paragraph_boundaries():
    paragraph = "Sentence about the mapper. " * 30  # ~810 chars
    body = "# Doc\n\n" + "\n\n".join([paragraph] * 6)
    chunks = chunk_markdown(body)
    assert len(chunks) > 1
    assert all(len(text) <= HARD_MAX_CHARS for _, text in chunks)
    # splitting on blank lines means no chunk begins mid-sentence
    assert all(text.strip().startswith("Sentence") for _, text in chunks)


def test_tiny_sections_are_merged_forward():
    body = "# A\n\nshort\n\n## B\n\n" + ("longer body text. " * 30)
    chunks = chunk_markdown(body)
    assert len(chunks) == 1, "a one-word section should not stand alone"
    assert "short" in chunks[0][1]


def test_merging_never_exceeds_the_hard_limit():
    body = "# A\n\ntiny\n\n## B\n\n" + ("y" * (HARD_MAX_CHARS - 100))
    assert all(len(text) <= HARD_MAX_CHARS for _, text in chunk_markdown(body))


def test_empty_body_produces_no_chunks():
    assert chunk_markdown("") == []
    assert chunk_markdown("\n\n   \n") == []
