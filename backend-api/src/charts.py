"""Static charts built once from flameo_tools (no LiveKit / FastAPI import)."""

from __future__ import annotations


def build_o2_vs_pressure(call) -> dict:
    """flameo's own spacesuit chart, unchanged: every tested ambient point by investigation, the burner-stream points
    (hollow markers) and the scenario points. `call` = flameo.call."""
    ans = call("scenario_coverage", scenario="spacesuit")
    chart = next((c for c in ans.get("charts", []) if c.get("id") == "o2_vs_pressure"), None)
    if chart is None:
        raise RuntimeError("flameo returned no o2_vs_pressure chart")
    return chart


# scenario id -> a word in the label of its cross point on the chart (flameo's labels: "ISS cabin", "Moon base habitat ...", "the spacesuit atmosphere", "Exploration 10.2 psia", "Exploration 8.2 psia")
_SCENARIO_WORD = {"iss": "iss", "moon_base": "moon base", "spacesuit": "spacesuit", "exploration_10_2": "10.2", "exploration_8_2": "8.2"}


def investigation_matches(name: str | None, wanted: str | None) -> bool:
    """True when `wanted` (a PSI code such as "PSI-20", or part of the investigation's name) is in `name`. No filter = everything matches."""
    if not wanted:
        return True
    return wanted.strip().lower() in (name or "").lower()


def series_matches(series: dict, wanted: str | None) -> bool:
    """One chart series against a filter word: a PSI code or name part, or the two groups that are not one investigation:
    `other` (the "other PSIs" series) and `burner` (the burner-stream series, hollow markers)."""
    if not wanted:
        return True
    w = wanted.strip().lower()
    if w == "burner":
        return series.get("marker") == "hollow"
    if w == "other":
        return series["name"].lower().startswith("other psis")
    return series.get("marker") != "hollow" and w in series["name"].lower()


def filter_o2_vs_pressure(chart: dict, investigation: str | None = None, scenario: str | None = None) -> dict:
    """The same chart, narrowed. `investigation` keeps only that investigation's ambient series (`other` = the other PSIs, `burner` = the burner-stream
    series; the scenario crosses always stay). `scenario` keeps every point and flags the matching cross
    `selected` so the screen can highlight it. Without both arguments the chart is returned unchanged (same object)."""
    if not investigation and not scenario:
        return chart
    word = _SCENARIO_WORD.get((scenario or "").lower(), (scenario or "").lower())
    series = []
    for s in chart["series"]:
        if investigation and s.get("marker") != "cross" and not series_matches(s, investigation):
            continue
        if s.get("marker") == "cross" and word:
            s = {**s, "points": [{**p, "selected": word in (p.get("label") or "").lower()} for p in s["points"]]}
        series.append(s)
    return {**chart, "series": series, "filter": {"investigation": investigation or None, "scenario": scenario or None}}
