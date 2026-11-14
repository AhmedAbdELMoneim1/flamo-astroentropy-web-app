"""Round 15 P1: the 12 question types, the understanding model (a fake), the five new tools through the router, follow-up lists, smart clarify, the glossary ladder,
adaptive retrieval depth and the server-side gate. Real flameo tools on serving.db, no network, no key."""
import asyncio
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

if not os.getenv("FLAMEO_DB"):
    pytest.skip("FLAMEO_DB not set", allow_module_level=True)

from src import flameo, rag, spoken  # noqa: E402
from src.categories import load_coverage  # noqa: E402
from src.router import llm_understand  # noqa: E402
from src.router.answer import Router  # noqa: E402
from src.router.gate import Gate, RecordingBridge  # noqa: E402
from src.router.session import Session  # noqa: E402
from src.router.understand import apply_model, understand  # noqa: E402
from src.state import DashboardState  # noqa: E402

ext = rag.extractor()
FORBIDDEN = ("safest", "safer", "unsafe")


class Bridge:
    def __init__(self):
        self.sent = []

    async def send(self, t, p, dest_identity=None):
        self.sent.append((t, p))


@pytest.fixture(autouse=True)
def setup(monkeypatch, tmp_path):
    from src import qlog
    flameo.init()
    load_coverage(flameo.call)
    monkeypatch.setattr(rag, "available", lambda: False)
    monkeypatch.setattr(qlog, "PATH", tmp_path / "q.jsonl")
    llm_understand.set_understander(None)
    yield
    llm_understand.set_understander(None)


def session_run(questions):
    async def go():
        b, st = Bridge(), DashboardState()
        r = Router(b, st)
        out = []
        for q in questions:
            st.last_transcript = q
            out.append(await r.answer(q))
        return b, out
    return asyncio.run(go())


# ── the 12 types by rules ────────────────────────────────────────────────────
CASES = [
    ("what's ignition?", "explain", {"term": "ignition"}), ("what does spread rate mean?", "explain", {}), ("explain opposed flow", "explain", {}),
    ("what is a cool flame", "explain", {}), ("what's iginition i see in screen ?", "explain", {}),
    ("what does 18 percent oxygen mean?", "interpret", {"o2": 18.0}), ("is 39.8 % at 14.8 psi dangerous?", "interpret", {"o2": 39.8, "pressure_psi": 14.8}),
    ("tell me about test 19115A1", "test", {"test_ids": ["19115A1"]}), ("compare 19150A1 and 19115A1", "compare_tests", {"test_ids": ["19150A1", "19115A1"]}),
    ("Compare BASS and BASS-II", "compare_tests", {}),
    ("i want tests in 40%", "nearest", {"o2": 40.0}), ("tests at 40 percent oxygen", "nearest", {"o2": 40.0}),
    ("what materials do you cover?", "catalogue", {}), ("what's the max oxygen in the data", "catalogue", {}), ("how many tests in Saffire-II?", "catalogue", {}),
    ("which paper appears most?", "papers", {}), ("papers on BASS-II", "papers", {}), ("what's best paper appear alot in sources ?", "papers", {}),
    ("does flow make fabric burn faster?", "effect", {}), ("why are flames round in space?", "effect", {}),
    ("which experiments matter most for prevention?", "ranking", {}), ("rank the investigations for detection", "ranking", {}),
    ("what should I do if a fire starts in the suit?", "procedure", {}), ("go back", "navigation", {}), ("tell me a joke", "navigation", {}),
]


@pytest.mark.parametrize("q,qtype,ents", CASES, ids=[c[0][:40] for c in CASES])
def test_rules_type_the_question(q, qtype, ents):
    u = understand(q, Session(), ext, None)
    assert u.qtype == qtype, (u.qtype, u.intents)
    for k, v in ents.items():
        assert (u.term if k == "term" else u.entities().get(k)) == v


def test_a_digit_inside_o2_is_not_a_percentage():
    assert understand("fabric is danger in what's o2 percentage ?", Session(), ext, None).o2 is None


