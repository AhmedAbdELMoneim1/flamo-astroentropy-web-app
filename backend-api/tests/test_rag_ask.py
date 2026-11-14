"""The checker (pure) and ask_sources with fakes: answer, extractive fallback, clarify, serving.db fallback, 4-second budget, the log line."""
import asyncio
import json

import pytest

from src.paper_rag import ask as askmod
from src.paper_rag import chunks as C
from src.paper_rag import retrieval_log
from src.paper_rag.ask import AskSources
from src.paper_rag.composer import check_sentences, extractive, numbers_in
from src.paper_rag.scope import Scope
from src.paper_rag.search import SearchResult
from src.paper_rag.stores.vector_db.providers.PGvectorProvider import RetrievedDocument

TEXT = "Generally, it has been found that oxygen levels of 26 % and above can allow steady flames. The flames are thin blue in color."
FIG = "[Figure] Figure 3. Spread rate. The figure shows spread rates of 1.2 to 3.4 mm/s."


def doc(cid, text, gen=False, page=31, kind="doc", score=0.9, **meta):
    return RetrievedDocument(cid, text, score, {"kind": kind, "type": "figure" if gen else "text", "generated": gen, "page": page, "title": "BRE thesis", "psis": ["PSI-20"], "download_url": "https://psi.nasa.gov/x", **meta})


CH = [doc("doc:a:p31:c3", TEXT), doc("doc:a:p31:f1", FIG, gen=True)]


# ── the checker ──────────────────────────────────────────────────────────────
def test_a_sentence_needs_a_citation_and_its_numbers_must_be_in_the_cited_text():
    r = check_sentences([
        {"text": "Oxygen levels of 26 % and above can allow steady flames.", "chunks": [1]},
        {"text": "Flames stay steady at 30 % oxygen.", "chunks": [1]},
        {"text": "The flames are thin blue in color.", "chunks": []},
    ], CH)
    assert [x["kept"] for x in r] == [True, False, False]
    assert "number not in the cited text: 30" in r[1]["reason"] and r[2]["reason"] == "no citation"
    assert check_sentences([{"text": "The flames are blue.", "chunks": [9]}], CH)[0]["reason"] == "no citation"      # an excerpt that does not exist


def test_numbers_are_compared_as_written_never_re_rounded():
    assert numbers_in("30 % at 1,200 s and 3.4 mm/s, 0.012") == {"30", "1200", "3.4", "0.012"}
    r = check_sentences([{"text": "It spread at 3.40 mm/s.", "chunks": [1]}], [doc("x", "It spread at 3.4 mm/s.")])
    assert not r[0]["kept"]                                                   # 3.40 is not 3.4: no new digits


def test_a_model_generated_chunk_can_be_cited_but_never_as_the_source_of_a_number():
    r = check_sentences([{"text": "The figure shows spread rates of 1.2 to 3.4 mm/s.", "chunks": [2]}, {"text": "A figure shows how the spread rate changes.", "chunks": [2]}], CH)
    assert [x["kept"] for x in r] == [False, True]
    assert r[0]["reason"].startswith("number not in the cited text")
    r2 = check_sentences([{"text": "The figure shows spread rates of 1.2 to 3.4 mm/s.", "chunks": [1, 2]}], [doc("a", "x " * 5), doc("b", FIG, gen=True)])
    assert not r2[0]["kept"]


@pytest.mark.parametrize("text", ["That level is safe for the crew.", "It is the safest atmosphere tested.", "Fire is unsafe here.", "Oxygen is dangerous above 26 % in the tests.",
                                  "Dangerous when oxygen rises.", "Above 26 % oxygen it becomes dangerous."])
def test_safe_and_danger_threshold_wording_is_dropped(text):
    r = check_sentences([{"text": text, "chunks": [1]}], CH)
    assert not r[0]["kept"] and r[0]["reason"].startswith("forbidden")


