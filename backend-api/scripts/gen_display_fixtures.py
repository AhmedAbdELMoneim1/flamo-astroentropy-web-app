"""Writes frontend/src/coreSolution/fixtures/display.json: the 20 overview payloads (5 views x iss / moon_base / spacesuit / custom)
and the adapted answer of every golden question, exactly as the agent would send them. The vitest display audit renders these.

    FLAMEO_DB=/path/serving.db .venv/bin/python scripts/gen_display_fixtures.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src import adapter, categories, flameo  # noqa: E402
from src.content import build_view  # noqa: E402
from src.state import DashboardState  # noqa: E402

OUT = ROOT / "frontend/src/coreSolution/fixtures/display.json"


async def main() -> None:
    db = os.environ["FLAMEO_DB"]
    flameo.init(db)
    categories.load_coverage(flameo.call)
    overviews = []
    for v in categories.VIEWS.values():
        for sc in ("iss", "moon_base", "spacesuit", None):
            st = DashboardState()
            st.pillar, st.view, st.scenario = v.pillar, v.id, sc
            c = await build_view(st)
            overviews.append({"name": f"{v.id}/{sc or 'custom'}", "payload": c["payload"]})
    golden = Path(os.environ.get("GOLDEN", ROOT.parent / "s1/s0-results/psi_stage1/tests/golden/golden_questions.yaml"))
    answers = []
    for g in yaml.safe_load(golden.read_text()):
        d = flameo.call(g["tool"], **g.get("args", {}))
        a = adapter.to_answer(d)
        a["question"] = g["question"]
        answers.append({"name": g["id"], "answer": a})
    OUT.write_text(json.dumps({"overviews": overviews, "answers": answers}, ensure_ascii=False, indent=0), encoding="utf-8")
    print(len(overviews), "overviews,", len(answers), "answers,", OUT.stat().st_size, "bytes")


asyncio.run(main())
