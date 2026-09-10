FROM python:3.12-slim

# git is a runtime dependency: each refresh clones the docs repo into a
# temporary directory.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git openssh-client ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Dependencies resolve in their own layer so code edits do not re-install them.
COPY pyproject.toml README.md ./
COPY src ./src
RUN uv sync --no-dev

ENV PATH="/app/.venv/bin:$PATH" \
    BYJG_DOCS_TRANSPORT=http \
    BYJG_DOCS_HOST=0.0.0.0 \
    BYJG_DOCS_PORT=8080 \
    BYJG_DOCS_INDEX_PATH=/data/index/byjg-docs.db \
    BYJG_DOCS_OLLAMA_URL=http://ollama:11434

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/healthz',timeout=4).status==200 else 1)"

CMD ["byjg-docs-mcp"]
