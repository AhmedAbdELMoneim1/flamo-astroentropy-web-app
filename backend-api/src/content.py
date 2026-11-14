"""Real content for the screen and the voice, from flameo_tools (no LiveKit import: unit-testable).

    build_view(state)            -> view.open payload (overview) + the facts the voice may use
    scene_arrival(bridge, state) -> scenario_coverage + overall ranking for a journey scene, pushed to the screen
    Runner.intent(name, **args)  -> one intent tool: run, push answer.show, log the question, return the small model payload

Every number on the screen or in the model payload comes from a flameo_tools answer; src/adapter.py only selects.
"""

from __future__ import annotations

import asyncio
import json
import logging

from src import adapter, flameo, qlog, rag
from src.bridge import Cmd, UiBridge
from src.categories import PILLARS, SCENARIOS, UI_TEXT, VIEWS, find_view
from src.state import DashboardState

logger = logging.getLogger("content")

# Phase 7: one fixed follow-up per tool, always a question the data can answer (never advice).
FOLLOW_UP = {
    "scenario_coverage": "Do you want the most relevant investigations for it?",
    "rank_investigations": "Do you want details on the first one?",
    "get_investigation": "Do you want to compare it with another investigation?",
    "compare": "Do you want the details of one of them?",
    "rank_materials": "Do you want to see how oxygen changes flame spread?",
    "get_findings": "Do you want the investigations behind these findings?",
    "rank_agents": "Do you want the open questions for suppression?",
    "gaps": "Do you want the experiments that come closest?",
    "search_text": "Do you want the data behind it?",
    "oxygen_effect": "Do you want to see the oxygen against pressure chart?",
}

# Phases 2 to 4: which speak lines of scenario_coverage the voice says, and the fixed sentence that ends the turn.
SCENE_LINES = {"iss": (0, 1), "moon_base": (0, 1), "spacesuit": (0, 2)}
SCENE_END = {
    "iss": "Pick a topic, or ask me something.",
    "moon_base": "BRE tested these atmospheres; ask me what it found.",
    "spacesuit": "The chart shows how far the suit is from every tested condition.",
}

# The all-conditions overview is used when the conditions are custom, and always for Detection (decisions 4.5).
ALWAYS_ALL_TESTS = {"smoke"}


async def fcall(name: str, **kwargs) -> dict:
    """flameo calls take milliseconds to a few tenths of a second; run them off the event loop."""
    return await asyncio.to_thread(flameo.call, name, **kwargs)


def chips_for(pillar: str | None) -> list[str]:
    p = PILLARS.get(pillar or "")
    return [c.text for c in p.suggestions if not c.pending_review] if p else []


def coverage_of(scenario: str | None) -> tuple[str | None, dict | None]:
    s = SCENARIOS.get(scenario or "")
    return (s.coverage, s.coverage_note) if s else (None, None)


async def build_view(state: DashboardState) -> dict:
    """Overview of the category on screen: show_view + rank_investigations, adapted. Always the same keys."""
    v = find_view(state.pillar, state.view)
    if v is None:
        return {"status": "no_content", "reason": "unknown pillar or view", "payload": None, "speak": []}
    custom = state.scenario is None
    all_tests = custom or v.id in ALWAYS_ALL_TESTS
    scenario_arg = None if all_tests else state.scenario
    d, rk = await asyncio.gather(
        fcall("show_view", view=v.id, scenario=scenario_arg),
        fcall("rank_investigations", pillar=v.pillar, scenario=state.scenario),
    )
    dash = adapter.to_dashboard(d, custom=custom, labels=flameo.labels())
    cov, note = coverage_of(state.scenario)
    dash["pillar"] = v.pillar
    if v.id in ALWAYS_ALL_TESTS and not custom:
        dash["note"] = UI_TEXT["detection_note"]
    payload = {
        "pillar": v.pillar,
        "view": v.id,
        "focus": state.focus,
        "scenario": state.scenario,
        "coverage": cov,
        "coverage_note": note,
        "headline": dash["headline"],
        "key_points": dash["key_points"],
        "dashboard": dash,
        "ranking": adapter.to_ranking(rk),
        "suggestions": chips_for(v.pillar),
    }
    return {"status": "ok", "reason": "", "payload": payload, "speak": list(d.get("speak", [])), "view": v, "coverage": cov}


