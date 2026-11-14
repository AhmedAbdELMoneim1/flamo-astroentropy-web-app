"""Pretty-print logs/retrieval.jsonl, live (like tail -f).

    .venv/bin/python scripts/rag/tail_retrieval.py [--once] [--last N]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

PATH = Path(__file__).resolve().parents[2] / "logs" / "retrieval.jsonl"


def show(e: dict) -> str:
    lat = e.get("latency_ms", {})
    out = [f"\n=== {e['request_id']}  {e['outcome'].upper()}  {lat.get('total', '?')} ms   {e['question']!r}",
           f"    path: {e.get('path', '?')}",
           f"    params {e.get('params')}  scope {e['scope'].get('n_psis', '-')} PSIs / {e['scope'].get('n_sources', '-')} sources  selected_by {e['scope'].get('selected_by')}"]
    if e.get("vector"):
        out.append("    vector : " + ", ".join(f"{r['chunk_id']}({r['score']})" for r in e["vector"][:4]))
        out.append("    keyword: " + (", ".join(f"{r['chunk_id']}({r['score']})" for r in e["keyword"][:4]) or "-"))
    for i, r in enumerate(e.get("reranked", []), 1):
        out.append(f"    top{i} {r['score']:<7} {r['chunk_id']}  {r['text'][:110]!r}")
    c = e.get("composer", {})
    if c.get("provider"):
        out.append(f"    composer: {c['provider']} ({c.get('key')}){'  fallback: ' + c['fallback_reason'] if c.get('fallback_reason') else ''}")
    for s in c.get("sentences", []):
        out.append(f"      {'KEPT   ' if s['kept'] else 'DROPPED'} {s['chunks']} {s['text'][:110]!r}{'  <- ' + s['reason'] if s['reason'] else ''}")
    if e.get("clarify"):
        out.append(f"    clarify: {e['clarify']['question']}  ({e['clarify']['why']})")
    if e.get("reason"):
        out.append(f"    reason : {e['reason']}")
    out.append("    latency: " + ", ".join(f"{k} {v}" for k, v in lat.items()))
    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--last", type=int, default=5)
    a = ap.parse_args()
    lines = PATH.read_text().splitlines() if PATH.exists() else []
    for l in lines[-a.last:]:
        print(show(json.loads(l)))
    if a.once:
        return
    pos = PATH.stat().st_size if PATH.exists() else 0
    while True:
        time.sleep(0.5)
        if PATH.exists() and PATH.stat().st_size > pos:
            with PATH.open() as f:
                f.seek(pos)
                for l in f.read().splitlines():
                    print(show(json.loads(l)), flush=True)
                pos = f.tell()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
