"""ask_sources (Round 6 §6.4, Round 8 §8.3 step 3): a question and the parameters Gemini heard -> sentences with sources, or one clarifying question.

    scope (serving.db) -> filtered hybrid search on the Cohere index -> Cohere rerank -> composer -> checker -> speak[] + sources[]

  clarify   the scope is empty, or the best rerank score is weak: one short question with 2-3 options the data covers
  fallback  Cohere, Postgres or the time budget failed: the serving.db full-text search (flameo search_text) answers
  budget    4 seconds in all; the composer gets what the search leaves, else the extractive sentence is used
Every call writes one line to logs/retrieval.jsonl (src/paper_rag/retrieval_log.py).
"""

from __future__ import annotations

import re
import asyncio
import os
import time
import uuid
from typing import Callable

from src.paper_rag import retrieval_log
from src.paper_rag.chunks import Vocab
from src.paper_rag.composer import Composer, check_sentences, extractive
from src.paper_rag.extract import merge
from src.paper_rag.rewrite import rewrite
from src.paper_rag.scope import ScopeResolver
from src.paper_rag.search import Searcher, SearchResult
from src.paper_rag.stores.vector_db.providers.PGvectorProvider import RetrievedDocument

KIND_LABEL = {"card": "Finding", "paper": "Paper", "doc": "NASA document", "challenge": "NASA Space Apps challenge text", "investigation": "Investigation profile", "reference": "Quoted reference"}
WEAK_RERANK = 0.65         # set from the Round 9 eval: covered questions score >= 0.76 (best rerank score of hits), uncovered probes 0.02-0.62; 0 of the 30 eval questions fall below it
TOP_FOR_COMPOSER = 5
SECOND_PASS_TOP = 8        # Round 15 adaptive depth: the second pass keeps the best 8 after the rerank
MIN_LEFT_S = 1.5           # ... and only runs when at least this much of the budget is left
FALLBACK_S = float(os.getenv("RAG_FALLBACK_S", "1.0"))   # hard cap on the serving.db fallback (the agent waits ~5 s in all)
MIN_CANDIDATES, MIN_PASSING = 10, 3
PARAMS = ("o2_pct", "pressure_kpa", "material", "fuel", "psi", "pillar", "scenario")


def source_of(d: RetrievedDocument, n: int) -> dict:
    """One entry of sources[]: the label, title, page and the link, all from the chunk's metadata (a link is never built by guessing)."""
    m = d.metadata
    kind = m.get("kind", "")
    label = "Table in a " + ("paper" if kind == "paper" else "NASA document") if m.get("type") == "table" and kind in ("paper", "doc") else KIND_LABEL.get(kind, kind)
    if m.get("type") == "figure":
        label = "Figure caption in a " + ("paper" if kind == "paper" else "NASA document")
    link = f"https://doi.org/{m['doi']}" if m.get("doi") else (m.get("download_url") or None)
    title = m.get("title")
    if kind in ("doc", "reference") or str(title or "").startswith("PSI-"):
        try:                                          # one label for a document everywhere (flameo's clean_title)
            from flameo_tools.tools import clean_title
            title = clean_title(title)
        except Exception:  # noqa: BLE001
            pass
    out = {"n": n, "chunk_id": d.chunk_id, "label": label, "kind": kind, "type": m.get("type"), "title": title, "page": m.get("page"), "section": m.get("section"),
           "link": link, "link_kind": "doi" if m.get("doi") else ("nasa_psi_download" if m.get("download_url") else None), "psis": m.get("psis", []), "generated": bool(m.get("generated", False))}
    if kind == "card":
        out["evidence"] = m.get("wording")
    if kind == "doc" and m.get("src_id") and not str(m["src_id"]).startswith(("ref:", "card:")):
        out["doc_id"], out["viewable"] = m["src_id"], True            # the viewer opens the local copy at the page
    out["quote"] = (d.chunk_text or "")[:240]
    return out


