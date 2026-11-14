"""D2-D5: results from the master -> descriptions -> chunks -> embeddings -> pgvector, per source, as soon as a file is done.

`embed_and_insert` is shared with the tier-1 script. `watch` runs on the master laptop (outside Docker) with the Gemini / Groq keys of the shell.
Resumable at every stage: descriptions are cached per item, a source whose row count already equals its chunk count is skipped, `replace_source` is idempotent.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import time
from pathlib import Path

from src.paper_rag import chunks as C
from src.paper_rag.db import db_client
from src.paper_rag.describe import Describer, safe
from src.paper_rag.docling_chunks import CHUNK_MODE, build_source_chunks, corpus_figure_counts
from src.paper_rag.helpers.config import get_settings
from src.paper_rag.keypool import KeyPool
from src.paper_rag.stores.llm.providers.GeminiEmbedder import GeminiEmbedder
from src.paper_rag.stores.vector_db.providers.PGvectorProvider import PGvectorProvider


_schema_locks: dict[int, asyncio.Lock] = {}


async def _ensure_table(store: PGvectorProvider, table: str, size: int) -> None:
    """Sources are processed concurrently: creating the table must happen once, not in a race."""
    lock = _schema_locks.setdefault(id(asyncio.get_running_loop()), asyncio.Lock())
    async with lock:
        await store.connect()
        await store.create_table(table, size)


async def embed_and_insert(by: dict[str, list[dict]], *, embedder: GeminiEmbedder, force: bool = False, log=print) -> dict:
    """Embed the chunks of each source (header + text, document task type) and replace that source's rows. Returns counts and mismatches."""
    st = get_settings()
    store = PGvectorProvider(db_client(), distance_metric="cosine")
    await _ensure_table(store, st.TABLE_NAME, st.EMBEDDING_SIZE)
    have = {} if force else await store.count_by_source(st.TABLE_NAME)
    todo = {k: v for k, v in by.items() if have.get(k) != len(v)}
    flat = [c for v in todo.values() for c in v]
    t0, tok0, calls0 = time.monotonic(), embedder.tokens, embedder.calls
    log(f"{len(flat)} chunks in {len(todo)} sources to embed ({len(by) - len(todo)} sources already complete)")
    vecs = await embedder.embed([c["text"] for c in flat], task="document") if flat else []
    it = iter(vecs)
    for src, cs in todo.items():
        for c in cs:
            c["embedding"] = next(it)
        await store.replace_source(st.TABLE_NAME, src, cs)
    got = await store.count_by_source(st.TABLE_NAME)
    bad = {k: (len(v), got.get(k, 0)) for k, v in by.items() if got.get(k, 0) != len(v)}
    return {"chunks_embedded": len(flat), "sources_done": len(todo), "sources_skipped": len(by) - len(todo), "seconds": round(time.monotonic() - t0, 1),
            "embedding_calls": embedder.calls - calls0, "embedding_tokens_est": embedder.tokens - tok0, "row_count_mismatch": bad}


def done_sources(queue_db: Path) -> tuple[dict[str, dict], dict]:
    """{src_id: task row} of the files the master marked done, and the status counts."""
    con = sqlite3.connect(f"file:{queue_db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    done = {r["src_id"]: dict(r) for r in con.execute("SELECT * FROM task WHERE status='done'")}
    counts = {r[0]: r[1] for r in con.execute("SELECT status, count(*) FROM task GROUP BY 1")}
    return done, counts


def read_ledger(path: Path) -> dict[str, dict]:
    out = {}
    if path.exists():
        for line in path.read_text().splitlines():
            if line.strip():
                d = json.loads(line)
                out[d["src_id"]] = d
    return out


async def process_source(row: dict, cache: Path, describer: Describer, vocab: C.Vocab, embedder: GeminiEmbedder, log=print, force: bool = False, dup_counts: dict | None = None) -> dict:
    t0 = time.monotonic()
    before = dict(describer.stats) if describer else {}
    kept, rep = await build_source_chunks(row, cache / "docling" / safe(row["src_id"]), describer, vocab, dup_counts=dup_counts)
    tc = time.monotonic()
    emb = await embed_and_insert({row["src_id"]: kept}, embedder=embedder, force=force, log=lambda *_: None) if kept else {"row_count_mismatch": {}}
    if emb["row_count_mismatch"]:
        raise RuntimeError(f"{row['src_id']}: rows != chunks {emb['row_count_mismatch']}")
    desc = {k: describer.stats[k] - before[k] for k in before} if describer else {}
    out = {"src_id": row["src_id"], "kind": row["kind"], "described": describer is not None, "mode": CHUNK_MODE, **rep, "describe": desc, "embedding_calls": emb.get("embedding_calls", 0), "embedding_tokens_est": emb.get("embedding_tokens_est", 0),
           "seconds": {"describe_chunk": round(tc - t0, 1), "embed_insert": round(time.monotonic() - tc, 1)}, "ts": round(time.time())}
    log(f"inserted {row['src_id']}: {rep['chunks']} chunks {rep['by_type']} from {rep['pages']} pages")
    return out


async def watch(manifest: Path, cache: Path, vocab: C.Vocab, describer: Describer, embedder: GeminiEmbedder, *, poll_s: float = 10, concurrency: int = 3, until_done: bool = True, log=print) -> dict:
    rows = {r["src_id"]: r for r in (json.loads(l) for l in manifest.read_text().splitlines() if l.strip())}
    table = get_settings().TABLE_NAME
    ledger_path = cache / ("ledger.jsonl" if table == "chunks" else f"ledger_{table}.jsonl")   # one ledger per index
    ledger = read_ledger(ledger_path)
    sem = asyncio.Semaphore(concurrency)
    dup_counts = corpus_figure_counts(cache)   # once per run: logos repeat across files (used by both caption and description modes)
    running: set[str] = set()
    failures: dict[str, str] = {}

    async def one(src):
        async with sem:
            try:
                rec = await process_source(rows[src], cache, describer, vocab, embedder, log, force=src in ledger, dup_counts=dup_counts)   # a redo (phase 2) replaces the rows even when the count is unchanged
                ledger[src] = rec
                with ledger_path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            except Exception as e:  # noqa: BLE001
                failures[src] = f"{type(e).__name__}: {e}"[:300]
                log(f"ERROR {src}: {failures[src]}")
            finally:
                running.discard(src)

    tasks: list[asyncio.Task] = []
    while True:
        done, counts = done_sources(cache / "queue.db")
        for src in done:
            # a source inserted without descriptions (phase 1) is redone when a describer is available (phase 2)
            finished = src in ledger and ledger[src].get("mode") == CHUNK_MODE and (ledger[src].get("described", True) or describer is None)
            if src in rows and not finished and src not in running and src not in failures:
                running.add(src)
                tasks.append(asyncio.create_task(one(src)))
        open_ = counts.get("pending", 0) + counts.get("leased", 0)
        if until_done and open_ == 0 and not running:
            break
        await asyncio.sleep(poll_s)
    await asyncio.gather(*tasks)
    failed_parse = {r[0] for r in sqlite3.connect(f"file:{cache / 'queue.db'}?mode=ro", uri=True).execute("SELECT src_id FROM task WHERE status='failed'")}
    missing = [s for s in rows if s not in ledger and s not in failed_parse]
    undescribed = sorted(s for s, r in ledger.items() if not r.get("described", True))
    return {"manifest_files": len(rows), "inserted": len(ledger), "parse_failed": sorted(failed_parse), "insert_failed": failures, "unaccounted": missing, "inserted_without_descriptions": len(undescribed)}
