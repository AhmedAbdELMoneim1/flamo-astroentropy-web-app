"""The master's task queue (SQLite, rag_cache/queue.db). Largest files first, so the long jobs do not finish last."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS task(
  src_id TEXT PRIMARY KEY, kind TEXT, path TEXT, sha256 TEXT, pages INTEGER, kept_pages TEXT,
  status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','leased','done','failed')),
  worker_id TEXT, lease_until REAL, attempts INTEGER NOT NULL DEFAULT 0, secs REAL, error TEXT,
  done_at REAL, image_tag TEXT, docling_version TEXT, n_kept INTEGER NOT NULL DEFAULT 0, upload_bytes INTEGER
);
CREATE INDEX IF NOT EXISTS task_status ON task(status, n_kept DESC);
"""


class TaskQueue:
    def __init__(self, path: Path | str, max_attempts: int = 2, clock=time.time) -> None:
        self.path, self.max_attempts, self.clock = Path(path), max_attempts, clock
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()   # one sqlite connection is shared by the request threads: every use takes the lock (re-entrant: fail() reads)
        self.db = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)

    def load_manifest(self, rows: list[dict]) -> int:
        """Add the manifest's files (idempotent: a known src_id keeps its status). Returns the number added."""
        n = 0
        with self._lock:
            for r in rows:
                cur = self.db.execute(
                    "INSERT OR IGNORE INTO task(src_id, kind, path, sha256, pages, kept_pages, n_kept) VALUES(?,?,?,?,?,?,?)",
                    (r["src_id"], r["kind"], r["path"], r["sha256"], r.get("pages"), json.dumps(r["kept_pages"]), len(r["kept_pages"])))
                n += cur.rowcount
        return n

    def _expire(self) -> None:
        now = self.clock()
        self.db.execute("UPDATE task SET status='failed', error=COALESCE(error,'')||' lease expired after the last attempt', worker_id=NULL WHERE status='leased' AND lease_until<? AND attempts>=?", (now, self.max_attempts))
        self.db.execute("UPDATE task SET status='pending', worker_id=NULL WHERE status='leased' AND lease_until<?", (now,))

    def lease(self, worker_id: str, lease_s: float) -> dict | None:
        with self._lock:
            self._expire()
            r = self.db.execute("SELECT * FROM task WHERE status='pending' ORDER BY n_kept DESC, src_id LIMIT 1").fetchone()
            if r is None:
                return None
            self.db.execute("UPDATE task SET status='leased', worker_id=?, lease_until=?, attempts=attempts+1 WHERE src_id=?", (worker_id, self.clock() + lease_s, r["src_id"]))
            return {"src_id": r["src_id"], "kind": r["kind"], "sha256": r["sha256"], "pages": r["pages"], "kept_pages": json.loads(r["kept_pages"]), "attempt": r["attempts"] + 1}

    def get(self, src_id: str) -> sqlite3.Row | None:
        with self._lock:
            return self.db.execute("SELECT * FROM task WHERE src_id=?", (src_id,)).fetchone()

    def reset_for_retry(self) -> int:
        """Everything not done goes back to pending with a fresh attempt count (used after a master bug, never needed in normal runs)."""
        with self._lock:
            return self.db.execute("UPDATE task SET status='pending', worker_id=NULL, attempts=0, error=NULL WHERE status!='done'").rowcount

    def heartbeat(self, worker_id: str, src_id: str, lease_s: float) -> bool:
        with self._lock:
            cur = self.db.execute("UPDATE task SET lease_until=? WHERE src_id=? AND worker_id=? AND status='leased'", (self.clock() + lease_s, src_id, worker_id))
            return cur.rowcount == 1

    def complete(self, src_id: str, secs: float, image_tag: str, docling_version: str, upload_bytes: int) -> None:
        with self._lock:
            self.db.execute("UPDATE task SET status='done', secs=?, done_at=?, image_tag=?, docling_version=?, upload_bytes=?, error=NULL WHERE src_id=?", (secs, self.clock(), image_tag, docling_version, upload_bytes, src_id))

    def fail(self, src_id: str, error: str) -> str:
        """A worker reports an error: back to pending until MAX_ATTEMPTS is used up, then failed. Returns the new status."""
        with self._lock:
            r = self.get(src_id)
            if r is None:
                return "unknown"
            status = "failed" if r["attempts"] >= self.max_attempts else "pending"
            self.db.execute("UPDATE task SET status=?, worker_id=NULL, error=? WHERE src_id=?", (status, error[:500], src_id))
            return status

    def release_worker(self, worker_id: str) -> int:
        with self._lock:
            return self.db.execute("UPDATE task SET status='pending', worker_id=NULL WHERE status='leased' AND worker_id=?", (worker_id,)).rowcount

    def status(self) -> dict:
        with self._lock:
            self._expire()
            counts = {r[0]: r[1] for r in self.db.execute("SELECT status, count(*) FROM task GROUP BY 1")}
            pages = {r[0]: r[1] or 0 for r in self.db.execute("SELECT status, sum(n_kept) FROM task GROUP BY 1")}
            workers = [dict(r) for r in self.db.execute("SELECT worker_id, count(*) AS files, sum(n_kept) AS pages, sum(secs) AS secs FROM task WHERE status='done' GROUP BY 1")]
            leased = [dict(r) for r in self.db.execute("SELECT src_id, worker_id, n_kept AS pages, attempts, lease_until FROM task WHERE status='leased'")]
            failed = [dict(r) for r in self.db.execute("SELECT src_id, error, attempts FROM task WHERE status='failed'")]
            first, last = self.db.execute("SELECT min(done_at - secs), max(done_at) FROM task WHERE status='done'").fetchone()
        done_p, todo_p = pages.get("done", 0), pages.get("pending", 0) + pages.get("leased", 0)
        wall = (last - first) if first and last and last > first else 0
        rate = done_p / wall if wall > 0 else 0.0         # pages per second of wall clock, all workers together
        for w in workers:
            w["pages_per_min"] = round(60 * w["pages"] / w["secs"], 2) if w["secs"] else None
        return {"counts": {k: counts.get(k, 0) for k in ("pending", "leased", "done", "failed")}, "pages": {"done": done_p, "todo": todo_p},
                "pages_per_min_all": round(rate * 60, 2), "eta_minutes": round(todo_p / rate / 60) if rate else None, "workers": workers, "leased": leased, "failed": failed}
