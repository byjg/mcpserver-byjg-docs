import random
import re

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


def test_shorter_fence_inside_a_longer_one_does_not_close_it():
    """Regression: only the first three characters of the opening fence were kept."""
    body = "# Real\n\n````md\nbefore\n```\n# not a heading\n```\nafter\n````\n\ntail\n"
    sections = split_sections(body)
    assert [s.heading_path for s in sections] == [["Real"]]
    assert sections[0].text.endswith("````\n\ntail")


def test_fence_followed_by_text_does_not_close_a_block():
    """A closing fence stands alone; "```php" inside a block is part of the sample."""
    body = "# Real\n\n```\n```php\n# not a heading\n```\n"
    assert [s.heading_path for s in split_sections(body)] == [["Real"]]


def test_fence_of_the_other_character_does_not_close_a_block():
    body = "# Real\n\n~~~\n```\n# not a heading\n```\n~~~\n"
    assert [s.heading_path for s in split_sections(body)] == [["Real"]]


def test_indented_fences_are_honoured():
    body = "# Real\n\n- step\n\n  ```sh\n  # not a heading\n  ```\n"
    assert [s.heading_path for s in split_sections(body)] == [["Real"]]


def test_heading_after_a_deeply_indented_fence_survives():
    body = '# Documentation\n\n    ```php\n    echo "example";\n    ```\n\n# Another section\n\ntext\n'
    assert [s.heading_path for s in split_sections(body)] == [
        ["Documentation"],
        ["Another section"],
    ]


def test_fence_nested_in_a_list_item_stays_whole_across_blank_lines():
    """Fences inside list items and MDX tabs sit four or more spaces in; they are still fences."""
    prose = "Sentence about the install. " * 30  # ~840 chars
    commands = [f"    sudo apt install package-{i}" for i in range(40)]
    fence = "    ```bash\n" + "\n\n".join(commands) + "\n    ```"
    body = f"# Install\n\n{prose}\n\n{prose}\n\n1. Run it:\n\n{fence}\n\n2. Done.\n\n{prose}"

    chunks = [text for _, text in chunk_markdown(body)]
    assert len(chunks) > 1
    assert sum(fence in text for text in chunks) == 1, "the nested sample stays in one chunk"


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


def _fences(text):
    return [line for line in text.split("\n") if line.startswith(("```", "~~~"))]


def test_blank_line_inside_fenced_code_is_not_a_paragraph_break():
    """Regression: a long section was cut at a blank line in the middle of a sample."""
    prose = "Sentence about the mapper. " * 30  # ~810 chars
    statements = [f"$step{i} = $repository->get({i});" for i in range(30)]
    code = "```php\n" + "\n\n".join(statements) + "\n```"
    body = f"# Doc\n\n{prose}\n\n{prose}\n\n{code}\n\n{prose}"

    chunks = [text for _, text in chunk_markdown(body)]
    assert len(chunks) > 1
    assert all(len(_fences(text)) % 2 == 0 for text in chunks)
    assert sum(code in text for text in chunks) == 1, "the sample stays in one chunk"


def test_oversized_fenced_block_is_closed_and_reopened_at_each_cut():
    statements = [f"$row{i} = $repository->get({i});" for i in range(400)]
    assert len("\n".join(statements)) > HARD_MAX_CHARS * 2
    body = "# Big\n\nIntro.\n\n```php\n" + "\n".join(statements) + "\n```\n"

    chunks = [text for _, text in chunk_markdown(body)]
    assert len(chunks) > 2
    assert all(len(text) <= HARD_MAX_CHARS for text in chunks)
    assert all(_fences(text) == ["```php", "```"] for text in chunks)
    # Nothing is lost or duplicated by the added fences.
    kept = [line for text in chunks for line in text.split("\n") if line.startswith("$row")]
    assert kept == statements