def test_at_most_three_sentences_and_the_extractive_sentence_is_the_sources_own():
    r = check_sentences([{"text": f"Flames are blue {i}.", "chunks": [1]} for i in range(5)], CH)
    assert len(r) == 3
    e = extractive(CH, n=1)
    assert e[0]["chunks"] == [1] and e[0]["text"].startswith("Generally, it has been found") and e[0]["kept"]
    assert extractive([CH[1]], n=1) == []                                      # never extracts from a generated chunk


# ── ask_sources with fakes ───────────────────────────────────────────────────
class Store:
    async def scope_size(self, table, scope): return (30, 4)


class Searcher:
    table, embedder, reranker = "chunks_cohere", type("E", (), {"last_key": "cohere#3"})(), None
    def __init__(self, docs, reranker="cohere", raises=None, delay=0.0):
        self.docs, self.rr, self.raises, self.delay, self.store, self.calls = docs, reranker, raises, delay, Store(), []
    async def search(self, q, scope=None, top_n=5, k=20, embed_timeout=None):
        self.calls.append(scope)
        if self.raises: raise self.raises
        await asyncio.sleep(self.delay)
        return SearchResult(final=self.docs[:top_n], vector=self.docs, keyword=self.docs[:1], fused=self.docs, reranker=self.rr, ms={"embed": 5, "db": 3, "rerank": 9})


class Resolver:
    def __init__(self, empty=False): self.empty = empty
    def resolve(self, **p): return Scope() if self.empty else Scope(["PSI-20"], {"psi": ["PSI-20"]}, False, p)


class Composer:
    def __init__(self, sents=None, boom=False): self.sents, self.boom = sents, boom
    async def compose(self, q, chunks, timeout):
        if self.boom: return [], {"provider": None, "key": None, "reason": "gemini: TimeoutError; groq: HTTPStatusError; "}
        return self.sents, {"provider": "gemini", "key": "gemini#4", "reason": ""}


VOCAB = C.Vocab({"PSI-20": "ACME BRE", "PSI-25": "BASS-II", "PSI-99": "Saffire-II"}, {}, [], [])
serving = lambda name, **kw: {"speak": ["Smoke particulate was larger in low gravity."], "matched": True, "table": {"rows": [{"kind": "card", "src": "F-1", "page": 8, "psi": "PSI-102"}]}}  # noqa: E731


@pytest.fixture(autouse=True)
def log(tmp_path, monkeypatch):
    monkeypatch.setattr(retrieval_log, "PATH", tmp_path / "retrieval.jsonl")
    monkeypatch.setenv("RAG_LOG", "summary")
    return tmp_path / "retrieval.jsonl"


def mk(searcher, composer=None, resolver=None, **kw):
    return AskSources(searcher, resolver or Resolver(), composer, VOCAB, serving_call=serving, **kw)


def lines(p): return [json.loads(l) for l in p.read_text().splitlines()]


def test_answer_keeps_checked_sentences_numbers_sources_and_logs_one_line(log):
    comp = Composer([{"text": "Oxygen levels of 26 % and above can allow steady flames.", "chunks": [1]}, {"text": "Flames stay steady at 99 % oxygen.", "chunks": [1]}])
    r = asyncio.run(mk(Searcher(CH), comp).ask("When do flames burn steadily?", psi="BRE"))
    assert r["status"] == "ok" and r["speak"] == ["Oxygen levels of 26 % and above can allow steady flames."] and r["speak_refs"] == [[1]]
    s = r["sources"][0]
    assert s["n"] == 1 and s["label"] == "NASA document" and s["page"] == 31 and s["link"] == "https://psi.nasa.gov/x" and s["link_kind"] == "nasa_psi_download"
    (e,) = lines(log)
    assert e["outcome"] == "answer" and e["scope"]["psis"] == ["PSI-20"] and e["scope"]["n_sources"] == 4 and e["params"] == {"psi": "BRE"}
    assert [s["kept"] for s in e["composer"]["sentences"]] == [True, False] and "number not in the cited text" in e["composer"]["sentences"][1]["reason"]
    assert e["reranked"][0]["chunk_id"] == "doc:a:p31:c3" and len(e["reranked"][0]["text"]) <= 200 and "raw_text" not in e["reranked"][0]
    assert e["keys"] == {"embed": "cohere#3", "composer": "gemini#4"} and e["latency_ms"]["total"] >= 0 and "AIza" not in json.dumps(e)


