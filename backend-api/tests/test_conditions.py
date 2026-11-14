"""Round 11 §11.1 / §11.6: the sliders follow the words; pressure in psi, kPa, atm or bar all end up in psi; the voice is told once."""
import asyncio

import pytest

from src import conditions
from src.bridge import Cmd
from src.state import DashboardState


class Bridge:
    def __init__(self):
        self.sent = []

    async def send(self, t, p, dest_identity=None):
        self.sent.append((t, p))


@pytest.mark.parametrize("text,want", [
    ("Is 34 percent oxygen dangerous?", {"oxygen_pct": 34}),
    ("What about 10 psi?", {"pressure_psi": 10}),
    ("What happens at 70 kPa and 30 percent oxygen?", {"oxygen_pct": 30, "pressure_psi": 10.2}),
    ("and at 0.7 atm?", {"pressure_psi": 10.3}),
    ("34 % oxygen at 8.2 psi", {"oxygen_pct": 34, "pressure_psi": 8.2}),
    ("Is 34 percent oxygen dangerous on the Moon base?", {"oxygen_pct": 34, "scenario": "moon_base"}),
    ("What is the oxygen level in the suit?", {"scenario": "spacesuit"}),
    ("Why are flames round in space?", {}),
    ("How were smoke points measured aboard the space station?", {}),
])
def test_parse(text, want):
    assert conditions.parse(text) == want


def run(text, state=None):
    b, st = Bridge(), state or DashboardState()
    return b, st, asyncio.run(conditions.apply_from_text(b, st, text))


def test_34_percent_oxygen_sets_the_slider_and_says_where_it_came_from():
    b, st, up = run("Is 34 percent oxygen dangerous?")
    assert up == {"oxygen_pct": 34.0} and st.inputs["oxygen_pct"] == 34.0 and st.scenario is None
    (t, p), = b.sent
    assert t == Cmd.CONDITIONS_SET and p["inputs"] == {"oxygen_pct": 34.0} and p["source"] == "From your question: 34 % O₂"
    assert st.conditions_note == "I set the oxygen to 34 percent; the panel shows the nearest tests."


def test_oxygen_on_the_moon_base_takes_the_rest_from_the_scenario():
    b, st, up = run("Is 34 percent oxygen dangerous on the Moon base?")
    assert up == {"oxygen_pct": 34.0, "pressure_psi": 10.2} and st.scenario is None            # not the Moon base preset any more: 34 % is the user's number
    assert "rest from Moon Base" in b.sent[0][1]["source"] and "scenario definition" in b.sent[0][1]["source"]


def test_a_scenario_word_alone_selects_the_scenario_and_repeating_it_changes_nothing():
    b, st, up = run("What is the oxygen level in the suit?")
    assert st.scenario == "spacesuit" and st.inputs["oxygen_pct"] == 100 and st.inputs["pressure_psi"] == 4.3
    b2, _, up2 = run("What is the oxygen level in the suit?", st)
    assert up2 is None and b2.sent == []


def test_nothing_named_nothing_set():
    b, st, up = run("Why are flames round in space?")
    assert up is None and b.sent == [] and st.conditions_note == ""


# ---- Round 13 §13.6: conditions are set only when the astronaut states them; a question about the data sets nothing (5 must set, 5 must not)
@pytest.mark.parametrize("text", ["What does the data say at 34 percent oxygen?", "what if the cabin had 30 percent oxygen", "Is 34 percent oxygen dangerous on the Moon base?",
                                  "set the oxygen to 40 percent", "what happens at 8 psi and 30 % oxygen"])
def test_states_conditions_sets_them(text):
    p = conditions.parse(text)
    assert "oxygen_pct" in p or "pressure_psi" in p, text


@pytest.mark.parametrize("text", ["I see the O2 covered in 22% ?", "ok this mean no test cover o2 > 25% ?", "what's the maximum o2 the data covers", "is there any test above 25 percent oxygen?",
                                  "ok yes i mean here i see max o2 covered is near to 22% right ?"])
def test_a_question_about_the_data_sets_nothing(text):
    p = conditions.parse(text)
    assert "oxygen_pct" not in p and "pressure_psi" not in p, (text, p)
