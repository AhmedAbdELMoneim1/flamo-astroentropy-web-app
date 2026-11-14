"""Voice-path transcripts (Round 9 STOP): the REAL tool path for three questions, no LiveKit and no Gemini voice.

    source ~/.stage4_keys.sh; TABLE_NAME=chunks_cohere EMBEDDING_PROVIDER=cohere EMBEDDING_SIZE=1024 EMBEDDING_MODEL_ID=embed-v4.0 \
      .venv/bin/python scripts/voice_path_transcripts.py > reports/stage7/voice_path_transcripts.md

For each question: what the astronaut says, the tool call the router goldens expect, what the model receives, what the prompt tells the voice to say
(the speak lines + the fixed closing; assembled here by the prompt's rules, NOT spoken by Gemini) and what lands on the screen (answer.show).
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

from src import adapter, content, flameo, rag  # noqa: E402
from src.bridge import Cmd  # noqa: E402
from src.paper_rag.db import engine  # noqa: E402
from src.state import DashboardState  # noqa: E402


class Bridge:
    def __init__(self): self.sent = []
    async def send(self, t, p, dest_identity=None): self.sent.append((t, p))


def voice_lines(m: dict) -> list[str]:
    """What the prompt asks the voice to say after a tool: the speak lines (first 3, mandatory caveats pulled forward), the closing, the next offer."""
    if m.get("status") == "clarify":
        return [m["clarify"]["question"]]
    if m.get("not_covered"):
        return ["That isn't covered in the PSI data or papers yet. It's an open question; answering it would need new experiments or papers on it. I can tell you about prevention instead."]
    lines = list(m["speak"])[:3]
    for cav in adapter.caveat_lines(m.get("speak_full", [])):
        if cav not in lines:
            lines.insert(1, cav)
    closing = "The sources are on the screen." if m.get("sources") else "The details are on the screen."
    return lines + [closing] + ([m["next_offer"]] if m.get("next_offer") else [])


async def case(title, utterance, call, run) -> str:
    b, st = Bridge(), DashboardState()
    m = await run(b, st)
    ans = next((p for t, p in b.sent if t == Cmd.ANSWER_SHOW), {})
    out = [f"## {title}", "", f"**Astronaut:** {utterance}", "", f"**Tool call:** `{call}`", "", "**The model receives:**", "```json",
           json.dumps({k: v for k, v in m.items() if k not in ("reply_guidance", "speak_full")}, indent=1, ensure_ascii=False)[:1800], "```", "",
           f"**Reply guidance to the model:** {m.get('reply_guidance', '')}", "", "**The voice says** (assembled from the prompt's rules, not spoken by Gemini):", ""]
    out += [f"> {l}" for l in voice_lines(m)]
    out += ["", f"**On screen (answer.show):** tool `{ans.get('tool')}`, {len(ans.get('speak', []))} spoken lines" + (f" with source numbers {ans.get('speak_refs')}" if ans.get("speak_refs") else "") + f", {len(ans.get('sources', []))} sources:", ""]
    out += [f"- [{s['n']}] {s['label']}: {s.get('title')}" + (f", page {s['page']}" if s.get('page') else "") + (f" ({s['link_kind']}: {s['link']})" if s.get("link") else " (no link)") + (" - View" if s.get("viewable") else "") for s in ans.get("sources", [])]
    return "\n".join(out) + "\n"


async def main() -> None:
    flameo.init()
    rag.set_asker(rag.build())
    parts = ["# Voice-path transcripts (Round 9)", "", "The real tool path (Cohere index, Gemini composer, flameo). No LiveKit session and no Gemini voice: the 'voice says' lines follow the prompt's rules.", ""]
    q1 = "What oxygen level allows steady flames in the BRE tests?"
    parts.append(await case("1. A free question: ask_sources answers", q1, 'ask_sources(question="…", psi="BRE")', lambda b, st: content.Runner(b, st).ask_sources(q1, psi="BRE")))
    q2 = "What happens to flames in the spacesuit atmosphere?"
    parts.append(await case("2. The parameters match no investigation: one clarifying question", q2, 'ask_sources(question="…", scenario="spacesuit")', lambda b, st: content.Runner(b, st).ask_sources(q2, scenario="spacesuit")))
    q3 = "What oxygen level makes the spacecraft dangerous?"

    async def oxy(b, st):
        m = await content.Runner(b, st).intent("oxygen_effect", scenario="iss")
        d = flameo.call("oxygen_effect", scenario="iss")
        m["speak_full"] = d["speak"]
        return m
    parts.append(await case("3. A danger question: oxygen_effect (never a threshold)", q3, 'oxygen_effect(scenario="iss")', oxy))
    print("\n".join(parts))
    await engine().dispose()


asyncio.run(main())