def test_when_no_sentence_survives_the_extractive_sentence_answers(log):
    r = asyncio.run(mk(Searcher(CH), Composer([{"text": "It is safe at 26 %.", "chunks": [1]}])).ask("q"))
    assert r["status"] == "ok" and r["composer"] == "extractive" and r["speak"][0].startswith("Generally, it has been found")
    assert any("extractive fallback" in s["reason"] for s in lines(log)[0]["composer"]["sentences"])
    r2 = asyncio.run(mk(Searcher(CH), Composer(boom=True)).ask("q"))
    assert r2["composer"] == "extractive" and "gemini: TimeoutError" in lines(log)[1]["composer"]["sentences"][0]["reason"]


def test_an_empty_scope_asks_one_question_with_options(log):
    s = Searcher([doc("a", TEXT, psis=["PSI-25"]), doc("b", TEXT, psis=["PSI-99"]), doc("c", TEXT, psis=["PSI-20"])])
    r = asyncio.run(mk(s, Composer([]), Resolver(empty=True)).ask("What happens in the suit atmosphere?", scenario="spacesuit"))
    assert r["status"] == "clarify" and r["clarify"]["options"] == ["BASS-II (PSI-25)", "Saffire-II (PSI-99)", "ACME BRE (PSI-20)"]
    assert r["speak"] == ["Which do you mean: BASS-II (PSI-25), Saffire-II (PSI-99) or ACME BRE (PSI-20)?"] and s.calls == [None]
    assert lines(log)[0]["outcome"] == "clarify"


def test_a_weak_rerank_score_asks_instead_of_guessing(log):
    s = Searcher([doc("a", TEXT, score=0.05, psis=["PSI-25"]), doc("b", TEXT, score=0.04, psis=["PSI-20"])])
    r = asyncio.run(mk(s, Composer([{"text": "x", "chunks": [1]}])).ask("something vague"))
    assert r["status"] == "clarify" and "below" in lines(log)[0]["clarify"]["why"]
    r2 = asyncio.run(mk(Searcher([doc("a", TEXT, score=0.05)], reranker="rrf"), Composer([{"text": "Oxygen levels of 26 % and above can allow steady flames.", "chunks": [1]}])).ask("fusion scores are not comparable"))
    assert r2["status"] == "ok"                                                # the weak check applies to Cohere scores only


def test_cohere_or_postgres_failure_falls_back_to_the_serving_db(log):
    r = asyncio.run(mk(Searcher(CH, raises=RuntimeError("cohere down")), Composer([])).ask("Why are smoke particles bigger in low gravity?"))
    assert r["status"] == "fallback" and r["speak"] == ["Smoke particulate was larger in low gravity."] and r["sources"][0]["psis"] == ["PSI-102"]
    assert lines(log)[0]["outcome"] == "fallback" and "RuntimeError" in lines(log)[0]["reason"]


def test_the_four_second_budget_falls_back_instead_of_waiting(log):
    s = Searcher(CH, delay=3.0)
    t = asyncio.get_event_loop_policy().new_event_loop()
    r = t.run_until_complete(mk(s, Composer([]), budget_s=1.2).ask("slow question"))
    assert r["status"] == "fallback" and "time budget" in lines(log)[0]["reason"] and r["latency_ms"] < 2500


def test_a_slow_serving_db_fallback_is_cut_off_instead_of_missing_the_agents_window(log, monkeypatch):
    import time
    monkeypatch.setattr(askmod, "FALLBACK_S", 0.2)
    def slow_serving(name, **kw):
        time.sleep(1.0)
        return {"speak": ["Too late to be heard."], "table": {"rows": []}}
    async def go():
        t0 = time.monotonic()
        r = await AskSources(Searcher(CH, raises=RuntimeError("cohere down")), Resolver(), Composer([]), VOCAB, serving_call=slow_serving).ask("slow fallback")
        return r, time.monotonic() - t0
    r, took = asyncio.run(go())                    # asyncio.run still joins the worker thread on exit; the ask itself must not wait for it
    assert took < 0.6 and r["speak"] == [] and r["sources"] == []
    assert "fallback over" in lines(log)[0]["reason"]


