"""Configuration, from environment or a .env file (prefix: BYJG_DOCS_)."""

from __future__ import annotations

import logging
import re

from pathlib import Path

from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

#: Ways the HTTP transport can authenticate a client.
AUTH_TYPES = {"none", "bearer"}

#: A source name is a path segment of every source_path it produces.
NAME_RE = re.compile(r"[A-Za-z0-9._-]+")


class Source(BaseModel):
    """One folder of the site repository, indexed into the shared index.

    A source is the unit everything else is scoped by: `name` prefixes every
    `source_path`, which keeps two folders from colliding on the same relative
    path and lets a refresh delete only what belongs to the folder it walked.
    """

    #: Prefix of every source_path from this folder, e.g. "docs/php/..." .
    name: str
    #: Folder inside the repository. "" indexes the repository root.
    subdir: str
    #: Route the site publishes it under: /docs/... or /blog/... .
    route: str
    #: Forces the category instead of deriving it from the folder layout.
    #: The reference docs nest as category/project/page.md; the blog is flat,
    #: so its posts would otherwise have no category to filter on.
    category: str = ""

    @property
    def prefix(self) -> str:
        return f"{self.name}/"

    @field_validator("name")
    @classmethod
    def _usable_as_a_path_prefix(cls, value: str) -> str:
        """A name becomes a path segment, so it has to look like one."""
        if not NAME_RE.fullmatch(value):
            raise ValueError(
                f"source name {value!r} must be letters, digits, dot, dash or "
                "underscore: it prefixes every source_path"
            )
        return value


DEFAULT_SOURCES = [
    Source(name="docs", subdir="docs", route="docs"),
    Source(name="blog", subdir="blog", route="blog", category="blog"),
]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="BYJG_DOCS_", env_file=".env", extra="ignore"
    )

    # -- corpus ---------------------------------------------------------
    # GitHub is the source of truth. Every refresh clones the repository into a
    # temporary directory, indexes it, and discards the checkout -- there is no
    # permanent working copy anywhere.
    repo_url: str = "https://github.com/byjg/byjg.github.io"
    git_branch: str = "master"
    #: Folders of the repository to index, as JSON in BYJG_DOCS_SOURCES:
    #:   [{"name": "docs", "subdir": "docs", "route": "docs"}]
    #: Defaults to the reference documentation plus the blog.
    sources: list[Source] = Field(default_factory=lambda: list(DEFAULT_SOURCES))
    #: Deprecated, folded into the first source: use `sources` instead.
    docs_subdir: str = ""
    #: Set this to index a tree already on disk instead of cloning. Intended for
    #: local development against an editable checkout; leave it unset in any
    #: deployment, so GitHub stays the only source.
    docs_root: Path | None = None

    site_url: str = "https://opensource.byjg.com"
    #: Deprecated, folded into the first source: use `sources` instead.
    docs_route: str = ""

    @model_validator(mode="after")
    def _sources_are_usable(self) -> "Settings":
        """Reject the two configurations that would break indexing silently.

        Nothing to index is a misconfiguration, not an empty corpus. Two
        sources sharing a name share a source_path prefix, which puts back the
        bug the prefix exists to prevent: each refresh would see the other's
        documents as deleted.
        """
        if not self.sources:
            raise ValueError("no sources configured: nothing would be indexed")
        names = [s.name for s in self.sources]
        duplicated = {n for n in names if names.count(n) > 1}
        if duplicated:
            raise ValueError(
                f"source names must be unique, got {sorted(duplicated)}: two "
                "sources sharing a name would delete each other's documents"
            )
        return self

    @model_validator(mode="after")
    def _fold_legacy_docs_folder(self) -> "Settings":
        """Keep BYJG_DOCS_DOCS_SUBDIR / _DOCS_ROUTE working for one release.

        They described the single folder this server used to index. Setting
        either now means "index just that one", which is what an existing .env
        meant when it was written.
        """
        if not (self.docs_subdir or self.docs_route):
            return self
        if "sources" in self.model_fields_set:
            # An explicit `sources` is the newer, clearer statement of intent:
            # a leftover variable in a .env file must not quietly undo it.
            logger.warning(
                "BYJG_DOCS_SOURCES and the deprecated BYJG_DOCS_DOCS_SUBDIR/"
                "_DOCS_ROUTE are both set; the deprecated pair is ignored."
            )
            return self
        subdir = self.docs_subdir or "docs"
        route = self.docs_route or subdir or "docs"
        object.__setattr__(
            self, "sources", [Source(name=subdir or "docs", subdir=subdir, route=route)]
        )
        logger.warning(
            "BYJG_DOCS_DOCS_SUBDIR/BYJG_DOCS_DOCS_ROUTE are deprecated; "
            "indexing only %r. Use BYJG_DOCS_SOURCES instead.",
            subdir,
        )
        return self

    @field_validator("docs_root", mode="before")
    @classmethod
    def _blank_means_unset(cls, value: object) -> object:
        """Treat an empty string as "not set".

        An unset variable and one set to "" are the same intent, but pydantic
        would coerce "" into Path("."), quietly switching the server into local
        mode and indexing the working directory instead of cloning.
        """
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @property
    def local_docs(self) -> bool:
        """True when indexing a tree on disk rather than cloning from GitHub."""
        return self.docs_root is not None

    # -- storage --------------------------------------------------------
    store_backend: str = "sqlite"
    #: File path for the sqlite backend; a DSN for a server-backed one.
    index_path: str = "./byjg-docs.db"

    # -- embeddings -----------------------------------------------------
    embedder_backend: str = "ollama"
    embedding_model: str = "nomic-embed-text"
    ollama_url: str = "http://localhost:11434"

    # -- server ---------------------------------------------------------
    #: "stdio" for a locally spawned server, "http" to expose it over the network.
    transport: str = "stdio"
    host: str = "127.0.0.1"
    port: int = 2954
    #: How the HTTP transport authenticates clients: "none" or "bearer".
    #: "none" serves everyone that can reach the port, which is appropriate on a
    #: loopback bind, on a trusted LAN, or behind an edge that authenticates
    #: (Cloudflare Access). Ignored under stdio, which has no HTTP layer.
    auth_type: str = "none"
    #: Bearer token clients must send. Required by auth_type="bearer", ignored
    #: by "none".
    auth_token: str = ""

    @field_validator("auth_type", mode="before")
    @classmethod
    def _known_auth_type(cls, value: object) -> object:
        if isinstance(value, str):
            normalised = value.strip().lower()
            if normalised not in AUTH_TYPES:
                raise ValueError(
                    f"BYJG_DOCS_AUTH_TYPE must be one of {', '.join(sorted(AUTH_TYPES))}"
                    f" (got {value!r})"
                )
            return normalised
        return value
    #: Externally reachable base URL (the Cloudflare Tunnel hostname, say).
    #: MCP's auth model advertises the resource under this URL, so it must
    #: match what clients actually connect to.
    public_url: str = "http://127.0.0.1:2954"
    #: File that records every tool call as a JSON line (query, hit count, best
    #: score), to find what the documentation does not cover. Empty disables it.
    query_log: str = ""

    # -- webhook --------------------------------------------------------
    #: Shared secret configured on the GitHub webhook. Empty disables the
    #: endpoint entirely rather than leaving it unauthenticated.
    webhook_secret: str = ""

    # -- retrieval ------------------------------------------------------
    default_limit: int = 8
    max_limit: int = 25


def load_settings() -> Settings:
    return Settings()
