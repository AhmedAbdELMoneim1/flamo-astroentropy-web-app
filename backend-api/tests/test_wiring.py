"""Real imports (livekit-agents and fastapi installed by `uv sync`): the event names the agent uses exist in the installed package."""
import inspect
import re

import pytest

from tests.helpers import needs_db

lk = pytest.importorskip("livekit.agents.voice.events")
rtc_room = pytest.importorskip("livekit.rtc.room")


def test_session_and_room_event_names_exist_in_the_installed_package():
    from typing import get_args

    names = set(get_args(lk.EventTypes))
    assert {"user_input_transcribed", "agent_state_changed"} <= names
    assert "reconnected" in inspect.getsource(rtc_room)
    assert {"transcript", "is_final"} <= set(lk.UserInputTranscribedEvent.model_fields)
    assert "new_state" in lk.AgentStateChangedEvent.model_fields
    assert {"listening", "speaking"} <= set(get_args(lk.AgentState))


def test_agent_source_uses_exactly_those_names():
    src = open("src/agent.py", encoding="utf-8").read()
    assert 'session.on("user_input_transcribed")' in src and 'session.on("agent_state_changed")' in src and 'ctx.room.on("reconnected")' in src
    assert re.search(r"ev\.transcript", src) and "ev.new_state" in src


def test_generate_reply_accepts_user_input_and_session_has_interrupt():
    from livekit.agents import AgentSession

    assert "user_input" in inspect.signature(AgentSession.generate_reply).parameters
    assert callable(AgentSession.interrupt) and hasattr(AgentSession, "current_agent")


@needs_db
def test_agent_and_api_import_for_real():
    import src.agent as agent
    import src.api as api

    assert agent.server is not None and api.app is not None
    from src.tools import flamoTools

    assert hasattr(flamoTools, "rank_investigations") and not hasattr(flamoTools, "query_data")
