"""Static checks: generated tool docstrings, tool count, router examples, hard-coded content, the never-say list."""
import ast
import importlib.util
import re
import sys
from pathlib import Path

import yaml

from tests.conftest import ROOT

SRC = ROOT / "src"
FRONT = ROOT.parent / "frontend" / "src" / "coreSolution"

FORBIDDEN = ["Water mist", "Dry powder", "Foam", "Easiest to ignite", "Fastest-burning materials", "Densest smoke sources", "Most effective suppressants",
             "Risk ranking", "SAFETY TAKEAWAY", "buildDemoData"]


def _gen():
    spec = importlib.util.spec_from_file_location("gen_tool_docs", ROOT / "scripts" / "gen_tool_docs.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_intent_wrappers_match_flameo_tool_specs():
    """The 9 wrappers are generated from tool_specs(); this fails when tools.py or vendor/flameo_tools drifts."""
    g = _gen()
    src = (SRC / "tools.py").read_text(encoding="utf-8")
    assert g.render(src) == src, "run: python scripts/gen_tool_docs.py"
    tree = ast.parse(src)
    docs = {n.name: ast.get_docstring(n) for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef)}
    specs = {s["name"]: s for s in g.F.tool_specs()}
    for name in g.INTENTS:
        assert specs[name]["description"].splitlines()[0] in docs[name], name


def test_gemini_gets_one_data_tool_and_the_action_tools():
    """Round 14 D14-1 (a): `answer` + the actions it must keep; the old data tools are server-only."""
    tree = ast.parse((SRC / "tools.py").read_text(encoding="utf-8"))
    tools = [n.name for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and any(getattr(d, "id", "") == "function_tool" for d in n.decorator_list)]
    assert sorted(tools) == sorted(["answer", "go_back", "show_dashboard", "set_conditions", "get_dashboard_state", "get_mission_context", "add_mission_note", "declare_fire_emergency", "clear_fire_emergency"]), tools
    assert "query_data" not in tools
    for n in ("get_investigation", "compare", "rank_materials", "scenario_coverage", "get_findings", "rank_agents", "gaps", "search_text", "rank_investigations", "oxygen_effect", "ask_sources"):
        assert n not in tools, n


def test_search_text_is_the_passage_lookup_and_points_to_ask_sources():
    tree = ast.parse((SRC / "tools.py").read_text(encoding="utf-8"))
    d = next(ast.get_docstring(n) for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == "search_text")
    assert "find the passage about X" in d and "use ask_sources" in d and "3 to 6 English key words" in d and "Never answer from memory" in d


def test_prompt_routes_every_question_to_answer_and_is_short():
    sys.modules.setdefault("livekit", sys.modules.get("livekit"))
    from src.prompts import ROUTER_EXAMPLES, build_instructions

    assert len(ROUTER_EXAMPLES) <= 10
    p = build_instructions()
    assert "call answer with the astronaut's own words" in p and "answered_by is \"clarify\"" in p and "only when answered_by is \"not_found\"" in p
    assert "You never pick a data tool or a paper search yourself" in p and "go_back" in p
    assert len(p) < 9000, len(p)            # short: the first reply waits for it


def test_prompt_never_say_list_and_removed_sections():
    from src.prompts import build_instructions

    p = build_instructions()
    for must in ("safest", "safer", "an amount of extinguishing agent", "any number for Mars", "on the ISS", "coverage"):
        assert must in p
    for gone in ("Being a guide", "Give insight", "what to do about it", "demo data", "Flameo demo", "query_data", "mock"):
        assert gone.lower() not in p.lower(), gone
    assert "Hi, I'm Flamo. I answer from NASA's microgravity fire experiments." in p


def test_no_hard_coded_content_left():
    files = [f for f in FRONT.glob("*") if f.suffix in (".js", ".jsx", ".css") and ".test." not in f.name] + list(SRC.glob("*.py"))
    for f in files:
        text = f.read_text(encoding="utf-8")
        for bad in FORBIDDEN:
            assert bad not in text, f"{bad!r} in {f.relative_to(ROOT)}"
        assert not re.search(r"mock\s*:\s*true|\"mock\"\s*:\s*True|'mock'\s*:\s*True", text, re.I), f"mock: true in {f.name}"
    for f in FRONT.glob("*"):
        if f.suffix in (".js", ".jsx") and ".test." not in f.name:
            assert "Math.random" not in f.read_text(encoding="utf-8"), f"Math.random in {f.name}"
    assert not (SRC / "mock_data.py").exists() and not (SRC / "data.py").exists()


def test_no_background_text_and_no_invented_data_in_categories():
    from src import categories

    for v in categories.VIEWS.values():
        assert not hasattr(v, "background")
    for ban in ("extinguishers", "water mist", "limits", "ranking"):
        assert not any(ban == o for v in categories.VIEWS.values() for o in v.focus_options)
    assert "which burn faster" not in categories.VIEWS["materials"].tagline
    assert categories.VIEWS["suppression"].tagline == "How flames die out, and which gases the experiments added to stop them."


def test_conditions_are_oxygen_and_pressure_only():
    from src import categories

    assert set(categories.CONDITIONS) == {"oxygen_pct", "pressure_psi"}
    assert categories.normalize_conditions({"oxygen_pct": 500, "gravity": "lunar", "material": "x"}) == {"oxygen_pct": 100.0}


def test_gitignore_keeps_data_and_logs_out():
    g = (ROOT.parent / ".gitignore").read_text(encoding="utf-8")
    assert "*.db" in g and "logs/" in g
    assert "FLAMEO_DB" in (ROOT / ".env.example").read_text(encoding="utf-8")
