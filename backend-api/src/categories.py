"""
Single source of truth for the flamo taxonomy, scenarios and input conditions.

Structure:  pillar -> view  (what the astronaut asks about)
            scenario        (which atmosphere we are talking about)
            conditions      (the dashboard inputs: oxygen and pressure only)

- The agent uses it to validate tool arguments and to build prompts.
- The frontend fetches it from GET /api/categories, so ids/labels/ranges are never duplicated in JavaScript.
- Coverage levels are NOT written here: `load_coverage()` reads them from flameo_tools at start-up
  (iss and moon_base from `scenario_coverage`; spacesuit = "None" plus the oxygen-rich-flames note).
- The intros and the "Ask me" chips are fixed texts decided by the team (chat_decisions/stage7-decisions.md
  Round 3 section 3.2 and Round 4 item 4.7). They contain no numbers.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

# pillars and views


@dataclass(frozen=True)
class Chip:
    text: str
    pending_review: bool = False  # the frontend hides a chip whose answer has not been reviewed yet


@dataclass(frozen=True)
class Pillar:
    id: str
    label: str
    intro: str  # spoken on the first visit, shown on the overview; no numbers
    overview_view: str  # the view the category overview opens
    suggestions: tuple[Chip, ...]  # "Ask me" chips


@dataclass(frozen=True)
class View:
    id: str
    pillar: str  # id of the Pillar this view lives under
    label: str
    icon: str
    tagline: str
    focus_options: tuple[str, ...]


PILLARS: dict[str, Pillar] = {
    p.id: p
    for p in (
        Pillar(
            "prevention",
            "Prevention",
            "Prevention is about what can catch fire. The flight tests burned fabrics and plastics such as SIBAL, Nomex and PMMA in BASS, BASS-II and the Saffire experiments. Ask me about a material, an investigation, or how oxygen changes burning.",
            "materials",
            (
                Chip("Which experiments matter most for prevention?"),
                Chip("Compare BASS and BASS-II"),
                Chip("What is BRE?"),
            ),
        ),
        Pillar(
            "flammability",
            "Flammability & Fire Behavior",
            "This is how a fire behaves once it starts. The flight tests measured how fast flames spread, and how that changed with oxygen and air flow. Ask me, for example, whether fire spreads faster in space.",
            "flame_spread",
            (
                Chip("Does fire spread faster in space?"),
                Chip("What is a cool flame?"),
                Chip("Show me the flame spread data"),
            ),
        ),
        Pillar(
            "detection",
            "Detection",
            "Smoke is usually the first warning. SAME and SAME-R measured the smoke from overheated spacecraft materials on the station. Ask me why smoke is different in space.",
            "smoke",
            (
                Chip("Why are smoke particles bigger in space?"),
                Chip("Which experiments matter most for detection?"),
                Chip("What did SAME measure?", pending_review=True),  # until get_investigation("SAME") is reviewed (Round 4 item 4.7)
            ),
        ),
        Pillar(
            "suppression",
            "Suppression",
            "This is about putting a fire out. FLEX and CFI burned fuel droplets while carbon dioxide or helium was added to the chamber. Ask me which gases the experiments added, or what happens to cool flames.",
            "suppression",
            (
                Chip("Which gases did the experiments add?"),
                Chip("What happens to cool flames with helium?"),
                Chip("How much CO2 puts a fire out?"),
            ),
        ),
    )
}

# Order matters: the first view of a pillar is what "open <pillar>" shows (Prevention opens Materials; Ignition is reached by a question).
VIEWS: dict[str, View] = {
    v.id: v
    for v in (
        View(
            id="materials",
            pillar="prevention",
            label="Materials",
            icon="🧵",
            tagline="How fast flames spread on tested materials.",
            focus_options=("fabrics", "plastics", "thickness", "flame-resistant materials"),
        ),
        View(
            id="ignition",
            pillar="prevention",
            label="Ignition",
            icon="⚡",
            tagline="What makes ignition more or less likely.",
            focus_options=("ignition sources", "overheated electronics", "ignition delay", "oxygen effect"),
        ),
        View(
            id="flame_spread",
            pillar="flammability",
            label="Flame Spread",
            icon="🔥",
            tagline="How fast and in which direction a flame travels across a fuel.",
            focus_options=("spread rate", "flame shape", "opposed vs concurrent flow", "flame size"),
        ),
        View(
            id="smoke",
            pillar="detection",
            label="Smoke",
            icon="💨",
            tagline="How smoke behaves in microgravity and how detectors respond.",
            focus_options=("smoke particles", "detector response", "toxic gases", "ventilation effects"),
        ),
        View(
            id="suppression",
            pillar="suppression",
            label="Suppression",
            icon="🧯",
            tagline="How flames die out, and which gases the experiments added to stop them.",
            focus_options=("airflow shutdown", "oxygen reduction", "added carbon dioxide / helium", "extinction"),
        ),
    )
}


def find_view(pillar: str | None = None, view: str | None = None) -> View | None:
    """Resolve a (pillar, view) pair to a View, or None if invalid.

    - view given  -> that view (and, if pillar is also given, it must match)
    - only pillar -> the pillar's first view, so "open Detection" works in one call
    """
    if view:
        v = VIEWS.get(view)
        return v if v and pillar in (None, v.pillar) else None
    if pillar:
        return next((v for v in VIEWS.values() if v.pillar == pillar), None)
    return None


#  scenarios

COVERAGE_LEVELS = ("High", "Medium", "Low", "None")  # "None" = a named scenario with no test; null = custom conditions


@dataclass(frozen=True)
class Scenario:
    id: str
    label: str
    summary: str  # human description of the atmosphere (the preset, not a data claim)
    inputs: dict  # preset values applied to the conditions
    coverage: str | None = None  # filled from flameo_tools by load_coverage()
    coverage_note: dict | None = None  # spacesuit only: {"label", "level"} for the oxygen-rich burner-stream flames


SCENARIOS: dict[str, Scenario] = {
    s.id: s
    for s in (
        Scenario("iss", "ISS", "About 21% oxygen at about 14.7 psi.", {"oxygen_pct": 21, "pressure_psi": 14.7}),
        Scenario(
            "moon_base",
            "Moon Base / pressurized rover",
            "30% oxygen or more at 10.2 psi or less.",
            # Moon Base is a RANGE; the preset uses its boundary values (30 % / 10.2 psi).
            {"oxygen_pct": 30, "pressure_psi": 10.2},
        ),
        Scenario("spacesuit", "Spacesuit", "100% oxygen at 4.3 psi.", {"oxygen_pct": 100, "pressure_psi": 4.3}),
    )
}

DEFAULT_SCENARIO = "iss"

OXYGEN_RICH_NOTE_LABEL = "Oxygen-rich flames (burner stream, not the atmosphere)"


def load_coverage(call) -> dict:
    """Read the coverage levels from flameo (`call` = flameo.call). Returns {scenario: (level, note)}."""
    out = {}
    for sid in list(SCENARIOS):
        a = call("scenario_coverage", scenario=sid)
        level = a.get("level")
        note = None
        if a.get("level_oxygen_rich_flames"):
            note = {"label": OXYGEN_RICH_NOTE_LABEL, "level": a["level_oxygen_rich_flames"]}
        if level not in COVERAGE_LEVELS:
            raise ValueError(f"flameo returned no coverage level for {sid}: {level!r}")
        SCENARIOS[sid] = replace(SCENARIOS[sid], coverage=level, coverage_note=note)
        out[sid] = (level, note)
    return out


# Fixed UI texts decided by the team (decisions Round 3 sections 3.1, 3.4, 3.7 and Round 4 item 4.5). No numbers.
UI_TEXT = {
    "ranking_title": "Most relevant investigations",
    "ranking_tier": "relevance tier (from the official PSI description)",
    "gaps_title": "Open questions: not in the data yet",
    "gaps_footer": "Gaps like these show where new experiments or papers are needed.",
    "cards_title": "What the authors report",
    "ask_title": "Ask me",
    "gravity": "Microgravity (PSI has no partial-gravity data)",
    "detection_note": "Smoke tests are shown for all conditions: the SAME and SAME-R records have no oxygen or pressure values.",
    "rank_materials_title": "Flame spread in the tested materials (not a safety ranking)",
    "rank_agents_title": "Gases added in the experiments",
    "no_coverage": "Spacesuit atmosphere: none tested",
}


#  input conditions
# Shown in the dashboard (two sliders) and settable by voice. Ranges must cover every scenario preset
# (spacesuit = 100 % O2 at 4.3 psi). Other inputs were removed: no flameo tool uses them.
CONDITIONS: dict[str, dict] = {
    "oxygen_pct": {"label": "Oxygen", "unit": "%", "kind": "number", "min": 0, "max": 100, "step": 0.5, "default": 21},
    "pressure_psi": {"label": "Pressure", "unit": "psi", "kind": "number", "min": 0, "max": 75, "step": 0.1, "default": 14.7},
}


def default_conditions() -> dict:
    """Defaults match DEFAULT_SCENARIO (ISS atmosphere)."""
    return {key: spec["default"] for key, spec in CONDITIONS.items()}


def normalize_conditions(partial: dict) -> dict:
    """Validate/clamp a partial conditions dict. Unknown keys and bad values are dropped."""
    out: dict = {}
    for key, value in partial.items():
        spec = CONDITIONS.get(key)
        if spec is None or value is None:
            continue
        try:
            out[key] = max(spec["min"], min(spec["max"], float(value)))
        except (TypeError, ValueError):
            continue
    return out


def public_catalog() -> dict:
    """JSON served at GET /api/categories."""
    return {
        "pillars": [
            {
                "id": p.id,
                "label": p.label,
                "intro": p.intro,
                "views": [v.id for v in VIEWS.values() if v.pillar == p.id],
            }
            for p in PILLARS.values()
        ],
        "views": [
            {"id": v.id, "pillar": v.pillar, "label": v.label, "icon": v.icon, "tagline": v.tagline, "focus_options": list(v.focus_options)}
            for v in VIEWS.values()
        ],
        "scenarios": [
            {"id": s.id, "label": s.label, "summary": s.summary, "inputs": s.inputs, "coverage": s.coverage, "coverage_note": s.coverage_note}
            for s in SCENARIOS.values()
        ],
        "default_scenario": DEFAULT_SCENARIO,
        "conditions": CONDITIONS,
        "texts": UI_TEXT,
    }