async def push_view(bridge: UiBridge, state: DashboardState) -> dict:
    """Send view.open for whatever the state says is on screen; return what was built (shared by tools and event handlers)."""
    content = await build_view(state)
    if content["payload"] is not None:
        await bridge.send(Cmd.VIEW_OPEN, content["payload"])
    return content


async def scene_arrival(bridge: UiBridge, state: DashboardState, scenario: str) -> dict:
    """Phases 2 to 4: the scenario's coverage answer and the overall ranking are shown; the voice gets their speak lines."""
    cov, rk = await asyncio.gather(fcall("scenario_coverage", scenario=scenario), fcall("rank_investigations", scenario=scenario))
    ans = adapter.to_answer(cov)
    ans["ranking"] = adapter.to_ranking(rk)  # one answer: the scenario's coverage with the overall ranking beside it
    ans = adapter.fit(ans, "scene answer")
    await bridge.send(Cmd.ANSWER_SHOW, ans)
    lines = [cov["speak"][i] for i in SCENE_LINES.get(scenario, (0, 1)) if i < len(cov["speak"])]
    return {
        "speak": lines,
        "end_with": SCENE_END.get(scenario, "Pick a topic, or ask me something."),
        "level": cov.get("level"),
        "note": cov.get("level_oxygen_rich_flames"),
        "top": adapter.to_model(rk).get("top", []),
    }


def guard_rag(r: dict) -> dict:
    """Last line of defence, after the checker: a spoken line with safe / unsafe / danger-threshold wording is removed, never softened."""
    from src.paper_rag.composer import FORBIDDEN
    keep = [i for i, t in enumerate(r.get("speak", [])) if not any(rx.search(t) for rx, _ in FORBIDDEN)]
    if len(keep) == len(r.get("speak", [])):
        return r
    refs = r.get("speak_refs", [])
    r = {**r, "speak": [r["speak"][i] for i in keep], "speak_refs": [refs[i] for i in keep if i < len(refs)]}
    if not r["speak"] and r["status"] == "ok":
        r.update(status="not_found", outcome="not_found", sources=[])
    return r


