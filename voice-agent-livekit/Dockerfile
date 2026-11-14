# syntax=docker/dockerfile:1
# The LiveKit Cloud agent image. LiveKit Cloud builds it from the staged folder made by deploy.sh (src, vendor, lock file, serving.db) -- do not build it from here by hand.
# Rules of the Cloud build: unprivileged user, fixed WORKDIR, fixed start command, no secrets and no LIVEKIT_* variables in the image.
ARG PYTHON_VERSION=3.12
FROM ghcr.io/astral-sh/uv:python${PYTHON_VERSION}-bookworm-slim AS base
ENV PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
ARG UID=10001
RUN adduser --disabled-password --gecos "" --home "/home/appuser" --shell "/sbin/nologin" --uid "${UID}" appuser
WORKDIR /app
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --locked --no-dev --no-install-project
COPY src ./src
COPY vendor ./vendor
COPY serving.db /app/data/serving.db
RUN mkdir -p logs rag_cache && chown -R appuser:appuser /app
ENV PATH="/app/.venv/bin:$PATH" FLAMEO_DB=/app/data/serving.db
USER appuser
CMD ["python", "-m", "src.agent", "start"]
