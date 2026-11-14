"""The emergency tools, the banner, typed questions and the question log (Round 10 §10.7 items 2, 3, 6; §10.1 item 8)."""
import asyncio
import json
from types import SimpleNamespace

import pytest

from src import alerts, qlog, turns
from src.bridge import Cmd, Evt
from src.state import DashboardState
from src.tools import flamoTools
from tests.helpers import FakeBridge


class Host(flamoTools):
    def __init__(self): self.bridge, self.state = FakeBridge(), DashboardState()


@pytest.fixture(autouse=True)
def log(tmp_path, monkeypatch):
    monkeypatch.setattr(qlog, "PATH", tmp_path / "q.jsonl")
    return tmp_path / "q.jsonl"


def lines(p): return [json.loads(l) for l in p.read_text().splitlines()]


def declare(h, text, situation="smoke"):
    h.state.typed(text)
    return asyncio.run(h.declare_fire_emergency(None, situation))


def test_a_hypothetical_question_does_not_declare_an_emergency_and_is_logged(log):
    h = Host()
    r = declare(h, "What should I do if a fire happens inside the suit?", "fire inside the spacesuit")
    assert r["status"] == "not_declared" and r["reason"] == "hypothetical" and "mission fire procedure" in r["reply_guidance"]
    assert not h.bridge.of(Cmd.ALERT_SET) and h.state.emergency is False
    assert lines(log)[0]["tool"] == "declare_fire_emergency" and lines(log)[0]["args"]["refused"] == "hypothetical"


def test_ambiguous_asks_once_and_a_real_report_declares_with_cabin_steps():
    h = Host()
    r = declare(h, "What should I do if I smell burning plastic in the cabin?")
    assert r["status"] == "not_declared" and "Is there a fire right now?" in r["reply_guidance"]
    r2 = declare(h, "There's smoke coming from the avionics rack", "smoke from the avionics rack")
    assert r2["status"] == "emergency_active" and len(r2["first_actions"]) == 5
    (pkt,) = h.bridge.of(Cmd.ALERT_SET)
    assert pkt["level"] == "emergency" and pkt["location"] == "cabin" and pkt["lang"] == "en" and h.state.emergency


def test_the_suit_banner_is_short_and_an_arabic_chat_gets_an_arabic_banner():
    h = Host()
    declare(h, "I see smoke in my suit", "smoke in the suit")
    assert h.bridge.of(Cmd.ALERT_SET)[-1]["steps"] == ["Alert the crew and ground control", "Follow your EVA emergency procedure"]
    h2 = Host()
    declare(h2, "في حريق في الكابينة", "حريق في الكابينة")
    assert h2.bridge.of(Cmd.ALERT_SET)[0]["lang"] == "ar" and h2.bridge.of(Cmd.ALERT_SET)[0]["footer"].startswith("اتبع")


def test_the_banner_clears_from_the_astronauts_words_from_the_dismiss_button_and_from_the_tool(log):
    h = Host()
    declare(h, "Fire in the galley!", "fire in the galley")
    assert asyncio.run(alerts.maybe_clear_from_text(h.bridge, h.state, "There is no fire, I was only asking.")) is True
    assert h.state.emergency is False and h.bridge.of(Cmd.ALERT_SET)[-1]["level"] == "clear"
    assert asyncio.run(alerts.maybe_clear_from_text(h.bridge, h.state, "What is BRE?")) is False
    declare(h, "I smell smoke", "smoke")
    from src.events import register_event_handlers
    class N:
        async def notify(self, *a, **k): pass
    handlers = {}
    class B(FakeBridge):
        def on(self, evt):
            def reg(fn): handlers[evt] = fn; return fn
            return reg
    b = B(); h.bridge = b
    register_event_handlers(b, h.state, N())
    asyncio.run(handlers[Evt.EMERGENCY_CLEARED]({}))
    assert h.state.emergency is False and b.of(Cmd.ALERT_SET)[-1]["level"] == "clear"
    asyncio.run(h.clear_fire_emergency(None))
    assert any(l["tool"] == "clear_fire_emergency" for l in lines(log))


def test_typed_questions_log_their_text_and_source_voice_questions_are_not_overwritten(log):
    st = DashboardState()
    assert turns.typed_text(st, "What is a cool flame?") is True and st.last_transcript == "What is a cool flame?" and st.last_source == "typed"
    st2 = DashboardState()
    st2.heard("Why do flames go out", True)                 # a voice turn is in progress: the conversation item is the same words
    assert turns.typed_text(st2, "Why do flames go out") is False and st2.last_source == "voice"


def test_every_tool_call_is_logged_and_a_turn_with_no_tool_is_logged_with_tool_null(log):
    st = DashboardState()
    turns.typed_text(st, "Open the suppression view")
    turns.tools_executed(st, [SimpleNamespace(name="show_dashboard", arguments='{"pillar": "suppression"}'), SimpleNamespace(name="ask_sources", arguments="{}")])
    turns.turn_without_tool(st)                              # a tool ran: nothing extra
    L = lines(log)
    assert [l["tool"] for l in L] == ["show_dashboard"] and L[0]["args"] == {"pillar": "suppression"} and L[0]["source"] == "typed"      # ask_sources is logged by the runner itself
    st2 = DashboardState()
    turns.typed_text(st2, "Tell me a joke about astronauts")
    turns.turn_without_tool(st2); turns.turn_without_tool(st2)
    assert [l["tool"] for l in lines(log)][-1:] == [None] and sum(1 for l in lines(log) if l["tool"] is None) == 1


def test_safety_net_declares_a_fire_now_when_the_model_does_not(monkeypatch):
    import asyncio
    import types

    from src import alerts

    monkeypatch.setattr(alerts, "SAFETY_NET_S", 0.01)
    sent = []

    class B:
        async def send(self, cmd, payload):
            sent.append(payload)

    st = types.SimpleNamespace(emergency=False, declared_at=0.0, last_transcript="there is smoke coming from the rack", last_source=None)
    assert asyncio.run(alerts.maybe_declare_from_text(B(), st, st.last_transcript)) is True
    assert sent and sent[-1]["level"] == "emergency" and st.emergency
    # a second emergency question shows the banner again
    st.last_transcript = "smoke from the rack again"
    assert asyncio.run(alerts.maybe_declare_from_text(B(), st, st.last_transcript)) is True and len(sent) == 2
    # a question is not a fire, and nothing is sent twice when the model already declared
    assert asyncio.run(alerts.maybe_declare_from_text(B(), st, "what should I do if there is smoke")) is False
    import time
    async def model_declares_first():
        t = asyncio.create_task(alerts.maybe_declare_from_text(B(), st, "there is fire in the rack"))
        await asyncio.sleep(0)
        st.declared_at = time.monotonic()
        return await t
    assert asyncio.run(model_declares_first()) is False
