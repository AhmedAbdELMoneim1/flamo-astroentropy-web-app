"""Round 15 P1 STOP evidence: the replay table (question -> type -> tools -> answered_by -> first spoken line), the not-covered count, the latency of answer(), and the adaptive-depth comparison.

    source ~/.stage4_keys.sh; TABLE_NAME=chunks_cohere EMBEDDING_PROVIDER=cohere EMBEDDING_SIZE=1024 EMBEDDING_MODEL_ID=embed-v4.0 \
      .venv/bin/python scripts/replay_p1.py [--no-rag] [--no-model] > reports/stage7/round15_p1_replay.md

Sets: the Round 15 transcript, the Round 13 / 10 sets and the Round 14 pairs. Keys are used through the key pools only; nothing prints a key.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import statistics
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("FLAMEO_DB", str(Path.home() / "Desktop/nasa-multi-agents-stages/s1/s0-results/psi_stage1/local_data/serving.db"))
if "--no-model" in sys.argv:
    os.environ["ROUTER_MODEL"] = "0"
LOG = ROOT / "logs" / "router_replay_p1.jsonl"
os.environ["QUESTIONS_LOG"] = str(LOG)

from src import flameo, rag  # noqa: E402
from src.categories import load_coverage  # noqa: E402
from src.router.answer import Router  # noqa: E402
from src.state import DashboardState  # noqa: E402


class Bridge:
    def __init__(self): self.sent = []
    async def send(self, t, p, dest_identity=None): self.sent.append((t, p))


async def run_set(rows):
    b, st = Bridge(), DashboardState()
    r = Router(b, st)
    out = []
    for row in rows:
        st.last_transcript, st.last_source = row["q"], "typed"
        m = await r.answer(row["q"])
        rt = m.get("router", {})
        log = json.loads(LOG.read_text().splitlines()[-1])["router"] if LOG.exists() and LOG.stat().st_size else {}
        by = rt.get("answered_by")
        speak = m.get("speak", [])
        ok = by in row["ok"] and (not row.get("find") or any(re.search(row["find"], x, re.I) for x in speak)) and not (row.get("not_find") and any(re.search(row["not_find"], x, re.I) for x in speak))
        und = log.get("understanding", {})
        out.append({"q": row["q"], "type": und.get("type"), "by_u": und.get("by"), "tools": [x.get("tool") or "rag" for x in log.get("plan", [])], "main": rt.get("main"), "by": by, "first": (speak or [""])[0], "ms": log.get("ms"),
                    "ok": ok and (not row.get("type") or und.get("type") == row["type"]) and (not row.get("main") or rt.get("main") == row["main"]), "want": row.get("type"), "retr": [x for x in (log.get("branches") or []) if x.get("kind") == "rag"]})
    return out


def pct(xs, p):
    xs = sorted(x for x in xs if x is not None)
    return xs[min(len(xs) - 1, int(round(p / 100 * (len(xs) - 1))))] if xs else None


async def main():
    flameo.init(); load_coverage(flameo.call)
    if "--no-rag" not in sys.argv:
        try:
            rag.set_asker(rag.build())
        except Exception as e:  # noqa: BLE001
            print("RAG off:", type(e).__name__, file=sys.stderr)
    LOG.parent.mkdir(exist_ok=True)
    LOG.write_text("")
    spec = yaml.safe_load((ROOT / "tests" / "golden" / "router_replay.yaml").read_text(encoding="utf-8"))
    spec["round15"] = yaml.safe_load((ROOT / "tests" / "golden" / "router_round15.yaml").read_text(encoding="utf-8"))
    res = {k: await run_set(spec[k]) for k in ("round15", "round13", "round10")}
    pairs = []
    for p in spec["pairs"]:
        g = (await run_set([{"q": p["general"], "ok": ["tool", "rag", "both", "clarify"]}]))[0]
        s = (await run_set([{"q": p["specific"], "ok": ["tool", "rag", "both", "clarify"]}]))[0]
        pairs.append((g, s))
    mode = ("RAG ON" if rag.available() else "RAG OFF (serving.db text search)") + (", model OFF (rules)" if os.environ.get("ROUTER_MODEL") == "0" else ", understanding model ON")
    print(f"# Round 15 P1 replay: {mode}\n")
    for name, rows in res.items():
        print(f"## {name}: {len(rows)} questions, not_found: {sum(1 for r in rows if r['by'] == 'not_found')}, expectations met: {sum(1 for r in rows if r['ok'])}/{len(rows)}\n")
        print("| # | question | type (by) | tools | answered_by | first spoken line | ms | ok |\n|---|---|---|---|---|---|---|---|")
        for i, r in enumerate(rows, 1):
            q = r["q"].replace("|", "/").replace("\t", " ")[:60]
            print(f"| {i} | {q} | {r['type']} ({r['by_u']}) | {', '.join(r['tools'])} | {r['by']} | {r['first'].replace('|', '/')[:100]} | {r['ms']} | {'yes' if r['ok'] else 'NO'} |")
        print()
    print("## general -> specific pairs\n\n| general | by | specific | by |\n|---|---|---|---|")
    for g, s in pairs:
        print(f"| {g['q']} | {g['by']} | {s['q']} | {s['by']} |")
    allr = [r for rows in res.values() for r in rows] + [x for g, s in pairs for x in (g, s)]
    ms = [r["ms"] for r in allr]
    nf = [r for r in allr if r["by"] == "not_found"]
    print(f"\n## latency of answer(): n={len(ms)}, p50={pct(ms, 50)} ms, p95={pct(ms, 95)} ms, max={max(x for x in ms if x)} ms\n")
    print(f"## not_found: {len(nf)} of {len(allr)}\n")
    for r in nf:
        print(f"- {r['q']}")
    from src.paper_rag.db import engine
    if rag.available():
        await engine().dispose()

asyncio.run(main())
