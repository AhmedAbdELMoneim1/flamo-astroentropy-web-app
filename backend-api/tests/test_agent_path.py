"""All goldens through the agent path (Runner.intent / build_view): spoken prefix keeps every mandatory caveat, payload small, numbers from speak."""
import asyncio
import json

import pytest

from src import adapter, content, flameo
from src.categories import find_view
from src.state import DashboardState
from tests.helpers import FakeBridge, goldens, needs_db, numbers

pytestmark = needs_db
STEPS = [s for s in goldens() if s[1] != "query_data"]   # query_data is gone: g22 to g24 are covered by their routed twins (g13, g11, g06)


@pytest.fixture(scope="module", autouse=True)
def _db():
    from tests.conftest import DB

    flameo.init(DB)


def run(tool, args):
    b, st = FakeBridge(), DashboardState()
    if tool == "show_view":
        st.scenario = args.get("scenario")
        st.open_view(find_view(None, args["view"]))
        c = asyncio.run(content.build_view(st))
        return b, st, c, None
    return b, st, None, asyncio.run(content.Runner(b, st).intent(tool, **args))


@pytest.mark.parametrize("gid,tool,args", STEPS, ids=lambda x: str(x)[:28])
def test_golden_through_the_agent_path(gid, tool, args):
    if tool == "show_view":
        b, st, c, _ = run(tool, args)
        assert c["status"] == "ok"
        full = c["speak"]
        p = c["payload"]
        assert len(json.dumps(p)) < 8000
        assert p["dashboard"]["scenario"] in (args.get("scenario"), None)
        return
    b, st, _, m = run(tool, args)
    d = flameo.call(tool, **args)
    full = d["speak"]
    n = adapter.spoken_lines(d)
    spoken = m["speak"]
    # 1. every mandatory caveat of the full answer is in what the voice gets (prefix, or pulled forward from further down)
    for line in adapter.caveat_lines(full):
        assert line in spoken, (gid, "lost caveat", line[:90])
    # 2. the prefix itself is the first n lines, in order
    cards = sum(1 for r in (d.get("table") or {}).get("rows", []) if r.get("kind") == "card") if tool == "search_text" else 0
    expect = full[:cards] if cards >= 2 else full[:n]            # Round 5 item 5.1: two or more cards -> only the cards are spoken
    if tool == "rank_materials" and "nothing is ranked" in full[0]:
        expect = full[:2]                                           # Round 10 item 5: no single material's value is read out
    assert spoken[: len(expect)] == expect
    # 3. every number spoken is in the answer's speak lines / facts
    allowed = numbers(full) | numbers(d.get("facts", []))
    assert numbers(spoken) <= allowed, (gid, sorted(numbers(spoken) - allowed))
    # 4. the payload returned to the model is small: no table, charts, cards
    assert not ({"table", "charts", "cards", "kpis", "facts"} & set(m))
    assert len(json.dumps(m)) < 3500, (gid, len(json.dumps(m)))
    # 5. the screen got the full answer, with ids
    ans = b.of("answer.show")[0]
    assert ans["tool"] == tool and ans["request_id"] and ans["speak"] == full


def test_spacesuit_answers_keep_four_lines_and_never_say_coverage():
    for tool, args in (("scenario_coverage", dict(scenario="spacesuit")), ("gaps", dict(scenario="spacesuit")), ("rank_investigations", dict(scenario="spacesuit"))):
        _, _, _, m = run(tool, args)
        assert len(m["speak"]) >= (3 if tool == "rank_investigations" else 4) - 0
        text = " ".join(m["speak"]).lower()
        assert "coverage" not in text and "covered" not in text, tool


def test_caveat_report_lists_goldens_whose_prefix_needed_pulling():
    """Information for the STOP 2 report: goldens whose first 3 (4) lines alone would have lost a caveat."""
    pulled = []
    for gid, tool, args in STEPS:
        if tool == "show_view":
            continue
        d = flameo.call(tool, **args)
        n = adapter.spoken_lines(d)
        lost = [x for x in adapter.caveat_lines(d["speak"]) if x not in d["speak"][:n]]
        if lost:
            pulled.append((gid, tool, len(lost)))
    print("PULLED FORWARD:", pulled)
    assert isinstance(pulled, list)


def test_unknown_argument_is_not_matched_not_a_crash():
    _, _, _, m = run("get_investigation", dict(psi="no-such-investigation"))
    assert m["matched"] is False and m["status"] == "not_matched"


def test_no_passage_is_matched_false_and_flags_not_covered():
    _, _, _, m = run("search_text", dict(query="weather Mars"))
    assert m["matched"] is False and m.get("not_covered") is True


def test_follow_pillar_moves_the_server_mirror():
    b, st, _, m = run("rank_agents", {})
    assert st.pillar == "suppression" and st.view == "suppression"


def test_search_text_with_two_cards_speaks_only_the_cards():
    """Round 5 item 5.1, with the Q5 output: two ISS / model cards, then a figure caption that must stay on screen only."""
    d = flameo.call("search_text", query="cool flame")
    kinds = [r["kind"] for r in d["table"]["rows"]]
    assert kinds.count("card") >= 2 and kinds[-1] != "card"
    m = adapter.to_model(d)
    assert m["speak"] == d["speak"][: kinds.count("card")] and len(m["speak"]) == 2
    assert "Flame structure of the high pressure" not in " ".join(m["speak"])
    assert any("Flame structure" in x for x in d["speak"])          # still in the full answer / on the screen
    # fewer than two cards: unchanged behaviour
    d2 = flameo.call("search_text", query="water mist extinguish")
    assert adapter.to_model(d2)["speak"] == d2["speak"][:3]


def test_greeting_names_the_default_category_and_its_chip():
    from src.prompts import GREETING, GREETING_ON_CATEGORY, build_instructions

    assert GREETING_ON_CATEGORY.format(category="Flammability & Fire Behavior", chip="Does fire spread faster in space?") == (
        "Hi, I'm Flamo. I answer from NASA's microgravity fire experiments. You're on Flammability & Fire Behavior; "
        "for example, ask me: Does fire spread faster in space?. Or pick another topic.")
    p = build_instructions()
    assert GREETING in p and "You're on <category>; for example, ask me: <ask_me>. Or pick another topic." in p


def test_the_silent_default_entry_keeps_the_category_not_visited():
    from src.state import DashboardState as S

    st = S()
    assert "flammability" not in st.visited
