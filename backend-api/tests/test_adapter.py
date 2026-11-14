"""Adapter unit tests: every limit, no new numbers, request_id / pillar, < 8000 bytes for everything in review_prints."""
import json
import re

import pytest

from src import adapter, flameo
from tests.helpers import needs_db, numbers

pytestmark = needs_db

VIEWS = ["ignition", "materials", "flame_spread", "smoke", "suppression", "gaps"]
SCEN = [None, "iss", "moon_base", "spacesuit", "exploration_10_2", "exploration_8_2", "high_o2"]


@pytest.fixture(scope="module", autouse=True)
def _db():
    from tests.conftest import DB

    flameo.init(DB)


def size(x):
    return len(json.dumps(x, ensure_ascii=False).encode("utf-8"))


def all_dashboards():
    L = flameo.labels()
    for v in VIEWS:
        for sc in SCEN:
            d = flameo.call("show_view", view=v, scenario=sc)
            yield v, sc, d, adapter.to_dashboard(d, custom=sc is None, labels=L)


def test_every_dashboard_obeys_every_limit():
    lim = adapter.LIMITS
    for v, sc, d, out in all_dashboards():
        assert size(out) < lim["bytes"], (v, sc, size(out))
        assert len(out["kpis"]) <= lim["kpis"]
        assert len(out["charts"]) <= lim["charts"]
        assert len(out["gaps"]) <= lim["gaps"]
        assert len(out["cards"]) <= lim["cards"]
        for c in out["charts"]:
            assert len(c.get("series", [])) <= lim["series"]
            assert all(len(s["points"]) <= lim["points"] for s in c.get("series", []) if c.get("type") != "scatter")      # scatter charts show every point
        t = out["table"]
        if t:
            assert len(t["columns"]) <= lim["cols"] and len(t["rows"]) <= lim["rows"]
            assert all(len(str(x)) <= lim["cell"] for r in t["rows"] for x in r.values() if isinstance(x, str))
            if len(d["table"]["rows"]) > lim["rows"]:
                assert t["footer"] == f"{lim['rows']} of {len(d['table']['rows'])} rows"
            if d.get("table_key") and d["table"]["rows"]:
                assert d["table_key"] in [c["key"] for c in t["columns"]], (v, sc, "the key column was dropped")


def test_gaps_are_deduplicated_and_free_of_internal_messages():
    for v, sc, d, out in all_dashboards():
        assert len(out["gaps"]) == len(set(out["gaps"]))
        assert not any("chart '" in g or "test rows" in g for g in out["gaps"])


def test_spacesuit_chart_is_a_ref_not_points():
    for v, sc, d, out in all_dashboards():
        if sc == "spacesuit":
            ch = out["charts"][0]
            assert ch["ref"] == "/api/charts/o2_vs_pressure" and "series" not in ch
            assert out["coverage"] == "None" and out["coverage_note"]["level"] in ("Medium", "High", "Low")


def test_custom_conditions_headline_gap_and_null_coverage():
    d = flameo.call("show_view", view="flame_spread")
    out = adapter.to_dashboard(d, custom=True)
    assert out["headline"].startswith("All PSI tests (not filtered to your conditions)")
    assert out["coverage"] is None and out["scenario"] is None
    assert out["gaps"][-1] == adapter.CUSTOM_GAP


def test_no_new_numbers_in_dashboards():
    for v, sc, d, out in all_dashboards():
        src = numbers(d) | numbers(d.get("facts", []))
        body = {k: x for k, x in out.items() if k != "source"}
        body["table"] = {k: x for k, x in (out["table"] or {}).items() if k != "footer"} if out["table"] else None   # "12 of N rows" is selection
        body["charts"] = [{k: x for k, x in c.items() if k != "shown"} for c in out["charts"]]
        new = {n for n in numbers(body) if n not in src and not n.endswith(".0")}
        assert not new, (v, sc, sorted(new)[:5])


