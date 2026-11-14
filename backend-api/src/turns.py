"""What the session hooks do with the conversation, as plain functions (the hooks in agent.py only call these; tests call them without LiveKit)."""
from __future__ import annotations

from src import qlog

# tools whose calls Runner already logs (with their arguments and whether they matched)
LOGGED_BY_RUNNER = {"answer", "get_investigation", "compare", "rank_materials", "scenario_coverage", "get_findings", "rank_agents", "gaps", "search_text", "rank_investigations", "oxygen_effect", "ask_sources"}


def typed_text(state, text: str) -> bool:
    """A message typed in the chat: its text is the question (a voice turn already filled the transcript through user_input_transcribed). True when it was typed."""
    text = (text or "").strip()
    if not text or (state.turn_parts and not state.turn_closed):
        return False
    if text.startswith("[screen]"):                      # a screen event (a tap, a slider) is not the astronaut's words: no extractor, no router, logged as source "screen"
        state.last_source = "screen"
        return False
    state.typed(text)
    state.last_source = "typed"
    state.turn_tools = 0
    return True


def tools_executed(state, calls) -> None:
    """Log every tool call that Runner does not log itself (show_dashboard, set_conditions, mission, emergency ...)."""
    import json
    for c in calls:
        state.turn_tools += 1
        if c.name in LOGGED_BY_RUNNER:
            continue
        try:
            args = json.loads(c.arguments or "{}")
        except ValueError:
            args = {"arguments": str(c.arguments)[:200]}
        lid = qlog.log(state.last_transcript, c.name, args, True, source=state.last_source)
        if lid:
            state.log_ids.append(lid)


def turn_without_tool(state) -> None:
    """The agent starts to answer and no tool ran this turn: log the question with tool null (small talk, off-topic, a decline, an answer from the prompt alone)."""
    if state.last_transcript and state.turn_tools == 0 and not state.turn_logged_null:
        state.turn_logged_null = True
        lid = qlog.log(state.last_transcript, None, {}, None, source=state.last_source)
        if lid:
            state.log_ids.append(lid)


def check_spoken_numbers(state, spoken: str) -> set:
    """What the voice said: every number must be in a tool line, a notification fact or the astronaut's own words. A miss is logged (tool "spoken_number_check") and warned about."""
    import logging

    from src import spoken as sp
    bad = sp.unsupported(spoken, [*state.allowed_text, state.last_transcript or ""])
    if bad:
        logging.getLogger("turns").warning("the voice said numbers that no tool returned: %s | %r", sorted(bad), spoken[:120])
        qlog.log(state.last_transcript, "spoken_number_check", {"unsupported": sorted(bad), "spoken": spoken[:200]}, False, source=state.last_source)
    return bad
