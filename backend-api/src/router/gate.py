"""Round 15 §15.1 item 5: the server runs `answer()` on every question turn, even when Gemini does not call the tool (the Round 14 leak: about 5 of 40 turns).

    kick(text)     a final transcript (or a typed message) arrives: if it is a data question, `answer()` starts at once on the server, with a recording bridge
                   (nothing reaches the screen yet: a wrong guess must not paint an answer card)
    take(question) the `answer` tool is called: the same question's result is used (no second run), its screen packets are sent now
    catch_up()     the agent starts to speak and no tool ran this turn: the packets are sent, the agent is interrupted and told the lines to say

Actions (a fire now, "go back", "go to the Moon base"), small talk and bare confirmations are never started here: Gemini's own tools handle them.
"""
from __future__ import annotations

import asyncio
import difflib
import logging
import re
import time

from src import emergency
from src.router.answer import Router
from src.router.understand import understand

logger = logging.getLogger("gate")
DATA_TYPES = {"explain", "interpret", "test", "compare_tests", "nearest", "catalogue", "papers", "effect", "ranking"}
SMALL_TALK = re.compile(r"^\W*(?:hi|hello|hey|thanks?|thank you|ok(?:ay)?|yes|no|yeah|yep|sure|stop|wait|what|huh|sorry|bye|good (?:morning|evening))\W*$", re.I)
FIRE_WORDS = re.compile(r"\b(?:fire|smoke|burning|burnt|smell\w*|overheat\w*|sparks?|alarm)\b", re.I)


def norm(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9% ]+", " ", (text or "").lower()).split())


class RecordingBridge:
    """Stands in for the UiBridge while a prefetched answer runs: the packets are kept and sent when the answer is used."""

    def __init__(self) -> None:
        self.sent: list[tuple] = []

    async def send(self, t, p, dest_identity=None) -> None:
        self.sent.append((t, p, dest_identity))

    async def flush(self, real) -> None:
        sent, self.sent = self.sent, []
        for t, p, d in sent:
            await real.send(t, p, d) if d else await real.send(t, p)


class Gate:
    def __init__(self, bridge, state, session=None, ext=None, router_factory=None) -> None:
        self.bridge, self.state, self.session, self.ext = bridge, state, session, ext
        self.tasks: dict[str, tuple[asyncio.Task, RecordingBridge, str]] = {}
        self.consumed: set[str] = set()
        self.make = router_factory or (lambda b: Router(b, state, ext))

    def likely_question(self, text: str) -> bool:
        t = (text or "").strip()
        if len(t.split()) < 2 or SMALL_TALK.match(t) or t.startswith("[screen]"):
            return False
        if FIRE_WORDS.search(t) and emergency.classify(t) in ("now", "ambiguous", "clear"):
            return False                                           # the emergency path belongs to Gemini's tool and the alerts code
        try:
            u = understand(t, self.state.ctx, self.ext or self.make(None).ext, self.state.scenario)
        except Exception:  # noqa: BLE001
            return False
        return u.qtype in DATA_TYPES and not (set(u.intents) & {"navigate", "offtopic"}) and not u.confirm and not u.go_back

    def kick(self, text: str) -> bool:
        k = norm(text)
        if not k or k in self.tasks or not self.likely_question(text):
            return False
        rb = RecordingBridge()
        self.tasks[k] = (asyncio.ensure_future(self.make(rb).answer(text)), rb, text)
        return True

    def _find(self, question: str):
        k = norm(question)
        if k in self.tasks:
            return k
        best = max(((difflib.SequenceMatcher(None, k, o).ratio(), o) for o in self.tasks), default=(0, None))
        return best[1] if best[0] >= 0.85 else None

    async def take(self, question: str) -> dict | None:
        """The prefetched result of this question (and its screen packets sent now), or None."""
        key = self._find(question)
        if key is None or key in self.consumed:
            return None
        task, rb, _ = self.tasks[key]
        try:
            model = await task
        except Exception:  # noqa: BLE001
            logger.warning("prefetched answer failed", exc_info=True)
            return None
        self.consumed.add(key)
        await rb.flush(self.bridge)
        model.setdefault("router", {})["prefetched"] = True
        return model

    def pending(self, transcript: str) -> str | None:
        key = self._find(transcript) if transcript else None
        return key if key and key not in self.consumed else None

    async def catch_up(self, transcript: str) -> bool:
        """Gemini began to speak without calling `answer`: use the server's answer instead. Returns True when the agent was redirected."""
        key = self.pending(transcript)
        if key is None or self.session is None:
            return False
        t0 = time.monotonic()
        model = await self.take(self.tasks[key][2])
        if not model or not model.get("speak"):
            return False
        lines = " ".join(model["speak"]) + (" " + model["next_offer"] if model.get("next_offer") else "")
        try:
            self.session.interrupt()
            self.session.generate_reply(instructions=f"The astronaut's question was answered by the server. Say exactly this, in your own calm words, keeping every number and name: {lines}")
        except Exception:  # noqa: BLE001
            logger.warning("could not redirect the agent", exc_info=True)
            return False
        self.state.turn_tools += 1
        logger.info("server-forced answer for %r (%d ms)", transcript[:60], round((time.monotonic() - t0) * 1000))
        return True
