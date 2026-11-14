"""Round 16: the Saffire answer layer through the router (real flameo tools on serving.db, no network): outcome questions, "What is Saffire?", a Saffire test, "fire safety" umbrella,
and a regression: the material family ("fabrics") must not be read as the Saffire family."""
import asyncio
import os

import pytest

if not os.getenv("FLAMEO_DB"):
    pytest.skip("FLAMEO_DB not set", allow_module_level=True)

from src import flameo, qlog, rag  # noqa: E402
from src.categories import load_coverage  # noqa: E402
from src.router.answer import Router  # noqa: E402
from src.state import DashboardState  # noqa: E402


class Bridge:
    async def send(self, t, p, dest_identity=None):
        pass


@pytest.fixture(autouse=True)
def setup(monkeypatch, tmp_path):
    flameo.init()
    load_coverage(flameo.call)
    monkeypatch.setattr(rag, "available", lambda: False)
    monkeypatch.setattr(qlog, "PATH", tmp_path / "q.jsonl")


def ask(q):
    async def go():
        st = DashboardState()
        return await Router(Bridge(), st).answer(q)
    return asyncio.run(go())


def test_saffire_ii_outcome_question_speaks_the_counted_materials_and_the_source():
    m = ask("Which Saffire-II materials did not burn in space?")
    t = " ".join(m["speak"])
    assert m["answered_by"] == "tool" and "4 Silicone samples did not spread in microgravity" in t and "Nomex part of 1 sample did not ignite" in t
    assert any(s["label"] == "Experiment table" for s in m["sources"]) and not m.get("not_covered")


def test_what_is_saffire_is_one_short_answer_for_the_three_flights_with_the_objective_first():
    m = ask("What is Saffire?")
    t = m["speak"]
    assert t[0].startswith("The objectives of the Saffire experiments were to") and len(t) <= 3
    assert any("Saffire-I (PSI-98)" in x for x in flameo.call("get_investigation", psi="saffire")["speak"])


def test_a_saffire_test_goes_to_get_test_and_speaks_thickness_and_the_sensor_values():
    m = ask("Tell me about sample 5 of Saffire-II")
    t = " ".join(m["speak"])
    assert "sample thickness of 0.33 millimeters" in t and "the normal-gravity test: Complete" in t        # the voice speaks 3 lines; the sensor line is the tool's 4th line and a table row on the screen
    d = flameo.call("get_test", test_id="2-5", psi="PSI-99")
    assert any("The flight sensors measured 21.8 percent oxygen" in x for x in d["speak"])
    assert any(r["field"].startswith("Pressure measured by the sensor") and r["value"] == "102.6 kPa" for r in d["table"]["rows"])
    assert any(s["label"] == "Sensor data" for s in m["sources"])


def test_fire_safety_is_an_umbrella_not_a_danger_question():
    t = " ".join(ask("Which experiments matter most for fire safety?")["speak"])
    assert "most relevant investigations" in t and "safest" not in t.lower()


def test_the_material_family_fabrics_is_not_the_saffire_family():
    m = ask("mmm.. want to ask about fabrics")
    assert m["answered_by"] in ("clarify", "tool", "both") and "objectives of the Saffire" not in " ".join(m["speak"])
