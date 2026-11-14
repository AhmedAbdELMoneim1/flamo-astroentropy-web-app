"""Round 15 P1: adaptive retrieval depth on vs off on the Round 9 retrieval eval set (scripts/rag/eval_rag.json, 30 questions with an answer key).

hit@5 = some top-5 reranked chunk holds ALL the key phrases (as scripts/rag/eval_rag.py); answer rate = status ok or fallback (not clarify / not_found); latency of ask().
Budget: about 2 Cohere calls per question per mode (1 embed + 1 rerank) plus the second pass when it runs; 30 x 2 modes stays well under 300.

    source ~/.stage4_keys.sh; TABLE_NAME=chunks_cohere EMBEDDING_PROVIDER=cohere EMBEDDING_SIZE=1024 EMBEDDING_MODEL_ID=embed-v4.0 .venv/bin/python scripts/eval_adaptive.py [--n 30] > reports/stage7/round15_p1_adaptive.md
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("FLAMEO_DB", str(Path.home() / "Desktop/nasa-multi-agents-stages/s1/s0-results/psi_stage1/local_data/serving.db"))
os.environ["RAG_LOG"] = "full"

from src import rag  # noqa: E402
from src.paper_rag import retrieval_log  # noqa: E402


def norm(s: str) -> str:
    import re
    return re.sub(r"\s+", " ", re.sub(r"\s*%", "%", (s or "").lower())).strip()


def pct(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(p / 100 * (len(xs) - 1))))] if xs else None


async def run_mode(asker, qs, adaptive: bool, path: Path):
    asker.adaptive = adaptive
    retrieval_log.PATH = path
    rows = []
    for q in qs:
        t = time.monotonic()
        r = await asker.ask(q["question"], **(q.get("params") or {}))
        ms = round((time.monotonic() - t) * 1000)
        e = json.loads(path.read_text().splitlines()[-1])
        top5 = e.get("reranked", [])[:5]
        hit = any(all(norm(k) in norm(c.get("raw_text", "")) for k in q["keys"]) for c in top5)
        ret = e.get("retrieval", [])
        rows.append({"id": q["id"], "hit": hit, "answered": r["status"] in ("ok", "fallback"), "status": r["status"], "ms": ms, "second": any(x.get("pass") == 2 for x in ret), "how": e.get("retrieval_widened"), "best": (top5[0]["score"] if top5 else 0)})
        await asyncio.sleep(0.5)
    return rows


async def main():
    n = int(sys.argv[sys.argv.index("--n") + 1]) if "--n" in sys.argv else 30
    qs = json.load(open(ROOT / "scripts" / "rag" / "eval_rag.json"))[:n]
    asker = rag.build()
    tmp = Path(tempfile.mkdtemp())
    off = await run_mode(asker, qs, False, tmp / "off.jsonl")
    on = await run_mode(asker, qs, True, tmp / "on.jsonl")
    print("# Round 15 P1: adaptive retrieval depth, on vs off\n")
    print(f"{len(qs)} questions of the Round 9 retrieval eval set (answer-key phrases).\n")
    print("| metric | off | on |\n|---|---|---|")
    f = lambda rows, k: sum(1 for r in rows if r[k])  # noqa: E731
    print(f"| hit@5 | {f(off, 'hit')}/{len(qs)} | {f(on, 'hit')}/{len(qs)} |")
    print(f"| answer rate (ok or fallback) | {f(off, 'answered')}/{len(qs)} | {f(on, 'answered')}/{len(qs)} |")
    print(f"| second pass ran | 0 | {f(on, 'second')}/{len(qs)} ({', '.join(sorted({r['how'] for r in on if r['how']})) or 'none'}) |")
    print(f"| latency p50 / p95 (ms) | {pct([r['ms'] for r in off], 50)} / {pct([r['ms'] for r in off], 95)} | {pct([r['ms'] for r in on], 50)} / {pct([r['ms'] for r in on], 95)} |")
    print("\n| id | hit off | hit on | status off | status on | second pass | ms off | ms on |\n|---|---|---|---|---|---|---|---|")
    for a, b in zip(off, on):
        print(f"| {a['id']} | {'y' if a['hit'] else '-'} | {'y' if b['hit'] else '-'} | {a['status']} | {b['status']} | {b['how'] or '-'} | {a['ms']} | {b['ms']} |")
    from src.paper_rag.db import engine
    await engine().dispose()

asyncio.run(main())
