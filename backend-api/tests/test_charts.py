"""The O2-vs-pressure scatter served at /api/charts/o2_vs_pressure: flameo's own chart, unchanged, all points."""
import pytest

from src import flameo
from src.charts import build_o2_vs_pressure
from tests.helpers import needs_db

pytestmark = needs_db


def test_o2_vs_pressure_is_flameos_full_chart():
    from tests.conftest import DB

    flameo.init(DB)
    c = build_o2_vs_pressure(flameo.call)
    ref = flameo.call("scenario_coverage", scenario="spacesuit")["charts"][0]
    assert c == ref and c["id"] == "o2_vs_pressure" and len(c["series"]) >= 8
    assert sum(len(s["points"]) for s in c["series"]) > 600                      # nothing cut: the adapter only cuts what travels in packets
    assert any(s.get("marker") == "hollow" for s in c["series"]) and any(s.get("marker") == "cross" for s in c["series"])


def test_api_route_exists():
    from tests.conftest import DB

    from src import api

    assert any(r.path == "/api/charts/o2_vs_pressure" for r in api.app.routes)
    c = next(r for r in api.app.routes if r.path == "/api/charts/o2_vs_pressure").endpoint()
    assert c["id"] == "o2_vs_pressure" and len(c["series"]) >= 8


def test_filter_by_investigation_and_scenario():
    from src.charts import filter_o2_vs_pressure

    chart = {"id": "o2_vs_pressure", "series": [
        {"name": "ACME BRE (PSI-20) ambient tests", "points": [{"x": 8, "y": 30}]},
        {"name": "FLEX (PSI-69) ambient tests", "points": [{"x": 10, "y": 18}]},
        {"name": "burner stream", "marker": "hollow", "points": [{"x": 6, "y": 85}]},
        {"name": "scenario points", "marker": "cross", "points": [{"x": 14.7, "y": 21, "label": "ISS cabin"}, {"x": 4.3, "y": 100, "label": "the spacesuit atmosphere"}]}]}
    assert filter_o2_vs_pressure(chart) is chart
    f = filter_o2_vs_pressure(chart, investigation="psi-20", scenario="iss")
    assert [s["name"] for s in f["series"]] == ["ACME BRE (PSI-20) ambient tests", "scenario points"]
    assert [p["selected"] for p in f["series"][1]["points"]] == [True, False]
    assert len(chart["series"]) == 4                     # the cached chart is never mutated


def test_filter_groups_other_and_burner():
    from src.charts import filter_o2_vs_pressure

    chart = {"id": "o2_vs_pressure", "series": [
        {"name": "ACME BRE (PSI-20) ambient tests", "points": [{"x": 8, "y": 30}]},
        {"name": "other PSIs, ambient tests", "points": [{"x": 7, "y": 21}]},
        {"name": "burner stream (inverse flames), not the atmosphere", "marker": "hollow", "points": [{"x": 6, "y": 85}]},
        {"name": "scenario points", "marker": "cross", "points": [{"x": 14.7, "y": 21, "label": "ISS cabin"}]}]}
    assert [s["name"] for s in filter_o2_vs_pressure(chart, investigation="other")["series"]] == ["other PSIs, ambient tests", "scenario points"]
    assert [s["name"] for s in filter_o2_vs_pressure(chart, investigation="burner")["series"]][0].startswith("burner stream")
    assert len(filter_o2_vs_pressure(chart, investigation="PSI-20")["series"]) == 2           # a PSI code never matches the burner series
