"""logs/questions.jsonl: one line per tool call {id, ts, transcript, tool, args, matched, source: voice|typed}; a turn without any tool has tool null.

No audio and no keys. The team reads it after a voice test to see how Gemini really routes questions and to add
router examples where it picks badly. The file is never committed (logs/ is in .gitignore).
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from pathlib import Path

logger = logging.getLogger("qlog")

PATH = Path(os.getenv("QUESTIONS_LOG", Path(__file__).resolve().parent.parent / "logs" / "questions.jsonl"))


_lock = threading.Lock()


def log(transcript: str | None, tool: str | None, args: dict, matched: bool | None, source: str | None = None, router: dict | None = None) -> str | None:
    """Append one line and return its id (so a transcript that arrives after the tool call can be filled in). Never raises."""
    try:
        PATH.parent.mkdir(parents=True, exist_ok=True)
        lid = uuid.uuid4().hex[:8]
        line = {"id": lid, "ts": round(time.time(), 3), "transcript": (transcript or "")[:300], "tool": tool, "args": args, "matched": matched, "source": source, **({"router": router} if router else {})}
        with _lock, PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")
        return lid
    except Exception:
        logger.warning("could not write the question log", exc_info=True)
        return None


def amend(ids: list[str], transcript: str) -> None:
    """Set the transcript of earlier lines (the speech-to-text result can arrive after the tool call). Never raises."""
    if not ids or not transcript:
        return
    try:
        with _lock:
            if not PATH.exists():
                return
            out, changed = [], False
            for raw in PATH.read_text(encoding="utf-8").splitlines():
                try:
                    d = json.loads(raw)
                except ValueError:
                    out.append(raw)
                    continue
                if d.get("id") in ids and d.get("transcript") != transcript[:300]:
                    d["transcript"], changed = transcript[:300], True
                    raw = json.dumps(d, ensure_ascii=False)
                out.append(raw)
            if changed:
                PATH.write_text("\n".join(out) + "\n", encoding="utf-8")
    except Exception:
        logger.warning("could not amend the question log", exc_info=True)
