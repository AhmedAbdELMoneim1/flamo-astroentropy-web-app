#!/usr/bin/env bash
# Dump the RAG database (pgvector) from a running Postgres container to data/postgres/paper_rag.dump (custom format, compressed) + its sha256.
# The flame-postgres image restores this file on the first start of an empty volume. After a new dump, rebuild the image (docker compose build postgres).
#   backend-api/scripts/db_export.sh [container=flame-postgres-1] [user=paper] [db=paper_rag]
set -euo pipefail
C="${1:-flame-postgres-1}"; U="${2:-paper}"; D="${3:-paper_rag}"
DIR="$(cd "$(dirname "$0")/../../data/postgres" && pwd)"
docker exec "$C" pg_dump -U "$U" -d "$D" -Fc --no-owner --no-acl > "$DIR/paper_rag.dump"
(cd "$DIR" && ls -lh paper_rag.dump && sha256sum paper_rag.dump | tee paper_rag.dump.sha256)