def test_a_threshold_is_not_a_stated_value():
    u = understand("is there any test above 25 percent oxygen?", Session(), ext, None)
    assert u.o2 is None and u.qtype == "catalogue"


# ── the understanding model (a fake): validated, never trusted blindly ─────────
def test_model_entities_must_exist_in_the_vocabulary_and_never_override_the_rules():
    u = understand("what's the thing about it", Session(), ext, None)
    apply_model(u, {"out": {"type": "explain", "confidence": 0.9, "psi": ["Saffire-II", "Nonexistent-9"], "material": "unobtainium", "fields": ["oxygen", "mood"], "term": "ignition",
                            "test_ids": ["19115A1", "not an id"], "o2": 250}, "by": "gemini", "key": "gemini#2", "ms": 300}, ext)
    assert u.psis == ["PSI-99"] and u.material is None and u.fields == ["oxygen"] and u.test_ids == ["19115A1"] and u.o2 is None
    assert u.term == "ignition" and u.qtype != "explain"           # the model named an investigation: a data question, not a glossary one
    assert u.model["entities_added"]["psi"] == ["PSI-99"] and "AIza" not in str(u.model)


def test_model_cannot_make_an_emergency_or_a_navigation_and_needs_its_prerequisites():
    u = understand("tell me about 40 percent oxygen", Session(), ext, None)
    apply_model(u, {"out": {"type": "emergency", "confidence": 1.0}}, ext)
    assert u.qtype != "emergency"
    u2 = understand("hmm what about it", Session(), ext, None)
    apply_model(u2, {"out": {"type": "test", "confidence": 0.95, "test_ids": []}}, ext)
    assert u2.qtype != "test"                                           # a test question with no test id is not accepted
    u3 = understand("what is a cool flame", Session(), ext, None)
    apply_model(u3, {"out": {"type": "effect", "confidence": 0.7}}, ext)
    assert u3.qtype == "explain"                                        # the rules were sure (0.9) and the model less so


def test_a_low_confidence_model_answer_lowers_the_confidence_and_keeps_the_alternative():
    u = understand("what is it about spread", Session(), ext, None)
    apply_model(u, {"out": {"type": "effect", "confidence": 0.4, "alt_type": "explain"}}, ext)
    assert u.qconf <= 0.4 and u.alt_types == ["explain"]


def test_no_model_or_a_failed_call_falls_back_to_the_rules():
    u = understand("what does 18 percent oxygen mean", Session(), ext, None)
    apply_model(u, {"out": None, "why": "gemini: TimeoutError; "}, ext)
    assert u.qtype == "interpret" and u.by == "rules" and u.model["used"] is False


def test_the_router_uses_the_model_and_logs_the_understanding(tmp_path):
    class Fake:
        async def classify(self, text, ctx=None, timeout=0.6):
            return {"out": {"type": "interpret", "confidence": 0.95, "o2": 34}, "by": "gemini", "key": "gemini#3", "ms": 210, "why": ""}
    llm_understand.set_understander(Fake())
    b, (m,) = session_run(["ايش يعني ثلاثين و اربعة بالمية اكسجين"])
    assert m["router"]["main"] == "interpret_conditions" and "34 percent oxygen" in m["speak"][0]


# ── the five new tools through the router ────────────────────────────────────
def spoken_ok(m):
    text = " ".join(m["speak"])
    assert len(m["speak"]) <= 3, m["speak"]
    assert not any(w in text.lower() for w in FORBIDDEN) and "coverage" not in text.lower().replace("coverage here is", "")
    return text


def test_explain_gives_the_glossary_definition_and_one_example_with_a_source():
    b, (m,) = session_run(["what is a cool flame?"])
    assert m["router"]["main"] == "explain" and spoken_ok(m).startswith("A cool flame is a faint")
    ans = next(p for t, p in b.sent if p.get("tool") == "explain")
    assert ans["glossary"]["status"] == "draft, to review" and ans["shape"]["direct"] and ans["qtype"] == "explain"


