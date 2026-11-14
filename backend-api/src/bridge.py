"""
Front <-> back communication contract (LiveKit reliable data packets).

This is the SPEC for the frontend. frontend/src/protocol.js mirrors it exactly.

Envelope -- every packet, in BOTH directions, is the same JSON:

    {"v": 1, "type": "<namespace.action>", "payload": {...}, "ts": 1730000000000}

Two topics, one per direction:

    ui.command   agent    -> frontend   "make the screen do X"
    ui.event     frontend -> agent      "the user did X on the screen"

The message TYPES are generic. Domain knowledge (pillars, views, scenarios) lives
only inside payloads, whose ids come from GET /api/categories.

Commands (agent -> frontend)
    view.open        Show a category overview. The frontend replaces what is on screen (overview state).
                     {pillar, view, focus, scenario, coverage, coverage_note, headline, key_points, dashboard,
                      ranking, suggestions}
                       pillar      str          pillar id, e.g. "detection"
                       view        str          view id, e.g. "smoke"
                       focus       str | null   optional sub-topic chip, e.g. "toxic gases"
                       scenario    str | null   scenario id, null = custom conditions
                       coverage    str | null   "High" | "Medium" | "Low" | "None"; null = custom conditions.
                                                "None" = a named scenario with no test (the spacesuit atmosphere)
                       coverage_note obj | null {label, level}: spacesuit only, the oxygen-rich burner-stream flames
                       ranking     obj | null   "Most relevant investigations" panel (rank_investigations, adapted):
                                                {pillar, scenario, rows[{rank|null, group, psi, name, tier, pillars, tests,
                                                tests_label, findings}], tier_label, divider, note, footer?}
                       suggestions str[]        "Ask me" chips (tap -> question.asked)
                       headline    str          short headline to show
                       key_points  str[]        short talking points to show (may be empty
                                                when there is no content for this combination)
                       dashboard   object      Dashboard (kpis, charts, table, gaps, source); see
                                                CONTRACT.md. headline/key_points equal its fields.
                     e.g. {"pillar": "flammability", "view": "flame_spread", "focus": null,
                           "scenario": "moon_base", "coverage": "Medium",
                           "headline": "...", "key_points": ["...", "..."], "dashboard": {...}}

    conditions.set   Update the input conditions (sliders / selects).
                     {scenario, inputs}
                       scenario    str | null   scenario these conditions now belong to,
                                                null = custom (values no longer a preset)
                       inputs      object       ONLY the values that changed, already clamped;
                                                merge into what is on screen
                     e.g. {"scenario": "spacesuit",
                           "inputs": {"oxygen_pct": 100, "pressure_psi": 4.3}}

    alert.set        Turn emergency mode on or off.
                     {level, title, steps, location?, lang?, footer?}   location cabin | suit; lang en | ar (the banner follows the chat language)
                       level       str          "emergency" | "clear"
                       title       str          short description ("" when clearing)
                       steps       str[]        first-response steps ([] when clearing)
                     e.g. {"level": "emergency", "title": "Smoke from rack", "steps": ["..."]}

    answer.show      Show the answer to a data question on top of the view (state unchanged).
                     payload = Answer {request_id, metric, question, speak, kpis, charts, table,
                     gaps, cards, source, pillar, ranking?}; shape in CONTRACT.md. `pillar` (or null) is the category
                     the answer belongs to: the frontend switches to it and opens the answer state there.
                     A chart may carry `ref` (a path under /api) instead of series.

    interaction.ack  The agent registered what the user just did. Show it as a short status line.
                     {kind, text}
                     e.g. {"kind": "view_opened", "text": "Opened Detection > Smoke"}

    note.add         Append a line to the mission log.
                     {text}
                     e.g. {"text": "Checked the extinguisher"}

Events (frontend -> agent)
    state.sync           Silent. Sent when the agent joins, so it can catch up, and when the
                         user returns to the entry view (pillar and view are then null).
                         {pillar, view, focus, scenario, inputs, mission}
                           all fields as above; inputs = the full set; mission = object | null
    mission.loaded       Silent. The mission details were loaded on screen.
                         {mission}
                           mission     object       free-form mission details
    view.selected        The user tapped a pillar/view/chip. The agent speaks, and
                         answers with a view.open carrying the content to show.
                         {pillar, view, focus, scenario, source}
                           view may be omitted to open the pillar's first view
                           source      str          where it came from, e.g. "user_tap"
                     e.g. {"pillar": "detection", "view": "smoke", "focus": null,
                           "scenario": "iss", "source": "user_tap"}
    question.asked       The user tapped an "Ask me" chip. The agent answers it as if it had been spoken.
                         {text}
    conditions.changed   The user changed an input or picked a scenario preset.
                         The agent speaks.
                         {scenario, inputs}
                           scenario    str          OPTIONAL. A preset id: the agent applies the
                                                    preset values. Omit it for a manual edit,
                                                    which makes the conditions "custom".
                           inputs      object       OPTIONAL. Changed values only; clamped by the
                                                    agent (explicit values win over the preset)
                     e.g. {"inputs": {"oxygen_pct": 35}}   or   {"scenario": "spacesuit"}

Adding a new interaction = add one constant here, one handler on each side.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Awaitable, Callable

from livekit import rtc

logger = logging.getLogger("bridge")

PROTOCOL_VERSION = 1

TOPIC_COMMAND = "ui.command"  # agent -> frontend
TOPIC_EVENT = "ui.event"  # frontend -> agent


class Cmd:
    VIEW_OPEN = "view.open"
    CONDITIONS_SET = "conditions.set"
    ALERT_SET = "alert.set"
    NOTE_ADD = "note.add"
    ANSWER_SHOW = "answer.show"
    INTERACTION_ACK = "interaction.ack"


class Evt:
    STATE_SYNC = "state.sync"
    MISSION_LOADED = "mission.loaded"
    VIEW_SELECTED = "view.selected"
    CONDITIONS_CHANGED = "conditions.changed"
    QUESTION_ASKED = "question.asked"
    EMERGENCY_CLEARED = "emergency.cleared"      # the banner's × button


EventHandler = Callable[[dict], Awaitable[None]]


class UiBridge:
    """Thin wrapper around the room: send commands, dispatch incoming events."""

    def __init__(self, room: rtc.Room) -> None:
        self._room = room
        self._handlers: dict[str, EventHandler] = {}
        self._tasks: set[asyncio.Task] = set()

    # ── agent -> frontend ───────────────────────────────────────────────────
    async def send(
        self,
        cmd_type: str,
        payload: dict,
        dest_identity: str | None = None,
    ) -> None:
        envelope = {
            "v": PROTOCOL_VERSION,
            "type": cmd_type,
            "payload": payload,
            "ts": int(time.time() * 1000),
        }
        kwargs: dict = {"reliable": True, "topic": TOPIC_COMMAND}
        if dest_identity:
            kwargs["destination_identities"] = [dest_identity]
        await self._room.local_participant.publish_data(
            json.dumps(envelope).encode("utf-8"), **kwargs
        )
        logger.info("-> ui.command %s", cmd_type)

    #  frontend -> agent 
    def on(self, event_type: str) -> Callable[[EventHandler], EventHandler]:
        """Decorator: register an async handler(payload) for an event type."""

        def register(fn: EventHandler) -> EventHandler:
            self._handlers[event_type] = fn
            return fn

        return register

    def start(self) -> None:
        """Begin listening. Call once, before session.start()."""
        self._room.on("data_received", self._on_data)

    def _on_data(self, data: rtc.DataPacket) -> None:
        if data.topic != TOPIC_EVENT:
            return
        try:
            envelope = json.loads(data.data.decode("utf-8"))
            event_type = envelope["type"]
            payload = envelope.get("payload") or {}
        except (json.JSONDecodeError, KeyError, UnicodeDecodeError):
            logger.warning("Bad packet on %s", TOPIC_EVENT)
            return

        handler = self._handlers.get(event_type)
        if handler is None:
            logger.debug("No handler for event %s", event_type)
            return

        logger.info("<- ui.event %s", event_type)
        task = asyncio.create_task(self._run(handler, event_type, payload))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    @staticmethod
    async def _run(handler: EventHandler, event_type: str, payload: dict) -> None:
        try:
            await handler(payload)
        except Exception:  # never let one bad event kill the session
            logger.exception("Handler for %s failed", event_type)
