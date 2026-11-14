"""The docling worker: lease a task from the master, download the PDF, parse it, upload the result, repeat. No API key, no outside network.

Env: MASTER_URL, WORKER_TOKEN (the LAN token), WORKER_ID, PROCS (files in parallel), THREADS_PER_PROC, OCR_LANG (default en),
     MAX_TASKS (0 = until the queue is empty), IMAGE_TAG, DOCLING_ARTIFACTS_PATH.
"""
from __future__ import annotations

import hashlib
import logging
import multiprocessing as mp
import os
import shutil
import signal
import tarfile
import threading
import time
from pathlib import Path

import httpx

log = logging.getLogger("worker")
HEARTBEAT_S = 60


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


class Worker:
    def __init__(self, client, worker_id: str, work: Path, parse, *, threads: int = 2, ocr_lang: str = "en", image_tag: str = "", artifacts: str | None = None, heartbeat_s: float = HEARTBEAT_S) -> None:
        self.c, self.id, self.work, self.parse = client, worker_id, work, parse
        self.threads, self.ocr_lang, self.image_tag, self.artifacts, self.heartbeat_s = threads, ocr_lang, image_tag, artifacts, heartbeat_s
        self.stop = threading.Event()
        work.mkdir(parents=True, exist_ok=True)

    def _beat(self, src_id: str, done: threading.Event) -> None:
        while not done.wait(self.heartbeat_s):
            try:
                self.c.post("/heartbeat", json={"worker_id": self.id, "src_id": src_id})
            except Exception:  # noqa: BLE001
                log.warning("heartbeat failed", exc_info=True)

    def one(self) -> str:
        """One task. Returns 'done', 'failed' or 'empty'."""
        r = self.c.post("/lease", json={"worker_id": self.id})
        if r.status_code == 204:
            return "empty"
        r.raise_for_status()
        t = r.json()
        src = t["src_id"]
        safe = hashlib.sha1(src.encode()).hexdigest()[:12]
        pdf, out, tgz = self.work / f"{safe}.pdf", self.work / f"{safe}_out", self.work / f"{safe}.tar.gz"
        done_evt = threading.Event()
        threading.Thread(target=self._beat, args=(src, done_evt), daemon=True).start()
        try:
            with self.c.stream("GET", f"/pdf/{src}") as resp:
                resp.raise_for_status()
                with pdf.open("wb") as f:
                    for chunk in resp.iter_bytes(1 << 20):
                        f.write(chunk)
            if sha256_file(pdf) != t["sha256"]:
                raise RuntimeError("downloaded file does not match the manifest sha256")
            info = self.parse(pdf, t["kept_pages"], out, threads=self.threads, ocr_lang=self.ocr_lang, artifacts=self.artifacts, worker_id=self.id, image_tag=self.image_tag, sha256=t["sha256"])
            with tarfile.open(tgz, "w:gz") as tf:
                tf.add(out, arcname=".")
            with tgz.open("rb") as f:
                resp = self.c.post(f"/result/{src}", content=f, headers={"Content-Type": "application/gzip"})
            resp.raise_for_status()
            log.info("done %s: %d pages in %.0fs, upload %.1f MB", src, info["pages_done"], info["seconds_total"], tgz.stat().st_size / 1e6)
            return "done"
        except Exception as e:  # noqa: BLE001
            log.error("failed %s: %s", src, e)
            try:
                self.c.post(f"/fail/{src}", json={"worker_id": self.id, "error": f"{type(e).__name__}: {e}"[:400]})
            except Exception:  # noqa: BLE001
                pass
            return "failed"
        finally:
            done_evt.set()
            shutil.rmtree(out, ignore_errors=True)
            pdf.unlink(missing_ok=True)
            tgz.unlink(missing_ok=True)

    def run(self, max_tasks: int = 0) -> dict:
        n = {"done": 0, "failed": 0}
        while not self.stop.is_set():
            if max_tasks and n["done"] + n["failed"] >= max_tasks:
                break
            s = self.one()
            if s == "empty":
                break
            n[s] += 1
        try:
            self.c.post("/release", json={"worker_id": self.id})   # a leased task of an interrupted run goes back to the queue
        except Exception:  # noqa: BLE001
            pass
        return n


def _proc(i: int, env: dict) -> None:
    from parse import parse_pdf   # imported in the process: docling loads its models there

    threads = int(env["THREADS_PER_PROC"])
    os.environ["OMP_NUM_THREADS"] = os.environ["MKL_NUM_THREADS"] = str(threads)
    try:
        import torch
        torch.set_num_threads(threads)
    except Exception:  # noqa: BLE001
        pass
    client = httpx.Client(base_url=env["MASTER_URL"], headers={"Authorization": f"Bearer {env['WORKER_TOKEN']}"}, timeout=httpx.Timeout(60, read=600))
    w = Worker(client, f"{env['WORKER_ID']}-p{i}", Path(env.get("WORK_DIR", "/work")) / f"p{i}", parse_pdf, threads=threads, ocr_lang=env.get("OCR_LANG", "en"),
               image_tag=env.get("IMAGE_TAG", ""), artifacts=env.get("DOCLING_ARTIFACTS_PATH") or None)
    signal.signal(signal.SIGTERM, lambda *_: w.stop.set())
    print(f"[{w.id}] {w.run(int(env.get('MAX_TASKS', 0) or 0))}", flush=True)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    env = dict(os.environ)
    for k in ("MASTER_URL", "WORKER_TOKEN", "WORKER_ID", "THREADS_PER_PROC"):
        if not env.get(k):
            raise SystemExit(f"{k} is not set (see .env.example)")
    procs = [mp.get_context("spawn").Process(target=_proc, args=(i, env)) for i in range(int(env.get("PROCS", "1")))]
    for p in procs:
        p.start()
    for p in procs:
        p.join()


if __name__ == "__main__":
    main()