class Runner:
    """Runs one flameo intent tool for the voice agent."""

    def __init__(self, bridge: UiBridge, state: DashboardState) -> None:
        self.bridge, self.state = bridge, state

    async def intent(self, name: str, **args) -> dict:
        args = {k: v for k, v in args.items() if v not in (None, "")}
        if name == "oxygen_effect":                      # a question that names an investigation is a question about THAT investigation (Round 10 §10.1 item 2)
            ex = rag.extractor()
            named = ex.psis(self.state.last_transcript or "") if ex else []
            if named:
                m = await self.ask_sources(self.state.last_transcript, **{k: v for k, v in ex.extract(self.state.last_transcript).items()})
                m["rerouted"] = f"oxygen_effect -> ask_sources (the question names {', '.join(named)})"
                return m
        try:
            d = await fcall(name, **args)
        except Exception as e:  # a bad argument must not break the voice turn
            logger.exception("flameo %s failed", name)
            self._log(name, args, False)
            return {"status": "error", "reason": f"{type(e).__name__}: {e}"}
        ans = adapter.to_answer(d, offer=self._offer(), title=self.state.last_transcript or None)
        await self.bridge.send(Cmd.ANSWER_SHOW, ans)
        self._follow_pillar(ans.get("pillar"))
        model = adapter.to_model(d)
        self._log(name, args, model["matched"])
        if model["matched"] and name in FOLLOW_UP:
            model["next_offer"] = FOLLOW_UP[name]
        self.state.allow(*model.get("speak", []), model.get("first_gap"), model.get("next_offer"), *(str(x.get("page", "")) for x in model.get("sources", [])), json.dumps(model.get("nearest") or {}))
        if not model["matched"] or (name == "gaps") or d.get("level") == "None":
            model["not_covered"] = True
        model["reply_guidance"] = (
            "Say these speak lines in your own words, keep every number and name exactly, then say the " + ("sources are" if model.get("sources") else "details are") + " on the screen "
            "and end with next_offer if present. Add nothing that is not in speak."
        )
        self._conditions_note(model)
        return model

    def _conditions_note(self, model: dict) -> None:
        """The sliders were just set from the question: say so once, first (Round 11 §11.1)."""
        n = self.state.conditions_note
        if n:
            self.state.conditions_note = ""
            model["conditions_set"] = n
            model["reply_guidance"] = f"First say once, in your own words: \"{n}\" Then " + model.get("reply_guidance", "")
            self.state.allow(n)

    async def _without_rag(self, question: str, params: dict, why: str) -> dict:
        """The old text search answers. Said loudly: a warning in the log and one line in logs/retrieval.jsonl with the path, so a demo without the RAG cannot go unnoticed."""
        import time
        import uuid

        from src.paper_rag import retrieval_log
        logger.warning("ask_sources answered by search_text, NOT the RAG (%s): %r", why, question[:80])
        t0 = time.monotonic()
        m = await self.intent("search_text", query=question, psi=params.get("psi"))
        retrieval_log.write({"ts": round(time.time(), 3), "request_id": uuid.uuid4().hex[:8], "question": question, "params": params, "scope": {}, "vector": [], "keyword": [], "reranked": [],
                             "composer": {"provider": "serving.db fts", "sentences": [{"text": t, "chunks": [], "kept": True, "reason": ""} for t in m.get("speak", [])], "fallback_reason": why},
                             "outcome": "search_text", "path": f"search_text, NOT the RAG ({why})", "reason": why, "latency_ms": {"total": round((time.monotonic() - t0) * 1000)}, "keys": {}})
        m["rag"] = "off"                                                      # visible to the model payload too
        return m

    async def ask_sources(self, question: str, **params) -> dict:
        """The scoped RAG (src/paper_rag/ask.py): sources[] + sentences the checker approved, one clarifying question at most, serving.db text search when the RAG is not available."""
        params = {k: v for k, v in params.items() if v not in (None, "")}
        if not rag.available():
            return await self._without_rag(question, params, f"RAG off: {rag.off_reason()}")
        try:
            r = await rag.get().ask(question, **params)
        except Exception as e:  # noqa: BLE001  (setup problems: Postgres down, keys missing): never break the voice turn, never hide it
            logger.warning("ask_sources unavailable (%s): search_text", type(e).__name__)
            return await self._without_rag(question, params, f"RAG error: {type(e).__name__}: {e}"[:160])
        if r["status"] == "clarify":
            if self.state.clarified:                      # one clarifying question per question: a second time it is "not covered"
                r = {**r, "status": "not_found", "speak": [], "clarify": None, "outcome": "not_found"}
            else:
                self.state.clarified = True
        elif r["status"] == "ok":
            self.state.clarified = False
        r = guard_rag(r)
        pillar = params.get("pillar") if params.get("pillar") in PILLARS else None
        await self.bridge.send(Cmd.ANSWER_SHOW, adapter.rag_to_answer(r, pillar, offer=self._offer()))
        self._log("ask_sources", {"question": question, **params}, r["status"] in ("ok", "fallback"))
        self.state.allow(*r.get("speak", []), *(str(x.get("page", "")) for x in r.get("sources", [])))
        m = adapter.rag_to_model(r, FOLLOW_UP["search_text"])
        self._conditions_note(m)
        return m

    def _offer(self) -> dict | None:
        """The "open question" card offers the category on the screen: its name and its Ask me chips (Round 10 §10.1 item 6)."""
        p = PILLARS.get(self.state.pillar or "")
        return {"category": p.label, "chips": chips_for(p.id)[:2]} if p else None

    def _log(self, name: str, args: dict, matched: bool) -> None:
        lid = qlog.log(self.state.last_transcript, name, args, matched, source=self.state.last_source)
        if lid:  # words of this turn may still arrive (or grow): agent.py fills the line in until the answer starts
            self.state.log_ids.append(lid)

    def _follow_pillar(self, pillar: str | None) -> None:
        """The screen switches to the answer's category (D3-2); keep the server mirror in step."""
        if pillar and pillar != self.state.pillar and pillar in PILLARS:
            self.state.pillar = pillar
            self.state.view = PILLARS[pillar].overview_view
            self.state.focus = None


def view_label(view_id: str) -> str:
    return VIEWS[view_id].label if view_id in VIEWS else view_id
