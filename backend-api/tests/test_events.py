"""Event handlers and phases with a fake bridge and notifier (no LiveKit, no model)."""
import asyncio

import pytest

from src import categories, flameo
from src.bridge import Evt
from src.events import register_event_handlers
from src.notify import Nudger
from src.state import DashboardState
from tests.helpers import FakeBridge, needs_db

pytestmark = needs_db


@pytest.fixture(scope="module", autouse=True)
def _db():
    from tests.conftest import DB

    flameo.init(DB)
    categories.load_coverage(flameo.call)


class Bridge(FakeBridge):
    def __init__(self):
        super().__init__()
        self.handlers = {}

    def on(self, evt):
        def reg(fn):
            self.handlers[evt] = fn
            return fn
        return reg


class Notifier:
    def __init__(self):
        self.items, self.asked, self.nudger = [], [], None

    async def notify(self, i, _from_nudge=False):
        self.items.append(i)

    async def ask(self, text):
        self.asked.append(text)


def setup(settle=0.05, scene=0.05):
    b, st, n = Bridge(), DashboardState(), Notifier()
    register_event_handlers(b, st, n, settle_s=settle, scene_settle_s=scene)
    return b, st, n


def fire(b, evt, payload):
    return asyncio.run(b.handlers[evt](payload))


def test_first_visit_gives_the_intro_overview_line_and_first_chip():
    b, st, n = setup()
    fire(b, Evt.VIEW_SELECTED, {"pillar": "suppression", "view": "suppression", "scenario": "iss", "source": "user_tap"})
    i = n.items[-1]
    assert i.kind == "view_opened" and i.speak and i.facts["phase"] == "category_entry" and i.facts["first_visit"] == "yes"
    assert i.facts["intro"].startswith("This is about putting a fire out") and i.facts["ask_me"] == "Which gases did the experiments add?"
    assert i.facts["overview_speak"].startswith("At the ISS cabin oxygen and pressure, 81 tests")
    vo = b.of("view.open")[0]
    assert vo["pillar"] == "suppression" and vo["coverage"] == "High" and vo["ranking"]["rows"] and len(vo["suggestions"]) == 3


def test_later_visit_has_no_intro_and_asks_anything():
    b, st, n = setup()
    for _ in range(2):
        fire(b, Evt.VIEW_SELECTED, {"pillar": "flammability", "view": "flame_spread", "source": "user_tap"})
    i = n.items[-1]
    assert i.facts["first_visit"] == "no" and "intro" not in i.facts and i.facts["ask_anything_about"] == "Flammability & Fire Behavior"


def test_automatic_entry_is_silent_and_not_counted_as_a_visit():
    b, st, n = setup()
    fire(b, Evt.VIEW_SELECTED, {"pillar": "flammability", "view": "flame_spread", "source": "auto"})
    assert n.items[-1].speak is False and n.items[-1].facts["phase"] == "silent"
    fire(b, Evt.VIEW_SELECTED, {"pillar": "flammability", "view": "flame_spread", "source": "user_tap"})
    assert n.items[-1].facts["first_visit"] == "yes"


def test_detection_overview_uses_all_tests_with_the_fixed_note():
    b, st, n = setup()
    fire(b, Evt.VIEW_SELECTED, {"pillar": "detection", "view": "smoke", "scenario": "moon_base"})
    d = b.of("view.open")[0]["dashboard"]
    assert d["note"] == "Smoke tests are shown for all conditions: the SAME and SAME-R records have no oxygen or pressure values."
    assert any(k["value"] == 10 for k in d["kpis"])             # the 10 PSI-101 particle sizes only exist with no scenario


