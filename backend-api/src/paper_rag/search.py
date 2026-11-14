"""Scoped hybrid search + rerank (Round 7 §7.4).

    vector top-k  +  keyword top-k  ->  reciprocal-rank fusion  ->  Cohere rerank if a Cohere key exists (else the fused order)

Every stage is returned so the retrieval log can show it. A Gemini reranker is not used: it would not fit the 4-second budget.
"""

from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass, field

from src.paper_rag.stores.vector_db.providers.PGvectorProvider import PGvectorProvider, RetrievedDocument

DEEP_K = 120
STOP = set("a an the of in on at to for and or is are was were be been what which who how why does do did can could would should will with from by as it its this that these those i you me my we our your about into than then there their when where after before over under between not no yes tell show give please".split())


def content_words(q: str, n: int = 8) -> list[str]:
    seen, out = set(), []
    for w in re.findall(r"[A-Za-z0-9][A-Za-z0-9\-\.%]*", q.lower()):
        w = w.strip(".-")
        if w and w not in STOP and w not in seen:
            seen.add(w)
            out.append(w)
    return out[:n]


def keyword_queries(q: str) -> list[str]:
    """websearch_to_tsquery strings, strictest first: all content words, then 'a or b or c' (still websearch syntax)."""
    w = content_words(q)
    if not w:
        return []
    return [" ".join(w), " or ".join(w)] if len(w) > 1 else [w[0]]


def rrf(lists: list[tuple[list[RetrievedDocument], float]], k: int = 60) -> list[RetrievedDocument]:
    """Reciprocal-rank fusion of several ranked lists (list, weight)."""
    score: dict[str, float] = {}
    keep: dict[str, RetrievedDocument] = {}
    for docs, weight in lists:
        for rank, d in enumerate(docs, start=1):
            score[d.chunk_id] = score.get(d.chunk_id, 0.0) + weight / (k + rank)
            keep.setdefault(d.chunk_id, d)
    return [RetrievedDocument(d.chunk_id, d.chunk_text, score[cid], d.metadata, d.embedded_text) for cid, d in sorted(keep.items(), key=lambda kv: -score[kv[0]])]


@dataclass
class SearchResult:
    final: list[RetrievedDocument] = field(default_factory=list)
    vector: list[RetrievedDocument] = field(default_factory=list)
    keyword: list[RetrievedDocument] = field(default_factory=list)
    fused: list[RetrievedDocument] = field(default_factory=list)
    reranker: str = "rrf"
    ms: dict = field(default_factory=dict)
    candidates: int = 0          # distinct chunks that survived the scope filter (vector + keyword, before the fusion cut)


class Searcher:
    def __init__(self, store: PGvectorProvider, table: str, embedder, reranker=None, rrf_weights=(0.95, 0.05), lanes: bool = True, tier1_top: int = 6, pdf_top: int = 40, rerank_in: int = 50, rerank_timeout: float | None = None) -> None:
        """reranker: an object with `async rerank(query, docs, top_n)` (Cohere) or None for rank fusion."""
        self.store, self.table, self.embedder, self.reranker, self.w = store, table, embedder, reranker, rrf_weights
        self._qcache: dict[str, list[float]] = {}
        self._t: dict[str, int] = {}
        self.lanes, self.tier1_top, self.pdf_top, self.rerank_in = lanes, tier1_top, pdf_top, rerank_in
        import os
        self.rerank_timeout = rerank_timeout if rerank_timeout is not None else float(os.getenv("RAG_RERANK_DEADLINE", "1.2"))      # Round 12 item 1: its own deadline

    async def _fused(self, query: str, vec, scope: dict | None, k: int) -> tuple[list, list, list]:
        async def keyword():
            qs = keyword_queries(query)
            docs: list = []
            for q in qs:
                docs = await self.store.search_by_keyword(self.table, q, scope=scope, limit=k)
                if len(docs) >= 3:
                    return docs
            return docs
        async def timed(coro, key):
            t = time.monotonic()
            r = await coro
            self._t[key] = max(self._t.get(key, 0), round((time.monotonic() - t) * 1000))
            return r
        vec_docs, kw_docs = await asyncio.gather(timed(self.store.search_by_vector(self.table, vec, scope=scope, limit=k), "vector"), timed(keyword(), "keyword"))
        return rrf([(vec_docs, self.w[0]), (kw_docs, self.w[1])]), vec_docs, kw_docs

    async def search(self, query: str, scope: dict | None = None, top_n: int = 6, k: int = 20, lanes: bool | None = None, embed_timeout: float | None = None, deep: bool = False) -> SearchResult:
        """lanes (Round 9 §9.3): the verified tier-1 chunks (cards, references, challenge) and the PDF chunks are searched separately, then merged
        (top `tier1_top` + top `pdf_top`) before the rerank, so 17,000 PDF chunks cannot drown the cards.
        deep (Round 15 adaptive depth, second pass): vector and keyword top 120 in the same scope, the best 50 go to the rerank."""
        lanes = self.lanes if lanes is None else lanes
        res, t0 = SearchResult(), time.monotonic()
        vec = self._qcache.get(query)
        if vec is None:
            vec = self._qcache[query] = (await self.embedder.embed(query, task="query", timeout=embed_timeout))[0]
        res.ms["embed"] = round((time.monotonic() - t0) * 1000)
        t1 = time.monotonic()
        if lanes:
            pdf_top = DEEP_K if deep else self.pdf_top
            (f1, v1, k1), (f2, v2, k2) = await asyncio.gather(
                self._fused(query, vec, {**(scope or {}), "origin": "serving"}, 30 if deep else 10), self._fused(query, vec, {**(scope or {}), "origin": "docling"}, pdf_top))
            res.vector, res.keyword = v1 + v2, k1 + k2
            res.fused = (f1[: self.tier1_top] + f2[:pdf_top])[: self.rerank_in]
            res.candidates = len({d.chunk_id for d in res.vector + res.keyword})
        else:
            res.fused, res.vector, res.keyword = await self._fused(query, vec, scope, DEEP_K if deep else k)
            res.candidates = len({d.chunk_id for d in res.vector + res.keyword})
        res.ms["db"] = round((time.monotonic() - t1) * 1000)
        res.ms["vector"], res.ms["keyword"] = self._t.pop("vector", 0), self._t.pop("keyword", 0)
        t2 = time.monotonic()
        if self.reranker and res.fused:
            try:
                res.final = await asyncio.wait_for(self.reranker.rerank(query, res.fused[: self.rerank_in if lanes else 20], top_n=top_n), timeout=self.rerank_timeout)
                res.reranker = "cohere" if getattr(self.reranker, "ok", True) else "rrf (rerank unavailable)"   # a fallback order carries fusion scores, not Cohere scores
            except asyncio.TimeoutError:                                   # a slow rerank must not change the answer: the fusion order is used and the answer is still composed
                res.final = res.fused[:top_n]
                res.reranker = "rrf (rerank timeout → fusion)"
        else:
            res.final = res.fused[:top_n]
        res.ms["rerank"] = round((time.monotonic() - t2) * 1000)
        return res
