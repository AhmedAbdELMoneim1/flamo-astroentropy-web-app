"""The parsing master: queue order, leases, PDF streaming, result checks, auth (FastAPI TestClient, no docling, no network)."""
import hashlib
import io
import json
import sys
import tarfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "docker" / "rag-master"))
from app import create_app  # noqa: E402

TOKEN = "t" * 24
H = {"Authorization": f"Bearer {TOKEN}"}


class Clock:
    t = 1000.0
    def __call__(self): return self.t


def sha(b): return hashlib.sha256(b).hexdigest()


@pytest.fixture
def env(tmp_path):
    pdfs = tmp_path / "pdfs"; pdfs.mkdir()
    rows = []
    for name, pages in (("small", 2), ("big", 9), ("mid", 4)):
        p = pdfs / f"{name}.pdf"; p.write_bytes(b"%PDF-" + name.encode() * 50)
        rows.append({"src_id": name if name != "mid" else "10.1000/mid", "kind": "doc", "path": str(p), "sha256": sha(p.read_bytes()), "pages": pages, "kept_pages": list(range(1, pages + 1))})
    clock = Clock()
    app = create_app(tmp_path / "rag_cache", TOKEN, lease_minutes=1, max_attempts=2, clock=clock)
    app.state.queue.load_manifest(rows)
    return TestClient(app), app, clock, rows, tmp_path


def tarball(files: dict, ) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name, data in files.items():
            ti = tarfile.TarInfo(name); ti.size = len(data); tf.addfile(ti, io.BytesIO(data))
    return buf.getvalue()


def good(rows, src, tag="img:1", ver="2.132.0", pages=None):
    r = next(x for x in rows if x["src_id"] == src)
    done = {"pages_done": len(r["kept_pages"]) if pages is None else pages, "image_tag": tag, "docling_version": ver, "seconds_total": 12.5, "sha256": r["sha256"], "worker_id": "w1"}
    return tarball({"done.json": json.dumps(done).encode(), "blocks.jsonl": b'{"type":"text"}\n'})