ANSWERS = [
    ("get_investigation", dict(psi="BRE")), ("get_investigation", dict(psi="SAME")), ("compare", dict(psi_a="BASS", psi_b="BASS-II")),
    ("rank_materials", dict(metric="spread rate")), ("rank_materials", dict(metric="spread rate", scenario="moon_base")),
    ("scenario_coverage", dict(scenario="iss")), ("scenario_coverage", dict(scenario="moon_base")), ("scenario_coverage", dict(scenario="spacesuit")),
    ("scenario_coverage", dict(scenario="high_o2")), ("get_findings", dict(x="oxygen", y="spread rate")), ("get_findings", dict(x="oxygen", y="particle size")),
    ("rank_agents", {}), ("rank_agents", dict(fuel_class="liquid")), ("gaps", {}), ("gaps", dict(scenario="Mars")), ("gaps", dict(scenario="spacesuit")),
    ("search_text", dict(query="cool flame")), ("search_text", dict(query="water mist extinguish")), ("search_text", dict(query="weather Mars")),
    ("rank_investigations", {}), ("rank_investigations", dict(scenario="iss")), ("rank_investigations", dict(scenario="spacesuit")),
    ("rank_investigations", dict(pillar="suppression", scenario="iss")),
]


@pytest.mark.parametrize("tool,args", ANSWERS, ids=lambda x: str(x)[:30])
def test_answer_limits_numbers_and_ids(tool, args):
    d = flameo.call(tool, **args)
    a = adapter.to_answer(d)
    assert size(a) < adapter.LIMITS["bytes"]
    assert re.fullmatch(r"[0-9a-f]{8}", a["request_id"]) and a["metric"] == tool and a["tool"] == tool
    assert "facts" not in a and a["source"]["mock"] is False
    assert len(a["gaps"]) <= 3 and len(a["cards"]) <= 3
    if a["table"]:
        assert len(a["table"]["columns"]) <= 6 and len(a["table"]["rows"]) <= 12
    src = numbers(d) | numbers(d.get("facts", []))
    body = {k: x for k, x in a.items() if k not in ("request_id", "source")}
    body["table"] = {k: x for k, x in (a["table"] or {}).items() if k != "footer"} if a["table"] else None
    body["charts"] = [{k: x for k, x in c.items() if k != "shown"} for c in a["charts"]]
    if a.get("ranking"):
        body["ranking"] = {k: x for k, x in a["ranking"].items() if k != "footer"}
    new = {n for n in numbers(body) if n not in src and not n.endswith(".0")}
    assert not new, sorted(new)[:5]


def test_two_ids_differ_and_pillar_map():
    a, b = adapter.to_answer(flameo.call("rank_agents")), adapter.to_answer(flameo.call("rank_agents"))
    assert a["request_id"] != b["request_id"]
    pillar = lambda t, **k: adapter.to_answer(flameo.call(t, **k))["pillar"]
    assert pillar("rank_agents") == "suppression" and pillar("rank_materials", metric="spread rate") == "prevention"
    assert pillar("get_findings", x="oxygen", y="spread rate") == "flammability"
    assert pillar("get_findings", x="oxygen", y="particle size") == "detection"
    assert pillar("rank_investigations", pillar="detection") == "detection"
    assert pillar("scenario_coverage", scenario="iss") is None and pillar("search_text", query="cool flame") is None
    assert pillar("compare", psi_a="BASS", psi_b="BASS-II") is None and pillar("gaps") is None
    assert adapter.pillar_for(flameo.call("show_view", view="smoke")) == "detection"


