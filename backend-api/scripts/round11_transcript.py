"""Round 11 STOP: the voice-path transcript of "Is 34 percent oxygen dangerous on the Moon base?" (real tool path, no LiveKit, no Gemini voice).

    .venv/bin/python scripts/round11_transcript.py > reports/stage7/round11_voice_transcript.md
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("FLAMEO_DB", str(Path.home() / "Desktop/nasa-multi-agents-stages/s1/s0-results/psi_stage1/local_data/serving.db"))

from src import adapter, conditions, content, flameo  # noqa: E402
from src.bridge import Cmd  # noqa: E402
from src.categories import load_coverage  # noqa: E402
from src.state import DashboardState  # noqa: E402


class Bridge:
    def __init__(self): self.sent = []
    async def send(self, t, p, dest_identity=None): self.sent.append((t, p))


async def main() -> None:
    flameo.init(); load_coverage(flameo.call)
    q = "Is 34 percent oxygen dangerous on the Moon base?"
    b, st = Bridge(), DashboardState()
    st.last_transcript = q
    up = await conditions.apply_from_text(b, st, q)
    m = await content.Runner(b, st).intent("oxygen_effect", scenario="moon_base")
    full = flameo.call("oxygen_effect", scenario="moon_base")
    lines = list(m["speak"])[:3]
    for cav in adapter.caveat_lines(full["speak"]):
        if cav not in lines:
            lines.insert(1, cav)
    says = [m["conditions_set"]] + lines + ["The details are on the screen."] + ([m["next_offer"]] if m.get("next_offer") else [])
    ans = next((p for t, p in b.sent if t == Cmd.ANSWER_SHOW), {})
    cs = [p for t, p in b.sent if t == Cmd.CONDITIONS_SET]
    print("# Voice-path transcript (Round 11): conditions follow the words\n")
    print("The real server path: the question text -> `conditions.apply_from_text` (deterministic, not Gemini) -> `conditions.set` to the screen; the model's tool call is the router golden's `oxygen_effect(scenario=\"moon_base\")`. No LiveKit, no Gemini voice: the 'voice says' lines follow the prompt's rules.\n")
    print(f"**Astronaut:** {q}\n")
    print(f"**Server sets the sliders (before any model call):** `{json.dumps(up)}`; `conditions.set` payload sent to the screen: `{json.dumps(cs[0], ensure_ascii=False)}`\n")
    print("**Tool call:** `oxygen_effect(scenario=\"moon_base\")`\n")
    print("**The voice says** (first the one-time conditions note, then the speak lines):\n")
    for s in says:
        print(f"> {s}")
    print(f"\n**On screen (answer.show):** `{ans.get('question')}`, {len(ans.get('speak', []))} lines, {len(ans.get('sources', []))} sources; panel data from `GET /api/nearest?o2=34&p=10.2` (flameo `nearest_tests`).")


asyncio.run(main())