def test_interpret_says_where_the_value_sits_and_the_coverage_never_safe_or_dangerous():
    b, (m,) = session_run(["what does 18 percent oxygen mean?"])
    t = spoken_ok(m)
    assert m["router"]["main"] == "interpret_conditions" and "18 percent oxygen is" in t and "oxygen partial pressure" in t
    ans = next(p for tt, p in b.sent if p.get("tool") == "interpret_conditions")
    assert set(ans["shape"]) >= {"direct", "evidence", "meaning", "coverage"}
    assert "dangerous" not in t.lower()


def test_a_pasted_table_row_answers_the_test_then_what_its_conditions_mean():
    b, (m,) = session_run(["is this ACME Flame Design (PSI-10)\t19150A1\tC2H₄\t39.8\t14.8 (101.766671622 kPa) – danger ?"])
    t = spoken_ok(m)
    assert m["router"]["main"] == "interpret_conditions" and t.startswith("Test 19150A1 is a flight test") and "39.8 percent oxygen" in t


def test_get_test_and_an_unknown_test_id_never_guesses():
    b, (m, m2) = session_run(["tell me about test 19115A1", "tell me about test 99999Z9"])
    assert m["router"]["main"] == "get_test" and "Test 19115A1 is a flight test in ACME Flame Design (PSI-10)" in m["speak"][0]
    assert m2["router"]["answered_by"] != "tool" or "19115A1" not in " ".join(m2["speak"])


def test_compare_tests_never_ranks():
    b, (m,) = session_run(["compare 19150A1 and 19115A1"])
    assert m["router"]["main"] == "compare_tests" and "the data does not rank them" in " ".join(m["speak"])


def test_papers_are_counted_not_rated():
    b, (m,) = session_run(["what's best paper appear alot in sources ?"])
    assert m["router"]["main"] == "list_papers" and "does not rate how good a paper is" in " ".join(m["speak"])


def test_ranking_drops_the_method_from_speech_and_keeps_it_as_a_footnote():
    b, (m,) = session_run(["Which experiments matter most for prevention?"])
    assert "ranked by" not in " ".join(m["speak"]) and m["speak"][0].startswith("For Prevention, the most relevant investigations are")
    ans = next(p for t, p in b.sent if p.get("tool") == "rank_investigations")
    assert ans["footnote"].startswith("Ranked by")


def test_every_spoken_number_of_the_new_tools_is_in_a_tool_line():
    for q in ("what does 18 percent oxygen mean?", "tell me about test 19115A1", "compare 19150A1 and 19115A1", "which paper appears most?", "what is a cool flame?"):
        b, (m,) = session_run([q])
        ans = b.sent[-1][1]
        assert spoken.unsupported(" ".join(m["speak"]), [" ".join(ans["speak"]), q]) == set(), q


# ── follow-ups: the list on screen ──────────────────────────────────────────
def test_they_the_first_one_and_compare_them_resolve_against_the_list_on_screen():
    b, ms = session_run(["Which experiments matter most for prevention?", "ok what they cover ?"])
    assert ms[1]["router"]["main"] == "get_investigation" and len(ms[1]["speak"]) >= 1
    b, ms = session_run(["Which experiments matter most for prevention?", "compare them"])
    assert ms[1]["router"]["main"] == "compare"
    b, ms = session_run(["Which experiments matter most for prevention?", "tell me about the first one"])
    assert ms[1]["router"]["main"] == "get_investigation" and "FLEX" in ms[1]["speak"][0]
    b, ms = session_run(["Which experiments matter most for prevention?", "a random one"])
    assert ms[1]["router"]["main"] == "get_investigation"


def test_what_it_means_reuses_the_last_conditions_or_the_last_term():
    b, ms = session_run(["tests at 18 percent oxygen", "i said what it mean !!!"])
    assert ms[1]["router"]["main"] == "interpret_conditions" and "18 percent oxygen" in ms[1]["speak"][0]