def test_ranking_panel_rules():
    d = flameo.call("rank_investigations", scenario="iss")
    a = adapter.to_answer(d)
    assert a["table"] is None                                    # the table duplicates ranking
    rk = a["ranking"]
    assert len(rk["rows"]) == 8 and rk["footer"] == f"8 of {len(d['ranking'])} investigations"
    assert all(r["rank"] for r in rk["rows"][:8]) or rk["divider"]
    m = adapter.to_answer(flameo.call("rank_investigations", scenario="moon_base"))["ranking"]
    assert m["divider"] == "No tests at these conditions"
    assert [r["rank"] for r in m["rows"][:2]] == [1, 2] and m["rows"][2]["rank"] is None
    p = adapter.to_answer(flameo.call("rank_investigations", pillar="suppression", scenario="iss"))["ranking"]
    assert p["divider"] is None and "footer" not in p


def test_zero_kpis_hidden_when_the_absence_is_stated():
    d = flameo.call("show_view", view="flame_spread", scenario="moon_base")
    assert any(k["value"] == 0 for k in d["kpis"])
    out = adapter.to_dashboard(d)
    assert not any(k["value"] in (0, "none") for k in out["kpis"])


def test_spacesuit_kpi_basis_is_not_cut():
    d = flameo.call("scenario_coverage", scenario="spacesuit")
    out = adapter.to_answer(d)
    full = max(len(k["basis"]) for k in d["kpis"])
    assert max(len(k["basis"]) for k in out["kpis"]) == full and full > 200


def test_model_payload_is_small_and_has_no_table_charts_or_cards():
    for tool, args in ANSWERS:
        m = adapter.to_model(flameo.call(tool, **args))
        assert not ({"table", "charts", "cards", "kpis", "facts"} & set(m))
        assert size(m) < 3500, (tool, args, size(m))


def test_cut_text_is_at_a_word_boundary():
    s = "word " * 40
    c = adapter.cut_text(s)
    assert len(c) <= 80 and c.endswith("…") and " …" not in c
    assert adapter.cut_text("short") == "short"


def test_number_check_catches_an_invented_number():
    d = flameo.call("rank_agents")
    a = adapter.to_answer(d)
    a["kpis"][0]["value"] = 987654                               # a number flameo never produced
    src = numbers(d) | numbers(d.get("facts", []))
    assert "987654" in numbers(a) and "987654" not in src


def test_after_a_nothing_is_ranked_answer_the_voice_reads_no_single_materials_value():
    d = flameo.call("rank_materials", metric="spread rate")
    m = adapter.to_model(d)
    assert "nothing is ranked" in m["speak"][0] and m["speak"][1].startswith("What the experiments did measure") and "millimeters per second" not in " ".join(m["speak"])
    assert len(m["speak"]) <= 3 and all(("No flight finding" in x) for x in m["speak"][2:])          # only the mandatory caveat is pulled forward


def test_not_found_renders_no_passages_and_a_clean_title():
    r = {"request_id": "r1", "question": "Why are flames round in space?", "status": "not_found", "speak": [], "speak_refs": [], "sources": [], "outcome": "not_found"}
    a = adapter.rag_to_answer(r)
    assert a["open_question"] is True and a["speak"] == [] and a["sources"] == [] and a["gaps"] == [adapter.OPEN_QUESTION]
    d = {"tool": "oxygen_effect", "question": "OXYGEN_EFFECT(ISS, NONE)", "speak": ["x"], "kpis": [], "charts": [], "table": None, "gaps": []}
    assert adapter.to_answer(d)["question"] == "Oxygen and fire: what the tests show"
    assert adapter.to_answer(d, title="Is more oxygen worse?")["question"] == "Is more oxygen worse?"


def test_sources_are_numbered_in_display_order_and_the_spoken_refs_follow():
    src = [{"n": 1, "label": "Paper", "title": "A"}, {"n": 2, "label": "NASA document", "title": "B"}, {"n": 3, "label": "Paper", "title": "C"}]
    out, refs = adapter.order_sources(src, [[1], [2], [3, 1]])
    assert [x["title"] for x in out] == ["A", "C", "B"] and [x["n"] for x in out] == [1, 2, 3]
    assert refs == [[1], [3], [1, 2]]
