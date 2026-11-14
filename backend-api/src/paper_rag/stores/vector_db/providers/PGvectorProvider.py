"""pgvector store for the scoped RAG (Round 7 §7.4).

Table: chunk_id TEXT PK, text (embedded: header + text), raw_text (shown, read by the checker), embedding VECTOR(n),
tsv on raw_text, metadata JSONB. Indexes: HNSW (cosine) on the vector, GIN on metadata and on the tsvector.

A scope is {"src_ids": [...], "psis": [...], "kinds": [...]}: a chunk is in scope when its metadata src_id is in src_ids OR one of its psis is in psis
OR its kind is in kinds (kinds only widen a scope that already has src_ids or psis).
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field

from sqlalchemy import text as sql_text
from sqlalchemy.exc import DBAPIError

from ..VectorDBEnums import DistanceMetricEnums, PgvectorDistanceMetricEnums

logger = logging.getLogger(__name__)
_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass
class RetrievedDocument:
    chunk_id: str
    chunk_text: str          # raw_text: what the screen shows and the checker reads
    score: float
    metadata: dict = field(default_factory=dict)
    embedded_text: str = ""


def _table(name: str) -> str:
    if not _IDENT.match(name):
        raise ValueError(f"bad table name {name!r}")
    return name


def vec_literal(v) -> str:
    return "[" + ",".join(repr(float(x)) for x in v) + "]"


def scope_sql(scope: dict | None) -> tuple[str, dict]:
    """The WHERE fragment (and its parameters) for a scope; empty when there is no scope.
    `origin` ("serving" = tier 1, "docling" = parsed PDFs) restricts a search to one lane and is ANDed with the rest."""
    if not scope:
        return "", {}
    src_ids, psis, kinds = list(scope.get("src_ids") or []), list(scope.get("psis") or []), list(scope.get("kinds") or [])
    parts, params = [], {}
    if src_ids:
        parts.append("metadata->>'src_id' = ANY(CAST(:src_ids AS text[]))")
        params["src_ids"] = src_ids
    if psis:
        parts.append("metadata->'psis' ?| CAST(:psis AS text[])")
        params["psis"] = psis
    clauses = []
    if parts:
        if kinds:                                # kinds that belong to every scope (e.g. the challenge text, which names no PSI)
            parts.append("metadata->>'kind' = ANY(CAST(:kinds AS text[]))")
            params["kinds"] = kinds
        clauses.append("(" + " OR ".join(parts) + ")")
    if scope.get("origin"):
        clauses.append("metadata->>'text_origin' = :origin")
        params["origin"] = scope["origin"]
    return " AND ".join(clauses), params


class PGvectorProvider:
    def __init__(self, db_client, distance_metric: str = "cosine", index_threshold: int = 10000) -> None:
        self.db_client = db_client
        self.index_threshold = index_threshold
        self.distance_metric = PgvectorDistanceMetricEnums.COSINE.value if distance_metric == DistanceMetricEnums.COSINE.value else PgvectorDistanceMetricEnums.L2.value
        self.text_search_config = "english"

    # ── schema ────────────────────────────────────────────────────────────────
    async def connect(self) -> None:
        async with self.db_client() as s, s.begin():
            await s.execute(sql_text("create extension if not exists vector"))

    async def is_table_exists(self, table_name: str) -> bool:
        async with self.db_client() as s:
            r = await s.execute(sql_text("select 1 from pg_tables where tablename = :t"), {"t": table_name})
            return r.scalar_one_or_none() is not None

    async def delete_table(self, table_name: str) -> bool:
        t = _table(table_name)
        async with self.db_client() as s, s.begin():
            await s.execute(sql_text(f"drop table if exists {t}"))
        return True

    async def create_table(self, table_name: str, embed_size: int, do_reset: bool = False) -> bool:
        t = _table(table_name)
        if do_reset:
            await self.delete_table(t)
        if await self.is_table_exists(t):
            return False
        ops = self.distance_metric
        async with self.db_client() as s, s.begin():
            await s.execute(sql_text(f"""
                CREATE TABLE {t} (
                    chunk_id TEXT PRIMARY KEY,
                    text TEXT NOT NULL,
                    raw_text TEXT NOT NULL,
                    embedding VECTOR({int(embed_size)}),
                    tsv TSVECTOR GENERATED ALWAYS AS (to_tsvector('english', raw_text)) STORED,
                    metadata JSONB NOT NULL DEFAULT '{{}}'::jsonb
                )"""))
            await s.execute(sql_text(f"CREATE INDEX {t}_hnsw ON {t} USING hnsw (embedding {ops})"))
            await s.execute(sql_text(f"CREATE INDEX {t}_meta ON {t} USING gin (metadata)"))
            await s.execute(sql_text(f"CREATE INDEX {t}_tsv ON {t} USING gin (tsv)"))
            await s.execute(sql_text(f"CREATE INDEX {t}_src ON {t} ((metadata->>'src_id'))"))
        return True

    # ── writing ───────────────────────────────────────────────────────────────
    @staticmethod
    def _rows(chunks: list[dict]) -> list[dict]:
        return [
            {
                "chunk_id": c["chunk_id"], "text": c["text"], "raw_text": c["raw_text"],
                "embedding": vec_literal(c["embedding"]),
                "metadata": json.dumps(c.get("metadata") or {}, ensure_ascii=False),
            }
            for c in chunks
        ]

    async def replace_source(self, table_name: str, src_id: str, chunks: list[dict], batch_size: int = 200) -> int:
        """Delete every row of this source, then insert its chunks, in one transaction (idempotent: a re-run gives the same rows).
        Each chunk: chunk_id, text, raw_text, embedding, metadata (with src_id)."""
        t = _table(table_name)
        rows = self._rows(chunks)
        async with self.db_client() as s, s.begin():
            await s.execute(sql_text(f"DELETE FROM {t} WHERE metadata->>'src_id' = :src"), {"src": src_id})
            for i in range(0, len(rows), batch_size):
                await s.execute(sql_text(f"""
                    INSERT INTO {t} (chunk_id, text, raw_text, embedding, metadata)
                    VALUES (:chunk_id, :text, :raw_text, CAST(:embedding AS vector), CAST(:metadata AS jsonb))
                    ON CONFLICT (chunk_id) DO UPDATE SET text = EXCLUDED.text, raw_text = EXCLUDED.raw_text,
                        embedding = EXCLUDED.embedding, metadata = EXCLUDED.metadata"""), rows[i:i + batch_size])
        return len(rows)

    async def count_by_source(self, table_name: str) -> dict[str, int]:
        """{src_id: rows}: the resume check (a source whose count equals its chunk count is done)."""
        t = _table(table_name)
        async with self.db_client() as s:
            r = await s.execute(sql_text(f"SELECT metadata->>'src_id', count(*) FROM {t} GROUP BY 1"))
            return {k: n for k, n in r.fetchall()}

    async def count(self, table_name: str) -> int:
        t = _table(table_name)
        async with self.db_client() as s:
            return (await s.execute(sql_text(f"SELECT count(*) FROM {t}"))).scalar_one()

    # ── reading ───────────────────────────────────────────────────────────────
    @staticmethod
    def _docs(rows) -> list[RetrievedDocument]:
        return [RetrievedDocument(chunk_id=r[0], chunk_text=r[1], score=float(r[2]), metadata=r[3] or {}, embedded_text=r[4] or "") for r in rows]

    async def search_by_vector(self, table_name: str, vector, scope: dict | None = None, limit: int = 5) -> list[RetrievedDocument]:
        t = _table(table_name)
        where, params = scope_sql(scope)
        sql = f"""SELECT chunk_id, raw_text, 1 - (embedding <=> CAST(:v AS vector)) AS score, metadata, text
                  FROM {t} {'WHERE ' + where if where else ''} ORDER BY embedding <=> CAST(:v AS vector) LIMIT :limit"""
        async with self.db_client() as s, s.begin():
            # HNSW fetches its nearest candidates first and the WHERE filter is applied afterwards: a selective scope returned too few rows.
            # pgvector >= 0.8 keeps scanning until the filtered LIMIT is filled (iterative scan); ef_search widens the first pass.
            await s.execute(sql_text("SET LOCAL hnsw.iterative_scan = 'strict_order'"))
            await s.execute(sql_text("SET LOCAL hnsw.ef_search = 100"))
            await s.execute(sql_text("SET LOCAL hnsw.max_scan_tuples = 100000"))
            r = await s.execute(sql_text(sql), {"v": vec_literal(vector), "limit": limit, **params})
            return self._docs(r.fetchall())

    async def search_by_keyword(self, table_name: str, query: str, scope: dict | None = None, limit: int = 5,
                                max_candidates: int = 400, timeout_ms: int = 800) -> list[RetrievedDocument]:
        """websearch_to_tsquery on raw_text (not an OR of every word: that matches everything).
        The 'a or b or c' fallback of search.keyword_queries can still match most of the 17k PDF chunks, and ts_rank_cd then has to read
        every matching tsvector (2.5 s on the 1-GB server, which blew the 4 s budget). So only the first `max_candidates` matches are ranked
        (the keyword lane is 5 % of the fusion), and a statement_timeout turns a slow keyword search into [] instead of a lost answer."""
        t = _table(table_name)
        where, params = scope_sql(scope)
        q = "websearch_to_tsquery('english', :query)"
        sql = f"""SELECT chunk_id, raw_text, ts_rank_cd(tsv, {q}) AS score, metadata, text
                  FROM (SELECT chunk_id, raw_text, tsv, metadata, text FROM {t}
                        WHERE tsv @@ {q} {'AND ' + where if where else ''} LIMIT :cap) c
                  ORDER BY score DESC LIMIT :limit"""
        try:
            async with self.db_client() as s, s.begin():
                await s.execute(sql_text(f"SET LOCAL statement_timeout = {int(timeout_ms)}"))
                r = await s.execute(sql_text(sql), {"query": query, "limit": limit, "cap": int(max_candidates), **params})
                return self._docs(r.fetchall())
        except DBAPIError as e:
            if "statement timeout" in str(e):
                logger.info("keyword search over %d ms, skipped: %r", timeout_ms, query[:60])
                return []
            raise

    async def get_chunks(self, table_name: str, chunk_ids: list[str]) -> list[RetrievedDocument]:
        """Chunks by id (the neighbours of a kept chunk on the same page, Round 15 adaptive depth)."""
        t = _table(table_name)
        if not chunk_ids:
            return []
        async with self.db_client() as s:
            r = await s.execute(sql_text(f"SELECT chunk_id, raw_text, 0.0 AS score, metadata, text FROM {t} WHERE chunk_id = ANY(CAST(:ids AS text[]))"), {"ids": list(chunk_ids)})
            return self._docs(r.fetchall())

    async def scope_size(self, table_name: str, scope: dict | None) -> tuple[int, int]:
        """(chunks, distinct sources) inside a scope."""
        t = _table(table_name)
        where, params = scope_sql(scope)
        async with self.db_client() as s:
            r = await s.execute(sql_text(f"SELECT count(*), count(DISTINCT metadata->>'src_id') FROM {t} {'WHERE ' + where if where else ''}"), params)
            a, b = r.one()
            return a, b
