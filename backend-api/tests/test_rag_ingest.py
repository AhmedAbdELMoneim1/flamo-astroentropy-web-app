"""D2-D5 end to end with fakes: a finished file in the queue -> chunks -> embedded -> rows in a throw-away table; resumable; row count == chunk count."""
import asyncio
import json
import math
import sys
import uuid
from pathlib import Path

import pytest
import pytest_asyncio

from src.paper_rag import chunks as C
from src.paper_rag import db
from src.paper_rag.describe import safe
from src.paper_rag.ingest import process_source, watch
from tests.test_rag_store import needs_pg

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "docker" / "rag-master"))
from queue_db import TaskQueue  # noqa: E402

PARA = "The flame spread rate of PMMA increased with oxygen concentration in the microgravity tests at 30% oxygen and 70 kPa. "
VOCAB = C.Vocab({"PSI-20": "ACME BRE"}, {"PSI-20": ["prevention"]}, ["PMMA"], [])
pytestmark = needs_pg


class FakeEmbedder:
    tokens, calls = 0, 0
    async def embed(self, texts, task="document"):
        self.calls += 1; self.tokens += sum(len(t) // 3 for t in texts)
        from src.paper_rag.helpers.config import get_settings
        dim = get_settings().EMBEDDING_SIZE                  # the index size of the .env (768 Gemini, 1024 Cohere)
        return [[math.cos(i + j) for j in range(dim)] for i, _ in enumerate(texts)]


class FakeDescriber:
    stats = {"groq_calls": 0, "gemini_calls": 0, "groq_429": 0, "cache_hits": 0, "failed": 0}
    async def table(self, *a): self.stats["groq_calls"] += 1; return "desc"
    async def figure(self, *a): return {"type": "line_plot", "summary": "x" * 250}


def row(src, pages=2):
    return {"src_id": src, "kind": "paper", "path": "/x", "sha256": "s" + src, "pages": pages, "kept_pages": [1, 2], "title": "T " + src, "psis": ["PSI-20"], "doi": src,
            "download_url": None, "doc_category": None, "doc_role": None, "sections": {"1": "results", "2": "results"}, "also_src_ids": []}


def finished(cache, r, text):
    d = cache / "docling" / safe(r["src_id"])
    d.mkdir(parents=True)
    (d / "blocks.jsonl").write_text(json.dumps({"type": "text", "page": 1, "text": text}) + "\n")


@pytest_asyncio.fixture
async def table(monkeypatch):
    from src.paper_rag.stores.vector_db.providers.PGvectorProvider import PGvectorProvider
    t = "t_" + uuid.uuid4().hex[:8]
    monkeypatch.setenv("TABLE_NAME", t)
    yield t
    await PGvectorProvider(db.db_client()).delete_table(t)
    await db.engine().dispose()
    db.engine.cache_clear(); db.db_client.cache_clear()


@pytest.mark.asyncio
async def test_watch_inserts_each_finished_file_and_is_resumable(tmp_path, table):
    from src.paper_rag.stores.vector_db.providers.PGvectorProvider import PGvectorProvider
    cache = tmp_path / "cache"
    rows = [row("10.1/a"), row("10.1/b")]
    cache.mkdir()
    (cache / "manifest.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    q = TaskQueue(cache / "queue.db")
    q.load_manifest(rows)
    for r in rows:                                                     # the master marked both done
        finished(cache, r, PARA * 5 + r["src_id"])
        q.lease("w", 60); q.complete(r["src_id"], 5.0, "img:1", "2.149.0", 1000)
    rep = await watch(cache / "manifest.jsonl", cache, VOCAB, FakeDescriber(), FakeEmbedder(), poll_s=0.05)
    assert rep["inserted"] == 2 and rep["unaccounted"] == [] and rep["insert_failed"] == {}
    ledger = [json.loads(l) for l in (cache / f"ledger_{table}.jsonl").read_text().splitlines()]
    assert {l["src_id"] for l in ledger} == {"10.1/a", "10.1/b"} and all(l["chunks"] >= 1 for l in ledger)
    got = await PGvectorProvider(db.db_client()).count_by_source(table)
    assert got == {l["src_id"]: l["chunks"] for l in ledger}          # rows == chunks, per source
    emb2 = FakeEmbedder()
    rep2 = await watch(cache / "manifest.jsonl", cache, VOCAB, FakeDescriber(), emb2, poll_s=0.05)
    assert rep2["inserted"] == 2 and emb2.calls == 0                  # nothing parsed or embedded twice


@pytest.mark.asyncio
async def test_a_failed_parse_is_listed_not_hidden(tmp_path, table):
    cache = tmp_path / "cache"; cache.mkdir()
    rows = [row("10.1/a"), row("10.1/bad")]
    (cache / "manifest.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    q = TaskQueue(cache / "queue.db", max_attempts=1)
    q.load_manifest(rows)
    finished(cache, rows[0], PARA * 5)
    q.lease("w", 60); q.complete("10.1/a", 5.0, "img:1", "v", 1)
    q.lease("w", 60); q.fail("10.1/bad", "boom")
    rep = await watch(cache / "manifest.jsonl", cache, VOCAB, FakeDescriber(), FakeEmbedder(), poll_s=0.05)
    assert rep["inserted"] == 1 and rep["parse_failed"] == ["10.1/bad"] and rep["unaccounted"] == []


@pytest.mark.asyncio
async def test_phase_one_without_a_describer_then_phase_two_redoes_those_sources(tmp_path, table):
    cache = tmp_path / "cache"; cache.mkdir()
    rows = [row("10.1/a")]
    (cache / "manifest.jsonl").write_text(json.dumps(rows[0]) + "\n")
    q = TaskQueue(cache / "queue.db"); q.load_manifest(rows)
    finished(cache, rows[0], PARA * 5)
    q.lease("w", 60); q.complete("10.1/a", 5.0, "img:1", "v", 1)
    r1 = await watch(cache / "manifest.jsonl", cache, VOCAB, None, FakeEmbedder(), poll_s=0.05)
    assert r1["inserted"] == 1 and r1["inserted_without_descriptions"] == 1
    emb = FakeEmbedder()
    r2 = await watch(cache / "manifest.jsonl", cache, VOCAB, FakeDescriber(), emb, poll_s=0.05)     # phase 2: described now
    assert r2["inserted_without_descriptions"] == 0 and emb.calls >= 1