def test_log_modes(log, monkeypatch):
    monkeypatch.setenv("RAG_LOG", "off")
    asyncio.run(mk(Searcher(CH), Composer([])).ask("q"))
    assert not log.exists()
    monkeypatch.setenv("RAG_LOG", "full")
    asyncio.run(mk(Searcher(CH), Composer([])).ask("q"))
    assert lines(log)[0]["reranked"][0]["raw_text"] == TEXT


def test_excerpts_of_the_same_page_share_one_source_number(log):
    ch = [doc("a", TEXT, page=31), doc("b", TEXT + " More.", page=31), doc("c", "Another page. " * 6, page=40)]
    comp = Composer([{"text": "Oxygen levels of 26 % and above can allow steady flames.", "chunks": [1, 2]}, {"text": "Another page.", "chunks": [3]}])
    r = asyncio.run(mk(Searcher(ch), comp).ask("q"))
    assert [s["page"] for s in r["sources"]] == [31, 40] and r["speak_refs"] == [[1], [2]]


def test_a_composer_that_finds_no_answer_means_not_covered_not_a_guessed_sentence(log):
    r = asyncio.run(mk(Searcher(CH), Composer([])).ask("q"))
    assert r["status"] == "not_found" and r["speak"] == [] and r["sources"] == []
    e = lines(log)[0]
    assert e["outcome"] == "not_found" and e["reason"] == "the composer found no answer in the excerpts" and e["composer"]["provider"] == "gemini"


def test_a_refusal_written_as_a_sentence_counts_as_not_covered(log):
    r = check_sentences([{"text": "The excerpts do not specify an oxygen level that makes a spacecraft dangerous.", "chunks": [1]},
                         {"text": "The text does not mention any threshold.", "chunks": [1]}, {"text": "Flames burn blue in microgravity.", "chunks": [1]}], CH)
    assert [x["kept"] for x in r] == [False, False, True]
    out = asyncio.run(mk(Searcher(CH), Composer([{"text": "The excerpts do not specify an oxygen level.", "chunks": [1]}])).ask("q"))
    assert out["status"] == "not_found" and out["speak"] == [] and lines(log)[0]["reason"] == "the composer found no answer in the excerpts"


def test_fusion_scores_after_a_failed_rerank_never_trigger_the_weak_score_clarify(log):
    s = Searcher([doc("a", TEXT, score=0.0156)], reranker="rrf (rerank unavailable)")
    r = asyncio.run(mk(s, Composer([{"text": "Oxygen levels of 26 % and above can allow steady flames.", "chunks": [1]}])).ask("q"))
    assert r["status"] == "ok" and lines(log)[0]["reranker"] == "rrf (rerank unavailable)"


def test_the_composer_keeps_one_deadline_across_providers():
    import time
    from src.paper_rag.composer import Composer as Real
    class Slow(Real):
        async def _gemini(self, prompt): await asyncio.sleep(5); return "{}"
        async def _groq(self, prompt): await asyncio.sleep(5); return "{}"
    pool = type("P", (), {})()
    c = Slow(pool, pool)
    t = time.monotonic()
    sents, info = asyncio.run(c.compose("q", CH, timeout=1.0))
    assert sents == [] and time.monotonic() - t < 1.3 and "gemini: TimeoutError" in info["reason"]


