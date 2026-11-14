#!/bin/bash
# Runs once, when the data volume is empty (docker-entrypoint-initdb.d). POSTGRES_USER / POSTGRES_DB are already created by the entrypoint.
set -euo pipefail
cd /seed && sha256sum -c paper_rag.dump.sha256 --quiet || { echo "paper_rag.dump is damaged"; exit 1; }
psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "CREATE EXTENSION IF NOT EXISTS vector;"
pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner --no-acl --exit-on-error /seed/paper_rag.dump
psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc "SELECT 'restored chunks_cohere: ' || count(*) FROM chunks_cohere;"
