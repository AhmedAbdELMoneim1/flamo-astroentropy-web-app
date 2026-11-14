"""The router (Round 14 §14.1): `answer(question)` decides on the server who answers.

    1 understand (no model)            -> entities, intents, context
    2 plan + run in parallel           -> the direct flameo tools the intent maps to, and the scoped RAG (one 4.5 s budget)
    3 merge                            -> numbers from the tools, the explanation from the RAG (cited), at most 3 spoken lines
    4 broaden, probe, clarify          -> never "not covered" first
    5 log                              -> the `router` object in logs/questions.jsonl
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import uuid

from src import adapter, alerts, emergency, flameo, qlog, rag
from src.bridge import Cmd
from src.categories import PILLARS, SCENARIOS
from src.content import FOLLOW_UP, chips_for, fcall, guard_rag
from src.router.session import Session
from src.router import llm_understand
from src.router.understand import SAFFIRE_PSIS, Understanding, apply_model, understand

logger = logging.getLogger("router")
BUDGET_S = 4.5
NEW_TYPES = ("explain", "interpret", "test", "compare_tests", "papers")
NEW_SPOKEN = ("interpret_conditions", "get_test", "explain", "list_papers", "compare_tests")
NO_RAG = {"ranges", "materials", "navigate", "compare", "coverage", "find_tests", "offtopic", "rank_materials", "gaps"}      # catalogue / navigation questions: the tools are the answer
OPEN_Q = adapter.OPEN_QUESTION
TOPIC_BY_WORD = [("prevention", r"ignit|prevent"), ("flammability", r"flammab|spread|burn|flame shape|cool flame"), ("detection", r"smoke|aerosol|detect|particle|soot"), ("suppression", r"suppress|extinguish|co2|helium")]
SCEN_LABEL = {"iss": "the ISS cabin", "moon_base": "the Moon base", "spacesuit": "the spacesuit"}


def _notation(line: str) -> str:
    """"XO2 = 17%" is spoken as "17 percent oxygen" (Round 12 item 2)."""
    return re.sub(r"\bXO2\s*=\s*(\d+(?:\.\d+)?)\s*%", r"\1 percent oxygen", line)


def _what(u: Understanding) -> str:
    return u.material or {"fabric": "fabrics", "plastic": "plastics"}.get(u.family or "", "") or (u.fields[0] if u.fields else "") or "that"


class Router:
    def __init__(self, bridge, state, ext=None) -> None:
        self.bridge, self.state = bridge, state
        self.ext = ext or rag.extractor()
        self.ctx: Session = state.ctx
        self._prefetch: tuple[str, asyncio.Task] | None = None          # the unscoped RAG started in parallel with the understanding step (Round 15 §15.1 item 7)

    # ────────────────────────────── plan ──────────────────────────────
    def plan(self, u: Understanding) -> list[dict]:
        """The direct tools (SQL, milliseconds) the intent words and entities map to, and whether the RAG runs too."""
        I, br = set(u.intents), []
        if not u.psis:
            I.discard("investigation")                    # "what's ..." without a named investigation is just a question
        qt = u.qtype
        if u.list_ref and not (qt in NEW_TYPES):
            return self._plan_list(u)
        st = self._saffire_test(u)
        if st and not u.outcome:                                                      # Round 16: "test 2-5 in Saffire-II", "sample S1 of Saffire-I"
            return [{"kind": "tool", "tool": "get_test", "args": {"test_id": st[1], "psi": st[0]}}]
        if u.outcome and not (I & {"compare", "ranges"}):                       # Round 16: which Saffire materials did not burn / did not ignite / burned completely
            return [{"kind": "tool", "tool": "find_tests", "args": {k: v for k, v in {"psi": u.psis[0] if len(u.psis) == 1 else None, "outcome": u.outcome}.items() if v}}]
        if u.saffire_family and not (I & {"compare", "ranges", "materials", "find_tests", "papers", "effect", "danger", "rank", "navigate", "gaps"}) and u.o2 is None and not u.material and qt not in ("test", "compare_tests", "interpret") \
                and not re.search(r"\b(?:measur\w*|diagnostics?|sensors?|instruments?|hardware|module|downlink\w*|cameras?)\b", u.text, re.I):
            return [{"kind": "tool", "tool": "get_investigation", "args": {"psi": u.saffire_family}}]           # "What is Saffire?": the flights in one short answer + their top findings
        if qt == "explain" and u.term:
            return [{"kind": "tool", "tool": "explain", "args": {"term": u.term}}, {"kind": "rag", "args": {}}]
        if qt == "interpret" and u.o2 is not None:
            ic = [{"kind": "tool", "tool": "interpret_conditions", "args": {k: v for k, v in {"o2_pct": u.o2, "pressure_psi": self._pressure(u), "material": u.material}.items() if v is not None}}]
            if "danger" in I:                                              # the oxygen-effect evidence of the scenario stays in the plan (Round 12 golden); interpret_conditions leads
                ic.append({"kind": "tool", "tool": "oxygen_effect", "args": {k: v for k, v in {"scenario": u.scenario, "material": u.material}.items() if v}})
            return ic
        if qt == "test" and u.test_ids:
            return [{"kind": "tool", "tool": "get_test", "args": {k: v for k, v in {"test_id": u.test_ids[0], "psi": u.psis[0] if len(u.psis) == 1 else None}.items() if v}}]
        if qt == "compare_tests" and len(u.test_ids) >= 2:
            return [{"kind": "tool", "tool": "compare_tests", "args": {"ids": u.test_ids[:3]}}]
        if qt == "papers":
            return [{"kind": "tool", "tool": "list_papers", "args": {k: v for k, v in {"psi": u.psis[0] if len(u.psis) == 1 else None, "topic": u.paper_topic}.items() if v}}]
        if qt == "ranking" and u.topic and not u.psis:
            return [{"kind": "tool", "tool": "rank_investigations", "args": {k: v for k, v in {"pillar": u.topic, "scenario": u.scenario}.items() if v}}, {"kind": "rag", "args": {}}]
        psi = u.psis[0] if len(u.psis) == 1 else None
        sc = u.scenario
        add = lambda tool, **a: br.append({"kind": "tool", "tool": tool, "args": {k: v for k, v in a.items() if v not in (None, "")}})      # noqa: E731
        field = next((f for f in u.fields if f in ("oxygen", "pressure", "flow speed", "spread rate", "thickness", "width", "particle size")), None)
        if "compare" in I and len(u.psis) >= 2:
            add("compare", psi_a=u.psis[0], psi_b=u.psis[1])
        if "ranges" in I and field:
            add("data_ranges", field=field, psi=psi, scenario=sc, above=u.above, below=u.below)
        if "materials" in I and "rank_materials" not in I and not (u.material and "find_tests" in I):
            add("list_materials", scenario=sc, psi=psi, family=u.family)
        elif (u.material or u.family) and not (I & {"why", "effect", "danger", "papers"}):
            add("find_tests", material=u.material, family=u.family, psi=psi, scenario=sc)
        if "danger" in I and "rank_materials" not in I and not u.psis:
            add("oxygen_effect", scenario=sc, material=u.material)
            o2 = u.o2 if u.o2 is not None else None
            if o2 is not None:
                p = u.pressure_psi if u.pressure_psi is not None else (SCENARIOS[sc].inputs["pressure_psi"] if sc in SCENARIOS else self.state.inputs.get("pressure_psi"))
                add("nearest_tests", o2_pct=o2, pressure_psi=p)
        if u.o2 is not None and not any(b["tool"] == "nearest_tests" for b in br if b["kind"] == "tool") and not (I & {"ranges", "materials"}):
            p = u.pressure_psi if u.pressure_psi is not None else (SCENARIOS[sc].inputs["pressure_psi"] if sc in SCENARIOS else self.state.inputs.get("pressure_psi"))
            add("nearest_tests", o2_pct=u.o2, pressure_psi=p)
        if "rank_materials" in I:
            add("rank_materials", scenario=sc)
        if "gaps" in I and not br:
            add("gaps", scenario="Mars" if re.search(r"\bmars\b", u.text, re.I) else "partial gravity")
        if "offtopic" in I and not br:
            br.append({"kind": "static", "name": "redirect", "args": {}})
        if "coverage" in I and sc and not any(b["tool"] == "scenario_coverage" for b in br if b["kind"] == "tool"):
            add("scenario_coverage", scenario=sc)
        if "coverage" in I and not sc and u.pillar and not u.psis:
            add("rank_investigations", pillar=u.pillar)
        elif "coverage" in I and not sc:
            br.append({"kind": "static", "name": "catalog", "args": {}})
        if "coverage" in I and sc:
            add("scenario_coverage", scenario=sc)
        if psi and "investigation" in I and not br:
            add("get_investigation", psi=psi)
        if psi and field and "investigation" in I and not any(b["tool"] == "data_ranges" for b in br):
            br.insert(0, {"kind": "tool", "tool": "data_ranges", "args": {"field": field, "psi": psi}})
        if "effect" in I and len(u.fields) >= 2:
            add("get_findings", x=u.fields[0], y=u.fields[1])
        if u.topic and not u.psis and not (u.material or u.family) and not br and not (I & {"danger", "effect", "ranges", "materials", "why", "passage"}):
            add("rank_investigations", pillar=u.topic, scenario=sc)          # a general question: what exists (the main investigations) + the RAG, then 2-3 ways to go deeper
        if "rank" in I and not br:
            add("rank_investigations", scenario=sc)
        if not br and psi and not (I & {"why", "effect", "papers", "danger"}) and len(u.text.split()) <= 5:
            add("get_investigation", psi=psi)
        if not br and psi in SAFFIRE_PSIS and not (I & {"why", "effect", "papers", "danger", "passage", "procedure"}):      # Round 16: a free question about one Saffire flight: its objective, samples, outcomes and top findings
            add("get_investigation", psi=psi)
        if not br and (u.scenario_strict or sc) and not (I & {"papers", "effect", "procedure", "passage"}) and (u.scenario_strict or sc in ("spacesuit", "moon_base") or re.search(r"\b(?:atmosphere|conditions?|environment)\b", u.text, re.I)):
            add("scenario_coverage", scenario=u.scenario_strict or sc)         # "what happens to flames in the spacesuit atmosphere": the atmosphere's coverage, with the RAG beside it
        if "procedure" in I and not br:
            br.append({"kind": "static", "name": "procedure", "args": {}})
        seen, uniq = set(), []
        for b in br:                                              # the same call twice is one call
            k = json.dumps([b["kind"], b.get("tool") or b.get("name"), b["args"]], sort_keys=True, default=str)
            if k not in seen:
                seen.add(k)
                uniq.append(b)
        br = uniq
        if (I - NO_RAG) or not br or (u.o2 is not None and not (I & {"ranges", "materials"})):
            br.append({"kind": "rag", "args": self._rag_args(u)})
        return br

    @staticmethod
    def _saffire_test(u: Understanding):
        """(psi, native test id) when one Saffire flight and one of its samples are named: Saffire-II "2-5" / "sample 5" / "test 2-5"; Saffire-I and III "S1" / "sample 2"."""
        if len(u.psis) != 1 or u.psis[0] not in SAFFIRE_PSIS:
            return None
        m = re.search(r"\b(?:test|sample|run)\s*#?\s*(?:S|2-)?([1-9])\b|\b2-([1-9])\b|\bS([1-9])\b", u.text, re.I)
        if not m:
            return None
        n = next(g for g in m.groups() if g)
        psi = u.psis[0]
        if psi == "PSI-99":
            return psi, f"2-{n}"
        return (psi, f"S{n}") if n in "12" else None

    def _pressure(self, u: Understanding):
        sc = u.scenario
        return u.pressure_psi if u.pressure_psi is not None else (SCENARIOS[sc].inputs["pressure_psi"] if sc in SCENARIOS else self.state.inputs.get("pressure_psi"))

    def _plan_list(self, u: Understanding) -> list[dict]:
        """"they / them / the first one / compare them / a random one" against the list on screen (Round 15 §15.1 item 5)."""
        lr = u.list_ref
        items, kind = lr["items"], lr["kind"]
        key = {"investigations": "psi", "tests": "test", "papers": "paper_id"}[kind]
        if lr["mode"] == "random":
            import random
            pick = [random.choice(items)]
            lr["picked"] = pick[0].get("label")
        elif lr["mode"] == "nth":
            pick = [items[lr["index"]]] if -len(items) <= lr["index"] < len(items) else items[:1]
        else:
            pick = items[:3]
        ids = [x[key] for x in pick if x.get(key)]
        if "compare" in u.intents and len(items) >= 2 and kind == "investigations":
            return [{"kind": "tool", "tool": "compare", "args": {"psi_a": items[0]["psi"], "psi_b": items[1]["psi"]}}]
        if "compare" in u.intents and len(items) >= 2 and kind == "tests":
            return [{"kind": "tool", "tool": "compare_tests", "args": {"ids": [x["test"] for x in items[:3]]}}]
        if kind == "investigations":
            return [{"kind": "tool", "tool": "get_investigation", "args": {"psi": i}} for i in ids]
        if kind == "tests":
            return [{"kind": "tool", "tool": "get_test", "args": {"test_id": i}} for i in ids[:1]]
        return [{"kind": "tool", "tool": "list_papers", "args": {}}]

    def _rag_args(self, u: Understanding) -> dict:
        a: dict = {}
        if len(u.psis) == 1:
            a["psi"] = u.psis[0]
        if u.material:
            a["material"] = u.material
        if u.scenario_strict:
            a["scenario"] = u.scenario_strict
        if u.o2 is not None:
            a["o2_pct"] = u.o2
        return a

    # ───────────────────────────── branches ─────────────────────────────
    async def _tool(self, b: dict) -> dict:
        t = time.monotonic()
        try:
            d = await fcall(b["tool"], **b["args"])
            return {**b, "d": d, "ms": round((time.monotonic() - t) * 1000), "has": self._tool_has(b["tool"], d)}
        except Exception as e:  # noqa: BLE001  (a bad argument must not break the turn; the branch is just empty)
            logger.warning("flameo %s failed: %s", b["tool"], e)
            return {**b, "d": None, "ms": round((time.monotonic() - t) * 1000), "has": False, "err": f"{type(e).__name__}: {e}"[:120]}

    @staticmethod
    def _tool_has(name: str, d: dict) -> bool:
        if not d or not adapter.matched(d) or not d.get("speak"):
            return False
        if name == "find_tests":
            return bool(d.get("n_anywhere"))
        if name == "data_ranges":
            return bool(d.get("ranges")) or bool(d.get("scope", {}).get("psi") or d.get("scope", {}).get("scenario"))
        if name == "list_materials":
            return bool(d.get("table")) or bool(d.get("scope", {}).get("family")) or bool(d.get("scope", {}).get("psi"))      # "no material recorded in X" is an answer
        if name == "nearest_tests":
            return True
        if name == "explain":
            return bool(d.get("found"))
        if name == "list_papers":
            return bool(d.get("n_papers"))
        if name == "compare_tests":
            return bool(d.get("compared"))
        return True

    async def _static(self, b: dict) -> dict:
        """Fixed answers: the catalogue of what Flamo covers, and the fire procedure sentence (a hypothetical "what should I do"; a real fire goes through declare_fire_emergency)."""
        if b["name"] == "redirect":
            d = {"tool": "redirect", "question": "", "speak": ["I'm here for fire safety in space. Ask me about flames, materials, or the tested atmospheres."], "kpis": [], "charts": [], "table": None, "gaps": [], "sources": [], "facts": [], "source": {"refs": []}}
            return {**b, "kind": "tool", "tool": "redirect", "d": d, "ms": 0, "has": True}
        if b["name"] == "catalog":
            names = [p.label for p in PILLARS.values()]
            d = {"tool": "catalog", "question": "What does the data cover?", "speak": ["The data covers " + ", ".join(names[:-1]) + " and " + names[-1] + ", for the ISS cabin, the Moon base and the spacesuit atmosphere.", "I can list the materials, the tested ranges of oxygen and pressure, or the investigations; which one?"],
                 "kpis": [], "charts": [], "table": None, "gaps": [], "sources": [], "facts": [], "source": {"refs": []}}
            return {**b, "kind": "tool", "tool": "catalog", "d": d, "ms": 0, "has": True}
        from src import emergency
        steps = emergency.banner("cabin", "")["steps"]
        d = {"tool": "procedure", "question": "What should I do?", "speak": ["Follow your mission fire procedure: " + "; ".join(x[0].lower() + x[1:] if x else x for x in steps[:4]) + "."], "kpis": [], "charts": [], "table": None,
             "gaps": [], "sources": [], "facts": [], "source": {"refs": []}}
        return {**b, "kind": "tool", "tool": "procedure", "d": d, "ms": 0, "has": True}

    async def _rag(self, question: str, args: dict) -> dict:
        t = time.monotonic()
        if not rag.available():
            try:
                d = await fcall("search_text", query=question, **({"psi": args["psi"]} if args.get("psi") else {}))
            except Exception as e:  # noqa: BLE001
                return {"kind": "rag", "r": None, "has": False, "ms": 0, "err": str(e)[:100], "path": "search_text (RAG off)"}
            m = adapter.matched(d)
            r = {"request_id": uuid.uuid4().hex[:8], "question": question, "status": "fallback" if m else "not_found", "outcome": "fallback" if m else "not_found", "speak": list(d.get("speak", []))[:3] if m else [],
                 "speak_refs": [[1] if d.get("sources") else [] for _ in d.get("speak", [])[:3]], "sources": d.get("sources", []), "clarify": None}
            return {"kind": "rag", "r": r, "has": bool(r["speak"]), "ms": round((time.monotonic() - t) * 1000), "path": "search_text (RAG off)"}
        try:
            r = await rag.get().ask(question, **args)
        except Exception as e:  # noqa: BLE001
            return {"kind": "rag", "r": None, "has": False, "ms": round((time.monotonic() - t) * 1000), "err": f"{type(e).__name__}: {e}"[:120], "path": "rag error"}
        r = guard_rag(r)
        return {"kind": "rag", "r": r, "has": r.get("status") in ("ok", "fallback") and bool(r.get("speak")), "ms": round((time.monotonic() - t) * 1000), "path": "rag",
                "options": (r.get("clarify") or {}).get("options", [])}

    async def run(self, question: str, plan: list[dict], deadline: float) -> list[dict]:
        def rag_branch(b):
            pf = self._prefetch
            if pf and pf[0] == question and not b["args"]:
                return pf[1]                                           # the unscoped RAG already running (Round 15 item 7)
            return self._rag(question, b["args"])
        tasks = [asyncio.ensure_future(self._tool(b) if b["kind"] == "tool" else (self._static(b) if b["kind"] == "static" else rag_branch(b))) for b in plan]
        if not tasks:
            return []
        left = max(0.3, deadline - time.monotonic())
        done, pending = await asyncio.wait(tasks, timeout=left + 0.5)
        out = []
        for b, t in zip(plan, tasks):
            if t in pending:
                if not (b["kind"] == "rag" and self._prefetch and t is self._prefetch[1]):
                    t.cancel()                                              # too slow: the branch is empty (the others still answer), never an unhandled timeout
                out.append({"kind": b["kind"], "has": False, "err": "timeout", "ms": round((left + 0.5) * 1000), **({"tool": b.get("tool")} if b["kind"] == "tool" else {})})
                continue
            try:
                x = t.result()
            except BaseException as e:  # noqa: BLE001
                x = {"kind": "tool", "has": False, "err": str(e)[:100]}
            out.append(x if isinstance(x, dict) else {"kind": "tool", "has": False, "err": str(x)[:100]})
        return out

    # ───────────────────────────── merge ─────────────────────────────
    def merge(self, u: Understanding, res: list[dict]) -> dict | None:
        tools = [r for r in res if r["kind"] == "tool" and r.get("has")]
        rg = next((r for r in res if r["kind"] == "rag" and r.get("has")), None)
        if not tools and not rg:
            return None
        if tools:
            main = tools[0]
            both = next((t for t in tools if t["tool"] == "interpret_conditions"), None) if main["tool"] == "get_test" else None
            if both is not None:                                         # a pasted table row with "danger?": the test, then what its conditions mean
                main = both
            d = dict(main["d"])
            lines = [_notation(x) for x in d.get("speak", [])]
            by = "tool"
            if main["tool"] in NEW_SPOKEN:
                lines = self._spoken(main["tool"], d, [t for t in tools if t["tool"] == "get_test"])
            if main["tool"] == "rank_investigations":
                lines, d = self._strip_method(lines, d)
            if main["tool"] == "oxygen_effect":
                near = next((t for t in tools if t["tool"] == "nearest_tests"), None)
                if near is not None and u.o2 is not None:
                    lines = self._conditions_lines(d, near["d"], u.o2)
            if main["tool"] == "data_ranges" and len(tools) > 1:
                lines = lines[:2]
            speak = lines[:3]
            sources = list(d.get("sources", []))
            if rg is not None and len(speak) < 3 and main["tool"] not in ("nearest_tests",):
                speak = (speak[:2] if len(speak) >= 3 else speak) + [rg["r"]["speak"][0]]
                for s in rg["r"].get("sources", []):
                    sources.append(s)
                by = "both"
            return {"by": by, "main": main["tool"], "d": d, "speak": speak[:3], "sources": sources, "rag": rg["r"] if rg else None, "tools": [t["tool"] for t in tools]}
        return {"by": "rag", "main": "ask_sources", "d": None, "speak": list(rg["r"]["speak"])[:3], "sources": rg["r"].get("sources", []), "rag": rg["r"], "tools": []}

    @staticmethod
    def _strip_method(lines: list[str], d: dict) -> tuple[list[str], dict]:
        """Ranking answers speak the meaning, not the machinery (Round 15 §15.1 item 3): the "ranked by ..." clause goes to the screen as a footnote."""
        out, foot = [], d.get("footnote")
        for x in lines:
            m = re.search(r",?\s*(ranked by [^.]*)\.", x)
            if m:
                foot = foot or m.group(1)[0].upper() + m.group(1)[1:] + "."
                x = x[:m.start()] + "." + x[m.end():]
            out.append(x)
        return out, ({**d, "footnote": foot} if foot else d)

    @staticmethod
    def _spoken(tool: str, d: dict, tests: list[dict]) -> list[str]:
        """The 3 spoken lines of the new tools: direct answer, evidence, meaning or the coverage note (the screen shows every part)."""
        lines = [_notation(x) for x in d.get("speak", [])]
        if tool == "interpret_conditions":
            it = d.get("interpretation", {})
            low = it.get("coverage_level") in ("Low", "None") or it.get("outside_tested_range")
            third = it.get("coverage_note") if low or not it.get("evidence") else it["evidence"]
            out = [it.get("where"), it.get("nearby"), _notation(third or "")]
            if tests:                                                    # the pasted row: the test comes first
                out = [(tests[0]["d"].get("speak") or [""])[0], it.get("where"), _notation(third or "")]
            return [x for x in out if x][:3]
        if tool == "get_test":
            return (lines[:3] if len(lines) >= 3 else lines)
        return lines[:3]

    @staticmethod
    def _conditions_lines(oxy: dict, near: dict, o2: float) -> list[str]:
        """The conditions answer (Round 12 item 2): the scenario line, the nearest-tests line, then the evidence line closest to the user's oxygen."""
        lines = [_notation(x) for x in oxy.get("speak", [])]
        defin = next((x for x in lines if " percent oxygen at " in x or x.startswith("The intermediate oxygen") or " has " in x and "percent oxygen" in x), None)
        evid = [x for x in lines if "authors report" in x or x.startswith("From ")]
        band17 = next((x for x in evid if "17 percent oxygen" in x), None)
        bre = next((x for x in evid if "26 %" in x), None)
        cool = next((x for x in evid if "0.4" in x or "cool flame" in x.lower()), None)
        pick = (band17 or bre) if o2 < 23 else (cool if (o2 >= 40 and cool) else (bre or band17))
        out = [x for x in (defin, (near.get("speak") or [None])[0], pick) if x]
        return out[:3] or lines[:3]

    # ───────────────────────────── probe ─────────────────────────────
    async def probe(self, u: Understanding, res: list[dict] | None = None) -> list[dict]:
        """Where does the data have something about the question's words? 2-3 options with counts, flight first."""
        args = {"material": u.material} if u.material else ({"family": u.family} if u.family else ({"field": u.fields[0]} if u.fields else None))
        opts: list[dict] = []
        if args:
            try:
                d = await fcall("facets", **args)
            except Exception:  # noqa: BLE001
                d = {"rows": []}
            what = _what(u)
            for r in d.get("rows", [])[:3]:
                ent = {"psi": [r["psi"]]}
                if u.material:
                    ent["material"] = u.material
                if u.family:
                    ent["family"] = u.family
                if u.fields and not (u.material or u.family):
                    ent["fields"] = [u.fields[0]]
                opts.append({"label": f"{what} in {r['investigation']}", "entities": ent, "n": r["n"]})
        if len(opts) < 2:                                          # nothing structured: the unscoped RAG's own candidates ("Label (PSI-xx)")
            for r in res or []:
                for o in r.get("options", []) if r.get("kind") == "rag" else []:
                    m = re.search(r"\((PSI-\d+)\)", o)
                    if m and all(m.group(1) not in x["entities"].get("psi", []) for x in opts):
                        opts.append({"label": o, "entities": {"psi": [m.group(1)]}, "n": 0})
        return opts[:3]

    # ───────────────────────────── the turn ─────────────────────────────
    async def answer(self, question: str) -> dict:
        try:
            return await self._answer(question)
        finally:
            pf, self._prefetch = self._prefetch, None
            if pf and not pf[1].done():
                pf[1].cancel()                                          # the model chose a scoped plan: the unscoped RAG is not needed

    async def _model_step(self, question: str, u: Understanding, log: dict) -> None:
        """Round 15 item 1 + 7: the understanding model (<= 0.6 s) runs in parallel with an unscoped RAG prefetch."""
        um = llm_understand.get()
        s = self.ctx
        unsure = u.qconf < llm_understand.SURE or not question.isascii() or len(question.split()) > 14
        if um is not None and not s.pending and not unsure:
            log["model_call"] = {"skipped": "the rules are sure"}
        if um is not None and not s.pending and unsure:
            ctx = {k: v for k, v in {"last_question": s.last_question[:120], "psi": s.psi, "scenario": s.scenario or self.state.scenario, "list_on_screen": s.rows["kind"] if s.rows else None}.items() if v}
            info = await um.classify(question, ctx)
            apply_model(u, info, self.ext)
            log["model_call"] = {k: info.get(k) for k in ("by", "key", "ms", "why")}
        log["understanding"] = u.to_dict()["understanding"]

    async def _answer(self, question: str) -> dict:
        t0 = time.monotonic()
        deadline = t0 + BUDGET_S
        s, st = self.ctx, self.state
        u = understand(question, s, self.ext, st.scenario)
        if s.pending and u.pending_choice is None and (u.intents or u.entities() or len(question.split()) > 4):
            s.pending = None                                          # a new question, not the reply to the clarifying one
        log: dict = {"entities": u.entities(), "intent": u.intents, "context_used": u.context_used, "context": s.snapshot(), "plan": [], "branches": [], "broaden": [], "probe": None}
        text = question
        # the reply to a clarifying question, or a "yes" to an offer
        if s.pending and u.pending_choice is None and len(question.split()) <= 4 and not u.entities() and not u.confirm:
            u.pending_choice = 0                                     # no option matched: the best one, and say which (Round 14 §14.2)
            log["clarify_reply"] = "no option matched: first option"
        em = emergency.classify(question) if re.search(r"\b(?:fire|smoke|burning|burnt|smell\w*|overheat\w*|sparks?|alarm)\b", question, re.I) else "unknown"
        if em in ("now", "ambiguous"):
            return await self._emergency(question, u, em, log, t0)
        if em == "clear" and self.state.emergency:
            await alerts.clear(self.bridge, self.state, "the astronaut said it is over")
            model = {"status": "cleared", "speak": ["Okay, I cleared the alert."], "answered_by": "action", "reply_guidance": "Say it in one short sentence."}
            self.state.allow(*model["speak"])
            return self._finish(question, u, "action", "clear_fire_emergency", model, log, t0, [])
        if "navigate" in u.intents and (u.go_back or u.pillar or u.scenario):
            return await self._navigate(question, u, log, t0)
        if not s.pending and not u.confirm and u.qtype in ("effect", "explain", "ranking") and rag.available() and not u.list_ref:
            self._prefetch = (question, asyncio.create_task(self._rag(question, {})))       # in parallel with the model call; used only when the plan's RAG branch is unscoped
        tm = time.monotonic()
        await self._model_step(question, u, log)
        deadline += time.monotonic() - tm                                 # the model call does not eat the answer's budget
        log["entities"], log["intent"] = u.entities(), u.intents
        if u.qconf < 0.6 and u.alt_types and not s.clarified and not s.pending and not u.list_ref:
            opts = self._type_options(u)
            if len(opts) >= 2:
                s.clarified = True
                return await self._clarify(question, u, opts, log, t0, q=f"Do you mean {opts[0]['label']}, or {opts[1]['label']}?")
        plan = None
        note = None
        chosen = None
        if s.pending and u.pending_choice is not None:
            pend, s.pending = s.pending, None
            text = pend["question"]
            if u.pending_choice == -1 and len([o for o in pend["options"] if o["entities"].get("psi")]) >= 2:
                ps = [o["entities"]["psi"][0] for o in pend["options"] if o["entities"].get("psi")]
                u = understand(text, s, self.ext, st.scenario)
                u.psis, u.intents = ps[:2], ["compare"]
                note = f"I compared {pend['options'][0]['label'].split(' in ')[-1]} and {pend['options'][1]['label'].split(' in ')[-1]}" + (f"; ask for the third one separately." if len(ps) > 2 else ".")
                s.options = []
            else:
                opt = pend["options"][u.pending_choice if u.pending_choice >= 0 else 0]
                u = understand(text, s, self.ext, st.scenario)
                e = opt["entities"]
                u.psis = e.get("psi", u.psis)
                u.material, u.family = e.get("material", u.material), e.get("family", u.family)
                u.fields = e.get("fields", u.fields)
                if e.get("qtype"):
                    u.qtype, u.qconf, u.alt_types, u.term, u.topic = e["qtype"], 1.0, [], e.get("term", u.term), e.get("topic", u.topic)
                note = f"Taking {opt['label']}."
                chosen = opt
            log["clarify_reply"] = log.get("clarify_reply") or "option chosen"
        elif "compare" in u.intents and len(u.psis) < 2 and len([o for o in s.options if o["entities"].get("psi")]) >= 2:
            opts = [o for o in s.options if o["entities"].get("psi")]
            u.psis = [opts[0]["entities"]["psi"][0], opts[1]["entities"]["psi"][0]]
            note = f"I compared {flameo.psi_name(u.psis[0])} and {flameo.psi_name(u.psis[1])}" + ("; the third one needs its own question." if len(opts) > 2 else ".")
        elif u.confirm and not s.offer and s.psi:
            plan = [{"kind": "tool", "tool": "find_tests", "args": {"psi": s.psi}}]
            log["offer_used"] = "default: the tests of the investigation in context"
        elif u.confirm and not s.offer and not s.psi:
            plan = [{"kind": "static", "name": "catalog", "args": {}}]
            log["offer_used"] = "none: the catalogue line"
        elif u.confirm and s.offer:
            plan = [dict(b, kind="tool") for b in s.offer["branches"]]
            log["offer_used"] = s.offer["label"]
        if plan is None:
            plan = self.plan(u)
        log["plan"] = [{"kind": b["kind"], "tool": b.get("tool"), "args": b["args"]} for b in plan]
        res = await self.run(text, plan, deadline)
        if u.also_interpret:                                              # a pasted row with "danger?": what the test's own conditions mean
            gt = next((r for r in res if r.get("tool") == "get_test" and r.get("has")), None)
            c = (gt["d"].get("conditions") if gt else None) or {}
            if c.get("o2_pct") is not None and c.get("pressure_psi") is not None:
                res.append(await self._tool({"kind": "tool", "tool": "interpret_conditions", "args": {"o2_pct": c["o2_pct"], "pressure_psi": c["pressure_psi"]}}))
        log["branches"] = [self._brief(r) for r in res]
        merged = self.merge(u, res)
        # broaden, step by step: never "not covered" first
        if merged is None:
            for desc, u2 in self._relax(u):
                if time.monotonic() > deadline:
                    break
                p2 = self.plan(u2)
                r2 = await self.run(text, p2, deadline)
                m2 = self.merge(u2, r2)
                log["broaden"].append({"step": desc, "plan": [b.get("tool") or "rag" for b in p2], "found": bool(m2)})
                if m2:
                    merged, u = m2, u2
                    note = f"I found no direct answer; here is what the data has on {u.topic}." if desc.startswith("directly") else f"I found nothing {desc}; here is what the data has."
                    res = res + r2
                    break
        if merged is None and u.qtype in ("explain", "effect") and (u.term or u.fields) and time.monotonic() < deadline + 1:       # the glossary before "not covered" (Round 15 item 6)
            term = u.term or u.fields[0]
            r5 = await self._tool({"kind": "tool", "tool": "explain", "args": {"term": term}})
            log["broaden"].append({"step": f"the glossary entry for {term}", "plan": ["explain"], "found": bool(r5.get("has"))})
            if r5.get("has"):
                merged = self.merge(u, [r5])
                note = note or "I found no direct answer in the papers; here is the definition."
        if merged is None and chosen is not None:                       # the astronaut chose: never ask again, show what the chosen place has
            ps = chosen["entities"].get("psi", [])
            fb = [{"kind": "tool", "tool": "find_tests", "args": {k: v for k, v in {"psi": ps[0] if ps else None, "material": u.material, "family": u.family}.items() if v}}] if (u.material or u.family) else \
                 [{"kind": "tool", "tool": "get_investigation", "args": {"psi": ps[0]}}]
            merged = self.merge(u, await self.run(text, fb, deadline + 2))
            log["broaden"].append({"step": "the chosen option, shown as it is", "plan": [b["tool"] for b in fb], "found": bool(merged)})
        if merged is None:
            opts = await self.probe(u, res)
            log["probe"] = [{"label": o["label"], "n": o["n"]} for o in opts]
            if len(opts) >= 2:
                return await self._clarify(question, u, opts[:3], log, t0)
            if len(opts) == 1:                                       # one place has data: answer from it and say which
                u3 = understand(text, s, self.ext, st.scenario)
                u3.psis, u3.material, u3.family = opts[0]["entities"]["psi"], u.material, u.family
                r3 = await self.run(text, self.plan(u3), deadline + 2)
                merged = self.merge(u3, r3)
                if merged is None:
                    r4 = await self.run(text, [{"kind": "tool", "tool": "get_investigation", "args": {"psi": opts[0]["entities"]["psi"][0]}}], deadline + 2)
                    merged = self.merge(u3, r4)
                if merged:
                    u, note = u3, f"Only {opts[0]['label'].split(' in ')[-1]} has data on this."
        if merged is None and u.qtype == "explain" and u.term:             # D15-1: one labelled sentence of general background, never numbers
            bg = await self._background(u.term)
            log["background"] = bool(bg)
            if bg:
                return await self._deliver_background(question, u, bg, log, t0)
        if merged is None:
            return await self._not_found(question, u, log, t0)
        return await self._deliver(question, u, merged, note, log, t0)

    async def _emergency(self, question: str, u: Understanding, em: str, log: dict, t0: float) -> dict:
        """A fire reported as happening now: the banner (server side, deterministic). Unsure: ask once. Hypothetical questions are answered with the procedure sentence (plan)."""
        if em == "now":
            await alerts.declare(self.bridge, self.state, question)
            model = {"status": "emergency", "speak": ["Alert the crew and ground control, and follow your mission fire procedure."], "answered_by": "action",
                     "reply_guidance": "Say the line calmly. The steps are on the screen."}
        else:
            model = {"status": "clarify", "speak": ["Is there a fire right now?"], "clarify": {"question": "Is there a fire right now?", "options": ["Yes, there is a fire now", "No, I am only asking"]}, "answered_by": "clarify",
                     "reply_guidance": "Ask exactly this question, nothing else."}
        self.state.allow(*model["speak"])
        return self._finish(question, u, model["answered_by"], "declare_fire_emergency" if em == "now" else None, model, log, t0, [])

    async def _navigate(self, question: str, u: Understanding, log: dict, t0: float) -> dict:
        """"go back", "go to Base env", "in prevention go to materials": the screen moves; the answer is the new overview's first line."""
        from src.content import push_view
        from src.categories import VIEWS, find_view
        st = self.state
        if u.go_back and st.previous:
            v = find_view(st.previous.get("pillar"), st.previous.get("view"))
        elif u.pillar:
            wanted = "materials" if u.pillar == "prevention" and re.search(r"\bmaterials?\b", question, re.I) else None
            v = find_view(u.pillar, wanted) or find_view(u.pillar, PILLARS[u.pillar].overview_view if u.pillar in PILLARS else None)
        else:
            v = find_view(st.pillar, st.view) if st.pillar else None
        if u.scenario in SCENARIOS:
            updates = st.update_conditions(scenario=u.scenario)
            await self.bridge.send(Cmd.CONDITIONS_SET, {"scenario": st.scenario, "inputs": updates})
        if v is None:
            v = find_view("flammability", None)
        st.open_view(v)
        self.ctx.psi = self.ctx.material = self.ctx.family = None
        self.ctx.scenario = u.scenario or self.ctx.scenario
        self.ctx.offer, self.ctx.options, self.ctx.pending, self.ctx.rows = None, [], None, None
        content = await push_view(self.bridge, st)
        line = (content.get("speak") or [""])[0] if content.get("status") == "ok" else ""
        model = {"status": "shown", "speak": [line] if line else [f"Showing {PILLARS[v.pillar].label}."], "answered_by": "action", "reply_guidance": "Say the first line, then 'Ask me anything about <category>.'"}
        self.state.allow(*model["speak"])
        return self._finish(question, u, "action", "show_dashboard", model, log, t0, [])

    def _relax(self, u: Understanding):
        """Drop the narrowest constraint first: scenario, then the investigation, then the material (keep its family), then the extra fields."""
        import copy
        steps = []
        if u.scenario or u.scenario_strict:
            v = copy.deepcopy(u)
            v.qtype = "effect" if v.qtype in ("nearest",) else v.qtype
            v.scenario = v.scenario_strict = None
            steps.append((f"for {SCEN_LABEL.get(u.scenario or u.scenario_strict, 'that atmosphere')}", v))
        if u.psis:
            v = copy.deepcopy(u)
            v.psis = []
            steps.append(("in that investigation", v))
        if u.material:
            v = copy.deepcopy(u)
            v.material, v.family = None, v.family
            steps.append((f"for {u.material}", v))
        if len(u.fields) > 1:
            v = copy.deepcopy(u)
            v.fields = v.fields[:1]
            steps.append(("for that pair of quantities", v))
        everything = copy.deepcopy(u)
        everything.psis, everything.material, everything.family, everything.scenario, everything.scenario_strict, everything.fields = [], None, None, None, None, []
        everything.intents, everything.qtype, everything.list_ref = ["why"], "effect", None
        steps.append(("with those filters", everything))
        if u.topic:
            t = copy.deepcopy(everything)
            t.intents, t.topic = [], u.topic
            steps.append(("directly", t))
        return steps[:5]

    @staticmethod
    def _brief(r: dict) -> dict:
        if r["kind"] == "tool":
            d = r.get("d") or {}
            return {"kind": "tool", "tool": r.get("tool"), "has": r.get("has"), "rows": len((d.get("table") or {}).get("rows", [])), "lines": len(d.get("speak", [])), "ms": r.get("ms"), **({"err": r["err"]} if r.get("err") else {})}
        rr = r.get("r") or {}
        return {"kind": "rag", "has": r.get("has"), "status": rr.get("status"), "sources": len(rr.get("sources", [])), "path": r.get("path"), "ms": r.get("ms"), **({"err": r["err"]} if r.get("err") else {})}

    # ───────────────────────────── outcomes ─────────────────────────────
    def _type_options(self, u: Understanding) -> list[dict]:
        """The options of a vague question, each one with data behind it (Round 15 §15.1 item 4): the concept, or what the data has on it."""
        if u.qtype == "explain" and u.term and "catalogue" in u.alt_types:
            opts = [{"label": f"what {u.term} is", "entities": {"qtype": "explain", "term": u.term}, "n": 0}]
            if u.topic:
                opts.append({"label": f"the {u.term} investigations in the data", "entities": {"qtype": "ranking", "topic": u.topic}, "n": 0})
            return opts
        return []

    async def _background(self, term: str) -> str | None:
        um = llm_understand.get()
        if um is None:
            return None
        try:
            return await um.background(term)
        except Exception:  # noqa: BLE001
            return None

    async def _deliver_background(self, question: str, u: Understanding, sentence: str, log: dict, t0: float) -> dict:
        line = "General background, not from the PSI data: " + sentence
        r = {"request_id": uuid.uuid4().hex[:8], "question": question, "status": "ok", "outcome": "answer", "speak": [line], "speak_refs": [[]], "sources": [], "clarify": None, "general_background": True}
        ans = adapter.rag_to_answer(r, None, offer=None)
        ans["general_background"] = True
        await self.bridge.send(Cmd.ANSWER_SHOW, ans)
        model = adapter.rag_to_model(r, "")
        model["answered_by"], model["general_background"] = "background", True
        model["reply_guidance"] = "Say the line exactly, including the words 'general background, not from the PSI data'. Add nothing."
        self.state.allow(line)
        return self._finish(question, u, "background", "general_background", model, log, t0, [])

    async def _clarify(self, question: str, u: Understanding, opts: list[dict], log: dict, t0: float, q: str | None = None) -> dict:
        labels = [o["label"] for o in opts]
        if not q:
            q = "Which one: " + ", or ".join(labels[:-1] + [labels[-1]]) + "?" if len(labels) == 2 else "Which one: " + ", ".join(labels[:-1]) + ", or " + labels[-1] + "?"
        self.ctx.pending = {"question": question, "options": opts}
        self.ctx.options = opts
        r = {"request_id": uuid.uuid4().hex[:8], "question": question, "status": "clarify", "outcome": "clarify", "speak": [q], "speak_refs": [[]], "sources": [], "clarify": {"question": q, "options": labels, "why": "the probe found data in several places"}}
        await self.bridge.send(Cmd.ANSWER_SHOW, adapter.rag_to_answer(r, None, offer=None))
        model = adapter.rag_to_model(r, "")
        model["answered_by"] = "clarify"
        model["reply_guidance"] = "Ask exactly this one short question, nothing else. The options are on the screen."
        self.state.allow(q)
        return self._finish(question, u, "clarify", None, model, log, t0, [])

    async def _not_found(self, question: str, u: Understanding, log: dict, t0: float) -> dict:
        """Only here: the tools, the scoped RAG, the broadened runs and the probe all found nothing."""
        r = {"request_id": uuid.uuid4().hex[:8], "question": question, "status": "not_found", "outcome": "not_found", "speak": [], "speak_refs": [], "sources": [], "clarify": None}
        pillar = None
        await self.bridge.send(Cmd.ANSWER_SHOW, adapter.rag_to_answer(r, pillar, offer=self._offer()))
        model = adapter.rag_to_model(r, "")
        model["answered_by"] = "not_found"
        model["not_covered"] = True
        model["reply_guidance"] = f"Say: \"{OPEN_Q}\" Then offer the category on the screen."
        self.state.allow(OPEN_Q)
        return self._finish(question, u, "not_found", None, model, log, t0, [])

    def _offer(self) -> dict | None:
        p = PILLARS.get(self.state.pillar or "")
        return {"category": p.label, "chips": chips_for(p.id)[:2]} if p else None

    def _make_offer(self, u: Understanding, merged: dict) -> tuple[dict | None, str]:
        """What "yes" shows next, named in the offer ("Do you want the Saffire-II test data?")."""
        psi = u.psis[0] if len(u.psis) == 1 else None
        name = flameo.psi_name(psi) if psi else None
        main = merged["main"]
        label = SCEN_LABEL.get(u.scenario or "", "")
        d = merged.get("d") or {}
        if main == "explain":
            if u.topic or (d.get("glossary") or {}).get("term"):
                topic = u.topic or next((t for t, rx in TOPIC_BY_WORD if re.search(rx, (d["glossary"]["term"] + " " + " ".join(d["glossary"].get("aliases", []))).lower())), None)
                if topic:
                    return {"label": f"the {topic} investigations", "branches": [{"tool": "rank_investigations", "args": {"pillar": topic}}]}, f"Want the investigations in the data on {d['glossary']['term']}?"
            return None, ""
        if main in ("get_test", "interpret_conditions"):
            c = d.get("conditions") or {}
            o2 = c.get("o2_pct")
            if o2 is not None and c.get("pressure_psi") is not None:
                return {"label": "the tests near these conditions", "branches": [{"tool": "nearest_tests", "args": {"o2_pct": o2, "pressure_psi": c["pressure_psi"]}}]}, "Want the tests near these conditions?"
            return None, ""
        if main in ("list_papers", "compare_tests"):
            return None, ""
        if main == "data_ranges" and psi:
            return {"label": f"the {name} test data", "branches": [{"tool": "find_tests", "args": {"psi": psi}}]}, f"Do you want the {name} tests behind it?"
        if main in ("find_tests", "nearest_tests") or (main == "data_ranges" and not psi):
            return None, ""
        if main == "list_materials" and psi:
            return {"label": f"the {name} test data", "branches": [{"tool": "find_tests", "args": {"psi": psi}}]}, f"Do you want the {name} tests behind it?"
        if main == "get_investigation" and psi:
            return {"label": f"the materials in {name}", "branches": [{"tool": "list_materials", "args": {"psi": psi}}]}, f"Do you want to see the materials {name} burned?"
        if (u.material or u.family) and main != "find_tests":
            args = {k: v for k, v in {"material": u.material, "family": u.family, "psi": psi, "scenario": u.scenario}.items() if v}
            return {"label": "the test data", "branches": [{"tool": "find_tests", "args": args}]}, f"Do you want the tests with {_what(u)}?"
        if merged["by"] in ("rag", "both") and psi:
            return {"label": f"the {name} test data", "branches": [{"tool": "find_tests", "args": {"psi": psi}}]}, f"Do you want the {name} test data?"
        if main == "scenario_coverage" and u.scenario:
            return {"label": "the most relevant investigations", "branches": [{"tool": "rank_investigations", "args": {"scenario": u.scenario}}]}, "Do you want the most relevant investigations for it?"
        return None, FOLLOW_UP.get(main, "") if main != "ask_sources" else ""

    async def _deliver(self, question: str, u: Understanding, merged: dict, note: str | None, log: dict, t0: float) -> dict:
        d, rg = merged["d"], merged["rag"]
        offer, offer_text = self._make_offer(u, merged)
        speak = ([note] if note else []) + merged["speak"]
        speak = speak[:3]
        sources = merged["sources"]
        for i, s in enumerate(sources, 1):
            sources[i - 1] = {**s, "n": i}
        pillar = None
        if merged["by"] == "rag":
            r = {**rg, "speak": speak, "speak_refs": rg.get("speak_refs", [])[: len(speak)]}
            await self.bridge.send(Cmd.ANSWER_SHOW, adapter.rag_to_answer(r, pillar, offer=self._offer()))
            model = adapter.rag_to_model(r, offer_text or FOLLOW_UP["search_text"])
        else:
            d2 = {**d, "speak": speak, "sources": sources}
            ans = adapter.to_answer(d2, offer=self._offer(), title=question)
            self.state.pillar = self.state.pillar or None
            model = adapter.to_model(d2)
            model["speak"] = speak if merged["by"] == "both" or merged["main"] == "oxygen_effect" or merged["main"] in NEW_SPOKEN or merged["main"] == "rank_investigations" else model["speak"]
            ans["shape"] = self._shape(speak, d, offer_text)
            if d.get("footnote"):
                ans["footnote"] = d["footnote"]
            ans["qtype"] = u.qtype
            if d.get("glossary"):
                ans["glossary"] = {"term": d["glossary"]["term"], "status": d["glossary"]["status"], "diagram": d["glossary"].get("diagram")}
            if offer_text:
                model["next_offer"] = offer_text
            elif merged["main"] in FOLLOW_UP:
                model["next_offer"] = FOLLOW_UP[merged["main"]]
            await self.bridge.send(Cmd.ANSWER_SHOW, ans)
        model["answered_by"] = merged["by"]
        model["reply_guidance"] = ("Say these speak lines in your own words, keep every number and name exactly, then say the " + ("sources are" if sources else "details are") + " on the screen "
                                   "and end with next_offer if present. Add nothing that is not in speak.")
        self.ctx.offer = offer
        self.ctx.rows = self._rows_of(merged, d)
        self.ctx.last_term = (d or {}).get("glossary", {}).get("term") or self.ctx.last_term
        if merged["main"] in ("find_tests", "list_materials") and d:
            ps = (d.get("appears_in") or d.get("found_in") or list((d.get("psis_by_family") or {}).values() and sorted({p for v in d["psis_by_family"].values() for p in v})) or [])[:3]
            self.ctx.options = [{"label": f"{_what(u)} in {flameo.psi_name(p)}", "entities": {"psi": [p]}, "n": 0} for p in ps]
        self.state.allow(*speak, model.get("next_offer"), *(str(x.get("page", "")) for x in sources), json.dumps(model.get("nearest") or {}))
        if self.state.conditions_note:
            n, self.state.conditions_note = self.state.conditions_note, ""
            model["conditions_set"] = n
            model["reply_guidance"] = f"First say once, in your own words: \"{n}\" Then " + model["reply_guidance"]
            self.state.allow(n)
        return self._finish(question, u, merged["by"], merged["main"], model, log, t0, merged.get("tools", []))

    @staticmethod
    def _shape(speak: list[str], d: dict, offer_text: str | None) -> dict:
        """The one answer shape (Round 15 item 3), every part for the screen: direct answer, evidence, meaning, coverage note, next step."""
        cut = lambda x: (x[:240] if isinstance(x, str) else x)      # noqa: E731
        return {k: cut(v) for k, v in {"direct": speak[0] if speak else None, "evidence": speak[1] if len(speak) > 1 else None, "meaning": d.get("meaning"),
                                       "coverage": d.get("coverage_note") or (d.get("gaps") or [None])[0], "next": offer_text or None}.items() if v}

    @staticmethod
    def _rows_of(merged: dict, d: dict | None) -> dict | None:
        """The list now on screen, for "they / the first one / compare them" (Round 15 item 5)."""
        d = d or {}
        main = merged["main"]
        if main == "rank_investigations" and d.get("ranking"):
            return {"kind": "investigations", "items": [{"psi": r["psi"], "label": r["name"]} for r in d["ranking"] if r.get("rank") and r.get("psi")][:5]} or None
        if main == "list_papers" and d.get("papers"):
            return {"kind": "papers", "items": [{"paper_id": x["paper_id"], "label": x["title"]} for x in d["papers"][:5]]}
        if main in ("nearest_tests", "find_tests", "interpret_conditions") and (d.get("table") or {}).get("rows"):
            items = [{"test": r["test"], "label": f"{r.get('investigation', '')} {r['test']}".strip()} for r in d["table"]["rows"] if r.get("test") is not None][:5]
            return {"kind": "tests", "items": items} if items else None
        if main == "get_test" and d.get("similar_tests"):
            return {"kind": "tests", "items": [{"test": r["test"], "label": f"test {r['test']}"} for r in d["similar_tests"][:5]]}
        return None

    def _finish(self, question: str, u: Understanding, by: str, main: str | None, model: dict, log: dict, t0: float, tools: list) -> dict:
        self.ctx.remember(u.entities(), main, {}, question)
        log["answered_by"], log["ms"] = by, round((time.monotonic() - t0) * 1000)
        log["why"] = {"tool": "the intent maps to a direct tool with data", "rag": "no direct tool had data; the scoped RAG answered", "both": "the tool gave the numbers and the RAG the cited explanation",
                      "clarify": "nothing found even broadened; the probe found data in several places", "not_found": "tools, RAG, broadened runs and the probe were all empty", "background": "the glossary and the RAG had no definition: one labelled sentence of general background (D15-1)", "action": "a navigation request: the screen moved"}[by]
        lid = qlog.log(question, "answer", {"main": main, "tools": tools}, by != "not_found", source=self.state.last_source, router=log)
        if lid:
            self.state.log_ids.append(lid)
        self.state.turn_tools += 1
        model["router"] = {"answered_by": by, "main": main}
        return model