def test_parameters_come_from_the_question_when_the_model_passes_none_and_the_source_is_logged(log):
    class X:
        def extract(self, q): return {"psi": "PSI-20", "o2_pct": 26.0}
    class Res(Resolver):
        def resolve(self, **p):
            self.seen = p
            return super().resolve(**p)
    r = Res()
    comp = Composer([{"text": "Oxygen levels of 26 % and above can allow steady flames.", "chunks": [1]}])
    asyncio.run(AskSources(Searcher(CH), r, comp, VOCAB, serving_call=serving, extractor=X()).ask("What oxygen allows steady flames in the BRE tests?", psi="PSI-25"))
    assert r.seen == {"psi": "PSI-25", "o2_pct": 26.0}                                   # the model's psi wins, the oxygen is extracted
    e = lines(log)[0]
    assert e["params"] == {"psi": "PSI-25", "o2_pct": 26.0} and e["params_source"] == {"psi": "model", "o2_pct": "extracted"}


def test_the_rewrite_adds_the_terms_the_papers_use_and_only_for_retrieval(log):
    from src.paper_rag.rewrite import rewrite
    assert "spherical" in rewrite("Why are flames round in space?") and "buoyancy" in rewrite("Why are flames round in space?")
    assert rewrite("What is BRE?") == "What is BRE?"
    seen = {}
    class S(Searcher):
        async def search(self, q, scope=None, top_n=5, k=20, embed_timeout=None):
            seen["q"], seen["t"] = q, embed_timeout
            return await super().search(q, scope, top_n, k)
    comp = Composer([{"text": "Oxygen levels of 26 % and above can allow steady flames.", "chunks": [1]}])
    asyncio.run(mk(S(CH), comp).ask("Why are flames round in space?"))
    assert "spherical" in seen["q"] and seen["t"] == 1.2                              # the retrieval query is rewritten and the embedding never waits longer than 1.2 s
    e = lines(log)[0]
    assert e["question"] == "Why are flames round in space?" and "spherical" in e["rewritten_query"] and {"embed", "db", "rerank"} <= {k.replace("search_", "") for k in e["latency_ms"]}


def test_a_query_embedding_never_sleeps_inside_the_budget():
    import time
    import httpx
    from src.paper_rag.stores.llm.providers.CohereEmbedder import CohereEmbedder
    from tests.test_rag_store import pool
    from src.paper_rag import keypool as kp
    emb = CohereEmbedder(pool(1, kp.Limits(rpm=1, tpm=10**9, rpd=0)), dim=2, http=httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"embeddings": {"float": [[0.1, 0.2]]}}))))
    async def go():
        await emb.embed("one", task="query", timeout=0.2)                     # the only key now paces for a minute
        t = time.monotonic()
        with pytest.raises(TimeoutError):
            await emb.embed("two", task="query", timeout=0.2)
        return time.monotonic() - t
    assert asyncio.run(go()) < 0.6


def test_a_rerank_timeout_uses_the_fusion_order_and_says_so():
    """Round 12 item 1: the rerank has its own deadline; on a timeout the fusion order is used (the answer is still composed) and the log says so."""
    from src.paper_rag.search import Searcher as Real
    from src.paper_rag.stores.vector_db.providers.PGvectorProvider import RetrievedDocument

    class Store:
        async def search_by_vector(self, table, vec, scope=None, limit=10):
            return [RetrievedDocument("a", "text a", 0.9, {}, "text a"), RetrievedDocument("b", "text b", 0.8, {}, "text b")]
        async def search_by_keyword(self, table, q, scope=None, limit=10):
            return [RetrievedDocument("b", "text b", 0.5, {}, "text b")]

    class Emb:
        async def embed(self, q, task="query", timeout=None):
            return [[0.1, 0.2]]

    class Slow:
        ok = True
        async def rerank(self, q, docs, top_n):
            await asyncio.sleep(5)

    r = Real(Store(), "t", Emb(), Slow(), rerank_timeout=0.05)
    res = asyncio.run(r.search("steady flames", scope=None, top_n=2))
    assert res.reranker == "rrf (rerank timeout \u2192 fusion)" and [d.chunk_id for d in res.final] == ["a", "b"] or [d.chunk_id for d in res.final] == ["b", "a"]
    assert "timeout" in res.reranker and len(res.final) == 2
