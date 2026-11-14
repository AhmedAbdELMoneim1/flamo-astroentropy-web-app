# syntax=docker/dockerfile:1
# Backend image: the FastAPI server (token, catalogue, charts, documents, internal RAG) -- and, with another command, the LiveKit agent for self-hosting.
# Build from the PROJECT ROOT (the context needs data/serving.db):
#   docker build -f backend-api/Dockerfile -t <hub-user>/flame-backend-api:1.0 .
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.13.7 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PYTHONUNBUFFERED=1 PATH="/app/.venv/bin:$PATH" \
    FLAMEO_DB=/data/serving.db DOCS_ROOT=/data/docs
RUN useradd --create-home --uid 10001 app && mkdir -p /app /data/docs && chown app:app /app /data
WORKDIR /app
COPY backend-api/pyproject.toml backend-api/uv.lock backend-api/.python-version ./
RUN uv sync --frozen --no-dev --no-install-project
COPY backend-api/src ./src
COPY backend-api/vendor ./vendor
COPY data/serving.db /data/serving.db
RUN mkdir -p logs rag_cache && chown -R app:app /app/logs /app/rag_cache
USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=4s --retries=3 CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3).status == 200 else 1)"
CMD ["uvicorn", "src.api:app", "--host", "0.0.0.0", "--port", "8000"]
