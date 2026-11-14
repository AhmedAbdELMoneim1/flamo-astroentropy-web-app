"""Retrieval check (Round 7 step 6): hit@5 inside the scope vs without it, on ~30 questions with the expected chunk(s).

    source ~/.stage4_keys.sh && .venv/bin/python scripts/rag/eval_retrieval.py [--top 5] [--out rag_cache/eval_tier1.md]

A question is a hit when one of the first `top` results is one of its expected chunk ids. The scope is what the agent would pass:
the question's `params` (what Gemini fills) resolved by src/paper_rag/scope.py. Run it on tier 1 first and again when the queue is done.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.paper_rag.db import db_client, engine  # noqa: E402
from src.paper_rag.helpers.config import get_settings  # noqa: E402
from src.paper_rag.factory import embedder, reranker  # noqa: E402
from src.paper_rag.scope import ScopeResolver  # noqa: E402
from src.paper_rag.search import Searcher  # noqa: E402
from src.paper_rag.stores.vector_db.providers.PGvectorProvider import PGvectorProvider  # noqa: E402


async def run(top: int = 5, questions: list[dict] | None = None, searcher: Searcher | None = None, resolver: ScopeResolver | None = None) -> dict:
    """Four variants per question: scoped / unscoped x with rerank / with rank fusion only. The query is embedded once per question."""
    st = get_settings()
    qs = questions or json.loads((ROOT / "scripts/rag/eval_questions.json").read_text())
    serving = os.getenv("FLAMEO_DB") or str(Path.home() / "Desktop/nasa-multi-agents-stages/s1/s0-results/psi_stage1/local_data/serving.db")
    resolver = resolver or ScopeResolver(serving)
    s = searcher or Searcher(PGvectorProvider(db_client()), st.TABLE_NAME, embedder(st), reranker(st))
    rr = s.reranker
    rows = []
    for q in qs:
        sc = resolver.resolve(**q["params"])
        exp, exp_psis = set(q["expect"]), set(q.get("expect_psis", []))
        pages = {(a, b) for a, b in q.get("expect_pages", [])}
        hit = lambda r: bool(r) and any(d.chunk_id in exp or (exp_psis & set(d.metadata.get("psis", []))) or (d.metadata.get("src_id"), d.metadata.get("page")) in pages for d in r.final[:top])  # noqa: E731
        srcs = {a for a, _ in pages}
        src_hit = lambda r: bool(r) and any(d.metadata.get("src_id") in srcs for d in r.final[:top])  # noqa: E731
        ids = lambda r: [d.chunk_id for d in r.final[:top]] if r else []  # noqa: E731
        out = {"id": q["id"], "question": q["question"], "scope_psis": len(sc.psis), "scope_empty": sc.empty and bool(q["params"]), "pdf": bool(pages), "expected": q["expect"] + sorted(exp_psis) + [f"{a} p{b}" for a, b in sorted(pages)]}
        for scoped in (True, False):
            for rerank in (True, False):
                name = ("scoped" if scoped else "free") + ("_rerank" if rerank else "_rrf")
                if scoped and out["scope_empty"]:
                    out[name], out[name + "_top"] = None, []
                    continue
                s.reranker = rr if rerank else None
                if rerank and rr is None:
                    out[name], out[name + "_top"] = None, []
                    continue
                r = await s.search(q["question"], sc.as_filter() if scoped else None, top_n=top)
                await asyncio.sleep(float(os.getenv("EVAL_PAUSE_S", "1.2")))     # trial keys: stay well inside the per-minute limits
                out[name], out[name + "_top"] = hit(r), ids(r)
                if pages:
                    out[name + "_src"] = src_hit(r)
        rows.append(out)
    s.reranker = rr
    def rate(rs, k):
        rs = [r[k] for r in rs if r[k] is not None]
        return (sum(rs) / len(rs)) if rs else None
    def src_rate(k):
        rs = [r[k + "_src"] for r in rows if r.get(k + "_src") is not None]
        return (sum(rs) / len(rs)) if rs else None
    sets = {"all": rows, "pdf_questions": [r for r in rows if r["pdf"]], "tier1_questions": [r for r in rows if not r["pdf"]]}
    summary = {grp: {k: rate(rs, k) for k in ("scoped_rerank", "scoped_rrf", "free_rerank", "free_rrf")} | {"n": len(rs)} for grp, rs in sets.items()}
    summary["pdf_questions_right_document"] = {k: src_rate(k) for k in ("scoped_rerank", "scoped_rrf", "free_rerank", "free_rrf")} | {"n": len(sets["pdf_questions"])}
    return {"summary": summary, "rows": rows, "table": st.TABLE_NAME}


def table(rep: dict) -> str:
    h = lambda x: "-" if x is None else ("yes" if x else "NO")  # noqa: E731
    lines = [f"index: `{rep['table']}`", "", "| id | question | scope PSIs | scoped+rerank | scoped, fusion | free+rerank | free, fusion |", "|---|---|---|---|---|---|---|"]
    for r in rep["rows"]:
        lines.append(f"| {r['id']} | {r['question'][:62]} | {'EMPTY' if r['scope_empty'] else r['scope_psis']} | {h(r['scoped_rerank'])} | {h(r['scoped_rrf'])} | {h(r['free_rerank'])} | {h(r['free_rrf'])} |")
    pct = lambda x: "n/a" if x is None else f"{100 * x:.0f}%"  # noqa: E731
    lines += ["", "hit@5:", "", "| question set | n | scoped+rerank | scoped, fusion | free+rerank | free, fusion |", "|---|---|---|---|---|---|"]
    for grp, s in rep["summary"].items():
        lines.append(f"| {grp} | {s['n']} | {pct(s['scoped_rerank'])} | {pct(s['scoped_rrf'])} | {pct(s['free_rerank'])} | {pct(s['free_rrf'])} |")
    return "\n".join(lines)


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=5)
    ap.add_argument("--out", type=Path)
    a = ap.parse_args()
    rep = await run(a.top)
    t = table(rep)
    print(t)
    if a.out:
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text(t + "\n\n```json\n" + json.dumps(rep, indent=1) + "\n```\n")
    await engine().dispose()


if __name__ == "__main__":
    asyncio.run(main())
