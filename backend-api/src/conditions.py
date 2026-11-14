"""Conditions follow the conversation (Round 11 §11.1): "34 percent oxygen", "at 10.2 psi", "on the Moon base" set the sliders from the SERVER,
deterministically, so it does not depend on Gemini remembering to call set_conditions. Pressure is read in psi / kPa / atm / bar and stored in psi
(flameo's own converter); the panel shows where the values came from. Pure parsing first, then one small apply().
"""
from __future__ import annotations

import re

from src import flameo as _flameo  # noqa: F401  (puts vendor/ on sys.path)
from src import qlog
from src.bridge import Cmd
from src.categories import SCENARIOS, normalize_conditions
from src.paper_rag.extract import Extractor
from flameo_tools import units as U

_P = re.compile(r"(\d+(?:\.\d+)?)\s*(psia|psi|kpa|kilopascals?|atm|bar)\b", re.I)


def pressure_psi(text: str) -> float | None:
    m = _P.search(text or "")
    if not m:
        return None
    v, u = float(m.group(1)), m.group(2).lower()
    if u in ("psi", "psia"):
        return round(v, 1)
    if u in ("kpa", "kilopascal", "kilopascals"):
        return U.to_psi(v)
    if u == "atm":
        return U.atm_to_psi(v)
    return U.to_psi(v * 100)          # bar


# Round 13 §13.6: conditions are set only when the astronaut states them for a place or a situation. A question ABOUT the data is not a statement of conditions.
DATA_QUESTION = re.compile(r"\b(?:cover(?:ed|s|age)?|maximum|minimum|max|min|highest|lowest|above|below|range|ranges|chart|graph|plot|any tests?|do you have|is there any|are there any|how many)\b|[<>]\s*\d", re.I)
STATES_CONDITIONS = re.compile(r"\b(?:at|with|if|when|in|under)\b[^.?]*\b(?:\d+(?:\.\d+)?\s*(?:%|percent|psi|kpa|atm)|moon base|iss|spacesuit)\b|\bset (?:the )?(?:oxygen|pressure)\b|\bwhat if\b", re.I)


def is_data_question(text: str | None) -> bool:
    t = text or ""
    return bool(DATA_QUESTION.search(t)) and not re.search(r"\bset (?:the )?(?:oxygen|pressure)\b|\bwhat if\b|\bif (?:the )?(?:cabin|base|suit)\b", t, re.I)


def parse(text: str | None) -> dict:
    """{oxygen_pct?, pressure_psi?, scenario?}: only what the text says. A scene word counts only in a question about the atmosphere."""
    t = text or ""
    out: dict = {}
    if is_data_question(t):
        return {k: v for k, v in {"scenario": Extractor.scenario(t) if Extractor.scenario(t) in SCENARIOS else None}.items() if v}
    o2 = Extractor.o2(t)
    if o2 is not None and 0 <= o2 <= 100:
        out["oxygen_pct"] = o2
    p = pressure_psi(t)
    if p is not None and 0 < p <= 40:
        out["pressure_psi"] = p
    sc = Extractor.scenario(t)
    if sc in SCENARIOS:
        out["scenario"] = sc
    return out


def label(parsed: dict, applied: dict) -> str:
    """"From your question: 34 % O₂ · Moon base habitat (scenario definition)": where each value came from."""
    bits = []
    if "oxygen_pct" in parsed:
        bits.append(f"{parsed['oxygen_pct']:g} % O₂")
    if "pressure_psi" in parsed:
        bits.append(f"{parsed['pressure_psi']:g} psi")
    sc = parsed.get("scenario")
    if sc:
        bits.append(f"{SCENARIOS[sc].label} (scenario definition)" if not ({"oxygen_pct", "pressure_psi"} & parsed.keys()) else f"rest from {SCENARIOS[sc].label} (scenario definition)")
    return "From your question: " + " · ".join(bits) if bits else ""


def note(parsed: dict) -> str:
    """The one sentence the voice says (once): what was set. Numbers are the astronaut's own."""
    if "oxygen_pct" in parsed and "pressure_psi" in parsed:
        what = f"the oxygen to {parsed['oxygen_pct']:g} percent and the pressure to {parsed['pressure_psi']:g} psi"
    elif "oxygen_pct" in parsed:
        what = f"the oxygen to {parsed['oxygen_pct']:g} percent"
    elif "pressure_psi" in parsed:
        what = f"the pressure to {parsed['pressure_psi']:g} psi"
    else:
        what = f"the conditions to {SCENARIOS[parsed['scenario']].label}"
    return f"I set {what}; the panel shows the nearest tests."


async def apply_from_text(bridge, state, text: str | None) -> dict | None:
    """Set the sliders from a question. Returns what changed, or None (nothing named, or already set). Never speaks: it leaves a note for the next answer."""
    parsed = parse(text)
    if not parsed:
        return None
    sc = parsed.get("scenario")
    explicit = {k: v for k, v in parsed.items() if k in ("oxygen_pct", "pressure_psi")}
    target = {**(SCENARIOS[sc].inputs if sc else {}), **normalize_conditions(explicit)}
    if not target or all(state.inputs.get(k) == v for k, v in target.items()):
        return None
    keep = sc if sc and all(target.get(k) == v for k, v in SCENARIOS[sc].inputs.items()) else None     # the scenario chip stays only while the values are its own
    updates = state.update_conditions(scenario=keep, inputs=target)
    if not updates:
        return None
    src = label(parsed, updates)
    state.conditions_note = note(parsed)
    await bridge.send(Cmd.CONDITIONS_SET, {"scenario": state.scenario, "inputs": updates, "source": src})
    qlog.log(text, "set_conditions", {"extracted": {k: v for k, v in parsed.items()}}, True, source=getattr(state, "last_source", None))
    return updates
