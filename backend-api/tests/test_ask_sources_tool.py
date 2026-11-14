"""ask_sources through the agent path (Runner): the screen packet, the model payload, one clarifying question, not covered, the guard rails. A fake asker: no Postgres, no Cohere."""
import asyncio

import pytest

from src import content, rag
from src.bridge import Cmd
from src.state import DashboardState
from tests.helpers import FakeBridge

SRC = {"n": 1, "label": "NASA document", "kind": "doc", "type": "text", "title": "PSI-20_Reports_Dissertation", "page": 31, "link": "https://psi.nasa.gov/x", "link_kind": "nasa_psi_download", "psis": ["PSI-20"], "generated": False}


class Asker:
    def __init__(self, results): self.results, self.calls = list(results), []
    async def ask(self, q, **p):
        self.calls.append((q, p)); return self.results.pop(0)


def ok(): return {"request_id": "r1", "question": "q", "speak": ["Oxygen levels of 26 % and above can allow steady flames."], "speak_refs": [[1]], "sources": [SRC], "status": "ok", "outcome": "answer", "clarify": None, "scope": {}}
def clar(): return {"request_id": "r2", "question": "q", "speak": ["Which do you mean: BASS-II (PSI-25) or ACME BRE (PSI-20)?"], "speak_refs": [], "sources": [], "status": "clarify", "outcome": "clarify", "clarify": {"question": "Which do you mean: BASS-II (PSI-25) or ACME BRE (PSI-20)?", "options": ["BASS-II (PSI-25)", "ACME BRE (PSI-20)"], "why": "x"}, "scope": {}}
def nf(): return {"request_id": "r3", "question": "q", "speak": [], "speak_refs": [], "sources": [], "status": "not_found", "outcome": "not_found", "clarify": None, "scope": {}}


@pytest.fixture(autouse=True)
def _reset():
    yield
    rag.set_asker(None)


def run(asker, q="When do flames burn steadily?", state=None, **p):
    rag.set_asker(asker)
    b, st = FakeBridge(), state or DashboardState()
    return b, st, asyncio.run(content.Runner(b, st).ask_sources(q, **p))


def test_an_answer_goes_to_the_screen_with_its_sources_and_to_the_model_without_excerpts():
    a = Asker([ok()])
    b, st, m = run(a, psi="BRE", o2_pct=26.0, material=None)
    assert a.calls == [("When do flames burn steadily?", {"psi": "BRE", "o2_pct": 26.0})]          # empty parameters are not passed
    (pkt,) = b.of(Cmd.ANSWER_SHOW)
    assert pkt["tool"] == "ask_sources" and pkt["speak"] == ok()["speak"] and pkt["sources"][0]["page"] == 31 and pkt["sources"][0]["link"] == "https://psi.nasa.gov/x"
    assert m["status"] == "ok" and m["matched"] and m["speak"] == ok()["speak"] and m["sources"] == [{"n": 1, "label": "NASA document", "title": "PSI-20_Reports_Dissertation", "page": 31}]
    assert "next_offer" in m and "sources are on the screen" in m["reply_guidance"] and "quote" not in str(m)


def test_a_clarifying_question_is_asked_once_then_it_is_not_covered():
    st = DashboardState()
    b, st, m1 = run(Asker([clar()]), state=st)
    assert m1["status"] == "clarify" and m1["clarify"]["options"] and "Ask it once" in m1["reply_guidance"] and st.clarified
    b2, st, m2 = run(Asker([clar()]), state=st)                                                      # the astronaut answered, it is still ambiguous
    assert m2["status"] == "not_found" and m2["not_covered"] and "open question" in m2["reply_guidance"]
    b3, st, m3 = run(Asker([ok()]), state=st)
    assert m3["status"] == "ok" and st.clarified is False                                           # an answer resets it


def test_not_covered_tells_the_model_to_say_so_and_not_to_guess():
    b, st, m = run(Asker([nf()]))
    assert m["status"] == "not_found" and m["not_covered"] and m["speak"] == [] and "Do not guess" in m["reply_guidance"]
    assert b.of(Cmd.ANSWER_SHOW)[0]["speak"] == []


