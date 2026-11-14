"""Generate the 9 intent-tool wrappers in src/tools.py (between the markers) from flameo_tools.tool_specs().

    python scripts/gen_tool_docs.py            rewrite the block
    python scripts/gen_tool_docs.py --check    exit 1 if tools.py differs from what would be generated (tests use this)

The docstring of each wrapper is the flameo docstring (what the tool answers, its arguments, what it never does) plus an
Args section. Gemini builds its function schema from it, so it cannot drift from flameo_tools.
"""
from __future__ import annotations

import os
import re
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "vendor"))
import flameo_tools as F  # noqa: E402

TOOLS = ROOT / "src" / "tools.py"
BEGIN, END = "    # <generated:intent_tools>", "    # </generated:intent_tools>"
INTENTS = ["get_investigation", "compare", "rank_materials", "scenario_coverage", "get_findings", "rank_agents", "gaps", "search_text", "rank_investigations", "oxygen_effect"]

# Round 2 step 3: the default tool for free fire questions (3 to 6 English key words). Prepended to the flameo docstring.
PREFIX = {
    "search_text": "Only for 'find the passage about X' requests (a quick text lookup in the documents and finding cards). For any other fire, combustion or "
                   "space-fire question use ask_sources, which searches only the right investigations and cites its sources. Pass 3 to 6 English key words. "
                   "Never answer from memory. Never use it for off-topic or unsafe questions.",
    "gaps": "Also the tool for fire on the Moon or Mars, partial gravity, or a candle on the Moon: pass scenario 'partial gravity' or 'Mars'.",
    "get_findings": "Also the tool for 'does fire spread faster in space?': x='oxygen', y='spread rate'.",
}
ARG_HELP = {
    "material": "optional: a material word (PMMA, SIBAL, Kapton ...) to keep only findings that name it.",
    "psi": "a PSI id, number or experiment name (for example PSI-20, 20, BRE, SAME).",
    "psi_a": "first investigation (id or name).",
    "psi_b": "second investigation (id or name).",
    "metric": "'spread rate' (the only rankable metric) or the metric the astronaut named.",
    "scenario": "optional: iss, moon_base, exploration_10_2, exploration_8_2, spacesuit, high_o2, Mars or partial gravity.",
    "x": "the quantity that changes (oxygen, pressure, flow ...).",
    "y": "the quantity that responds (spread rate, particle size, extinction diameter ...).",
    "fuel": "optional fuel or material word.",
    "fuel_class": "optional: liquid, gas, solid:PMMA ...",
    "query": "3 to 6 English key words.",
    "pillar": "optional: prevention, flammability, detection or suppression.",
}


def method(spec: dict) -> str:
    name = spec["name"]
    props = spec["parameters"]["properties"]
    req = set(spec["parameters"].get("required", []))
    doc = (PREFIX.get(name, "") + ("\n\n" if name in PREFIX else "") + spec["description"]).strip()
    doc_lines = ["Call BEFORE you speak. The answer appears on the screen by itself.", "", *doc.splitlines(), "", "Args:"]
    sig = ["self", "context: RunContext"]
    call = []
    for k in props:
        doc_lines.append(f"    {k}: {ARG_HELP.get(k, k)}")
        sig.append(f"{k}: str" if k in req else f"{k}: str | None = None")
        call.append(f"{k}={k}")
    body = "\n".join(("        " + ln).rstrip() for ln in doc_lines)
    return (
        "    # server-only since Round 14: the router calls it, Gemini does not (no @function_tool)\n"
        f"    async def {name}({', '.join(sig)}) -> dict:\n"
        f'        """{body.lstrip()}\n        """\n'
        f"        return await self._intent(\"{name}\", {', '.join(call)})\n"
    )


def block() -> str:
    specs = {s["name"]: s for s in F.tool_specs()}
    return BEGIN + "\n" + "\n".join(method(specs[n]) for n in INTENTS) + END


def render(src: str) -> str:
    a, b = src.index(BEGIN), src.index(END) + len(END)
    return src[:a] + block() + src[b:]


if __name__ == "__main__":
    src = TOOLS.read_text(encoding="utf-8")
    new = render(src)
    if "--check" in sys.argv:
        sys.exit(0 if new == src else 1)
    TOOLS.write_text(new, encoding="utf-8")
    print("tools.py intent block regenerated")
