"""Configuration, from environment or a .env file (prefix: BYJG_DOCS_)."""

from __future__ import annotations

from pathlib import Path

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


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
    #: Folder inside the repository holding the documentation.
    docs_subdir: str = "docs"
    #: Set this to index a tree already on disk instead of cloning. Intended for
    #: local development against an editable checkout; leave it unset in any
    #: deployment, so GitHub stays the only source.
    docs_root: Path | None = None

    site_url: str = "https://opensource.byjg.com"
    docs_route: str = "docs"

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
    #: Bearer token required by the HTTP transport. Empty means unauthenticated,
    #: which is only ever appropriate on a loopback bind.
    auth_token: str = ""
    #: Externally reachable base URL (the Cloudflare Tunnel hostname, say).
    #: MCP's auth model advertises the resource under this URL, so it must
    #: match what clients actually connect to.
    public_url: str = "http://127.0.0.1:2954"

    # -- webhook --------------------------------------------------------
    #: Shared secret configured on the GitHub webhook. Empty disables the
    #: endpoint entirely rather than leaving it unauthenticated.
    webhook_secret: str = ""

    # -- retrieval ------------------------------------------------------
    default_limit: int = 8
    max_limit: int = 25


def load_settings() -> Settings:
    return Settings()