class AskSources:
    def __init__(self, searcher: Searcher, resolver: ScopeResolver, composer: Composer | None, vocab: Vocab, *, serving_call: Callable | None = None,
                 budget_s: float = 4.0, weak_rerank: float = WEAK_RERANK, extractor=None, adaptive: bool | None = None) -> None:
        self.s, self.resolver, self.composer, self.vocab, self.serving_call = searcher, resolver, composer, vocab, serving_call
        self.extractor = extractor            # parameters from the question text (src/paper_rag/extract.py); the model's own arguments win
        self.budget_s, self.weak = budget_s, weak_rerank
        import os
        self.adaptive = (os.getenv("ADAPTIVE_RETRIEVAL", "1") != "0") if adaptive is None else adaptive      # Round 15: the second pass; off for the on/off eval

    # ── helpers ──────────────────────────────────────────────────────────────
    def _options(self, res: SearchResult | None) -> list[str]:
        psis: list[str] = []
        for d in (res.final if res else []):
            for p in d.metadata.get("psis", [])[:1]:
                if p not in psis:
                    psis.append(p)
        return [f"{self.vocab.label.get(p, p)} ({p})" for p in psis[:3]]

    def _clarify(self, question: str, options: list[str], why: str) -> dict:
        if len(options) >= 2:
            q = "Which do you mean: " + ", ".join(options[:-1]) + " or " + options[-1] + "?"
        elif options:
            q = f"Do you mean {options[0]}?"
        else:
            q = "Could you say which experiment, material or oxygen level you mean?"
        return {"question": q, "options": options, "why": why}

    async def _fallback(self, question: str, why: str) -> dict:
        """The serving.db full-text search (flameo search_text): used when Cohere, Postgres or the time budget fails."""
        if self.serving_call is None:
            return {"speak": [], "sources": [], "reason": why + "; no serving.db fallback configured"}
        try:      # the voice agent stops waiting ~5 s after the question: a fallback that arrives later is never heard, so it gets a hard cap
            d = await asyncio.wait_for(asyncio.to_thread(self.serving_call, "search_text", query=question), FALLBACK_S)
        except (asyncio.TimeoutError, TimeoutError):
            return {"speak": [], "sources": [], "reason": why + f"; serving.db fallback over {FALLBACK_S:g} s"}
        speak = [x for x in list(d.get("speak", []))[:3] if not str(x).startswith("No passage")]        # "No passage ... matches" is not an answer
        rows = (d.get("table") or {}).get("rows", [])
        if d.get("sources"):                                  # flameo's own source list (clean titles, numbered)
            sources = [{**{k: v for k, v in x.items() if k != "src_id"}, "type": "text", "section": None, "generated": False,
                        "psis": x.get("psis") or ([rows[i]["psi"]] if i < len(rows) and rows[i].get("psi") else [])} for i, x in enumerate(d["sources"][:5])]
        else:
            sources = [{"n": i, "chunk_id": r.get("src"), "label": "Finding" if r.get("kind") == "card" else "NASA document or paper", "kind": r.get("kind"), "type": "text", "title": None, "page": r.get("page"),
                        "section": None, "link": f"https://doi.org/{r['src']}" if str(r.get("src", "")).startswith("10.") else None, "link_kind": "doi" if str(r.get("src", "")).startswith("10.") else None,
                        "psis": [r["psi"]] if r.get("psi") else [], "generated": False} for i, r in enumerate(rows[:3], 1)]
        if not speak:
            sources = []
        return {"speak": speak, "sources": sources, "reason": why}

    # ── adaptive retrieval depth (Round 15 §15.1 item 8) ─────────────────────
    def _stats(self, res: SearchResult | None) -> dict:
        final = res.final if res else []
        cohere = bool(res and res.reranker == "cohere")
        passing = len([d for d in final if d.score >= self.weak]) if cohere else len(final)
        return {"candidates": getattr(res, "candidates", 0) or len(res.fused if res else []), "passing": passing, "best_score": round(final[0].score, 4) if final else 0.0, "cohere": cohere}

    def _too_little(self, st: dict) -> list[str]:
        why = []
        if st["candidates"] < MIN_CANDIDATES:
            why.append(f"fewer than {MIN_CANDIDATES} candidates in the scope")
        if st["passing"] < MIN_PASSING:
            why.append(f"fewer than {MIN_PASSING} chunks pass the rerank cutoff")
        if st["cohere"] and st["best_score"] < self.weak:
            why.append("the best rerank score is below the cutoff")
        return why

    def _enough(self, st: dict) -> bool:
        return not self._too_little(st)

    @staticmethod
    def expand_query(rq: str, question: str) -> str:
        """The glossary synonyms and the key terms of the question (ignition -> ignite, ignition delay, autoignition)."""
        try:
            from flameo_tools.learn import find_term
            e = find_term(question)
        except Exception:  # noqa: BLE001
            e = None
        add = [t for t in ([e["term"], *e.get("aliases", [])] if e else []) if t.lower() not in rq.lower() and len(t) > 3]
        return (rq + " " + " ".join(add[:5])).strip() if add else rq

    async def _second_pass(self, rq: str, question: str, scope, scope_filter, res1, t0: float, entry: dict, why: list[str], accept_any: bool = False):
        """One extra pass, in this order until enough: deeper (top 120, rerank 50), a wider scope, an expanded query. Returns (res, scope_filter, how) or None. Never raises: a failure keeps pass 1."""
        best, best_st, how_best, flt = res1, self._stats(res1), None, scope_filter
        cur_filter, cur_q = scope_filter, rq
        log = entry.setdefault("retrieval", [])
        if log:
            log[0]["why"] = why
        for how in ("deeper", "scope", "query"):
            left = self.budget_s - (time.monotonic() - t0)
            if left < MIN_LEFT_S:
                break
            if how == "scope":
                wider = self.resolver.widen(scope) if hasattr(self.resolver, "widen") else None
                if wider is None or wider.empty:
                    continue
                cur_filter = wider.as_filter()
                entry["scope"]["widened_to"] = {"psis": wider.psis, "used": wider.used}
            elif how == "query":
                q2 = self.expand_query(rq, question)
                if q2 == rq:
                    continue
                cur_q = q2
                entry["expanded_query"] = q2
            t = time.monotonic()
            try:
                r = await asyncio.wait_for(self.s.search(cur_q, cur_filter, top_n=SECOND_PASS_TOP, embed_timeout=1.2, deep=True), max(0.5, left - 0.7))
            except Exception as e:  # noqa: BLE001  (a fake or a slow store: pass 1 stands)
                log.append({"pass": 2, "widened": how, "error": type(e).__name__})
                break
            st = self._stats(r)
            log.append({"pass": 2, "k": 120, "widened": how, **{k: v for k, v in st.items() if k != "cohere"}, "ms": round((time.monotonic() - t) * 1000)})
            new_chunks = {d.chunk_id for d in r.final} != {d.chunk_id for d in best.final}
            if (st["passing"], st["best_score"]) > (best_st["passing"], best_st["best_score"]) or how_best is None and (st["candidates"] > best_st["candidates"] or accept_any and new_chunks):
                best, best_st, how_best, flt = r, st, how, cur_filter
            if self._enough(st):
                break
        return (best, flt, how_best) if how_best else None

    async def _with_neighbours(self, chunks: list) -> list:
        """The kept chunks plus their neighbours on the same page (c-1, c+1), so a sentence cut by the chunker is whole. The citation stays the kept chunk's page; the numbers the checker allows are the whole text."""
        import re as _re
        store = getattr(self.s, "store", None)
        if store is None or not hasattr(store, "get_chunks"):
            return chunks
        want: dict[str, tuple[str | None, str | None]] = {}
        for d in chunks:
            m = _re.match(r"^(.*:c)(\d+)$", d.chunk_id)
            want[d.chunk_id] = (f"{m.group(1)}{int(m.group(2)) - 1}", f"{m.group(1)}{int(m.group(2)) + 1}") if m and not d.metadata.get("generated") else (None, None)
        ids = [x for pair in want.values() for x in pair if x]
        try:
            got = {x.chunk_id: x for x in await asyncio.wait_for(store.get_chunks(self.s.table, ids), 0.6)}
        except Exception:  # noqa: BLE001
            return chunks
        out = []
        for d in chunks:
            a, b = want[d.chunk_id]
            parts = [got[a].chunk_text if a in got and not got[a].metadata.get("generated") else "", d.chunk_text, got[b].chunk_text if b in got and not got[b].metadata.get("generated") else ""]
            out.append(RetrievedDocument(d.chunk_id, "\n".join(x for x in parts if x), d.score, d.metadata, d.embedded_text))
        return out

    # ── the call ─────────────────────────────────────────────────────────────
    async def ask(self, question: str, **params) -> dict:
        t0 = time.monotonic()
        rid = uuid.uuid4().hex[:8]
        model_params = {k: v for k, v in params.items() if k in PARAMS and v not in (None, "")}
        params, params_source = merge(model_params, self.extractor.extract(question) if self.extractor else {})
        lat: dict[str, int] = {}
        ms = lambda a: round((time.monotonic() - a) * 1000)  # noqa: E731
        entry: dict = {"ts": round(time.time(), 3), "request_id": rid, "question": question, "params": params, "params_source": params_source, "scope": {}, "vector": [], "keyword": [], "reranked": [],
                       "composer": {"sentences": []}, "outcome": "", "latency_ms": lat, "keys": {}}
        result: dict = {"request_id": rid, "question": question, "speak": [], "speak_refs": [], "sources": [], "clarify": None, "status": "ok", "scope": {}}

        t = time.monotonic()
        scope = self.resolver.resolve(**params)
        lat["scope"] = ms(t)
        scope_filter = scope.as_filter()
        try:
            n_chunks, n_sources = await asyncio.wait_for(self.s.store.scope_size(self.s.table, scope_filter), 1.0) if scope_filter else (None, None)
        except Exception:  # noqa: BLE001
            n_chunks = n_sources = None
        entry["scope"] = {"psis": scope.psis, "n_psis": len(scope.psis), "n_sources": n_sources, "n_chunks": n_chunks, "selected_by": scope.selected_by, "widened": scope.widened, "params_used": scope.used}
        result["scope"] = {"psis": scope.psis, "n_sources": n_sources, "selected_by": scope.selected_by}

        res: SearchResult | None = None
        try:
            # 1. an empty scope: the parameters match no investigation, so ask what is meant (one search without scope names the candidates)
            rq = rewrite(question)                      # the retrieval query carries the terms the papers use; the composer and the log keep the question
            if rq != question:
                entry["rewritten_query"] = rq
            if params and scope.empty:
                t = time.monotonic()
                res = await asyncio.wait_for(self.s.search(rq, None, top_n=5, embed_timeout=1.2), max(0.5, self.budget_s - 0.5))
                lat["search"] = ms(t)
                return self._finish(entry, result, t0, clarify=self._clarify(question, self._options(res), "the parameters match no investigation"), outcome="clarify", res=res)

            # 2. the search (embed, vector + keyword, fusion, Cohere rerank)
            t = time.monotonic()
            res = await asyncio.wait_for(self.s.search(rq, scope_filter, top_n=TOP_FOR_COMPOSER, embed_timeout=1.2), max(0.5, self.budget_s - 0.7))
            lat["search"] = ms(t)
            lat.update({f"search_{k}": v for k, v in res.ms.items()})        # embed, db, vector, keyword, rerank: where the time went
            entry["keys"]["embed"] = getattr(self.s.embedder, "last_key", None)
            pass2, st1 = False, self._stats(res)
            entry["retrieval"] = [{"pass": 1, **{k: v for k, v in st1.items() if k != "cohere"}, "k": 40, "widened": None, "ms": lat["search"]}]
            if not res.final or (self.adaptive and self._too_little(st1)):
                why = self._too_little(st1) if res.final else ["no excerpt found"]
                p2 = await self._second_pass(rq, question, scope, scope_filter, res, t0, entry, why) if self.adaptive else None
                if p2:
                    res, scope_filter, how2 = p2
                    pass2 = True
                    entry["retrieval_widened"] = how2
            if not res.final:
                return await self._fallback_result(entry, result, t0, question, "no excerpt found", res)
            best = res.final[0].score
            if res.reranker == "cohere" and best < self.weak:
                opts = self._options(res)
                return self._finish(entry, result, t0, clarify=self._clarify(question, opts, f"best rerank score {best:.2f} is below {self.weak}"), outcome="clarify", res=res)

            # 3. the composer, then the checker
            n_take = SECOND_PASS_TOP if pass2 else TOP_FOR_COMPOSER
            chunks = res.final[:n_take]
            ctx = await self._with_neighbours(chunks) if pass2 else chunks         # neighbours only on the second pass (the first pass is the eval-tuned one)
            left = self.budget_s - (time.monotonic() - t0)
            sents, info = ([], {"provider": None, "key": None, "reason": "no composer"}) if self.composer is None else await self.composer.compose(question, ctx, left - 0.2)
            lat["compose"] = ms(t0) - sum(v for k, v in lat.items() if k in ("scope", "search"))
            checked = check_sentences(sents, ctx) if sents else []
            kept = [s for s in checked if s["kept"]]
            how = info["provider"] or "extractive"
            composer_found_nothing = bool(info["provider"]) and (not sents or all(c["reason"] == "the model says the excerpts do not answer" for c in checked))
            if self.adaptive and not pass2 and (composer_found_nothing or not kept) and self.composer is not None and self.budget_s - (time.monotonic() - t0) >= MIN_LEFT_S + 0.8:
                p2 = await self._second_pass(rq, question, scope, scope_filter, res, t0, entry, ["the composer dropped every sentence"], accept_any=True)
                if p2:
                    res, scope_filter, how2 = p2
                    pass2 = True
                    entry["retrieval_widened"] = how2
                    chunks = res.final[:SECOND_PASS_TOP]
                    ctx = await self._with_neighbours(chunks)
                    left = self.budget_s - (time.monotonic() - t0)
                    sents, info = await self.composer.compose(question, ctx, left - 0.2)
                    checked = check_sentences(sents, ctx) if sents else []
                    kept = [s for s in checked if s["kept"]]
                    how = info["provider"] or "extractive"
                    composer_found_nothing = bool(info["provider"]) and (not sents or all(c["reason"] == "the model says the excerpts do not answer" for c in checked))
            if composer_found_nothing:                                # a working composer says the excerpts do not answer it: that is "not covered", never a guessed sentence
                checked = []
            elif not kept:                                            # the composer failed, or the checker dropped every sentence: the source's own sentence answers
                ext = extractive(chunks, n=1)
                reason = "no sentence survived the checker" if checked else (info["reason"] or "composer returned nothing")
                checked += [{**e, "reason": f"extractive fallback ({reason})"} for e in ext]
                kept, how = ext, "extractive"
            if composer_found_nothing:
                how = info["provider"]
                entry["reason"] = "the composer found no answer in the excerpts"
            entry["composer"] = {"provider": how, "model": None if how == "extractive" else ("gemini-3.5-flash-lite" if how == "gemini" else "qwen/qwen3.8-27b"), "key": info.get("key"), "fallback_reason": info.get("reason", ""), "sentences": checked}
            entry["keys"]["composer"] = info.get("key")
            order: list[int] = []
            for s in kept:
                for c in s["chunks"]:
                    if c not in order:
                        order.append(c)
            # one entry per document page: several excerpts of the same page (or a quoted reference of it) share a source number
            number: dict[int, int] = {}
            sources: list[dict] = []
            seen: dict[tuple, int] = {}
            for c in order:
                src = source_of(chunks[c - 1], len(sources) + 1)
                key = (src["title"], src["page"], src["link"])
                if key in seen:
                    number[c] = seen[key]
                else:
                    seen[key] = number[c] = src["n"]
                    sources.append(src)
            result["speak"] = [re.sub(r"\s*\[\d+(?:\s*[,\u2013-]\s*\d+)*\]", "", s["text"]).strip() for s in kept]      # a citation marker of the source text ("[2]") is not our superscript
            result["speak_refs"] = [sorted({number[c] for c in s["chunks"]}) for s in kept]
            result["sources"] = sources
            result["composer"] = how
            return self._finish(entry, result, t0, outcome="answer" if kept else "not_found", res=res, reason=entry.get("reason", ""))
        except (asyncio.TimeoutError, TimeoutError):
            return await self._fallback_result(entry, result, t0, question, f"time budget of {self.budget_s:g} s used up", res)
        except Exception as e:  # noqa: BLE001  (Cohere, Postgres or an unexpected error: never break the voice turn)
            return await self._fallback_result(entry, result, t0, question, f"{type(e).__name__}", res)

    async def _fallback_result(self, entry, result, t0, question, why, res) -> dict:
        t = time.monotonic()
        fb = await self._fallback(question, why)
        entry["latency_ms"]["fallback"] = round((time.monotonic() - t) * 1000)
        result.update(speak=fb["speak"], sources=fb["sources"], speak_refs=[[1] if fb["sources"] else [] for _ in fb["speak"]], composer="serving.db")
        entry["composer"] = {"provider": "serving.db fts", "sentences": [{"text": s, "chunks": [], "kept": True, "reason": ""} for s in fb["speak"]], "fallback_reason": fb["reason"]}
        return self._finish(entry, result, t0, outcome="fallback" if fb["speak"] else "not_found", res=res, reason=fb["reason"], via_fallback=True)

    def _finish(self, entry: dict, result: dict, t0: float, *, outcome: str, clarify: dict | None = None, res: SearchResult | None = None, reason: str = "", via_fallback: bool = False) -> dict:
        entry["outcome"] = outcome
        # which path answered: the RAG itself, or the serving.db text search it fell back to (and why)
        entry["path"] = f"rag -> serving.db text search ({reason})" if via_fallback else "rag"
        entry["latency_ms"]["total"] = round((time.monotonic() - t0) * 1000)
        if reason:
            entry["reason"] = reason
        if clarify:
            result["clarify"] = clarify
            result["speak"] = [clarify["question"]]
            entry["clarify"] = clarify
        result["status"] = {"answer": "ok", "clarify": "clarify", "fallback": "fallback", "not_found": "not_found"}[outcome]
        if res is not None:
            row = lambda d: {"chunk_id": d.chunk_id, "type": d.metadata.get("type"), "page": d.metadata.get("page"), "score": round(d.score, 4)}  # noqa: E731
            entry["vector"], entry["keyword"] = [row(d) for d in res.vector[:10]], [row(d) for d in res.keyword[:10]]
            entry["reranker"] = res.reranker
            entry["reranked"] = [{"chunk_id": d.chunk_id, "score": round(d.score, 4), "text": d.chunk_text[:200], "raw_text": d.chunk_text} for d in res.final]
        entry["outcome_reason"] = reason
        retrieval_log.write(entry)
        result["outcome"] = outcome
        result["latency_ms"] = entry["latency_ms"]["total"]
        return result
