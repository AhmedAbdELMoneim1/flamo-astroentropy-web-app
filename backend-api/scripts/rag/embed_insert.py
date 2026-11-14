"""Embed chunks with the Gemini key pool and insert them into pgvector, one source at a time (resumable, idempotent).

    source ~/.stage4_keys.sh
    .venv/bin/python scripts/rag/embed_insert.py rag_cache/tier1/chunks.jsonl [--force]

A source whose row count already equals its chunk count is skipped (resume). The run ends by checking that the rows equal the chunk count
and prints the key pool statistics (requests and tokens per key index, 429s, cooldown time).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.paper_rag.db import engine  # noqa: E402
from src.paper_rag.ingest import embed_and_insert  # noqa: E402
from src.paper_rag.factory import embedder  # noqa: E402


def load(path: Path) -> dict[str, list[dict]]:
    by: dict[str, list[dict]] = defaultdict(list)
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            c = json.loads(line)
            by[c["metadata"]["src_id"]].append(c)
    return by


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("chunks", type=Path)
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    emb = embedder()
    by = load(a.chunks)
    rep = await embed_and_insert(by, embedder=emb, force=a.force)
    print(json.dumps({**rep, "pool": emb.pool.stats()}, indent=1))
    await engine().dispose()
    if rep["row_count_mismatch"]:
        sys.exit("row count does not equal the chunk count for: " + ", ".join(rep["row_count_mismatch"]))
    print("OK: rows == chunks for", len(by), "sources")


asyncio.run(main())
