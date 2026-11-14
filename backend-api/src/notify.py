"""One generic way to tell the agent (and the dashboard) that the user did something on screen.

Modes (env UI_EVENT_REPLY)
    prompt   (default) user-turn notification; the model replies by itself, silent fallback.
    context  never speak about taps; only keep the agent informed.
    force    the old behaviour: generate_reply(instructions=...).
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field

from livekit.agents import AgentSession

from src.bridge import Cmd, UiBridge

logger = logging.getLogger("notify")

MODES = ("prompt", "context", "force")


@dataclass(frozen=True)
class Interaction:
    """Something that happened on the screen, described once and used by both channels."""

    kind: str  # machine name: "view_opened", "conditions_changed", "session_started", ...
    text: str  # short plain sentence, shown on the dashboard AND given to the model
    facts: dict = field(default_factory=dict)  # small grounded details the model may rely on
    speak: bool = True  # False = tell the agent silently (tiny changes)
    ack: bool = True  # False = nothing to show on the dashboard (e.g. session_started)

    def prompt(self) -> str:
        facts = " | ".join(f"{k}: {v}" for k, v in self.facts.items() if v not in (None, ""))
        return f"[screen] {self.kind}: {self.text}" + (f" | {facts}" if facts else "")


NUDGE_AFTER_S = 20.0
NUDGE_TEXT = "You can tap a question, or ask me something like: {chip}"


class Nudger:
    """Phase 11: once per category, 20 s after a first-visit entry with no speech, tap or other agent turn, say one nudge.

    Armed when a first-visit entry is notified; the timer starts only after the agent has finished speaking that entry
    (speaking -> listening). Any user speech, tap or new agent turn cancels it.
    """

    def __init__(self, notifier: "Notifier", state, delay: float = NUDGE_AFTER_S) -> None:
        self.notifier, self.state, self.delay = notifier, state, delay
        self.pending: tuple[str, str] | None = None  # (pillar id, chip text)
        self.saw_speaking = False
        self.task: asyncio.Task | None = None

    def arm(self, pillar: str, chip: str | None) -> None:
        self.cancel()
        if chip and pillar not in self.state.nudged:
            self.pending, self.saw_speaking = (pillar, chip), False

    def cancel(self) -> None:
        self.pending, self.saw_speaking = None, False
        if self.task and not self.task.done():
            self.task.cancel()
        self.task = None

    def on_agent_state(self, new_state: str) -> None:
        if not self.pending:
            return
        if new_state == "speaking":
            self.saw_speaking = True
        elif new_state == "listening" and self.saw_speaking and self.task is None:
            self.task = asyncio.create_task(self._fire(self.pending))

    async def _fire(self, pending: tuple[str, str]) -> None:
        try:
            await asyncio.sleep(self.delay)
        except asyncio.CancelledError:
            return
        pillar, chip = pending
        if self.pending != pending or pillar in self.state.nudged:
            return
        self.state.nudged.add(pillar)
        self.pending, self.task = None, None
        await self.notifier.notify(
            Interaction("silence_nudge", "No input for a while", {"phase": "silence", "say": NUDGE_TEXT.format(chip=chip)}, ack=False),
            _from_nudge=True,
        )


class Notifier:
    def __init__(self, session: AgentSession, bridge: UiBridge, mode: str | None = None) -> None:
        mode = (mode or os.getenv("UI_EVENT_REPLY", "prompt")).strip().lower()
        if mode not in MODES:
            logger.warning("unknown UI_EVENT_REPLY=%r, using 'prompt'", mode)
            mode = "prompt"
        self.session, self.bridge, self.mode = session, bridge, mode
        self.nudger: Nudger | None = None  # set by agent.py

    async def ask(self, text: str) -> None:
        """A tapped "Ask me" chip: deliver it as a normal user turn (not a [screen] note)."""
        if self.nudger:
            self.nudger.cancel()
        try:
            self.session.interrupt()
            self.session.generate_reply(user_input=text)
        except Exception:
            logger.warning("could not deliver the tapped question", exc_info=True)

    async def notify(self, i: Interaction, _from_nudge: bool = False) -> None:
        """Tell the dashboard and the agent about `i`. Never raises."""
        if self.nudger and not _from_nudge:
            self.nudger.cancel()
        st = getattr(self, "state", None)
        if st is not None:
            st.allow(*[str(v) for v in (i.facts or {}).values() if isinstance(v, (str, int, float))])   # the voice may quote what the notification told it
        if i.ack:
            try:
                await self.bridge.send(Cmd.INTERACTION_ACK, {"kind": i.kind, "text": i.text})
            except Exception:
                logger.warning("could not send interaction.ack", exc_info=True)

        if not i.speak or self.mode == "context":
            await self._note(i)
            return
        try:
            self.session.interrupt()  # the newest interaction wins
            if self.mode == "force":
                self.session.generate_reply(instructions=i.prompt())
            else:
                self.session.generate_reply(user_input=i.prompt())
        except Exception:
            logger.warning("could not ask the agent to react to %s, noting it silently", i.kind, exc_info=True)
            await self._note(i)

    async def _note(self, i: Interaction) -> None:
        """Silent: the agent knows what happened but is not asked to speak."""
        try:
            agent = self.session.current_agent
            ctx = agent.chat_ctx.copy()
            ctx.add_message(role="user", content=i.prompt())
            await agent.update_chat_ctx(ctx)
        except Exception:
            logger.warning("silent screen update failed", exc_info=True)