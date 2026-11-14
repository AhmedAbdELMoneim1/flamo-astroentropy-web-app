"""The parsing master: a small FastAPI service in front of the task queue. It holds the PDFs, hands out tasks, receives results.
No API key lives here or on a worker; the only secret is the LAN WORKER_TOKEN (a bearer header on every request)."""
from __future__ import annotations

import hmac
import json
import os
import re
import shutil
import tarfile
import time
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, Response
from pydantic import BaseModel

from queue_db import TaskQueue


def safe_name(src_id: str) -> str:
    """A src_id (a DOI has slashes) as one folder name."""
    return re.sub(r"[^A-Za-z0-9._-]", "_", src_id)


class Lease(BaseModel):
    worker_id: str


class Beat(BaseModel):
    worker_id: str
    src_id: str


class Fail(BaseModel):
    worker_id: str | None = None
    error: str = ""


def create_app(cache: Path, token: str, *, lease_minutes: float = 30, max_attempts: int = 2, expected_image_tag: str = "", max_upload_mb: int = 800, clock=time.time) -> FastAPI:
    if not token:
        raise RuntimeError("WORKER_TOKEN is empty: set it in .env (a random LAN secret)")
    app = FastAPI(title="rag-master")
    q = TaskQueue(cache / "queue.db", max_attempts=max_attempts, clock=clock)
    app.state.queue, app.state.expected = q, {"image_tag": expected_image_tag, "docling_version": ""}
    out_root = cache / "docling"
    out_root.mkdir(parents=True, exist_ok=True)
    lease_s = lease_minutes * 60

    def auth(request: Request) -> None:
        got = request.headers.get("authorization", "")
        if not got.startswith("Bearer ") or not hmac.compare_digest(got[7:].encode(), token.encode()):
            raise HTTPException(401, "bad or missing token")

    @app.post("/lease", dependencies=[Depends(auth)])
    def lease(body: Lease):
        t = q.lease(body.worker_id, lease_s)
        return Response(status_code=204) if t is None else t

    @app.get("/pdf/{src_id:path}", dependencies=[Depends(auth)])
    def pdf(src_id: str):
        r = q.get(src_id)                                   # only files of the manifest; the path comes from the queue, never from the request
        if r is None or not Path(r["path"]).is_file():
            raise HTTPException(404, "not in the manifest")
        return FileResponse(r["path"], media_type="application/pdf", headers={"X-SHA256": r["sha256"]})

    @app.post("/heartbeat", dependencies=[Depends(auth)])
    def heartbeat(b: Beat):
        if not q.heartbeat(b.worker_id, b.src_id, lease_s):
            raise HTTPException(409, "no such lease")
        return {"ok": True}

    @app.post("/fail/{src_id:path}", dependencies=[Depends(auth)])
    def fail(src_id: str, b: Fail):
        return {"status": q.fail(src_id, b.error)}

    @app.post("/release", dependencies=[Depends(auth)])
    def release(b: Lease):
        return {"released": q.release_worker(b.worker_id)}

    @app.post("/result/{src_id:path}", dependencies=[Depends(auth)])
    async def result(src_id: str, request: Request):
        r = q.get(src_id)
        if r is None or r["status"] != "leased":
            raise HTTPException(409, "no open lease for this file")
        tmp = cache / "uploads" / f"{safe_name(src_id)}.tar.gz"
        tmp.parent.mkdir(parents=True, exist_ok=True)
        size = 0
        with tmp.open("wb") as f:
            async for chunk in request.stream():
                size += len(chunk)
                if size > max_upload_mb * 1024 * 1024:
                    f.close(); tmp.unlink(missing_ok=True)
                    raise HTTPException(413, "upload too large")
                f.write(chunk)
        dest = out_root / safe_name(src_id)
        stage = out_root / (safe_name(src_id) + ".partial")
        shutil.rmtree(stage, ignore_errors=True)
        try:
            with tarfile.open(tmp, "r:gz") as tf:
                for m in tf.getmembers():                     # only plain files and folders, nothing that leaves the folder
                    if not (m.isfile() or m.isdir()) or m.name.startswith("/") or ".." in Path(m.name).parts:
                        raise ValueError(f"unsafe member {m.name!r}")
                tf.extractall(stage, filter="data")
            done = json.loads((stage / "done.json").read_text())
            exp = app.state.expected
            tag, ver = str(done.get("image_tag", "")), str(done.get("docling_version", ""))
            if exp["image_tag"] and tag != exp["image_tag"]:
                raise ValueError(f"image tag {tag!r} is not the expected {exp['image_tag']!r}")
            if exp["docling_version"] and ver != exp["docling_version"]:
                raise ValueError(f"docling version {ver!r} is not {exp['docling_version']!r}")
            if int(done.get("pages_done", -1)) != r["n_kept"]:
                raise ValueError(f"done.json says {done.get('pages_done')} pages, the task has {r['n_kept']} kept pages")
            if done.get("sha256") and done["sha256"] != r["sha256"]:
                raise ValueError("the worker parsed a file with another sha256")
        except Exception as e:  # noqa: BLE001
            shutil.rmtree(stage, ignore_errors=True)
            tmp.unlink(missing_ok=True)
            q.fail(src_id, f"result rejected: {e}")
            raise HTTPException(422, f"result rejected: {e}") from e
        if not exp["image_tag"]:                              # the first accepted result pins the image: the others must match it
            exp["image_tag"], exp["docling_version"] = tag, ver
        shutil.rmtree(dest, ignore_errors=True)
        stage.rename(dest)
        tmp.unlink(missing_ok=True)
        q.complete(src_id, float(done.get("seconds_total", 0)), tag, ver, size)
        return {"status": "done", "pages": r["n_kept"]}

    @app.get("/status", dependencies=[Depends(auth)])
    def status():
        return q.status()

    @app.get("/", response_class=HTMLResponse)
    def page():
        """A tiny page for the team to watch (it shows counts only; the data comes from /status with the token)."""
        return """<!doctype html><meta charset=utf-8><title>RAG parsing</title><body style="font:15px system-ui;margin:24px;max-width:900px">
<h2>RAG parsing queue</h2><p>Token: <input id=t type=password size=30> <button onclick="go()">watch</button></p><pre id=o>enter the token</pre>
<script>let h;function go(){clearInterval(h);const f=async()=>{const r=await fetch('/status',{headers:{Authorization:'Bearer '+document.getElementById('t').value}});
document.getElementById('o').textContent=r.ok?JSON.stringify(await r.json(),null,1):'HTTP '+r.status};f();h=setInterval(f,5000)}</script>"""

    return app


def from_env() -> FastAPI:
    app = create_app(Path(os.getenv("RAG_CACHE", "/app/rag_cache")), os.getenv("WORKER_TOKEN", ""), lease_minutes=float(os.getenv("LEASE_MINUTES", "30")),
                     max_attempts=int(os.getenv("MAX_ATTEMPTS", "2")), expected_image_tag=os.getenv("EXPECTED_IMAGE_TAG", ""))
    manifest = Path(os.getenv("MANIFEST", "/app/rag_cache/manifest.jsonl"))
    if manifest.exists():
        app.state.queue.load_manifest([json.loads(l) for l in manifest.read_text().splitlines() if l.strip()])
    return app