def test_without_the_rag_the_agent_uses_the_serving_db_text_search(monkeypatch):
    called = {}
    async def fake_intent(self, name, **args):
        called.update(name=name, **args); return {"status": "ok", "matched": True, "speak": ["x"]}
    monkeypatch.setattr(content.Runner, "intent", fake_intent)
    monkeypatch.setattr(rag, "available", lambda: False)
    b, st = FakeBridge(), DashboardState()
    m = asyncio.run(content.Runner(b, st).ask_sources("Why are smoke particles bigger?", psi="SAME"))
    assert called == {"name": "search_text", "query": "Why are smoke particles bigger?", "psi": "SAME"} and m["status"] == "ok"


def test_a_failure_while_building_the_rag_falls_back_instead_of_breaking_the_turn(monkeypatch):
    async def fake_intent(self, name, **args): return {"status": "ok", "matched": True, "speak": ["fallback"]}
    monkeypatch.setattr(content.Runner, "intent", fake_intent)
    monkeypatch.setattr(rag, "available", lambda: True)
    monkeypatch.setattr(rag, "get", lambda: (_ for _ in ()).throw(RuntimeError("postgres down")))
    m = asyncio.run(content.Runner(FakeBridge(), DashboardState()).ask_sources("q"))
    assert m["speak"] == ["fallback"]


def test_the_runner_removes_a_spoken_line_with_safe_or_threshold_wording_even_if_the_checker_missed_it():
    r = ok()
    r["speak"] = ["Oxygen levels of 26 % and above can allow steady flames.", "That level is safe for the crew."]; r["speak_refs"] = [[1], [1]]
    b, st, m = run(Asker([r]))
    assert m["speak"] == ["Oxygen levels of 26 % and above can allow steady flames."] and b.of(Cmd.ANSWER_SHOW)[0]["speak"] == m["speak"]
    only_bad = ok(); only_bad["speak"] = ["It is the safest atmosphere."]; only_bad["speak_refs"] = [[1]]
    b2, st2, m2 = run(Asker([only_bad]))
    assert m2["status"] == "not_found" and m2["not_covered"]


def test_an_oxygen_question_that_names_an_investigation_is_rerouted_to_ask_sources(monkeypatch):
    class Ex:
        def psis(self, t): return ["PSI-20"] if "BRE" in t else []
        def extract(self, t): return {"psi": "PSI-20"} if "BRE" in t else {}
    monkeypatch.setattr(rag, "extractor", lambda: Ex())
    a = Asker([ok()])
    rag.set_asker(a)
    b, st = FakeBridge(), DashboardState()
    st.typed("What oxygen level allows steady flames in the BRE tests?")
    m = asyncio.run(content.Runner(b, st).intent("oxygen_effect", scenario="iss"))
    assert m["status"] == "ok" and "ask_sources" in m["rerouted"] and a.calls[0][1] == {"psi": "PSI-20"}
    assert b.of(Cmd.ANSWER_SHOW)[0]["tool"] == "ask_sources"


def test_not_covered_shows_the_open_question_card_with_the_screens_category_and_no_passages(monkeypatch):
    from src.categories import PILLARS
    async def fake_call(name, **kw):
        return {"tool": "search_text", "question": "q", "speak": ["No passage in the documents, papers or cards matches that."], "table": {"columns": [], "rows": [{"text": "News calendar"}]},
                "cards": [], "gaps": ["no passage matches the query"], "source": {}, "version": 1}
    monkeypatch.setattr(content, "fcall", fake_call)
    b, st = FakeBridge(), DashboardState()
    st.pillar = "flammability"
    m = asyncio.run(content.Runner(b, st).intent("search_text", query="flames round space"))
    pkt = b.of(Cmd.ANSWER_SHOW)[0]
    assert pkt["open_question"] is True and pkt["table"] is None and pkt["cards"] == [] and pkt["speak"] == [] and pkt["offer"]["category"] == PILLARS["flammability"].label and pkt["offer"]["chips"]
    assert m["not_covered"] is True
    rag.set_asker(Asker([nf()]))
    b2 = FakeBridge(); st2 = DashboardState(); st2.pillar = "detection"
    asyncio.run(content.Runner(b2, st2).ask_sources("q"))
    p2 = b2.of(Cmd.ANSWER_SHOW)[0]
    assert p2["open_question"] is True and p2["speak"] == [] and p2["offer"]["category"] == PILLARS["detection"].label
