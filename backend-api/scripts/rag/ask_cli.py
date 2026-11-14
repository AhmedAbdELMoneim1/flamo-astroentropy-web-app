"""Run ask_sources once against the real stack (Cohere index + rerank, Gemini / Groq composer, serving.db fallback). Writes logs/retrieval.jsonl.

    source ~/.stage4_keys.sh
    TABLE_NAME=chunks_cohere EMBEDDING_PROVIDER=cohere EMBEDDING_SIZE=1024 EMBEDDING_MODEL_ID=embed-v4.0 \
      .venv/bin/python scripts/rag/ask_cli.py "What oxygen level allows steady flames?" --psi BRE [--budget 4]
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

from src import flameo  # noqa: E402
from src.paper_rag import chunks as C  # noqa: E402
from src.paper_rag.ask import PARAMS, AskSources  # noqa: E402
from src.paper_rag.db import db_client, engine  # noqa: E402
from src.paper_rag.factory import composer_pools, embedder, reranker  # noqa: E402
from src.paper_rag.helpers.config import get_settings  # noqa: E402
from src.paper_rag.scope import ScopeResolver  # noqa: E402
from src.paper_rag.search import Searcher  # noqa: E402
from src.paper_rag.stores.vector_db.providers.PGvectorProvider import PGvectorProvider  # noqa: E402

SERVING = os.getenv("FLAMEO_DB") or str(Path.home() / "Desktop/nasa-multi-agents-stages/s1/s0-results/psi_stage1/local_data/serving.db")


def build(budget_s: float = 4.0) -> AskSources:
    st = get_settings()
    flameo.init(SERVING)
    store = PGvectorProvider(db_client())
    searcher = Searcher(store, st.TABLE_NAME, embedder(st), reranker(st))
    from src.paper_rag.extract import Extractor
    return AskSources(searcher, ScopeResolver(SERVING), composer_pools(), C.Vocab.from_serving(SERVING), serving_call=flameo.call, budget_s=budget_s, extractor=Extractor(SERVING))


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("question")
    ap.add_argument("--budget", type=float, default=4.0)
    for p in PARAMS:
        ap.add_argument(f"--{p.replace('_', '-')}")
    a = ap.parse_args()
    params = {p: getattr(a, p) for p in PARAMS if getattr(a, p) is not None}
    for k in ("o2_pct", "pressure_kpa"):
        if k in params:
            params[k] = float(params[k])
    r = await build(a.budget).ask(a.question, **params)
    print(json.dumps({k: r[k] for k in ("status", "outcome", "speak", "speak_refs", "clarify", "latency_ms") if k in r}, indent=1, ensure_ascii=False))
    for s in r.get("sources", []):
        print(f"  [{s['n']}] {s['label']}: {s.get('title')} p{s.get('page')} -> {s.get('link')}")
    await engine().dispose()


if __name__ == "__main__":
    asyncio.run(main())
