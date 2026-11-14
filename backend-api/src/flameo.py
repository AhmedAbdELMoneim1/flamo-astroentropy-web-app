"""Access to the vendored flameo_tools (read-only serving.db, stdlib only).

`init()` is called once at start-up (agent.py, api.py). It fails with a clear message when FLAMEO_DB is unset or the
file is missing, and logs the flameo version. `call()` runs one intent tool (blocking: use asyncio.to_thread).
"""

from __future__ import annotations

import logging
import os
import sys
import threading
from pathlib import Path

VENDOR = Path(__file__).resolve().parent.parent / "vendor"
if str(VENDOR) not in sys.path:
    sys.path.insert(0, str(VENDOR))

import flameo_tools as _F  # noqa: E402
from flameo_tools import shapes as _shapes  # noqa: E402

logger = logging.getLogger("flameo")

_ready = False
# flameo_tools keeps ONE read-only sqlite connection per db file, and a sqlite3 connection must not run two statements
# at once (concurrent calls from asyncio.to_thread raised "bad parameter or other API misuse"). Calls take milliseconds,
# so they are simply serialized here.
_LOCK = threading.Lock()


class FlameoNotConfigured(RuntimeError):
    pass


def init(path: str | os.PathLike | None = None) -> str:
    """Point flameo_tools at serving.db. Raises FlameoNotConfigured with a plain message when it cannot."""
    global _ready
    raw = str(path or os.getenv("FLAMEO_DB", "")).strip()
    if not raw:
        raise FlameoNotConfigured("FLAMEO_DB is not set. Point it at serving.db (see .env.example).")
    p = Path(raw).expanduser()
    if not p.is_file():
        raise FlameoNotConfigured(f"FLAMEO_DB points to a missing file: {p}")
    _F.configure(p)
    _F.tools._CON.clear()
    _ready = True
    logger.info("flameo_tools version %s, serving.db %s (%.1f MB)", _shapes.VERSION, p.name, p.stat().st_size / 1e6)
    return str(p)


def ready() -> bool:
    return _ready


def call(name: str, **kwargs) -> dict:
    with _LOCK:
        return _F.call(name, **{k: v for k, v in kwargs.items() if v is not None})


def specs() -> list[dict]:
    return _F.tool_specs()


def labels() -> dict:
    """Display labels per field from flameo's own config (config/serving.yaml `labels`), for table headers."""
    from flameo_tools import queries as Q

    with _LOCK:
        return Q.cfg(_F.tools.con()).get("labels", {})


def psi_name(psi: str) -> str:
    """"Saffire-II" for PSI-99 (the name the voice uses), or the id when unknown."""
    with _LOCK:
        full = _F.tools._nm(_F.tools.con(), psi)
    return full.split(" (")[0] if full else psi


def specs_names() -> set:
    return {x["name"] for x in _F.tool_specs()}


def tolerance() -> dict | None:
    """How close a test must be to count as "near" in nearest_tests: {o2_pts, p_rel}, read from flameo's own config (never hard-coded here)."""
    try:
        from flameo_tools import queries as _Q, tools as _T
        with _LOCK:
            t = _Q.cfg(_T.con())["groups"]["tol"]
        return {"o2_pts": t["o2_pts"], "p_rel": t["p_rel"]}
    except Exception:        # the chart just draws no tolerance box
        return None
