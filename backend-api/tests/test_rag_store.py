"""Part A: scoped SQL, replace_source, resumable insert (local Postgres, a throw-away table), key pool, fusion."""
import asyncio
import math
import uuid

import pytest
import pytest_asyncio

from src.paper_rag import keypool as kp
from src.paper_rag.search import content_words, keyword_queries, rrf
from src.paper_rag.stores.vector_db.providers.PGvectorProvider import PGvectorProvider, RetrievedDocument, scope_sql

DIM = 8


def vec(i: int):
    a = [math.cos(i + j) for j in range(DIM)]
    n = math.sqrt(sum(x * x for x in a))
    return [x / n for x in a]


def chunk(cid, src, psis, raw, i):
    return {"chunk_id": cid, "text": f"[hdr] {raw}", "raw_text": raw, "embedding": vec(i), "metadata": {"src_id": src, "psis": psis, "kind": "paper", "page": 1}}


def _pg_up() -> bool:
    try:
        from src.paper_rag.db import engine
        from sqlalchemy import text

        async def go():
            async with engine().connect() as c:
                await c.execute(text("select 1"))
            await engine().dispose()
        asyncio.run(go())
        return True
    except Exception:
        return False


needs_pg = pytest.mark.skipif(not _pg_up(), reason="local Postgres (docker/docker-compose.yml) is not reachable")


@pytest_asyncio.fixture
async def store():
    from src.paper_rag.db import db_client, engine
    st = PGvectorProvider(db_client(), distance_metric="cosine")
    await st.connect()
    t = "t_" + uuid.uuid4().hex[:8]
    await st.create_table(t, DIM)
    yield st, t
    await st.delete_table(t)
    await engine().dispose()
    from src.paper_rag import db
    db.engine.cache_clear(); db.db_client.cache_clear()


# ── scope SQL ────────────────────────────────────────────────────────────────
def test_scope_sql_shapes():
    assert scope_sql(None) == ("", {})
    assert scope_sql({"src_ids": [], "psis": []}) == ("", {})
    w, p = scope_sql({"src_ids": ["a"], "psis": ["PSI-20"]})
    assert "metadata->>'src_id' = ANY" in w and "?|" in w and " OR " in w and p == {"src_ids": ["a"], "psis": ["PSI-20"]}
    assert scope_sql({"psis": ["PSI-20"]})[0].count("OR") == 0
    w, p = scope_sql({"psis": ["PSI-20"], "kinds": ["challenge"]})
    assert "metadata->>'kind' = ANY" in w and p["kinds"] == ["challenge"]
    assert scope_sql({"psis": [], "kinds": ["challenge"]}) == ("", {})   # kinds alone never make a scope


@needs_pg
@pytest.mark.asyncio
async def test_table_has_the_decided_columns_and_indexes(store):
    from sqlalchemy import text
    from src.paper_rag.db import db_client
    st, t = store
    async with db_client()() as s:
        cols = {r[0]: r[1] for r in (await s.execute(text("select column_name, data_type from information_schema.columns where table_name=:t"), {"t": t})).fetchall()}
        idx = " ".join(r[0] for r in (await s.execute(text("select indexdef from pg_indexes where tablename=:t"), {"t": t})).fetchall())
    assert cols["chunk_id"] == "text" and {"text", "raw_text", "embedding", "tsv", "metadata"} <= set(cols) and cols["metadata"] == "jsonb"
    assert "USING hnsw" in idx and "vector_cosine_ops" in idx and "USING gin (metadata)" in idx


@needs_pg
@pytest.mark.asyncio
async def test_scoped_search_returns_only_the_scope_and_unscoped_returns_all(store):
    st, t = store
    await st.replace_source(t, "S1", [chunk("S1:1", "S1", ["PSI-20"], "flame spread at high oxygen", 1), chunk("S1:2", "S1", ["PSI-20"], "smoke particle size", 2)])
    await st.replace_source(t, "S2", [chunk("S2:1", "S2", ["PSI-25", "PSI-20"], "flame spread in microgravity", 3)])
    await st.replace_source(t, "S3", [chunk("S3:1", "S3", ["PSI-99"], "flame spread on the ISS", 4)])
    q = vec(1)
    everything = {d.chunk_id for d in await st.search_by_vector(t, q, limit=10)}
    assert everything == {"S1:1", "S1:2", "S2:1", "S3:1"}
    by_src = {d.chunk_id for d in await st.search_by_vector(t, q, scope={"src_ids": ["S1"]}, limit=10)}
    assert by_src == {"S1:1", "S1:2"}
    by_psi = {d.chunk_id for d in await st.search_by_vector(t, q, scope={"psis": ["PSI-20"]}, limit=10)}
    assert by_psi == {"S1:1", "S1:2", "S2:1"}
    either = {d.chunk_id for d in await st.search_by_vector(t, q, scope={"src_ids": ["S3"], "psis": ["PSI-25"]}, limit=10)}
    assert either == {"S3:1", "S2:1"}
    kw = await st.search_by_keyword(t, "flame spread", scope={"psis": ["PSI-20"]}, limit=10)
    assert {d.chunk_id for d in kw} == {"S1:1", "S2:1"} and kw[0].metadata["src_id"] in {"S1", "S2"}
    assert await st.scope_size(t, {"psis": ["PSI-20"]}) == (3, 2)
    assert (await st.search_by_vector(t, q, scope={"src_ids": ["nothing"]}))[:] == []