# ── smart clarify and the ladder before "not covered" ──────────────────────
def test_a_bare_concept_word_asks_one_question_with_two_options_that_have_data_then_never_again():
    b, ms = session_run(["ignition", "the first one"])
    assert ms[0]["router"]["answered_by"] == "clarify" and "what ignition is" in ms[0]["speak"][0] and "investigations" in ms[0]["speak"][0]
    assert ms[1]["router"]["main"] == "explain"


def test_the_second_option_shows_the_data():
    b, ms = session_run(["ignition", "the data"])
    assert ms[1]["router"]["main"] == "rank_investigations"


def test_an_unknown_concept_gets_one_labelled_sentence_of_general_background_without_numbers():
    class Fake:
        async def classify(self, *a, **k): return {"out": None, "why": "off"}
        async def background(self, term): return "A flame front is the thin zone where the burning happens."
    llm_understand.set_understander(Fake())
    b, (m,) = session_run(["what does zzqx mean?"])
    assert m["router"]["answered_by"] == "background" and m["speak"][0].startswith("General background, not from the PSI data: ")
    assert not any(ch.isdigit() for ch in m["speak"][0])


def test_the_background_checker_rejects_numbers_and_safety_words():
    bad = llm_understand.BAD_BG
    assert bad.search("It burns at 300 degrees.") and bad.search("This is the safest option.") and not bad.search("A flame front is the thin zone where the burning happens.")


def test_not_covered_stays_possible_and_is_the_last_step():
    b, (m,) = session_run(["what does zzqx mean?"])
    assert m["router"]["answered_by"] == "not_found"


# ── adaptive retrieval depth ────────────────────────────────────────────────
from src.paper_rag import ask as askmod  # noqa: E402
from src.paper_rag import chunks as C  # noqa: E402
from src.paper_rag import retrieval_log  # noqa: E402
from src.paper_rag.scope import Scope  # noqa: E402
from src.paper_rag.search import SearchResult  # noqa: E402
from src.paper_rag.stores.vector_db.providers.PGvectorProvider import RetrievedDocument  # noqa: E402

TEXT = "Generally, it has been found that oxygen levels of 26 % and above can allow steady flames. The flames are thin blue in color."


def D(cid, score=0.9, text=TEXT):
    return RetrievedDocument(cid, text, score, {"kind": "doc", "type": "text", "generated": False, "page": 31, "title": "BRE thesis", "psis": ["PSI-20"], "download_url": "https://psi.nasa.gov/x"})


class DeepSearcher:
    table, embedder, reranker = "t", SimpleNamespace(last_key="cohere#1"), None

    def __init__(self, first, second, raises_deep=None):
        self.first, self.second, self.raises, self.calls = first, second, raises_deep, []
        self.store = SimpleNamespace(scope_size=self._size)

    async def _size(self, t, s): return (30, 4)

    async def search(self, q, scope=None, top_n=5, k=20, embed_timeout=None, deep=False):
        self.calls.append({"q": q, "scope": scope, "deep": deep, "top_n": top_n})
        if deep and self.raises:
            raise self.raises
        docs, cand = (self.second, 80) if deep else (self.first, 4)
        return SearchResult(final=docs[:top_n], vector=docs, keyword=docs[:1], fused=docs, reranker="cohere", ms={"embed": 1}, candidates=cand)


class Resolver:
    def resolve(self, **p): return Scope(["PSI-20"], {"psi": ["PSI-20"]}, False, p)
    def widen(self, scope): return Scope(["PSI-20", "PSI-25"], {"pillar": ["PSI-20"]}, False, {"pillar": "prevention"})


class Comp:
    def __init__(self, sents): self.sents, self.n = sents, 0
    async def compose(self, q, chunks, timeout):
        self.n += 1
        return self.sents, {"provider": "gemini", "key": "gemini#1", "reason": ""}


