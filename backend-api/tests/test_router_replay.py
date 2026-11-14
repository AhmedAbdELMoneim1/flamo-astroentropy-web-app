"""Round 14 §14.4 / §14.7 step 6: the replays and the general -> specific pairs, through the real router with the real flameo tools and the serving.db text search standing in
for the RAG (so the test is deterministic and needs no keys). The live replay with the RAG is scripts/replay_router.py."""
import asyncio
import os
from pathlib import Path

import pytest
import yaml

if not os.getenv("FLAMEO_DB"):
    pytest.skip("FLAMEO_DB not set", allow_module_level=True)

from src import flameo, rag  # noqa: E402
from src.categories import load_coverage  # noqa: E402
from src.router.answer import Router  # noqa: E402
from src.state import DashboardState  # noqa: E402

SPEC = yaml.safe_load((Path(__file__).parent / "golden" / "router_replay.yaml").read_text(encoding="utf-8"))


class Bridge:
    def __init__(self):
        self.sent = []

    async def send(self, t, p, dest_identity=None):
        self.sent.append((t, p))


@pytest.fixture(autouse=True)
def no_rag(monkeypatch, tmp_path):
    from src import qlog
    flameo.init()
    load_coverage(flameo.call)
    monkeypatch.setattr(rag, "available", lambda: False)
    monkeypatch.setattr(qlog, "PATH", tmp_path / "q.jsonl")


def run(rows):
    async def go():
        st = DashboardState()
        r = Router(Bridge(), st)
        out = []
        for row in rows:
            st.last_transcript = row["q"]
            m = await r.answer(row["q"])
            out.append((row, m.get("router", {}).get("answered_by"), m))
        return out
    return asyncio.run(go())


def test_round_13_replay_never_says_not_covered_and_meets_the_expectations():
    out = run(SPEC["round13"])
    assert [row["q"] for row, by, _ in out if by == "not_found"] == []
    bad = [(row["q"], by, row["ok"]) for row, by, _ in out if by not in row["ok"]]
    assert bad == [], bad


def test_round_10_replay_never_says_not_covered_and_meets_the_expectations():
    out = run(SPEC["round10"])
    assert [row["q"] for row, by, _ in out if by == "not_found"] == []
    bad = [(row["q"], by, row["ok"]) for row, by, _ in out if by not in row["ok"]]
    assert bad == [], bad


def test_the_key_words_of_the_regression_turns_are_spoken():
    out = run(SPEC["round13"])
    for row, by, m in out:
        if row.get("find"):
            import re
            assert any(re.search(row["find"], x, re.I) for x in m["speak"]), (row["q"], m["speak"])


@pytest.mark.parametrize("pair", SPEC["pairs"], ids=[p["general"][:40] for p in SPEC["pairs"]])
def test_general_then_specific_pairs(pair):
    """If the specific question answers, the general one must answer or clarify, never "not covered"."""
    (g,), (s,) = run([{"q": pair["general"], "ok": []}]), run([{"q": pair["specific"], "ok": []}])
    assert g[1] != "not_found", (pair, g[1])
    if s[1] in ("tool", "rag", "both"):
        assert g[1] in ("tool", "rag", "both", "clarify")


def test_a_clarify_is_asked_once_and_its_reply_runs_the_chosen_option(monkeypatch):
    """The scoped RAG finds nothing (stubbed); the facet probe finds fabrics in BASS-II, BASS and Saffire-II: one short question with those options, then the chosen option runs."""
    class Ask:
        async def ask(self, q, **p):
            return {"request_id": "x", "question": q, "status": "not_found", "outcome": "not_found", "speak": [], "speak_refs": [], "sources": [], "clarify": None}
    monkeypatch.setattr(rag, "available", lambda: True)
    monkeypatch.setattr(rag, "get", lambda: Ask())
    out = run([{"q": "thin vs thick fabric", "ok": []}, {"q": "second", "ok": []}])
    (r1, by1, m1), (r2, by2, m2) = out
    assert by1 == "clarify" and m1["clarify"]["options"] and "Which one" in m1["speak"][0] and len(m1["speak"]) == 1
    assert by2 in ("tool", "rag", "both") and m2["speak"][0].startswith("Taking ")


def test_not_found_only_when_the_probe_is_empty(monkeypatch):
    class Ask:
        async def ask(self, q, **p):
            return {"request_id": "x", "question": q, "status": "not_found", "outcome": "not_found", "speak": [], "speak_refs": [], "sources": [], "clarify": None}
    monkeypatch.setattr(rag, "available", lambda: True)
    monkeypatch.setattr(rag, "get", lambda: Ask())
    (row, by, m), = run([{"q": "xylophone quasar pudding", "ok": []}])
    assert by == "not_found" and m["not_covered"] and "open question" in m["reply_guidance"]
    (row, by, m), = run([{"q": "what about silicone fabric tests?", "ok": []}])
    assert by != "not_found"


def test_every_answer_has_at_most_three_spoken_lines_and_logs_a_router_object(tmp_path):
    import json
    out = run(SPEC["round13"][:12])
    assert all(len(m["speak"]) <= 3 for _, _, m in out)
    from src import qlog
    lines = [json.loads(x) for x in qlog.PATH.read_text().splitlines()]
    assert lines and all("router" in x and x["router"]["answered_by"] for x in lines if x["tool"] == "answer")
    r = next(x["router"] for x in lines if x["tool"] == "answer")
    assert {"entities", "intent", "context", "plan", "branches", "broaden", "probe", "answered_by", "why"} <= set(r)