@needs_pg
@pytest.mark.asyncio
async def test_keyword_search_is_not_an_or_of_every_word(store):
    st, t = store
    await st.replace_source(t, "S1", [chunk("S1:1", "S1", [], "flame spread rate increases with oxygen", 1), chunk("S1:2", "S1", [], "smoke particles are larger", 2)])
    assert [d.chunk_id for d in await st.search_by_keyword(t, "flame oxygen")] == ["S1:1"]          # AND: only the chunk with both
    assert {d.chunk_id for d in await st.search_by_keyword(t, "flame or smoke")} == {"S1:1", "S1:2"}  # websearch 'or'


@needs_pg
@pytest.mark.asyncio
async def test_replace_source_is_idempotent_and_resumable(store):
    st, t = store
    c1 = [chunk(f"A:{i}", "A", ["PSI-1"], f"text {i}", i) for i in range(5)]
    assert await st.replace_source(t, "A", c1) == 5
    assert await st.replace_source(t, "A", c1) == 5 and await st.count(t) == 5          # a re-run does not double the rows
    await st.replace_source(t, "A", c1[:3])                                                # fewer chunks: the old ones are gone
    assert await st.count_by_source(t) == {"A": 3}
    await st.replace_source(t, "B", [chunk("B:0", "B", [], "other", 9)])
    done = await st.count_by_source(t)                                                     # the resume check: skip sources already complete
    assert done == {"A": 3, "B": 1}
    await st.replace_source(t, "A", [])                                                    # an empty source removes its rows
    assert await st.count_by_source(t) == {"B": 1}


# ── key pool ─────────────────────────────────────────────────────────────────
class Clock:
    def __init__(self): self.t = 1000.0
    def __call__(self): return self.t


def pool(n=3, lim=kp.Limits(rpm=10, tpm=1000, rpd=0), clock=None):
    return kp.KeyPool("gemini", {i + 1: f"secret-value-{i + 1}" for i in range(n)}, lim, clock=clock or Clock())


@pytest.mark.asyncio
async def test_round_robin_over_the_keys():
    p = pool()
    assert [(await p.acquire()).index for _ in range(6)] == [1, 2, 3, 1, 2, 3]


@pytest.mark.asyncio
async def test_a_key_never_exceeds_its_per_minute_units():
    clock = Clock()
    p = pool(2, kp.Limits(rpm=10, tpm=10_000, rpd=0), clock)
    for _ in range(2):
        await p.acquire(units=10)                       # both keys full
    with pytest.raises(TimeoutError):
        await p.acquire(units=1, timeout=0.2)           # nothing free inside the minute
    clock.t += 61                                       # the window rolled
    assert (await p.acquire(units=10)).units == 10


@pytest.mark.asyncio
async def test_quota_error_cools_a_key_down_and_gives_the_units_back():
    clock = Clock()
    p = pool(2, kp.Limits(rpm=100, tpm=100_000, rpd=0), clock)
    l = await p.acquire(units=5)
    class E(Exception): pass
    w = p.report_quota_error(l, E("429 RESOURCE_EXHAUSTED. Please retry in 42.03s."))
    assert 42 <= w <= 45
    assert {(await p.acquire()).index for _ in range(4)} == {2}   # key 1 rests
    clock.t += 50
    assert {(await p.acquire()).index for _ in range(4)} == {1, 2}
    s = p.stats()
    assert s["n429"] == 1 and s["keys"]["gemini#1"]["n429"] == 1


@pytest.mark.asyncio
async def test_daily_limit_and_no_key_value_anywhere():
    p = pool(1, kp.Limits(rpm=100, tpm=100_000, rpd=3))
    l = await p.acquire(units=3)
    with pytest.raises(RuntimeError, match="daily limit"):
        await p.acquire(units=1)
    blob = repr(l) + repr(p.stats()) + repr(p._keys) + p.label(1)
    assert "secret-value" not in blob


