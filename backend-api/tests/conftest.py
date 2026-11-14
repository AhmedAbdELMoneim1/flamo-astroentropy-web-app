"""Test setup: stub livekit (not installed here), point flameo at serving.db, no network, no API call."""
import os
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

if "livekit" not in sys.modules:
    try:
        import livekit.agents  # noqa: F401
    except Exception:
        lk, ag = types.ModuleType("livekit"), types.ModuleType("livekit.agents")
        ag.RunContext = object
        ag.AgentSession = object
        ag.function_tool = lambda fn: fn
        lk.agents, lk.rtc = ag, types.SimpleNamespace(Room=object, DataPacket=object)
        sys.modules.update({"livekit": lk, "livekit.agents": ag, "livekit.rtc": lk.rtc})

_DEFAULT_DB = Path.home() / "Desktop/nasa-multi-agents-stages/s1/s0-results/psi_stage1/local_data/serving.db"
DB = Path(os.getenv("FLAMEO_DB") or _DEFAULT_DB)
os.environ.setdefault("QUESTIONS_LOG", str(ROOT / "logs" / "test_questions.jsonl"))
GOLDEN = Path(os.getenv("FLAMEO_GOLDEN") or DB.parent.parent / "tests" / "golden" / "golden_questions.yaml")
os.environ.setdefault("FLAMEO_DB", str(DB))
os.environ.setdefault("ROUTER_MODEL", "0")      # Round 15: the understanding model is off in tests (no network); a fake is injected where it is tested
