"""Tool registry: one entry per intent (name, function, docstring, argument schema, router examples). Adding an intent = one function + one entry + golden questions."""
import inspect
import os
from dataclasses import dataclass, field
from typing import Callable, Dict, List

from . import tools as T
from . import learn as L


@dataclass
class Tool:
    name: str
    fn: Callable
    args: Dict[str, dict]
    examples: List[str] = field(default_factory=list)

    @property
    def doc(self):
        return inspect.getdoc(self.fn)


S = {"type": "string"}
REGISTRY: Dict[str, Tool] = {t.name: t for t in [
    Tool("get_investigation", T.get_investigation, {"psi": {**S, "required": True}}, ["What is BRE?", "What did PSI-69 test?"]),
    Tool("compare", T.compare, {"psi_a": {**S, "required": True}, "psi_b": {**S, "required": True}}, ["Compare BASS and BASS-II"]),
    Tool("rank_materials", T.rank_materials, {"metric": S, "scenario": S}, ["Which material spreads flame fastest?"]),
    Tool("scenario_coverage", T.scenario_coverage, {"scenario": {**S, "required": True}}, ["Tests near the Moon base atmosphere?"]),
    Tool("get_findings", T.get_findings, {"x": {**S, "required": True}, "y": {**S, "required": True}, "fuel": S}, ["How does spread rate change with oxygen?"]),
    Tool("rank_agents", T.rank_agents, {"fuel_class": S}, ["Which suppressant works best?"]),
    Tool("rank_investigations", T.rank_investigations, {"pillar": S, "scenario": S}, ["Which experiments matter most for the Moon base?"]),
    Tool("oxygen_effect", T.oxygen_effect, {"scenario": S, "material": S}, ["What oxygen level makes the spacecraft dangerous?", "Is more oxygen dangerous?"]),
    Tool("nearest_tests", T.nearest_tests, {"o2_pct": {"type": "number", "required": True}, "pressure_psi": {"type": "number"}, "pressure_kpa": {"type": "number"}, "material": S}, ["What does the data say at 34 percent oxygen and 8.2 psi?"]),
    Tool("list_materials", T.list_materials, {"scenario": S, "psi": S, "family": S}, ["What materials do you cover?", "Which materials did Saffire-II burn?"]),
    Tool("find_tests", T.find_tests, {"material": S, "psi": S, "scenario": S, "family": S, "outcome": S}, ["Show the tests with fabric", "Silicone tests near the Moon base", "Which Saffire-II materials did not burn in space?"]),
    Tool("data_ranges", T.data_ranges, {"field": {**S, "required": True}, "psi": S, "scenario": S, "above": {"type": "number"}, "below": {"type": "number"}}, ["What is the maximum oxygen in the data?", "Is there any test above 25 percent oxygen?"]),
    Tool("facets", T.facets, {"field": S, "material": S, "family": S, "scenario": S}, []),
    Tool("explain", L.explain, {"term": {**S, "required": True}}, ["What is ignition?", "What is a cool flame?", "What does spread rate mean?"]),
    Tool("interpret_conditions", L.interpret_conditions, {"o2_pct": {"type": "number", "required": True}, "pressure_psi": {"type": "number"}, "pressure_kpa": {"type": "number"}, "material": S}, ["What does 18 percent oxygen mean?", "Is 39.8 percent at 14.8 psi dangerous?"]),
    Tool("get_test", L.get_test, {"test_id": {**S, "required": True}, "psi": S}, ["Tell me about test 19115A1"]),
    Tool("compare_tests", L.compare_tests, {"ids": {"type": "array", "items": S, "required": True}}, ["Compare 19150A1 and 19115A1"]),
    Tool("list_papers", L.list_papers, {"psi": S, "topic": S}, ["Which paper appears most in the sources?", "Papers on BASS-II"]),
    Tool("gaps", T.gaps, {"scenario": S}, ["What don't we know for Mars?"]),
    Tool("search_text", T.search_text, {"query": {**S, "required": True}, "psi": S}, ["Why are space smoke particles bigger?"]),
    Tool("show_view", T.show_view, {"view": {**S, "required": True}, "scenario": S, "params": {"type": "object"}}, ["Show me the flame spread view"]),
    Tool("get_dashboard", T.get_dashboard, {"view": {**S, "required": True}, "scenario": S, "inputs": {"type": "object"}}, []),
    Tool("query_data", T.query_data, {"metric": {**S, "required": True}, "filters": {"type": "object"}}, []),
]}


def call(name, **kwargs):
    if name not in REGISTRY:
        raise KeyError(f"unknown tool {name}")
    return REGISTRY[name].fn(**kwargs)


def tool_specs():
    """Function-calling specs (name, description = docstring, JSON schema) for the agent's router."""
    out = []
    for t in REGISTRY.values():
        props = {k: {kk: vv for kk, vv in v.items() if kk != "required"} for k, v in t.args.items()}
        out.append({"name": t.name, "description": t.doc, "parameters": {"type": "object", "properties": props, "required": [k for k, v in t.args.items() if v.get("required")]}})
    return out
