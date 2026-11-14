"""Every number the voice says must appear in what the tool returned (Round 10 §10.7 item 1), with Arabic digits and number words normalised."""
import json

import pytest

from src import qlog, spoken, turns
from src.state import DashboardState

TOOL = ["ISS cabin has 21 percent oxygen at 101.3 kilopascals.", "In microgravity, there is still flame spread at XO2 = 17%."]


def test_the_memory_answer_of_the_live_test_is_caught():
    # "about 21 percent at a pressure of about 14.7 psi": 14.7 is in no tool line (the tool says 101.3 kilopascals)
    assert spoken.unsupported("It is about 21 percent oxygen at a pressure of about 14.7 psi.", TOOL) == {"14.7"}
    assert spoken.unsupported("It is 21 percent oxygen at 101.3 kilopascals.", TOOL) == set()


@pytest.mark.parametrize("said,ok", [("اكسجين ٢١ بالمئة", True), ("twenty one percent oxygen", True), ("twenty-one percent", True), ("seventeen percent oxygen", True),
                                     ("thirty percent oxygen", False), ("٣٠ بالمئة", False), ("one moment please", True), ("about 1,200 seconds", False)])
def test_digits_in_arabic_and_number_words_are_normalised(said, ok):
    assert (spoken.unsupported(said, TOOL) == set()) is ok


def test_the_astronauts_own_numbers_and_notification_facts_are_allowed(tmp_path, monkeypatch):
    monkeypatch.setattr(qlog, "PATH", tmp_path / "q.jsonl")
    st = DashboardState()
    st.typed("Is 34 percent oxygen dangerous on the Moon base?")
    st.allow("Near 34 percent oxygen there are 12 tests in 3 investigations.")
    assert turns.check_spoken_numbers(st, "At 34 percent oxygen there are 12 tests.") == set()
    assert not (tmp_path / "q.jsonl").exists()
    bad = turns.check_spoken_numbers(st, "That is 14.7 psi, about 40 percent more.")
    assert bad == {"14.7", "40"}
    line = json.loads((tmp_path / "q.jsonl").read_text().splitlines()[0])
    assert line["tool"] == "spoken_number_check" and line["args"]["unsupported"] == ["14.7", "40"] and line["matched"] is False
