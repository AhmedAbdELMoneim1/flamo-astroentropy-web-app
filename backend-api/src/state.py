"""Server-side mirror of what the astronaut currently sees on screen."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from src.router.session import Session
from src.categories import (
    DEFAULT_SCENARIO,
    SCENARIOS,
    default_conditions,
    View,
    find_view,
    normalize_conditions,
)


@dataclass
class DashboardState:
    pillar: str | None = None
    view: str | None = None
    focus: str | None = None
    previous: dict | None = None  # {"pillar", "view"} shown before the current one, for "go back"
    scenario: str | None = DEFAULT_SCENARIO  # None = custom conditions (no preset)
    inputs: dict = field(default_factory=default_conditions)
    mission: dict = field(default_factory=dict)
    emergency: bool = False
    declared_at: float = 0.0     # monotonic time of the last emergency banner sent
    notes: list[str] = field(default_factory=list)
    visited: set[str] = field(default_factory=set)  # categories (pillar ids) already introduced this session
    nudged: set[str] = field(default_factory=set)  # categories that already got their one silence nudge
    last_transcript: str = ""  # what the astronaut said in the CURRENT turn (final fragments joined; only for logs/questions.jsonl)
    turn_parts: list[str] = field(default_factory=list)
    turn_interim: str = ""
    turn_closed: bool = True  # the previous turn is over: the next fragment starts a new one
    log_ids: list[str] = field(default_factory=list)  # question-log lines of this turn, filled in if the transcript arrives late
    last_source: str = "voice"  # where the last question came from: voice | typed
    turn_tools: int = 0  # tool calls this turn (a turn without any is logged with tool null)
    turn_logged_null: bool = False
    ctx: Session = field(default_factory=Session)  # what the conversation is about (Round 13 §13.5): psi, material, scenario, the offer, a pending clarify
    conditions_note: str = ""  # "I set the oxygen to 34 percent; ...": the voice says it once, with the next answer
    allowed_text: list = field(default_factory=list)  # what the voice may take numbers from: the last tool results and notification facts
    clarified: bool = False  # ask_sources already asked its one clarifying question; reset when an answer is given
    synced: bool = False  # a state.sync arrived (the frontend and the agent have met)
    synced_event: asyncio.Event = field(default_factory=asyncio.Event)
    scene_announced: bool = False  # the opening scene (from the URL) was already said once

    def heard(self, text: str, final: bool) -> list[str]:
        """A speech-to-text fragment. Final fragments of one turn are joined (the recogniser splits one question in pieces);
        a fragment after the agent started answering opens a new turn. Returns the log lines whose transcript changed."""
        text = (text or "").strip()
        if not text:
            return []
        if self.turn_closed:
            self.turn_parts, self.turn_interim, self.turn_closed = [], "", False  # log_ids kept: a tool call may precede the first words
            self.turn_tools, self.turn_logged_null, self.last_source = 0, False, "voice"
        if final:
            self.turn_parts.append(text)
            self.turn_interim = ""
        else:
            self.turn_interim = text
        self.last_transcript = " ".join(self.turn_parts + ([self.turn_interim] if self.turn_interim else []))
        return list(self.log_ids)

    def typed(self, text: str) -> None:
        """A typed or tapped question is its own turn."""
        self.turn_parts, self.turn_interim, self.log_ids, self.turn_closed = [text], "", [], False
        self.turn_logged_null = False
        self.last_transcript = text

    def close_turn(self) -> None:
        self.turn_closed = True
        self.log_ids = []  # lines of the finished turn are no longer filled in

    def allow(self, *texts) -> None:
        """Text the voice may quote numbers from (kept short: the latest few results)."""
        self.allowed_text = (self.allowed_text + [str(t) for t in texts if t])[-12:]

    def first_visit(self, pillar_id: str) -> bool:
        """True only the first time a category opens in this session (call it once per open)."""
        first = pillar_id not in self.visited
        self.visited.add(pillar_id)
        return first

    def snapshot(self) -> dict:
        scenario = SCENARIOS.get(self.scenario or "")
        return {
            "pillar": self.pillar,
            "view": self.view,
            "focus": self.focus,
            "previous_view": self.previous,
            "scenario": self.scenario,
            "coverage": scenario.coverage if scenario else None,
            "coverage_note": scenario.coverage_note if scenario else None,
            "conditions": self.inputs,
            "emergency": self.emergency,
            "notes_count": len(self.notes),
        }

    def open_view(self, view: View, focus: str | None = None) -> None:
        """Record that `view` is now on screen (remembers the one it replaces)."""
        if self.view and self.view != view.id:
            self.previous = {"pillar": self.pillar, "view": self.view}
        self.pillar, self.view, self.focus = view.pillar, view.id, focus

    def update_conditions(self, scenario: str | None = None, inputs: dict | None = None) -> dict:
        """Apply a scenario preset and/or explicit values. Returns what changed (clamped).

        One rule keeps screen and agent honest: a scenario is only kept while the
        user/agent says so. Passing a scenario selects it (explicit values then
        override its preset); passing only values makes the conditions "custom".
        Callers validate `scenario` first (unknown ids are ignored here).
        """
        updates: dict = {}
        if scenario in SCENARIOS:
            updates.update(SCENARIOS[scenario].inputs)
        updates.update(normalize_conditions(inputs or {}))
        if not updates:
            return {}
        self.inputs.update(updates)
        self.scenario = scenario if scenario in SCENARIOS else None
        return updates

    def apply_sync(self, payload: dict) -> None:
        """Apply a state.sync payload from the frontend. Unknown ids are dropped."""
        if "view" in payload or "pillar" in payload:
            v = find_view(payload.get("pillar"), payload.get("view"))
            self.pillar, self.view = (v.pillar, v.id) if v else (None, None)
        if "focus" in payload:
            self.focus = payload["focus"]
        if "scenario" in payload:
            self.scenario = payload["scenario"] if payload["scenario"] in SCENARIOS else None
        if isinstance(payload.get("inputs"), dict):
            self.inputs.update(payload["inputs"])
        if isinstance(payload.get("mission"), dict):
            self.mission = payload["mission"]