GOOD = [{"text": "Oxygen levels of 26 % and above can allow steady flames.", "chunks": [1]}]


def mk(searcher, comp=None, **kw):
    return askmod.AskSources(searcher, Resolver(), comp or Comp(GOOD), C.Vocab({"PSI-20": "ACME BRE"}, {}, [], []), serving_call=lambda *a, **k: {"speak": [], "table": {"rows": []}}, **kw)


@pytest.fixture
def rlog(tmp_path, monkeypatch):
    monkeypatch.setattr(retrieval_log, "PATH", tmp_path / "r.jsonl")
    monkeypatch.setenv("RAG_LOG", "summary")
    return tmp_path / "r.jsonl"


def entries(p):
    import json
    return [json.loads(x) for x in p.read_text().splitlines()]


def test_too_little_in_pass_one_runs_one_deeper_pass_and_logs_both(rlog):
    s = DeepSearcher([D("a", 0.9)], [D(f"c{i}", 0.9) for i in range(6)])
    r = asyncio.run(mk(s).ask("when do flames burn steadily?", psi="BRE"))
    assert r["status"] == "ok" and [c["deep"] for c in s.calls] == [False, True] and s.calls[1]["top_n"] == 8
    (e,) = entries(rlog)
    assert [x["pass"] for x in e["retrieval"]] == [1, 2] and e["retrieval"][1]["widened"] == "deeper" and e["retrieval"][1]["k"] == 120 and e["retrieval"][0]["candidates"] == 4
    assert e["retrieval"][0]["why"] and e["retrieval_widened"] == "deeper"


def test_enough_in_pass_one_means_no_second_pass(rlog):
    s = DeepSearcher([D(f"c{i}", 0.9) for i in range(6)], [])
    s.search_orig = s.search

    async def search(q, scope=None, top_n=5, k=20, embed_timeout=None, deep=False):
        r = await s.search_orig(q, scope, top_n, k, embed_timeout, deep)
        r.candidates = 40
        return r
    s.search = search
    asyncio.run(mk(s).ask("q"))
    assert [c["deep"] for c in s.calls] == [False] and len(entries(rlog)[0]["retrieval"]) == 1


def test_a_weak_first_pass_is_retried_before_the_question_is_asked_back(rlog):
    s = DeepSearcher([D("a", 0.05), D("b", 0.04)], [D(f"c{i}", 0.9) for i in range(6)])
    r = asyncio.run(mk(s).ask("something vague"))
    assert r["status"] == "ok"                                          # without the second pass this was a clarify


def test_when_the_second_pass_is_still_weak_it_clarifies_as_before(rlog):
    s = DeepSearcher([D("a", 0.05)], [D("b", 0.05)])
    r = asyncio.run(mk(s).ask("something vague"))
    assert r["status"] == "clarify"


def test_the_second_pass_never_runs_without_1_5_seconds_left(rlog):
    s = DeepSearcher([D("a", 0.9)], [D(f"c{i}", 0.9) for i in range(6)])
    asyncio.run(mk(s, budget_s=1.2).ask("q"))
    assert [c["deep"] for c in s.calls] == [False]


def test_adaptive_depth_can_be_switched_off(rlog):
    s = DeepSearcher([D("a", 0.9)], [D(f"c{i}", 0.9) for i in range(6)])
    asyncio.run(mk(s, adaptive=False).ask("q"))
    assert [c["deep"] for c in s.calls] == [False]


def test_a_failing_second_pass_keeps_the_first_result(rlog):
    s = DeepSearcher([D("a", 0.9)], [], raises_deep=RuntimeError("cohere"))
    r = asyncio.run(mk(s).ask("q"))
    assert r["status"] == "ok" and entries(rlog)[0]["retrieval"][-1].get("error") == "RuntimeError"


