"""Handlers for events sent by the frontend (topic ui.event).

The system prompt (prompts.py, "Phases") says how to react to each [screen] message.
Each handler updates state, pushes the screen, then only DESCRIBES what happened as an
``Interaction``; src/notify.py delivers it to the dashboard and to the agent (no forced reply).

Phases (decisions Round 3 section 3.3): 2-4 scene arrival, 5-6 category entry (first / later visit),
9 custom conditions once settled, 11 silence nudge (notify.Nudger), "Ask me" chips = question.asked.
"""

from __future__ import annotations

import asyncio
import logging

from src import qlog
from src import alerts
from src.bridge import Evt, UiBridge
from src.categories import PILLARS, SCENARIOS, find_view, normalize_conditions
from src.content import chips_for, push_view, scene_arrival
from src.notify import Interaction, Notifier
from src.state import DashboardState

logger = logging.getLogger("events")

# Custom conditions: stay silent while the astronaut slides, speak once when the values have settled.
SETTLE_S = 1.5
# Scene buttons: the screen follows at once, the voice speaks only for the scene that stayed on screen this long
# (the live test logged 12 scene arrivals in 30 seconds while the astronaut clicked through the scenes).
SCENE_SETTLE_S = 1.5
CUSTOM_LINE = (
    "These are custom conditions. Data is rated only for the ISS, Moon base and suit; the chart shows where your point "
    "sits among the tested conditions."
)


def register_event_handlers(bridge: UiBridge, state: DashboardState, notifier: Notifier, settle_s: float = SETTLE_S, scene_settle_s: float = SCENE_SETTLE_S) -> None:
    settle: dict = {"task": None}

    # ── handlers ─────────────────────────────────────────────────────────────
    @bridge.on(Evt.STATE_SYNC)
    async def _sync(payload: dict) -> None:
        # Silent: the agent joined late (or reconnected) and just needs to catch up.
        if "inputs" in payload:
            payload = {**payload, "inputs": normalize_conditions(payload["inputs"] or {})}
        state.apply_sync(payload)
        state.synced = True
        state.synced_event.set()

    @bridge.on(Evt.MISSION_LOADED)
    async def _mission(payload: dict) -> None:
        state.apply_sync({"mission": payload.get("mission")})

    @bridge.on(Evt.QUESTION_ASKED)
    async def _question(payload: dict) -> None:
        text = str(payload.get("text") or "").strip()[:300]
        if not text:
            return
        state.typed(text)
        await notifier.ask(text)

    @bridge.on(Evt.EMERGENCY_CLEARED)
    async def _alert_dismissed(payload: dict) -> None:
        await alerts.clear(bridge, state, "dismissed on the screen")

    @bridge.on(Evt.VIEW_SELECTED)
    async def _view(payload: dict) -> None:
        v = find_view(payload.get("pillar"), payload.get("view"))
        if v is None:
            return
        auto = payload.get("source") == "auto"  # the screen opened its own default category: no voice, not counted as a visit
        first_visit = False if auto else state.first_visit(v.pillar)
        state.open_view(v, payload.get("focus"))
        if payload.get("scenario") in SCENARIOS:
            state.update_conditions(scenario=payload["scenario"])

        content = await push_view(bridge, state)  # the frontend has no content of its own: answer the tap with view.open

        facts = {
            "phase": "category_entry" if not auto else "silent",
            "category": PILLARS[v.pillar].label,
            "first_visit": "yes" if first_visit else "no",
            "scenario": state.scenario or "custom",
            "coverage": content.get("coverage") or "n/a",
        }
        if first_visit:
            facts["intro"] = PILLARS[v.pillar].intro
        if state.focus:
            facts["focus"] = state.focus
        if content["status"] == "ok":
            facts["overview_speak"] = (content["speak"] or [""])[0]
        chips = chips_for(v.pillar)
        if first_visit and chips:
            facts["ask_me"] = chips[0]
        else:
            facts["ask_anything_about"] = PILLARS[v.pillar].label
        label = f"{PILLARS[v.pillar].label} > {v.label}" + (f" > {state.focus}" if state.focus else "")
        await notifier.notify(
            Interaction("focus_selected" if state.focus else "view_opened", f"Opened {label}", facts, speak=not auto, ack=not auto)
        )
        if first_visit and notifier.nudger:
            notifier.nudger.arm(v.pillar, chips[1] if len(chips) > 1 else (chips[0] if chips else None))

    async def _settled() -> None:
        try:
            await asyncio.sleep(settle_s)
        except asyncio.CancelledError:
            return
        if state.scenario is not None:  # a preset was tapped meanwhile
            return
        await notifier.notify(
            Interaction(
                "conditions_changed",
                "Conditions changed to custom values",
                {"phase": "custom_conditions", "scenario": "custom", "coverage": "n/a", "say": CUSTOM_LINE},
            )
        )

    async def _scene_settled(sid: str, scene: dict) -> None:
        try:
            await asyncio.sleep(scene_settle_s)
        except asyncio.CancelledError:
            return
        if state.scenario != sid:
            return
        qlog.log(None, "scene_arrival", {"scenario": sid}, True)
        await notifier.notify(
            Interaction(
                "scene_arrival",
                f"Scene: {SCENARIOS[sid].label}",
                {
                    "phase": "scene",
                    "scenario": sid,
                    "coverage": None if SCENARIOS[sid].coverage_note else SCENARIOS[sid].coverage,
                    "scene_speak": " ".join(scene["speak"]),
                    "end_with": scene["end_with"],
                },
            )
        )

    @bridge.on(Evt.CONDITIONS_CHANGED)
    async def _conditions(payload: dict) -> None:
        previous_scenario = state.scenario
        updates = state.update_conditions(payload.get("scenario"), payload.get("inputs"))
        if not updates:
            return
        if settle["task"] and not settle["task"].done():
            settle["task"].cancel()
        # View content depends on the scenario: if it changed, the screen must follow.
        if state.view and state.scenario != previous_scenario:
            await push_view(bridge, state)

        if payload.get("scenario") in SCENARIOS:
            # Scene arrival (phases 2 to 4): the screen gets coverage + overall ranking at once; the voice waits until the scene stays.
            sid = state.scenario
            scene = await scene_arrival(bridge, state, sid)
            settle["task"] = asyncio.create_task(_scene_settled(sid, scene))
            return

        # Manual edit (Round 12 item 6): the agent stays silent and only keeps the conditions for the next question. The screen refreshes itself (GET /api/nearest);
        # no [screen] event, no model turn, no free Gemini sentence.
        qlog.log(None, "conditions_changed", {k: v for k, v in updates.items()}, True, source="screen")