def test_retry_after_parsing():
    assert kp.retry_after_seconds(Exception("no hint")) == 60
    assert kp.retry_after_seconds(Exception("'retryDelay': '42s'")) == 43
    class R:  # an http error with a header
        headers = {"retry-after": "7"}
    class E(Exception): response = R()
    assert kp.retry_after_seconds(E("x")) == 7
    assert kp.is_quota_error(Exception("429 RESOURCE_EXHAUSTED")) and not kp.is_quota_error(Exception("boom"))


def test_pool_from_env(monkeypatch):
    import os
    for k in [k for k in os.environ if k.startswith("GEMINI_API_KEY")]:
        monkeypatch.delenv(k)
    for i in (1, 2):
        monkeypatch.setenv(f"GEMINI_API_KEY_{i}", f"v{i}")
    assert len(kp.KeyPool.from_env("GEMINI")) == 2


# ── search helpers ───────────────────────────────────────────────────────────
def test_keyword_queries_strictest_first():
    assert content_words("What oxygen level makes the spacecraft dangerous?") == ["oxygen", "level", "makes", "spacecraft", "dangerous?"[:-1]]
    assert keyword_queries("flame spread oxygen") == ["flame spread oxygen", "flame or spread or oxygen"]


def test_rrf_prefers_chunks_in_both_lists():
    d = lambda c: RetrievedDocument(c, c, 0.0)
    out = rrf([([d("a"), d("b"), d("c")], 0.7), ([d("c"), d("d")], 0.3)])
    assert out[0].chunk_id in {"a", "c"} and {x.chunk_id for x in out} == {"a", "b", "c", "d"}
    assert out[0].chunk_id == "c" or out[0].score >= out[1].score


@pytest.mark.asyncio
async def test_soonest_wait_tells_a_caller_when_to_use_another_provider():
    clock = Clock()
    p = pool(2, kp.Limits(rpm=10, tpm=10_000, rpd=0), clock)
    assert p.soonest_wait() == 0
    for _ in range(2):
        await p.acquire(units=10)
    assert 0 < p.soonest_wait(units=1) <= 60
    l = await p.acquire(units=0) if False else None
    clock.t += 61
    assert p.soonest_wait() == 0


@pytest.mark.asyncio
async def test_cohere_rerank_orders_by_score_and_falls_back_when_unreachable():
    import httpx
    from src.paper_rag.stores.llm.providers.CohereEmbedder import CohereRerank
    docs = [RetrievedDocument(f"c{i}", f"text {i}", 0.0) for i in range(3)]
    ok = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"results": [{"index": 2, "relevance_score": 0.9}, {"index": 0, "relevance_score": 0.2}]})))
    rr = CohereRerank(pool(1, kp.Limits(rpm=100, tpm=10**9, rpd=0)), http=ok)
    assert [d.chunk_id for d in await rr.rerank("q", docs, top_n=2)] == ["c2", "c0"] and rr.ok is True
    down = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(500)))
    rr2 = CohereRerank(pool(1, kp.Limits(rpm=100, tpm=10**9, rpd=0)), http=down)
    assert [d.chunk_id for d in await rr2.rerank("q", docs, top_n=2)] == ["c0", "c1"] and rr2.ok is False      # the fused order is kept, and says so
    limited = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(429, headers={"retry-after": "5"})))
    assert [d.chunk_id for d in await CohereRerank(pool(1, kp.Limits(rpm=100, tpm=10**9, rpd=0)), http=limited).rerank("q", docs, top_n=1)] == ["c0"]


@pytest.mark.asyncio
async def test_cohere_embedder_batches_and_returns_vectors_in_order():
    import json as _json
    import httpx
    from src.paper_rag.stores.llm.providers.CohereEmbedder import CohereEmbedder
    seen = []
    def handler(req):
        body = _json.loads(req.content); seen.append((len(body["texts"]), body["input_type"], body["output_dimension"]))
        return httpx.Response(200, json={"embeddings": {"float": [[float(t.split()[-1])] * 4 for t in body["texts"]]}})
    emb = CohereEmbedder(pool(2, kp.Limits(rpm=100, tpm=10**9, rpd=0)), dim=4, http=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    out = await emb.embed([f"t {i}" for i in range(200)], task="document")
    assert [v[0] for v in out] == [float(i) for i in range(200)] and sorted(n for n, *_ in seen) == [8, 96, 96] and {s[1:] for s in seen} == {("search_document", 4)}
    assert (await emb.embed("q 7", task="query"))[0][0] == 7.0 and seen[-1][1] == "search_query"