def test_the_widened_scope_and_the_expanded_query_come_after_deeper(rlog):
    s = DeepSearcher([D("a", 0.9)], [D("x", 0.1)])
    asyncio.run(mk(s, budget_s=9).ask("what is ignition?"))
    assert [c["deep"] for c in s.calls] == [False, True, True, True]
    assert s.calls[2]["scope"] != s.calls[1]["scope"] and "ignite" in s.calls[3]["q"] or "ignition" in s.calls[3]["q"].lower()
    e = entries(rlog)[0]
    assert [x.get("widened") for x in e["retrieval"]] == [None, "deeper", "scope", "query"] and e["scope"]["widened_to"]["psis"] == ["PSI-20", "PSI-25"]


def test_when_the_composer_drops_every_sentence_a_second_pass_recomposes(rlog):
    s = DeepSearcher([D(f"c{i}", 0.9) for i in range(6)], [D(f"d{i}", 0.9) for i in range(6)])
    async def search(q, scope=None, top_n=5, k=20, embed_timeout=None, deep=False):
        s.calls.append({"deep": deep})
        r = SearchResult(final=[D(f"{'d' if deep else 'c'}{i}", 0.9) for i in range(6)], fused=[1] * 20, reranker="cohere", ms={}, candidates=40)
        return r
    s.search = search
    comp = Comp([{"text": "It is safe at 26 %.", "chunks": [1]}])
    r = asyncio.run(mk(s, comp, budget_s=9).ask("q"))
    assert [c["deep"] for c in s.calls] == [False, True] and comp.n == 2 and r["composer"] == "extractive"


def test_the_widened_scope_is_a_superset_of_the_first_one():
    from src.paper_rag.scope import ScopeResolver
    r = ScopeResolver(os.environ["FLAMEO_DB"])
    sc = r.resolve(psi="BASS-II", scenario="moon_base", material="SIBAL")
    w = r.widen(sc)
    assert set(sc.psis) <= set(w.psis) and "scenario" not in w.used and isinstance(w.used["material"], tuple)
    assert r.widen(r.resolve(o2_pct=30.0)) is None


# ── the gate ─────────────────────────────────────────────────────────────────
class FakeRouter:
    def __init__(self, bridge, calls): self.bridge, self.calls = bridge, calls
    ext = ext
    async def answer(self, q):
        self.calls.append(q)
        await self.bridge.send("ANSWER_SHOW", {"q": q})
        return {"speak": ["Line one.", "Line two."], "router": {"answered_by": "tool", "main": "explain"}, "next_offer": "Want more?"}


class Session2:
    def __init__(self): self.said = []
    def interrupt(self): self.said.append("interrupt")
    def generate_reply(self, instructions=None, user_input=None): self.said.append(instructions)


def gate(session=None):
    calls, real = [], Bridge()
    st = DashboardState()
    return Gate(real, st, session, ext, router_factory=lambda b: FakeRouter(b, calls)), calls, real, st


def test_the_gate_starts_data_questions_only():
    g, calls, real, st = gate()
    assert g.likely_question("what is ignition") and g.likely_question("tell me about test 19115A1")
    for q in ("yes", "thanks", "go back", "there is smoke from the rack", "ok", "tell me a joke"):
        assert not g.likely_question(q), q


def test_the_tool_call_takes_the_prefetched_answer_once_and_the_screen_gets_it_then():
    async def go():
        g, calls, real, st = gate()
        assert g.kick("what is ignition?") and not g.kick("what is ignition?")      # one run per question
        await asyncio.sleep(0)
        assert real.sent == []                                                       # nothing on the screen yet
        m = await g.take("What is ignition")
        assert m["speak"][0] == "Line one." and m["router"]["prefetched"] and len(real.sent) == 1 and calls == ["what is ignition?"]
        assert await g.take("what is ignition?") is None                             # used once
    asyncio.run(go())


def test_when_gemini_skips_the_tool_the_server_answer_is_said_instead():
    async def go():
        s = Session2()
        g, calls, real, st = gate(s)
        g.kick("what is ignition?")
        assert g.pending("what is ignition?")
        assert await g.catch_up("what is ignition?") is True
        assert s.said[0] == "interrupt" and "Line one. Line two. Want more?" in s.said[1] and len(real.sent) == 1 and st.turn_tools == 1
        assert g.pending("what is ignition?") is None and await g.catch_up("what is ignition?") is False
    asyncio.run(go())


