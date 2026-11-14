"""Cohere embeddings and rerank through the key pool (a trial key: 100 calls a minute, 1,000 a month, per endpoint).

Unit of the pool = one API call (up to 96 texts). Model: embed-v4.0 at 1024 dimensions (pgvector's HNSW index handles up to 2000);
both models were chosen from the models list of the API. The document / query input types are Cohere's `search_document` / `search_query`.
"""

from __future__ import annotations

import asyncio
import logging

import httpx

from src.paper_rag.keypool import KeyPool, is_quota_error
from src.paper_rag.stores.vector_db.providers.PGvectorProvider import RetrievedDocument

logger = logging.getLogger("cohere")
BASE = "https://api.cohere.com/v2"
INPUT = {"document": "search_document", "query": "search_query"}


class CohereEmbedder:
    def __init__(self, pool: KeyPool, model: str = "embed-v4.0", dim: int = 1024, batch: int = 96, retries: int = 12, http: httpx.AsyncClient | None = None) -> None:
        self.pool, self.model, self.dim, self.batch, self.retries = pool, model, dim, min(batch, 96), retries
        self.http = http or httpx.AsyncClient(timeout=httpx.Timeout(60, connect=15))
        self.tokens = 0
        self.calls = 0
        self.last_key = None

    async def _batch(self, texts: list[str], task: str, timeout: float | None = None) -> list[list[float]]:
        last: BaseException | None = None
        for attempt in range(self.retries):
            # a query never sleeps inside the budget: when no key is free within `timeout` this raises TimeoutError and the caller falls back at once
            lease = await self.pool.acquire(units=1, tokens=sum(len(t) // 3 for t in texts), timeout=timeout)   # the trial key also has a tokens-per-minute limit
            self.last_key = self.pool.label(lease.index)
            try:
                r = await self.http.post(f"{BASE}/embed", headers={"Authorization": f"Bearer {lease.key}"}, json={
                    "model": self.model, "texts": texts, "input_type": INPUT[task], "embedding_types": ["float"], "output_dimension": self.dim}, **({"timeout": timeout} if timeout else {}))
                if r.status_code == 429:
                    last = RuntimeError("429: " + (r.json().get("message", "") if r.headers.get("content-type", "").startswith("application/json") else r.text)[:120])
                    self.pool.report_quota_error(lease, httpx.HTTPStatusError("429", request=r.request, response=r), default=30)
                    continue
                r.raise_for_status()
                vecs = r.json()["embeddings"]["float"]
                if len(vecs) != len(texts):
                    raise RuntimeError(f"{len(vecs)} vectors for {len(texts)} texts")
                self.calls += 1
                self.tokens += sum(len(t) // 3 for t in texts)
                return vecs
            except httpx.HTTPError as e:
                last = e
                await asyncio.sleep(min(2 ** attempt, 20))
        raise RuntimeError(f"cohere embedding failed after {self.retries} attempts: {last}")

    async def embed(self, texts: list[str] | str, task: str = "document", timeout: float | None = None) -> list[list[float]]:
        if isinstance(texts, str):
            texts = [texts]
        batches = [texts[i:i + self.batch] for i in range(0, len(texts), self.batch)]
        sem = asyncio.Semaphore(len(self.pool))
        async def run(b):
            async with sem:
                return await self._batch(b, task, timeout)
        return [v for part in await asyncio.gather(*(run(b) for b in batches)) for v in part]


class CohereRerank:
    """rerank(query, docs, top_n) over the pool; falls back to the given order if Cohere is unreachable (the caller's 4-second budget wins)."""

    def __init__(self, pool: KeyPool, model: str = "rerank-v3.5", http: httpx.AsyncClient | None = None, timeout: float = 3.0, with_header: bool = True) -> None:
        self.pool, self.model, self.timeout, self.with_header = pool, model, timeout, with_header
        self.http = http or httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=2.0))
        self.ok = True              # False when the last call fell back to the given order: its scores are NOT Cohere relevance scores
        self.last_key: str | None = None

    def document(self, d: RetrievedDocument) -> str:
        """What the reranker reads: the chunk header (investigation, document, page, section) + the text, so "BRE thesis, page 31" can match the question."""
        head = (d.embedded_text or "").split("\n", 1)[0]
        return f"{head}\n{d.chunk_text}" if self.with_header and head.startswith("[") else d.chunk_text

    async def rerank(self, query: str, documents: list[RetrievedDocument], top_n: int = 5) -> list[RetrievedDocument]:
        if not documents:
            return []
        self.ok = False
        try:
            lease = await self.pool.acquire(units=1, timeout=1.0)
            self.last_key = self.pool.label(lease.index)
            r = await self.http.post(f"{BASE}/rerank", headers={"Authorization": f"Bearer {lease.key}"}, json={
                "model": self.model, "query": query, "documents": [self.document(d) for d in documents], "top_n": min(top_n, len(documents))})
            if r.status_code == 429:
                self.pool.report_quota_error(lease, httpx.HTTPStatusError("429", request=r.request, response=r), default=30)
                return documents[:top_n]
            r.raise_for_status()
            self.ok = True
        except Exception as e:  # noqa: BLE001
            logger.warning("rerank unavailable (%s): the fused order is used", type(e).__name__)
            return documents[:top_n]
        return [RetrievedDocument(documents[x["index"]].chunk_id, documents[x["index"]].chunk_text, x["relevance_score"], documents[x["index"]].metadata, documents[x["index"]].embedded_text)
                for x in r.json()["results"]]
