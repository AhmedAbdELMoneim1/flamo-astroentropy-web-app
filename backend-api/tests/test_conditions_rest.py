"""Round 11: slider -> REST -> panel. GET /api/nearest answers from flameo's nearest_tests (one SQL pass, no model call), psi first, no rating."""
import json

from fastapi.testclient import TestClient


def client():
    from src.api import app
    return TestClient(app)


def test_the_route_returns_counts_psi_and_the_formula_from_flameo():
    r = client().get("/api/nearest", params={"o2": 34, "p": 8.2, "source": "From your question: 34 % O₂"})
    assert r.status_code == 200
    d = r.json()
    assert d["conditions"] == {"o2_pct": 34.0, "pressure_psi": 8.2, "pressure_kpa": 56.5, "material": None}
    assert d["n_near"] > 0 and d["n_psis"] >= 1 and d["po2"]["value_psi"] == 2.8 and d["po2"]["formula"] == "computed: 34 % × 8.2 psi"
    assert d["ranges"]["spread_o2_min"] == 17.9 and any("No spread-rate tests at 34 % oxygen" in g for g in d["gaps"])
    assert [s["id"] for s in d["scenarios"]][:2] == ["exploration_10_2", "exploration_8_2"] or {s["id"] for s in d["scenarios"]} >= {"iss", "moon_base", "spacesuit"}
    assert {m["o2_pct"] for m in d["markers"]} == {17, 26, 40}
    assert all(r_["p_psi"] is not None and r_["p_kpa"] is not None for r_ in d["rows"])          # psi first, the source kPa beside it
    assert "kilopascals" not in json.dumps(d) and not any(w in json.dumps(d).lower() for w in ("dangerous above", "safe below"))


def test_the_suit_has_no_nearby_test_and_the_nearest_points_are_listed():
    d = client().get("/api/nearest", params={"o2": 100, "p": 4.3}).json()
    assert d["n_near"] == 0 and d["nearest_points"] and d["rows"] and any("No PSI test at these conditions" in g for g in d["gaps"])
    assert d["po2"]["value_psi"] == 4.3


def test_each_scenario_psi_is_the_challenge_number():
    d = client().get("/api/nearest", params={"o2": 21, "p": 14.7}).json()
    by = {s["id"]: s for s in d["scenarios"]}
    assert (by["iss"]["p_psi"], by["moon_base"]["p_psi"], by["spacesuit"]["p_psi"], by["exploration_8_2"]["p_psi"]) == (14.7, 10.2, 4.3, 8.2)


def test_values_are_clamped_and_a_missing_value_is_rejected():
    c = client()
    assert c.get("/api/nearest", params={"o2": 500, "p": 99}).json()["conditions"]["o2_pct"] == 100.0
    assert c.get("/api/nearest", params={"o2": 21}).status_code == 422


def test_a_material_narrows_the_list():
    d = client().get("/api/nearest", params={"o2": 21, "p": 14.7, "material": "PMMA"}).json()
    full = client().get("/api/nearest", params={"o2": 21, "p": 14.7}).json()
    assert 0 < d["n_near"] < full["n_near"] and all("PMMA" in (r["material"] or "") for r in d["rows"])