def test_the_recording_bridge_keeps_packets_until_flushed():
    async def go():
        rb, real = RecordingBridge(), Bridge()
        await rb.send("a", {"x": 1})
        assert real.sent == []
        await rb.flush(real)
        assert real.sent == [("a", {"x": 1})]
    asyncio.run(go())


def test_a_slow_branch_comes_back_empty_instead_of_raising():
    import time

    async def go():
        r = Router(Bridge(), DashboardState())

        async def slow(b):
            await asyncio.sleep(5)
            return {"kind": "tool", "has": True}
        r._tool = slow
        fast_rag = {"kind": "rag", "args": {"x": 1}}
        r._rag = lambda q, a: asyncio.sleep(0, result={"kind": "rag", "has": True})
        return await r.run("q", [{"kind": "tool", "tool": "x", "args": {}}, fast_rag], time.monotonic() + 0.05)
    out = asyncio.run(go())
    assert out[0]["has"] is False and out[0]["err"] == "timeout" and out[1]["has"] is True


def test_a_named_investigation_is_never_turned_into_a_glossary_question_by_the_model():
    u = understand("What is BRE?", Session(), ext, None)
    apply_model(u, {"out": {"type": "explain", "confidence": 0.9, "term": "BRE"}, "by": "groq"}, ext)
    assert u.qtype == "catalogue" and u.psis == ["PSI-20"]


# ── deployment: the remote RAG of a deployed agent ───────────────────────────
def test_the_internal_rag_endpoint_needs_the_shared_secret(monkeypatch):
    from fastapi.testclient import TestClient
    monkeypatch.setenv("LIVEKIT_URL", "wss://x.livekit.cloud")
    from src import api
    c = TestClient(api.app)
    body = {"question": "what is ignition", "params": {"psi": "BRE"}}
    monkeypatch.delenv("RAG_INTERNAL_KEY", raising=False)
    assert c.post("/api/internal/rag/ask", json=body).status_code == 404            # off unless a key is configured
    monkeypatch.setenv("RAG_INTERNAL_KEY", "s3cret")
    assert c.post("/api/internal/rag/ask", json=body).status_code == 403
    assert c.post("/api/internal/rag/ask", json=body, headers={"X-Internal-Key": "wrong"}).status_code == 403

    async def fake_ask(q, **p):
        return {"status": "ok", "speak": ["x"], "sources": [], "got": p}
    monkeypatch.setattr(rag, "available", lambda: True)
    monkeypatch.setattr(rag, "get", lambda: SimpleNamespace(ask=fake_ask))
    r = c.post("/api/internal/rag/ask", json={**body, "params": {"psi": "BRE", "evil": "x"}}, headers={"X-Internal-Key": "s3cret"})
    assert r.status_code == 200 and r.json()["got"] == {"psi": "BRE"}               # only the known parameters pass


def test_the_remote_asker_posts_to_the_api_with_the_key(monkeypatch):
    import httpx
    seen = {}

    def handler(req):
        seen["url"], seen["key"], seen["body"] = str(req.url), req.headers["x-internal-key"], req.content.decode()
        return httpx.Response(200, json={"status": "ok", "speak": ["hi"], "sources": []})
    ra = rag.RemoteAsker("https://api.example.com/", "k1")
    ra.http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    out = asyncio.run(ra.ask("what is ignition", psi="BRE", material=None))
    assert out["speak"] == ["hi"] and seen["url"] == "https://api.example.com/api/internal/rag/ask" and seen["key"] == "k1" and '"material"' not in seen["body"]
    monkeypatch.setenv("RAG_API_URL", "https://api.example.com")
    assert rag.remote_url() and isinstance(rag.build(), rag.RemoteAsker)
