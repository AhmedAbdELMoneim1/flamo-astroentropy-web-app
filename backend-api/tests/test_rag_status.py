"""No silent fallback: the startup line says ON or OFF with the reason, every answer records its path, and the old text search is never used unannounced."""
import asyncio
import json
import uuid

import pytest

from src import content, rag
from src.paper_rag import retrieval_log
from src.state import DashboardState
from tests.helpers import FakeBridge
from tests.test_rag_store import needs_pg


@pytest.fixture(autouse=True)
def clean(monkeypatch, tmp_path):
    monkeypatch.setattr(retrieval_log, "PATH", tmp_path / "retrieval.jsonl")
    monkeypatch.setenv("RAG_LOG", "summary")
    monkeypatch.setenv("FLAMEO_DB", str(tmp_path / "serving.db"))
    monkeypatch.setenv("cohere_api_key_1", "x")
    old = rag.STATUS
    yield tmp_path / "retrieval.jsonl"
    rag.STATUS = old
    rag.set_asker(None)


def check(): return asyncio.run(rag.check())


def test_off_with_a_reason_for_each_thing_that_can_be_missing(monkeypatch):
    monkeypatch.setenv("RAG_ENABLED", "0")
    s = check()
    assert not s.on and "RAG_ENABLED=0" in s.reason and s.line.startswith("RAG: OFF, disabled by RAG_ENABLED=0")
    monkeypatch.delenv("RAG_ENABLED")
    monkeypatch.delenv("cohere_api_key_1")
    for k in [k for k in __import__("os").environ if k.lower().startswith("cohere_api_key")]:
        monkeypatch.delenv(k)
    assert "no COHERE_API_KEY_*" in check().reason
    monkeypatch.setenv("cohere_api_key_1", "x"); monkeypatch.delenv("FLAMEO_DB")
    assert "FLAMEO_DB is not set" in check().reason
    monkeypatch.setenv("FLAMEO_DB", "/x"); monkeypatch.setenv("POSTGRES_PORT", "1")
    s = check()
    assert not s.on and s.reason.startswith("Postgres not reachable at") and "Old" not in s.line and "text search" in s.line


@needs_pg
def test_missing_or_empty_index_table_and_the_on_line(monkeypatch):
    monkeypatch.setenv("TABLE_NAME", "no_such_table_" + uuid.uuid4().hex[:6])
    assert "does not exist" in check().reason
    # the real index (chunks_cohere) when it is there
    monkeypatch.setenv("TABLE_NAME", "chunks_cohere")
    s = check()
    if s.on:
        assert s.line.startswith("RAG: ON (chunks_cohere, ") and "chunks" in s.line and "embed-v4.0" in s.line


def test_startup_prints_one_clear_line_and_required_mode_stops(monkeypatch, capsys):
    monkeypatch.setenv("RAG_ENABLED", "0")
    s = rag.startup_check(required=False)
    out = capsys.readouterr().out.strip().splitlines()
    assert out == [s.line] and out[0].startswith("RAG: OFF, disabled by RAG_ENABLED=0")
    with pytest.raises(SystemExit) as e:
        rag.startup_check(required=True)
    assert "RAG: OFF" in str(e.value) and "RAG_REQUIRED=1" in str(e.value)


def test_without_the_rag_the_answer_is_logged_with_its_path_and_the_model_is_told(monkeypatch, clean):
    async def fake_intent(self, name, **args): return {"status": "shown", "matched": True, "speak": ["A passage."]}
    monkeypatch.setattr(content.Runner, "intent", fake_intent)
    rag.STATUS = rag.Status(False, "Postgres not reachable at localhost:5432 (OSError)", checked=True)
    m = asyncio.run(content.Runner(FakeBridge(), DashboardState()).ask_sources("Why are smoke particles bigger?", psi="SAME"))
    assert m["rag"] == "off" and m["speak"] == ["A passage."]
    (e,) = [json.loads(l) for l in clean.read_text().splitlines()]
    assert e["outcome"] == "search_text" and e["path"] == "search_text, NOT the RAG (RAG off: Postgres not reachable at localhost:5432 (OSError))" and e["params"] == {"psi": "SAME"}
    assert e["composer"]["fallback_reason"].startswith("RAG off")


def test_a_failure_while_asking_is_also_logged_not_hidden(monkeypatch, clean):
    async def fake_intent(self, name, **args): return {"status": "shown", "matched": True, "speak": ["x"]}
    monkeypatch.setattr(content.Runner, "intent", fake_intent)
    class Boom:
        async def ask(self, q, **p): raise RuntimeError("cohere key rejected")
    rag.set_asker(Boom())
    asyncio.run(content.Runner(FakeBridge(), DashboardState()).ask_sources("q"))
    e = json.loads(clean.read_text().splitlines()[0])
    assert e["path"].startswith("search_text, NOT the RAG (RAG error: RuntimeError: cohere key rejected")


def test_every_rag_answer_records_that_the_rag_answered_and_a_fallback_records_why(clean):
    from tests.test_rag_ask import CH, Composer, Searcher, mk, lines  # the fakes of the ask_sources tests
    asyncio.run(mk(Searcher(CH), Composer([{"text": "Oxygen levels of 26 % and above can allow steady flames.", "chunks": [1]}])).ask("q"))
    asyncio.run(mk(Searcher(CH, raises=RuntimeError("cohere down")), Composer([])).ask("q"))
    a, b = lines(clean)
    assert a["path"] == "rag" and b["path"] == "rag -> serving.db text search (RuntimeError)"