def test_every_request_needs_the_token(env):
    c, *_ = env
    assert c.post("/lease", json={"worker_id": "w"}).status_code == 401
    assert c.post("/lease", json={"worker_id": "w"}, headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert c.get("/status").status_code == 401 and c.get("/pdf/big").status_code == 401


def test_leases_the_largest_file_first_and_204_when_empty(env):
    c, *_ = env
    got = [c.post("/lease", json={"worker_id": "w"}, headers=H).json()["src_id"] for _ in range(3)]
    assert got == ["big", "10.1000/mid", "small"]
    assert c.post("/lease", json={"worker_id": "w"}, headers=H).status_code == 204


def test_pdf_streams_with_its_sha256_and_only_manifest_files(env):
    c, _, _, rows, tmp = env
    r = c.get("/pdf/big", headers=H)
    assert r.status_code == 200 and r.headers["x-sha256"] == rows[1]["sha256"] and r.content.startswith(b"%PDF-")
    assert c.get("/pdf/10.1000/mid", headers=H).status_code == 200      # a DOI with a slash
    (tmp / "secret.txt").write_text("x")
    for bad in ("../secret.txt", "..%2Fsecret.txt", "/etc/passwd", str(tmp / "secret.txt"), "nope"):
        assert c.get(f"/pdf/{bad}", headers=H).status_code == 404


def test_a_lease_expires_without_heartbeat_and_a_heartbeat_extends_it(env):
    c, app, clock, *_ = env
    t = c.post("/lease", json={"worker_id": "w1"}, headers=H).json()
    clock.t += 50
    assert c.post("/heartbeat", json={"worker_id": "w1", "src_id": t["src_id"]}, headers=H).status_code == 200
    clock.t += 50                                                         # 100 s since the lease, 50 since the beat: still leased
    assert app.state.queue.status()["counts"]["leased"] == 1
    clock.t += 20                                                         # now past the extended lease
    s = app.state.queue.status()
    assert s["counts"]["pending"] == 3 and s["counts"]["leased"] == 0
    assert c.post("/heartbeat", json={"worker_id": "w1", "src_id": t["src_id"]}, headers=H).status_code == 409


def test_at_most_max_attempts_then_failed(env):
    c, app, clock, *_ = env
    for _ in range(2):
        t = c.post("/lease", json={"worker_id": "w"}, headers=H).json()
        assert t["src_id"] == "big"
        c.post("/fail/big", json={"error": "boom"}, headers=H) if _ == 0 else None
        clock.t += 100                                                    # the second attempt just expires
    s = app.state.queue.status()
    assert s["counts"]["failed"] == 1 and s["failed"][0]["src_id"] == "big"
    assert c.post("/lease", json={"worker_id": "w"}, headers=H).json()["src_id"] == "10.1000/mid"


def test_result_is_checked_unpacked_and_marks_done(env):
    c, app, _, rows, tmp = env
    t = c.post("/lease", json={"worker_id": "w1"}, headers=H).json()
    r = c.post(f"/result/{t['src_id']}", content=good(rows, t["src_id"]), headers=H)
    assert r.status_code == 200 and r.json() == {"status": "done", "pages": 9}
    assert (tmp / "rag_cache" / "docling" / "big" / "blocks.jsonl").exists()
    assert app.state.queue.get("big")["status"] == "done"
    s = c.get("/status", headers=H).json()
    assert s["counts"]["done"] == 1 and s["pages"]["done"] == 9


def test_result_with_another_image_tag_or_wrong_page_count_is_rejected(env):
    c, app, _, rows, tmp = env
    a = c.post("/lease", json={"worker_id": "w1"}, headers=H).json()["src_id"]
    assert c.post(f"/result/{a}", content=good(rows, a, tag="img:1"), headers=H).status_code == 200      # pins img:1
    b = c.post("/lease", json={"worker_id": "w2"}, headers=H).json()["src_id"]
    r = c.post(f"/result/{b}", content=good(rows, b, tag="img:2"), headers=H)
    assert r.status_code == 422 and "image tag" in r.json()["detail"]
    assert app.state.queue.get(b)["status"] == "pending"                                                 # back in the queue for another worker
    b = c.post("/lease", json={"worker_id": "w2"}, headers=H).json()["src_id"]
    r = c.post(f"/result/{b}", content=good(rows, b, tag="img:1", pages=1), headers=H)
    assert r.status_code == 422 and "pages" in r.json()["detail"]
    assert not (tmp / "rag_cache" / "docling" / "small").exists()


def test_unsafe_tar_members_are_rejected(env):
    c, _, _, rows, tmp = env
    t = c.post("/lease", json={"worker_id": "w"}, headers=H).json()["src_id"]
    evil = tarball({"../../escape.txt": b"x", "done.json": b"{}"})
    assert c.post(f"/result/{t}", content=evil, headers=H).status_code == 422
    assert not (tmp / "escape.txt").exists() and not (tmp.parent / "escape.txt").exists()


def test_a_result_without_a_lease_is_refused(env):
    c, _, _, rows, _ = env
    assert c.post("/result/big", content=good(rows, "big"), headers=H).status_code == 409


def test_empty_token_refuses_to_start(tmp_path):
    with pytest.raises(RuntimeError):
        create_app(tmp_path, "")


def test_many_threads_can_read_and_lease_at_once(env):
    """Regression: 8 worker processes hit the master together; one shared sqlite connection raised 'bad parameter or other API misuse' and a false 404."""
    from concurrent.futures import ThreadPoolExecutor
    c, *_ = env
    def hit(i):
        return [c.get("/pdf/big", headers=H).status_code, c.post("/lease", json={"worker_id": f"w{i}"}, headers=H).status_code, c.get("/status", headers=H).status_code]
    with ThreadPoolExecutor(16) as ex:
        res = [x for r in ex.map(hit, range(64)) for x in r]
    assert set(res) <= {200, 204} and res.count(404) == 0 and res.count(500) == 0
