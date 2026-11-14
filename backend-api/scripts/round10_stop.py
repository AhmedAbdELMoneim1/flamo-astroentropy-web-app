"""Round 10 STOP: five questions through the real tool path (Cohere index, composer, flameo); no LiveKit, no Gemini voice.
Writes reports/stage7/round10_retrieval.jsonl (the retrieval.jsonl lines of these questions) and frontend/public/fx2.json (the answer packets, for the screenshots).

    source ~/.stage4_keys.sh; RETRIEVAL_LOG=reports/stage7/round10_retrieval.jsonl TABLE_NAME=chunks_cohere EMBEDDING_PROVIDER=cohere EMBEDDING_SIZE=1024 \
      EMBEDDING_MODEL_ID=embed-v4.0 .venv/bin/python scripts/round10_stop.py
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

from src import content, flameo, rag  # noqa: E402
from src.bridge import Cmd  # noqa: E402
from src.paper_rag.db import engine  # noqa: E402
from src.state import DashboardState  # noqa: E402


class Bridge:
    def __init__(self): self.sent = []
    async def send(self, t, p, dest_identity=None): self.sent.append((t, p))


QUESTIONS = [
    ("bre26", "What oxygen level allows steady flames in the BRE tests?", "ask_sources", {}),
    ("suit", "What happens to flames in the spacesuit atmosphere?", "scenario_coverage", {"scenario": "spacesuit"}),
    ("notcovered", "Why are flames round in space?", "ask_sources", {}),
    ("smoke", "How were laminar smoke points measured aboard the space station?", "ask_sources", {}),
    ("bre", "What is BRE?", "get_investigation", {"psi": "BRE"}),
    ("uncovered", "How do astronauts repair the cabin air conditioning?", "ask_sources", {}),      # a question the sources do not cover: the open-question state
]


async def main() -> None:
    flameo.init()
    rag.set_asker(rag.build())
    out = {}
    for key, q, tool, args in QUESTIONS:
        b, st = Bridge(), DashboardState()
        st.last_transcript = q
        r = content.Runner(b, st)
        m = await (r.ask_sources(q, **args) if tool == "ask_sources" else r.intent(tool, **args))
        ans = next((p for t, p in b.sent if t == Cmd.ANSWER_SHOW), {})
        out[key] = ans
        print(f"{key}: tool={tool} status={m.get('status')} speak={len(ans.get('speak', []))} sources={len(ans.get('sources', []))} title={ans.get('question')!r}")
    (ROOT / "frontend/public/fx2.json").write_text(json.dumps(out, ensure_ascii=False))
    await engine().dispose()


asyncio.run(main())
