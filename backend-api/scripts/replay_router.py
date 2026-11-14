"""Round 14 §14.7 step 6: replay the logged questions through the router (typed, one session per set), real flameo tools + real RAG.

    source ~/.stage4_keys.sh; TABLE_NAME=chunks_cohere EMBEDDING_PROVIDER=cohere EMBEDDING_SIZE=1024 EMBEDDING_MODEL_ID=embed-v4.0 \
      .venv/bin/python scripts/replay_router.py [--no-rag] > reports/stage7/round14_replay.md

Writes the replay table (question -> answered_by -> first spoken line), the pair-set results, the not-covered count, and the router log lines to logs/router_replay.jsonl.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("FLAMEO_DB", str(Path.home() / "Desktop/nasa-multi-agents-stages/s1/s0-results/psi_stage1/local_data/serving.db"))
LOG = ROOT / "logs" / "router_replay.jsonl"
os.environ["QUESTIONS_LOG"] = str(LOG)

from src import flameo, rag  # noqa: E402
from src.categories import load_coverage  # noqa: E402
from src.router.answer import Router  # noqa: E402
from src.state import DashboardState  # noqa: E402


class Bridge:
    def __init__(self): self.sent = []
    async def send(self, t, p, dest_identity=None): self.sent.append((t, p))


async def run_set(rows, rag_on):
    b, st = Bridge(), DashboardState()
    r = Router(b, st)
    out = []
    for row in rows:
        st.last_transcript = row["q"]
        st.last_source = "typed"
        m = await r.answer(row["q"])
        by = m.get("router", {}).get("answered_by")
        first = (m.get("speak") or [""])[0]
        ok = by in row["ok"] and (not row.get("find") or any(re.search(row["find"], x, re.I) for x in m.get("speak", [])))
        out.append({"q": row["q"], "by": by, "first": first, "ok": ok, "want": row["ok"], "n_lines": len(m.get("speak", [])), "clarify": (m.get("clarify") or {}).get("options")})
    return out


def logged_set():
    """The English questions of logs/questions.jsonl (typed or transcribed), unique, with the BEFORE result of the old path (matched false in the log)."""
    path = ROOT / "logs" / "questions.jsonl"
    seen, rows, before = set(), [], 0
    if not path.exists():
        return rows, 0
    by: dict = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            d = json.loads(line)
        except ValueError:
            continue
        t = (d.get("transcript") or "").strip()
        by.setdefault(t, []).append(d)
    for t, v in by.items():
        if not t or t.startswith("[screen]") or not t.isascii() or len(t.split()) < 4 or re.match(r"(?i)^(yeah|yes|ya|eh|ok)\b", t):
            continue
        rows.append({"q": t, "ok": ["tool", "rag", "both", "clarify", "action"]})
        before += 1 if any(x.get("matched") is False for x in v) else 0
    return rows, before


async def main(rag_on: bool):
    flameo.init(); load_coverage(flameo.call)
    if rag_on:
        try:
            rag.set_asker(rag.build())
        except Exception as e:  # noqa: BLE001
            print("RAG off:", e, file=sys.stderr)
    LOG.parent.mkdir(exist_ok=True)
    LOG.write_text("")
    spec = yaml.safe_load((ROOT / "tests" / "golden" / "router_replay.yaml").read_text(encoding="utf-8"))
    lg, lg_before = logged_set()
    spec["logged"] = lg
    res = {k: await run_set(spec[k], rag_on) for k in ("round13", "round10", "logged")}
    pairs = []
    for p in spec["pairs"]:
        g = (await run_set([{"q": p["general"], "ok": ["tool", "rag", "both", "clarify"]}], rag_on))[0]
        s = (await run_set([{"q": p["specific"], "ok": ["tool", "rag", "both", "clarify"]}], rag_on))[0]
        good = s["by"] in ("tool", "rag", "both") and g["by"] != "not_found"
        pairs.append({"general": g, "specific": s, "pass": good if s["by"] in ("tool", "rag", "both") else g["by"] != "not_found"})
    print("# Round 14 replay (router), RAG " + ("ON" if rag_on else "OFF (serving.db text search)") + "\n")
    for name in ("round13", "round10", "logged"):
        rows = res[name]
        print(f"## {name}: {len(rows)} questions, not_found: {sum(1 for r in rows if r['by'] == 'not_found')}, expectations met: {sum(1 for r in rows if r['ok'])}/{len(rows)}\n")
        print("| # | question | answered_by | first spoken line | ok |\n|---|---|---|---|---|")
        for i, r in enumerate(rows, 1):
            q = r["q"].replace("|", "/")[:70]
            print(f"| {i} | {q} | {r['by']} | {r['first'].replace('|', '/')[:110]} | {'yes' if r['ok'] else 'NO (wanted ' + '/'.join(r['want']) + ')'} |")
        print()
    print("## general -> specific pairs\n\n| general | answered_by | specific | answered_by | pass |\n|---|---|---|---|---|")
    for p in pairs:
        print(f"| {p['general']['q']} | {p['general']['by']} | {p['specific']['q']} | {p['specific']['by']} | {'yes' if p['pass'] else 'NO'} |")
    nf = [r for n in res for r in res[n] if r["by"] == "not_found"]
    print(f"\n## not-covered before / after\n\n- Round 13 transcript (45 user turns): before 9 agent replies with the not-covered sentence (counted in chat_decisions/round13_session_transcript.txt); after {sum(1 for r in res['round13'] if r['by'] == 'not_found')}")
    print(f"- logged English questions ({len(res['logged'])}): before {lg_before} with a tool result that did not match (logs/questions.jsonl); after {sum(1 for r in res['logged'] if r['by'] == 'not_found')}")
    print(f"- Round 10 sets ({len(res['round10'])}): before: the Round 10 live tests saw not-covered for 3 of 13 (Round 10 §10.1, 10.7); after {sum(1 for r in res['round10'] if r['by'] == 'not_found')}")
    print(f"\n## not_found in the replays: {len(nf)}\n")
    for r in nf:
        print(f"- {r['q']}")
    from src.paper_rag.db import engine
    await engine().dispose()

asyncio.run(main("--no-rag" not in sys.argv))
