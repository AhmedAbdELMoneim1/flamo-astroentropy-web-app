"""Round 9 retrieval eval: the RAG questions only, an ANSWER KEY per question, before / after the tuning.

hit@5 = some top-5 chunk's raw_text holds ALL the key phrases of the question (any page of any source). Extra columns: the right document
(every source that holds the key) and the strict page. Variants: scoped / free x before (one lane, raw text to the reranker) / after (two lanes, header + text).
For every question where scoped < free it also says whether the key chunk was INSIDE the scope (a resolver bug) or ranked low (a retrieval issue).
Budget: 1 embed + 4 rerank calls per question.

    source ~/.stage4_keys.sh && TABLE_NAME=chunks_cohere EMBEDDING_PROVIDER=cohere EMBEDDING_SIZE=1024 EMBEDDING_MODEL_ID=embed-v4.0 \
      .venv/bin/python scripts/rag/eval_rag.py --out rag_cache/eval_r9.md
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from sqlalchemy import text  # noqa: E402

from src.paper_rag.db import db_client, engine  # noqa: E402
from src.paper_rag.factory import embedder, reranker  # noqa: E402
from src.paper_rag.helpers.config import get_settings  # noqa: E402
from src.paper_rag.scope import ScopeResolver  # noqa: E402
from src.paper_rag.search import Searcher  # noqa: E402
from src.paper_rag.stores.vector_db.providers.PGvectorProvider import PGvectorProvider, scope_sql  # noqa: E402

SERVING = os.getenv("FLAMEO_DB") or str(Path.home() / "Desktop/nasa-multi-agents-stages/s1/s0-results/psi_stage1/local_data/serving.db")


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"\s*%", "%", (s or "").lower())).strip()


def holds(raw: str, keys: list[str]) -> bool:
    r = norm(raw)
    return all(norm(k) in r for k in keys)


async def key_sources(keys: list[str]) -> set[str]:
    conds = " AND ".join(f"regexp_replace(lower(raw_text), '\\s*%', '%', 'g') LIKE :k{i}" for i in range(len(keys)))
    async with db_client()() as s:
        r = await s.execute(text(f"SELECT DISTINCT metadata->>'src_id' FROM {get_settings().TABLE_NAME} WHERE {conds}"), {f"k{i}": "%" + norm(k) + "%" for i, k in enumerate(keys)})
        return {x[0] for x in r.fetchall()}


async def key_in_scope(keys: list[str], scope: dict | None) -> int:
    where, params = scope_sql(scope)
    conds = " AND ".join(f"regexp_replace(lower(raw_text), '\\s*%', '%', 'g') LIKE :k{i}" for i in range(len(keys)))
    async with db_client()() as s:
        r = await s.execute(text(f"SELECT count(*) FROM {get_settings().TABLE_NAME} WHERE {conds} {'AND ' + where if where else ''}"), {f"k{i}": "%" + norm(k) + "%" for i, k in enumerate(keys)} | params)
        return r.scalar_one()


async def run(top: int = 5, questions: list[dict] | None = None, searcher: Searcher | None = None, resolver: ScopeResolver | None = None, pause: float = 1.0) -> dict:
    st = get_settings()
    qs = questions or json.loads((ROOT / "scripts/rag/eval_rag.json").read_text())
    resolver = resolver or ScopeResolver(SERVING)
    s = searcher or Searcher(PGvectorProvider(db_client()), st.TABLE_NAME, embedder(st), reranker(st))
    rr = s.reranker
    rows = []
    for q in qs:
        sc = resolver.resolve(**q["params"])
        flt = sc.as_filter()
        pages = {(a, b) for a, b in q.get("expect_pages", [])}
        key_srcs = await key_sources(q["keys"])
        out = {"id": q["id"], "question": q["question"], "scope_psis": len(sc.psis), "scope_empty": sc.empty and bool(q["params"]), "keys": q["keys"], "key_sources": len(key_srcs)}
        out["key_chunks_in_scope"] = await key_in_scope(q["keys"], flt) if flt else None
        for scoped in (True, False):
            for mode in ("before", "after"):
                name = f"{'scoped' if scoped else 'free'}_{mode}"
                if scoped and (out["scope_empty"] or not flt):
                    out[name] = None
                    continue
                s.lanes = mode == "after"
                s.w, s.tier1_top = ((0.95, 0.05), 6) if mode == "after" else ((0.7, 0.3), 3)      # before = the Round 8 settings
                if rr is not None:
                    rr.with_header = mode == "after"
                r = await s.search(q["question"], flt if scoped else None, top_n=top)
                final = r.final[:top]
                out[name] = any(holds(d.chunk_text, q["keys"]) for d in final)
                out[name + "_doc"] = any(d.metadata.get("src_id") in key_srcs for d in final)
                out[name + "_page"] = any((d.metadata.get("src_id"), d.metadata.get("page")) in pages for d in final) if pages else None
                out[name + "_best"] = round(final[0].score, 4) if final else None
                out[name + "_rerank"] = r.reranker
                out[name + "_top"] = [d.chunk_id for d in final]
                await asyncio.sleep(pause)
        rows.append(out)
    s.lanes, s.w, s.tier1_top = True, (0.95, 0.05), 6
    if rr is not None:
        rr.with_header = True
    def rate(k, rs=None):
        v = [r[k] for r in (rs or rows) if r.get(k) is not None]
        return (sum(v) / len(v)) if v else None
    names = ["scoped_before", "scoped_after", "free_before", "free_after"]
    summary = {"n": len(rows), "n_scoped": sum(1 for r in rows if r["scoped_after"] is not None)}
    for k in names:
        summary[k] = rate(k); summary[k + "_doc"] = rate(k + "_doc"); summary[k + "_page"] = rate(k + "_page")
    # scope diagnosis: scoped < free, was the key chunk inside the scope?
    diag = []
    for r in rows:
        if r["scoped_after"] is not None and r["free_after"] and not r["scoped_after"]:
            diag.append({"id": r["id"], "key_chunks_in_scope": r["key_chunks_in_scope"], "verdict": "resolver bug: the key chunk is outside the scope" if not r["key_chunks_in_scope"] else "retrieval: the key chunk is in the scope but ranked below the top 5"})
    # weak-score cutoff: best rerank score of hits vs misses (after, Cohere scores only)
    hits = sorted(r["scoped_after_best"] for r in rows if r.get("scoped_after") and r.get("scoped_after_rerank") == "cohere" and r["scoped_after_best"] is not None)
    miss = sorted(r["scoped_after_best"] for r in rows if r.get("scoped_after") is False and r.get("scoped_after_rerank") == "cohere" and r["scoped_after_best"] is not None)
    return {"summary": summary, "rows": rows, "diagnosis": diag, "scores": {"best_score_of_hits": hits, "best_score_of_misses": miss}, "table": st.TABLE_NAME}


def table(rep: dict) -> str:
    h = lambda x: "-" if x is None else ("yes" if x else "NO")  # noqa: E731
    pct = lambda x: "n/a" if x is None else f"{100 * x:.0f}%"  # noqa: E731
    L = [f"index `{rep['table']}`, {rep['summary']['n']} RAG questions ({rep['summary']['n_scoped']} with a scope)", "",
         "| id | question | scope PSIs | key chunks in scope | scoped before | scoped after | free before | free after |", "|---|---|---|---|---|---|---|---|"]
    for r in rep["rows"]:
        L.append(f"| {r['id']} | {r['question'][:58]} | {'EMPTY' if r['scope_empty'] else r['scope_psis']} | {r['key_chunks_in_scope'] if r['key_chunks_in_scope'] is not None else '-'} | {h(r['scoped_before'])} | {h(r['scoped_after'])} | {h(r['free_before'])} | {h(r['free_after'])} |")
    s = rep["summary"]
    L += ["", "answer-key hit@5:", "", "| metric | scoped before | scoped after | free before | free after |", "|---|---|---|---|---|"]
    for label, suf in (("answer key", ""), ("right document", "_doc"), ("strict page (n=8)", "_page")):
        L.append(f"| {label} | " + " | ".join(pct(s[k + suf]) for k in ("scoped_before", "scoped_after", "free_before", "free_after")) + " |")
    if rep["diagnosis"]:
        L += ["", "scoped < free (after tuning):"] + [f"- {d['id']}: {d['verdict']} (key chunks in scope: {d['key_chunks_in_scope']})" for d in rep["diagnosis"]]
    L += ["", f"best rerank score, hits: {rep['scores']['best_score_of_hits']}", f"best rerank score, misses: {rep['scores']['best_score_of_misses']}"]
    return "\n".join(L)


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path)
    ap.add_argument("--pause", type=float, default=1.0)
    a = ap.parse_args()
    rep = await run(pause=a.pause)
    t = table(rep)
    print(t)
    if a.out:
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text(t + "\n\n```json\n" + json.dumps(rep, indent=1) + "\n```\n")
    await engine().dispose()


if __name__ == "__main__":
    asyncio.run(main())
