ARG PYTHON_VERSION=3.14
ARG UV_VERSION=0.11.19

FROM ghcr.io/astral-sh/uv:${UV_VERSION}-python${PYTHON_VERSION}-trixie-slim AS builder

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/locust-venv

COPY pyproject.toml uv.lock ./
RUN uv venv /opt/locust-venv \
    && uv sync --frozen --no-dev --group stress --no-install-project

FROM python:${PYTHON_VERSION}-slim-trixie AS runtime

ARG PYTHON_VERSION

ENV PATH=/opt/locust-venv/bin:$PATH \
    PYTHONUNBUFFERED=1

COPY --from=builder /opt/locust-venv /opt/locust-venv
COPY tests/stress/locust/locustfile.py tests/stress/locust/mcp_streamable_http.py /stress/

WORKDIR /stress

EXPOSE 8089

ENTRYPOINT ["locust", "-f", "/stress/locustfile.py"]
