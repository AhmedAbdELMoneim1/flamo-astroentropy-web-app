"""Gemini embeddings through the key pool: document task type for chunks, query task type for questions.

Model: gemini-embedding-001 (chosen from the models.list of the API: gemini-embedding-2 folds a whole batch into ONE vector, so it
cannot embed chunks in batches). Output size 768 (`output_dimensionality`). The free tier counts every text of a batch as one request.
"""

from __future__ import annotations

import asyncio
import logging

from google import genai
from google.genai import types

from src.paper_rag.keypool import KeyPool, is_quota_error

logger = logging.getLogger("embed")
TASKS = {"document": "RETRIEVAL_DOCUMENT", "query": "RETRIEVAL_QUERY"}


def est_tokens(text: str) -> int:
    return max(1, len(text) // 3)      # a safe over-estimate: the TPM budget must never be exceeded


class GeminiEmbedder:
    def __init__(self, pool: KeyPool, model: str = "gemini-embedding-001", dim: int = 768, batch: int = 50, retries: int = 6) -> None:
        self.pool, self.model, self.dim, self.batch, self.retries = pool, model, dim, min(batch, 100), retries
        self._clients: dict[int, genai.Client] = {}
        self.tokens = 0
        self.calls = 0

    def _client(self, lease) -> genai.Client:
        c = self._clients.get(lease.index)
        if c is None:
            c = self._clients[lease.index] = genai.Client(api_key=lease.key)
        return c

    async def _batch(self, texts: list[str], task: str) -> list[list[float]]:
        tokens = sum(est_tokens(t) for t in texts)
        last: BaseException | None = None
        for attempt in range(self.retries):
            lease = await self.pool.acquire(units=len(texts), tokens=tokens)
            try:
                r = await self._client(lease).aio.models.embed_content(
                    model=self.model, contents=texts,
                    config=types.EmbedContentConfig(task_type=TASKS[task], output_dimensionality=self.dim),
                )
                vecs = [list(e.values) for e in r.embeddings]
                if len(vecs) != len(texts):
                    raise RuntimeError(f"{self.pool.label(lease.index)}: {len(vecs)} vectors for {len(texts)} texts")
                self.tokens += tokens
                self.calls += 1
                return vecs
            except Exception as e:  # noqa: BLE001
                last = e
                if is_quota_error(e):
                    self.pool.report_quota_error(lease, e)
                else:
                    logger.warning("%s: embed failed (%s), attempt %d", self.pool.label(lease.index), type(e).__name__, attempt + 1)
                    await asyncio.sleep(min(2 ** attempt, 20))
        raise RuntimeError(f"embedding failed after {self.retries} attempts: {type(last).__name__}")

    async def embed(self, texts: list[str] | str, task: str = "document", timeout: float | None = None) -> list[list[float]]:
        """All texts, in order. Batches run in parallel, one in flight per key, each inside its key's limits."""
        if isinstance(texts, str):
            texts = [texts]
        batches = [texts[i:i + self.batch] for i in range(0, len(texts), self.batch)]
        sem = asyncio.Semaphore(len(self.pool))
        async def run(b):
            async with sem:
                return await self._batch(b, task)
        out = await asyncio.gather(*(run(b) for b in batches))
        return [v for part in out for v in part]
