"""logs/retrieval.jsonl: one JSON line per ask_sources call, plus a short console summary (RAG_LOG=off|summary|full, default summary).

No key values, no audio. `full` adds the whole raw_text of the reranked chunks. Key indexes appear as e.g. "cohere#3".
"""
from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path

logger = logging.getLogger("retrieval")
PATH = Path(os.getenv("RETRIEVAL_LOG", Path(__file__).resolve().parent.parent.parent / "logs" / "retrieval.jsonl"))
_lock = threading.Lock()


def mode() -> str:
    m = os.getenv("RAG_LOG", "summary").lower()
    return m if m in ("off", "summary", "full") else "summary"


def summary_line(e: dict) -> str:
    kept = sum(1 for s in e.get("composer", {}).get("sentences", []) if s.get("kept"))
    total = sum(1 for _ in e.get("composer", {}).get("sentences", []))
    lat = e.get("latency_ms", {})
    return (f"ask_sources [{e['request_id']}] {e['outcome']} via {e.get('path', '?')} | scope {e['scope'].get('n_psis', '-')} PSIs / {e['scope'].get('n_sources', '-')} sources"
            f" | top {len(e.get('reranked', []))} | sentences kept {kept}/{total} | {lat.get('total', '?')} ms | {e['question'][:60]!r}")


def write(entry: dict) -> None:
    m = mode()
    if m == "off":
        return
    if m != "full":
        for r in entry.get("reranked", []):
            r.pop("raw_text", None)
    try:
        PATH.parent.mkdir(parents=True, exist_ok=True)
        with _lock, PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001
        logger.warning("could not write the retrieval log", exc_info=True)
    logger.info(summary_line(entry))
    print(summary_line(entry), flush=True)
