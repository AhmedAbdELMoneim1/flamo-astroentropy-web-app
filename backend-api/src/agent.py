"""
flamo — LiveKit voice copilot for fire safety on a space mission.

Run from the project root:   python -m src.agent dev

Wiring only. Everything else lives in:
    bridge.py      front <-> back packet contract
    tools.py       function tools (show_dashboard, set_conditions, mission, emergency)
    events.py      handlers for user actions on the screen
    prompts.py     persona + briefings
    categories.py  pillars, views, scenarios & input conditions (single source of truth)
    content.py     real content from flameo_tools (vendor/flameo_tools + FLAMEO_DB), adapter.py trims it
"""
import sys
from pathlib import Path

# Make `src.*` imports work no matter how the agent is launched
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import asyncio
import logging
import os

from dotenv import load_dotenv

from livekit.agents import Agent, AgentServer, AgentSession, JobContext, cli, room_io
from livekit.plugins import google

from src import alerts, conditions, flameo, qlog, rag, turns
from src.bridge import UiBridge
from src.categories import DEFAULT_SCENARIO, PILLARS, SCENARIOS, load_coverage
from src.content import chips_for, scene_arrival
from src.events import register_event_handlers
from src.notify import Interaction, Notifier, Nudger
from src.prompts import build_instructions
from src.router.gate import Gate
from src.state import DashboardState
from src.tools import flamoTools

logger = logging.getLogger("agent")

load_dotenv(".env.local")
load_dotenv(".env")

# Fail early and clearly: no serving.db, no agent. Coverage levels come from the data, not from code.
flameo.init()
load_coverage(flameo.call)
rag.startup_check()   # one clear line: RAG: ON (index, chunks, models) or RAG: OFF, <reason>; RAG_REQUIRED=1 stops the agent instead

MODEL = os.getenv("AGENT_MODEL", "gemini-3.8-live")


class flamoAgent(flamoTools, Agent):
    def __init__(self, bridge: UiBridge, state: DashboardState) -> None:
        super().__init__(
            instructions=build_instructions(),
            llm=google.realtime.RealtimeModel(
                model=MODEL,
                voice="Puck",
                language="en-US",  # fixed speech language: no sudden switches
                temperature=0.6,   
            ),
        )
        self.bridge = bridge
        self.state = state


# A small server (2 CPUs) needs time to import the RAG in each job process: a longer init timeout, one idle process, and a load threshold that does not mark the worker full while it starts.
server = AgentServer(initialize_process_timeout=int(os.getenv("AGENT_INIT_TIMEOUT", "60")), num_idle_processes=int(os.getenv("AGENT_IDLE_PROCS", "1")), load_threshold=float(os.getenv("AGENT_LOAD_THRESHOLD", "0.95")))