def test_scene_arrival_pushes_one_answer_with_ranking_and_speaks_the_decided_lines():
    async def go():
        b, st, n = setup()
        await b.handlers[Evt.CONDITIONS_CHANGED]({"scenario": "moon_base"})
        a = b.of("answer.show")[0]                               # the screen follows at once ...
        assert a["tool"] == "scenario_coverage" and a["ranking"]["divider"] == "No tests at these conditions"
        assert not n.items                                       # ... the voice waits for the scene to stay
        await asyncio.sleep(0.15)
        i = n.items[-1]
        assert i.kind == "scene_arrival" and i.facts["coverage"] == "Medium" and i.facts["end_with"] == "BRE tested these atmospheres; ask me what it found."
        assert "51 tests in 2 PSIs" in i.facts["scene_speak"]
        await b.handlers[Evt.CONDITIONS_CHANGED]({"scenario": "spacesuit"})
        await asyncio.sleep(0.15)
        j = n.items[-1]
        assert j.facts["coverage"] is None and "coverage" not in j.facts["scene_speak"].lower()
        assert j.facts["end_with"].startswith("The chart shows how far the suit is")
    asyncio.run(go())


def test_clicking_through_scenes_speaks_only_the_one_that_stayed():
    async def go():
        b, st, n = setup(scene=0.1)
        for sid in ("moon_base", "spacesuit", "iss", "moon_base", "spacesuit"):
            await b.handlers[Evt.CONDITIONS_CHANGED]({"scenario": sid})
            await asyncio.sleep(0.02)
        assert len(b.of("answer.show")) == 5                     # every click updated the screen
        assert not n.items
        await asyncio.sleep(0.25)
        assert [i.facts["scenario"] for i in n.items] == ["spacesuit"]
        # a slider move right after a scene tap cancels the scene line
        await b.handlers[Evt.CONDITIONS_CHANGED]({"scenario": "iss"})
        await b.handlers[Evt.CONDITIONS_CHANGED]({"inputs": {"oxygen_pct": 33}})
        await asyncio.sleep(0.25)
        assert [i.facts["scenario"] for i in n.items if i.speak and i.kind == "scene_arrival"] == ["spacesuit"]
    asyncio.run(go())


def test_scene_arrival_while_a_view_is_open_refreshes_the_view_too():
    b, st, n = setup()
    fire(b, Evt.VIEW_SELECTED, {"pillar": "suppression", "view": "suppression", "scenario": "iss"})
    fire(b, Evt.CONDITIONS_CHANGED, {"scenario": "spacesuit"})
    assert b.of("view.open")[-1]["scenario"] == "spacesuit" and b.of("view.open")[-1]["coverage"] == "None"
    assert b.of("view.open")[-1]["coverage_note"]["level"] == "Medium"


def test_chip_tap_is_delivered_as_a_normal_question():
    b, st, n = setup()
    fire(b, Evt.QUESTION_ASKED, {"text": "What is BRE?"})
    assert n.asked == ["What is BRE?"] and st.last_transcript == "What is BRE?" and not n.items
    fire(b, Evt.QUESTION_ASKED, {"text": "   "})
    assert n.asked == ["What is BRE?"]


def test_a_slider_move_never_reaches_the_model_and_the_conditions_stay(tmp_path, monkeypatch):
    """Round 12 item 6: no notification at all (no model turn, no free Gemini sentence), the values are kept, the scenario goes custom, the move is logged as source screen."""
    import json
    from src import qlog
    monkeypatch.setattr(qlog, "PATH", tmp_path / "q.jsonl")

    async def go():
        b, st, n = setup(settle=0.05)
        for v in (22, 25, 28, 56.5):
            await b.handlers[Evt.CONDITIONS_CHANGED]({"inputs": {"oxygen_pct": v}})
            await asyncio.sleep(0.02)
        await asyncio.sleep(0.2)
        assert n.items == []
        assert st.inputs["oxygen_pct"] == 56.5 and st.scenario is None
    asyncio.run(go())
    lines = [json.loads(x) for x in (tmp_path / "q.jsonl").read_text().splitlines()]
    assert len(lines) == 4 and all(x["source"] == "screen" and x["tool"] == "conditions_changed" for x in lines)


def test_a_screen_event_is_not_the_astronauts_words():
    from src import conditions, turns
    from src.state import DashboardState
    st = DashboardState()
    assert turns.typed_text(st, "[screen] conditions_changed: oxygen_pct 56.5 | {'say': 'These are custom conditions. Data is rated only for the ISS'}") is False
    assert st.last_source == "screen" and st.last_transcript == ""
    assert turns.typed_text(st, "what about the ISS?") is True and st.last_source == "typed"
    assert "scenario" in conditions.parse("the ISS cabin oxygen?")


