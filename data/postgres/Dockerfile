# syntax=docker/dockerfile:1
# Postgres + pgvector with the RAG index inside: on its FIRST start (empty data volume) it restores paper_rag.dump (17,424 chunks, table chunks_cohere).
# Build with this folder as the context:   docker build -t <hub-user>/flame-postgres:1.0 data/postgres
FROM pgvector/pgvector:0.8.6-pg18-trixie
COPY paper_rag.dump /seed/paper_rag.dump
COPY paper_rag.dump.sha256 /seed/paper_rag.dump.sha256
COPY initdb/10-restore.sh /docker-entrypoint-initdb.d/10-restore.sh
RUN chmod 0755 /docker-entrypoint-initdb.d/10-restore.sh
HEALTHCHECK --interval=10s --timeout=5s --retries=30 CMD pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB" || exit 1