@server.rtc_session(agent_name="nasa-agent")
async def my_agent(ctx: JobContext):
    ctx.log_context_fields = {"room": ctx.room.name}
    asyncio.create_task(rag.warm_up())          # one embed + one rerank call now, so the first question is not the slow one (Round 12 item 1)

    state = DashboardState()
    bridge = UiBridge(ctx.room)
    session = AgentSession()

    state.gate = Gate(bridge, state, session, rag.extractor())      # Round 15: the server runs answer() on every data-question turn
    notifier = Notifier(session, bridge)
    notifier.nudger = Nudger(notifier, state)
    notifier.state = state
    register_event_handlers(bridge, state, notifier)
    bridge.start()  # listen before the session starts so no early packet is missed

    @session.on("user_input_transcribed")
    def _heard(ev) -> None:
        notifier.nudger.cancel()  # any speech cancels the silence nudge
        ids = state.heard(ev.transcript, bool(getattr(ev, "is_final", False)))
        if ids:  # the tool call came before the speech-to-text result: fill the log line in
            qlog.amend(ids, state.last_transcript)
        if getattr(ev, "is_final", False):
            state.gate.kick(state.last_transcript)       # a data question starts on the server at once (nothing is shown until it is used)
            asyncio.create_task(alerts.maybe_clear_from_text(bridge, state, state.last_transcript))   # "there is no fire": the banner goes away at once
            asyncio.create_task(alerts.maybe_declare_from_text(bridge, state, state.last_transcript))   # "smoke from the rack": the banner shows every time, model or not
            asyncio.create_task(conditions.apply_from_text(bridge, state, state.last_transcript))       # "34 percent oxygen": the sliders follow the words (Round 11 §11.1)

    @session.on("conversation_item_added")
    def _item(ev) -> None:
        item = ev.item
        if getattr(item, "role", None) == "user" and turns.typed_text(state, getattr(item, "text_content", "") or ""):
            state.gate.kick(state.last_transcript)
            asyncio.create_task(alerts.maybe_clear_from_text(bridge, state, state.last_transcript))   # a typed message is a question too
            asyncio.create_task(alerts.maybe_declare_from_text(bridge, state, state.last_transcript))
            asyncio.create_task(conditions.apply_from_text(bridge, state, state.last_transcript))
        elif getattr(item, "role", None) == "assistant":
            turns.check_spoken_numbers(state, getattr(item, "text_content", "") or "")

    @session.on("function_tools_executed")
    def _tools(ev) -> None:
        turns.tools_executed(state, ev.function_calls)

    @session.on("agent_state_changed")
    def _agent_state(ev) -> None:
        if ev.new_state == "speaking":
            if state.turn_tools == 0 and state.gate.pending(state.last_transcript):
                asyncio.create_task(state.gate.catch_up(state.last_transcript))   # Gemini skipped the answer tool: the server's answer is said instead
            else:
                turns.turn_without_tool(state)  # a turn that ran no tool is logged with tool null
            state.close_turn()  # the answer started: the next words are a new question
        notifier.nudger.on_agent_state(ev.new_state)

    @ctx.room.on("reconnected")
    def _reconnected() -> None:
        asyncio.create_task(notifier.notify(Interaction("reconnected", "The connection was lost for a moment and is back", {"phase": "reconnected"}, ack=False)))

    await session.start(
        agent=flamoAgent(bridge, state),
        room=ctx.room,
        room_options=room_io.RoomOptions(audio_input=room_io.AudioInputOptions()),
    )
    await ctx.connect()
    logger.info("flamo agent ready in room %s", ctx.room.name)

    # The greeting goes through the same notification path as every tap. If the page was opened with ?env=moonbase|spacesuit,
    # the scene is announced in the SAME turn (one utterance, never two): wait briefly for the frontend's state.sync.
    facts: dict = {}
    try:
        await asyncio.wait_for(state.synced_event.wait(), timeout=1.5)
    except asyncio.TimeoutError:
        pass
    for _ in range(15):  # the screen opens its default category by itself right after the agent joins; wait up to 1.5 s for it
        if state.pillar:
            break
        await asyncio.sleep(0.1)
    if state.pillar in PILLARS:  # that category stays "not visited": its intro plays when the astronaut comes back to it
        chips = chips_for(state.pillar)
        facts.update(category=PILLARS[state.pillar].label)
        if chips:
            facts["ask_me"] = chips[0]
    if state.scenario in SCENARIOS and state.scenario != DEFAULT_SCENARIO and not state.scene_announced:
        state.scene_announced = True
        scene = await scene_arrival(bridge, state, state.scenario)
        facts |= {"phase": "scene", "scenario": state.scenario, "coverage": None if SCENARIOS[state.scenario].coverage_note else SCENARIOS[state.scenario].coverage, "scene_speak": " ".join(scene["speak"]), "end_with": scene["end_with"]}
    await notifier.notify(Interaction("session_started", "The session has just started", facts, ack=False))


if __name__ == "__main__":
    cli.run_app(server)
