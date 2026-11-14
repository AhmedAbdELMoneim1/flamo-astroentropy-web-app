"""Run typed questions through the Round 14 router, one session, real tools + real RAG (no LiveKit, no Gemini).
    source ~/.stage4_keys.sh; TABLE_NAME=chunks_cohere EMBEDDING_PROVIDER=cohere EMBEDDING_SIZE=1024 EMBEDDING_MODEL_ID=embed-v4.0 .venv/bin/python scripts/try_router.py "question" "question" ..."""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("FLAMEO_DB", str(Path.home() / "Desktop/nasa-multi-agents-stages/s1/s0-results/psi_stage1/local_data/serving.db"))
os.environ.setdefault("QUESTIONS_LOG", "/tmp/claude-1000/try_questions.jsonl")

from src import flameo, rag  # noqa: E402
from src.categories import load_coverage  # noqa: E402
from src.paper_rag.db import engine  # noqa: E402
from src.router.answer import Router  # noqa: E402
from src.state import DashboardState  # noqa: E402


class Bridge:
    def __init__(self): self.sent = []
    async def send(self, t, p, dest_identity=None): self.sent.append((t, p))


async def main(qs):
    flameo.init(); load_coverage(flameo.call)
    try:
        rag.set_asker(rag.build())
    except Exception as e:  # noqa: BLE001
        print("RAG off:", e)
    b, st = Bridge(), DashboardState()
    r = Router(b, st)
    for q in qs:
        st.last_transcript = q
        m = await r.answer(q)
        lg = m.get("router", {})
        print(f"\n> {q}\n  [{lg.get('answered_by')}] main={lg.get('main')}")
        for s in (m.get("speak") or []):
            print("   -", s[:230])
        if m.get("next_offer"):
            print("   ?", m["next_offer"])
        if m.get("clarify"):
            print("   clarify:", m["clarify"])
    await engine().dispose()

asyncio.run(main(sys.argv[1:]))