def test_oversized_line_inside_fenced_code_is_still_cut():
    body = "# Big\n\n```json\n" + ("x" * (HARD_MAX_CHARS * 3)) + "\n```\n"
    chunks = [text for _, text in chunk_markdown(body)]
    assert all(len(text) <= HARD_MAX_CHARS for text in chunks)
    assert all(len(_fences(text)) % 2 == 0 for text in chunks)
    assert sum(text.count("x") for text in chunks) == HARD_MAX_CHARS * 3


def test_oversized_long_fence_is_reopened_with_its_own_delimiter():
    statements = [f"$row{i} = $repository->get({i});" for i in range(300)]
    statements[150] = "```"  # a shorter fence, shown inside the sample
    body = "# Big\n\n````php\n" + "\n".join(statements) + "\n````\n"

    chunks = [text for _, text in chunk_markdown(body)]
    assert len(chunks) > 1
    assert all(text.startswith("````php\n") and text.endswith("\n````") for text in chunks)
    inner = [line for text in chunks for line in text.split("\n")[1:-1]]
    assert inner == statements


FENCE_LINE = re.compile(r"^\s*(`{3,}|~{3,})(.*)$")


def _ends_inside_a_fence(text):
    """An independent reading of the fence rules, so the chunker is not its own judge."""
    opened = None
    for line in text.split("\n"):
        match = FENCE_LINE.match(line)
        if not match:
            continue
        marker, rest = match.groups()
        if opened is None:
            opened = marker
        elif marker[0] == opened[0] and len(marker) >= len(opened) and not rest.strip():
            opened = None
    return opened is not None


def _random_document(rng):
    """Markdown mixing prose and fenced code, and the content it must preserve."""
    lines, payload, serial = [], [], 0

    def token():
        nonlocal serial
        serial += 1
        return f"t{serial}"

    for section in range(rng.randint(1, 5)):
        lines += [f"{'#' * rng.randint(1, 3)} Heading {section}", ""]
        for _ in range(rng.randint(1, 5)):
            if rng.random() < 0.4:
                prose = " ".join(token() for _ in range(rng.randint(3, 250)))
                lines += [prose, ""]
                payload.append(prose)
                continue
            char = rng.choice("`~")
            fence = char * rng.randint(3, 5)
            indent = rng.choice(["", "", "  "])
            lines.append(f"{indent}{fence}{rng.choice(['', 'php', 'bash'])}")
            for _ in range(rng.randint(1, 160)):
                roll = rng.random()
                if roll < 0.10:
                    lines.append("")  # a blank line inside the sample
                elif roll < 0.14:
                    other = "~" if char == "`" else "`"
                    lines.append(indent + other * rng.randint(3, 5))  # the other kind of fence
                elif roll < 0.18 and len(fence) > 3:
                    lines.append(indent + char * 3)  # too short to close this block
                elif roll < 0.22:
                    lines.append(f"{indent}{char * 3}php")  # a fence with text closes nothing
                else:
                    if roll < 0.24:
                        code = token() + "x" * rng.randint(HARD_MAX_CHARS, HARD_MAX_CHARS * 2)
                    elif roll < 0.34:
                        code = f"# {token()} is a comment, not a heading"
                    else:
                        code = f"{token()} = call({token()});"
                    lines.append(indent + code)
                    payload.append(code)
            lines += [indent + fence, ""]
    return "\n".join(lines), payload


def _content(lines):
    """Everything but fences and whitespace: what a cut must neither lose nor repeat."""
    kept = [line for line in lines if not FENCE_LINE.match(line)]
    return re.sub(r"\s+", "", "".join(kept))


def test_random_documents_keep_their_content_and_their_fences():
    rng = random.Random(42)  # fixed seed: a failure in CI reproduces locally
    for case in range(300):
        body, payload = _random_document(rng)
        chunks = [text for _, text in chunk_markdown(body)]

        assert all(len(text) <= HARD_MAX_CHARS for text in chunks), case
        assert not any(_ends_inside_a_fence(text) for text in chunks), case
        produced = [line for text in chunks for line in text.split("\n")]
        assert _content(produced) == _content(payload), case
