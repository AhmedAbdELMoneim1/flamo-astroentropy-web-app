"""The watcher (D2-D5): as the master marks a file done, describe its tables and figures, chunk it, embed it and insert it.

    source ~/.stage4_keys.sh            # GEMINI_API_KEY_1.. and GROQ_API_KEY_1..; keys are never printed
    .venv/bin/python scripts/rag/run_pipeline.py [--no-until-done] [--no-describe]

Runs on the master laptop next to the master container (shares rag_cache/). Ends when no task is pending or leased and every done file is inserted;
the final check lists every manifest file as inserted, parse-failed or unaccounted.
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

from src.paper_rag import chunks as C  # noqa: E402
from src.paper_rag.db import engine  # noqa: E402
from src.paper_rag.describe import Describer  # noqa: E402
from src.paper_rag.helpers.config import get_settings  # noqa: E402
from src.paper_rag.ingest import watch  # noqa: E402
from src.paper_rag.keypool import KeyPool, Limits, env_limits  # noqa: E402
from src.paper_rag.factory import embedder as make_embedder  # noqa: E402


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-until-done", action="store_true", help="keep watching after the queue is empty")
    ap.add_argument("--no-describe", action="store_true", help="index tables without a description and skip figures")
    ap.add_argument("--concurrency", type=int, default=8)
    ap.add_argument("--manifest", type=Path, default=ROOT / "rag_cache" / "manifest.jsonl", help="e.g. rag_cache/pilot_manifest.jsonl for the pilot")
    a = ap.parse_args()
    cache = ROOT / "rag_cache"
    st = get_settings()
    serving = Path(os.getenv("FLAMEO_DB") or Path.home() / "Desktop/nasa-multi-agents-stages/s1/s0-results/psi_stage1/local_data/serving.db")
    vocab = C.Vocab.from_serving(serving)
    gem = KeyPool.from_env("GEMINI", state_file=cache / "keypool_state.json")
    try:
        groq = KeyPool.from_env("GROQ", limits=env_limits("GROQ_POOL", Limits(rpm=30, tpm=6000, rpd=1000)), state_file=cache / "groq_state.json")
    except ValueError:
        groq = None
    # descriptions use a generation model with much lower free limits than the embedding model: their own pool and counters
    gem_desc = KeyPool.from_env("GEMINI", limits=env_limits("GEMINI_DESC_POOL", Limits(rpm=8, tpm=200_000, rpd=400)), state_file=cache / "gemini_desc_state.json")
    desc = None if a.no_describe else Describer(groq, gem_desc, cache / "desc", gemini_model=os.getenv("DESCRIBE_GEMINI_MODEL", "gemini-3.5-flash-lite"))
    emb = make_embedder(st)
    rep = await watch(a.manifest, cache, vocab, desc, emb, concurrency=a.concurrency, until_done=not a.no_until_done)
    rep["pools"] = {"embedding": emb.pool.stats(), "gemini_desc": gem_desc.stats(), **({"groq": groq.stats()} if groq else {})}
    if desc:
        rep["describe"] = desc.stats
    (cache / "pipeline_report.json").write_text(json.dumps(rep, indent=1))
    print(json.dumps({k: v for k, v in rep.items() if k != "pools"}, indent=1))
    await engine().dispose()


asyncio.run(main())
