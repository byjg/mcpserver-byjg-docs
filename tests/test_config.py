"""Configuring which folders of the site repository get indexed."""

import pytest

from byjg_docs_mcp.config import Settings


@pytest.fixture
def clean_env(tmp_path, monkeypatch):
    """Settings with nothing inherited: no .env in reach, no BYJG_DOCS_* set."""
    monkeypatch.chdir(tmp_path)
    for name in ("SOURCES", "DOCS_SUBDIR", "DOCS_ROUTE"):
        monkeypatch.delenv(f"BYJG_DOCS_{name}", raising=False)
    return monkeypatch


def test_the_documentation_and_the_blog_are_indexed_by_default(clean_env):
    sources = Settings().sources

    assert [(s.name, s.subdir, s.route, s.category) for s in sources] == [
        ("docs", "docs", "docs", ""),
        ("blog", "blog", "blog", "blog"),
    ]


def test_sources_can_be_described_as_json(clean_env):
    clean_env.setenv(
        "BYJG_DOCS_SOURCES",
        '[{"name": "guides", "subdir": "guides", "route": "g", "category": "guide"}]',
    )

    sources = Settings().sources

    assert len(sources) == 1
    assert (sources[0].name, sources[0].route, sources[0].prefix) == ("guides", "g", "guides/")


def test_the_deprecated_pair_still_pins_a_single_folder(clean_env, caplog):
    """An existing .env said "index this one folder"; it keeps meaning that."""
    clean_env.setenv("BYJG_DOCS_DOCS_SUBDIR", "documentation")
    clean_env.setenv("BYJG_DOCS_DOCS_ROUTE", "docs")

    sources = Settings().sources

    assert len(sources) == 1
    assert (sources[0].subdir, sources[0].route) == ("documentation", "docs")
    assert "deprecated" in caplog.text


def test_an_explicit_sources_wins_over_the_deprecated_pair(clean_env, caplog):
    clean_env.setenv("BYJG_DOCS_DOCS_SUBDIR", "documentation")
    clean_env.setenv("BYJG_DOCS_SOURCES", '[{"name": "docs", "subdir": "docs", "route": "docs"}]')

    sources = Settings().sources

    assert [s.subdir for s in sources] == ["docs"]
    assert "ignored" in caplog.text


def test_configuring_no_source_is_refused(clean_env):
    with pytest.raises(ValueError, match="nothing would be indexed"):
        Settings(sources=[])


def test_two_sources_may_not_share_a_name(clean_env):
    """They would share a source_path prefix and prune each other's rows."""
    from byjg_docs_mcp.config import Source

    with pytest.raises(ValueError, match="must be unique"):
        Settings(
            sources=[
                Source(name="same", subdir="docs", route="docs"),
                Source(name="same", subdir="blog", route="blog"),
            ]
        )


def test_a_name_that_is_not_a_path_segment_is_refused(clean_env):
    from byjg_docs_mcp.config import Source

    with pytest.raises(ValueError, match="source name"):
        Source(name="docs/nested", subdir="docs", route="docs")
