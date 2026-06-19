ARG PYTHON_VERSION=3.14
ARG UV_VERSION=0.11.19

FROM ghcr.io/astral-sh/uv:${UV_VERSION}-python${PYTHON_VERSION}-trixie-slim AS builder

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

COPY pyproject.toml uv.lock README.md LICENSE ./
COPY src ./src

RUN uv build --no-sources --wheel \
    && uv venv /opt/timebase-mcp \
    && wheel="$(echo dist/timebase_mcp-*.whl)" \
    && uv pip install --no-config --python /opt/timebase-mcp/bin/python "${wheel}[all]"

FROM python:${PYTHON_VERSION}-slim-trixie AS runtime

ARG PYTHON_VERSION
ARG UV_VERSION

LABEL org.opencontainers.image.title="TimeBase MCP" \
    org.opencontainers.image.description="Model Context Protocol (MCP) server for TimeBase" \
    org.opencontainers.image.source="https://github.com/epam/TimeBase-MCP" \
    org.opencontainers.image.base.name="python:${PYTHON_VERSION}-slim-trixie"

ENV MCP_TRANSPORT=streamable-http \
    MCP_HOST=0.0.0.0 \
    MCP_PORT=8000 \
    PATH=/opt/timebase-mcp/bin:$PATH \
    PYTHONUNBUFFERED=1

RUN groupadd --system timebase-mcp \
    && useradd --system --gid timebase-mcp --create-home --home-dir /home/timebase-mcp timebase-mcp

COPY --from=builder /opt/timebase-mcp /opt/timebase-mcp

USER timebase-mcp
WORKDIR /home/timebase-mcp

EXPOSE 8000

ENTRYPOINT ["timebase-mcp"]
