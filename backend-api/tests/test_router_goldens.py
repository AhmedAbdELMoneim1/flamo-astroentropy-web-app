"""Router goldens (Round 9): every expected tool is a tool the model has, and the prompt and the tool docs route to it."""
import ast
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
GOLD = yaml.safe_load((ROOT / "tests" / "golden" / "router_goldens.yaml").read_text(encoding="utf-8"))


def tools_and_docs():
    tree = ast.parse((ROOT / "src" / "tools.py").read_text(encoding="utf-8"))
    return {n.name: ast.get_docstring(n) or "" for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and any(getattr(d, "id", "") == "function_tool" for d in n.decorator_list)}


ACTION_TOOLS = {"declare_fire_emergency", "clear_fire_emergency", "show_dashboard", "set_conditions", "go_back", "none"}


def test_every_golden_names_a_tool_the_server_or_the_model_has():
    from src import flameo
    T = tools_and_docs()
    assert "answer" in T and "go_back" in T
    for g in GOLD:
        assert g["tool"] in ACTION_TOOLS or g["tool"] in ("ask_sources", "search_text") or g["tool"] in flameo.specs_names(), g


def test_the_prompt_sends_data_questions_to_answer_and_the_answer_doc_says_how_to_speak():
    from src.prompts import build_instructions
    p = build_instructions()
    assert "call answer with the astronaut's own words" in p
    docs = tools_and_docs()
    assert "ANY question" in docs["answer"] and "clarify" in docs["answer"] and "not_found" in docs["answer"]


def test_the_router_plan_includes_the_golden_tool_for_every_data_question():
    """The server, not Gemini, picks the tool: for each golden the plan has the expected flameo tool (or the RAG for ask_sources / search_text)."""
    import os
    import pytest
    if not os.getenv("FLAMEO_DB"):
        pytest.skip("FLAMEO_DB not set")
    from src import rag
    from src.router.answer import Router
    from src.router.session import Session
    from src.router.understand import understand
    from src.state import DashboardState
    ext = rag.extractor()
    r = Router(None, DashboardState(), ext)
    for g in GOLD:
        if g["tool"] in ACTION_TOOLS or any("\u0600" <= ch <= "\u06ff" for ch in g["question"]):
            continue                                                     # actions go through their own tools / the emergency classifier; Arabic goes to the RAG (not understood by the router)
        names = [b.get("tool") or b.get("name") or "rag" for b in r.plan(understand(g["question"], Session(), ext, None))]
        assert g["tool"] in names or (g["tool"] in ("ask_sources", "search_text") and "rag" in names), (g["question"], g["tool"], names)