def test_custom_conditions_open_view_shows_all_tests():
    b, st, n = setup()
    fire(b, Evt.VIEW_SELECTED, {"pillar": "flammability", "view": "flame_spread", "scenario": "iss"})
    fire(b, Evt.CONDITIONS_CHANGED, {"inputs": {"oxygen_pct": 33}})
    vo = b.of("view.open")[-1]
    assert vo["scenario"] is None and vo["coverage"] is None and vo["headline"].startswith("All PSI tests (not filtered to your conditions)")
    assert vo["dashboard"]["gaps"][-1] == "Coverage is rated only for the ISS, Moon base and spacesuit atmospheres."


def test_state_sync_marks_the_session_synced():
    b, st, n = setup()
    fire(b, Evt.STATE_SYNC, {"scenario": "moon_base", "inputs": {"oxygen_pct": 30}})
    assert st.synced and st.scenario == "moon_base" and st.synced_event.is_set()


# ── silence nudge ────────────────────────────────────────────────────────────
def nudge_setup(delay=0.05):
    st, n = DashboardState(), Notifier()
    ng = Nudger(n, st, delay=delay)
    n.nudger = ng
    return st, n, ng


def test_nudge_fires_once_per_category_after_the_agent_finished_speaking():
    async def go():
        st, n, ng = nudge_setup()
        ng.arm("detection", "Which experiments matter most for detection?")
        ng.on_agent_state("listening")                       # not yet: the entry turn was never spoken
        await asyncio.sleep(0.1)
        assert not n.items
        ng.on_agent_state("speaking"); ng.on_agent_state("listening")
        await asyncio.sleep(0.12)
        assert len(n.items) == 1 and n.items[0].kind == "silence_nudge" and "Which experiments matter most for detection?" in n.items[0].facts["say"]
        ng.arm("detection", "x"); ng.on_agent_state("speaking"); ng.on_agent_state("listening")
        await asyncio.sleep(0.12)
        assert len(n.items) == 1                             # once per category
    asyncio.run(go())


def test_speech_or_a_tap_cancels_the_nudge():
    async def go():
        st, n, ng = nudge_setup()
        ng.arm("flammability", "chip"); ng.on_agent_state("speaking"); ng.on_agent_state("listening")
        ng.cancel()
        await asyncio.sleep(0.12)
        assert not n.items
        ng.arm("suppression", "chip"); ng.on_agent_state("speaking"); ng.on_agent_state("listening")
        ng.arm("prevention", "chip2")                        # a newer entry replaces the pending one
        await asyncio.sleep(0.12)
        assert not n.items
    asyncio.run(go())


# ── question log: the transcript of the turn ─────────────────────────────────
def test_fragments_of_one_turn_are_joined_and_a_new_turn_starts_after_the_answer():
    st = DashboardState()
    st.heard("Yeah, what", False)
    assert st.last_transcript == "Yeah, what"
    st.heard("Yeah, what is", True)
    st.heard("BRE?", True)
    assert st.last_transcript == "Yeah, what is BRE?"
    st.close_turn()                                          # the agent started to speak
    st.heard("And the Moon?", True)
    assert st.last_transcript == "And the Moon?"             # never the previous utterance


def test_a_transcript_that_arrives_after_the_tool_call_fills_the_log_line_in(tmp_path, monkeypatch):
    import json
    from src import qlog
    monkeypatch.setattr(qlog, "PATH", tmp_path / "q.jsonl")
    st = DashboardState()
    lid = qlog.log(st.last_transcript, "get_investigation", {"psi": "BRE"}, True)   # nothing heard yet
    st.log_ids.append(lid)
    ids = st.heard("What is BRE?", True)
    qlog.amend(ids, st.last_transcript)
    line = json.loads((tmp_path / "q.jsonl").read_text().splitlines()[0])
    assert line["transcript"] == "What is BRE?" and line["tool"] == "get_investigation"
