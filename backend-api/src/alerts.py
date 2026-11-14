"""The emergency banner: declare, clear (voice, typed or the banner's own × button). One place, so the server mirror and the screen cannot disagree."""
from __future__ import annotations

import asyncio
import time

from src import emergency, qlog
from src.bridge import Cmd


async def declare(bridge, state, situation: str | None) -> dict:
    b = emergency.banner(situation, state.last_transcript)
    state.emergency = True
    state.declared_at = time.monotonic()
    await bridge.send(Cmd.ALERT_SET, b)          # sent on every declaration: the screen shows (or re-shows) the banner each time
    return b


async def clear(bridge, state, why: str = "cleared") -> bool:
    """True when an emergency was active and is now cleared."""
    was = state.emergency
    state.emergency = False
    await bridge.send(Cmd.ALERT_SET, {"level": "clear", "title": "", "steps": []})
    if was:
        qlog.log(state.last_transcript, "clear_fire_emergency", {"why": why}, True, source=getattr(state, "last_source", None))
    return was


async def maybe_clear_from_text(bridge, state, text: str | None) -> bool:
    """"there is no fire", "false alarm", "it's out", "I was only asking": the banner goes away without waiting for the model to remember the tool."""
    if state.emergency and emergency.classify(text) == "clear":
        return await clear(bridge, state, "the astronaut said it is over")
    return False


SAFETY_NET_S = 4.0


async def maybe_declare_from_text(bridge, state, text: str | None) -> bool:
    """A fire reported as happening NOW shows the banner even when the model forgets the tool (it tends to skip it the second time, because the chat already
    holds an earlier declaration). The model gets a few seconds to declare with its own short title first; if it did, nothing is sent twice."""
    if emergency.classify(text) != "now":
        return False
    started = time.monotonic()
    await asyncio.sleep(SAFETY_NET_S)
    if getattr(state, "declared_at", 0.0) >= started or emergency.classify(state.last_transcript) == "clear":
        return False
    await declare(bridge, state, (text or "").strip()[:80] or None)
    qlog.log(text, "declare_fire_emergency", {"by": "server safety net"}, True, source=getattr(state, "last_source", None))
    return True
