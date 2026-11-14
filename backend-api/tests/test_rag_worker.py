"""The worker loop against the real master app (TestClient) with a fake parser: lease, download, sha check, upload, fail, release."""
import hashlib
import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "docker" / "rag-master"), str(ROOT / "docker" / "docling-worker")]
from app import create_app  # noqa: E402
from parse import plan_runs, runs_of  # noqa: E402
from worker import Worker  # noqa: E402

TOKEN = "k" * 24


def fake_parse(pdf, kept, out, *, threads, ocr_lang, artifacts, worker_id, image_tag, sha256):
    out.mkdir(parents=True)
    (out / "blocks.jsonl").write_text('{"type":"text","page":1,"text":"x"}\n')
    done = {"pages_done": len(kept), "image_tag": image_tag, "docling_version": "2.149.0", "seconds_total": 1.5, "sha256": sha256, "worker_id": worker_id}
    (out / "done.json").write_text(json.dumps(done))
    return done


@pytest.fixture
def rig(tmp_path):
    pdfs, rows = tmp_path / "pdfs", []
    pdfs.mkdir()
    for n, pages in (("a", 3), ("b", 5), ("c", 1)):
        p = pdfs / f"{n}.pdf"; p.write_bytes(b"%PDF-" + n.encode() * 100)
        rows.append({"src_id": n, "kind": "doc", "path": str(p), "sha256": hashlib.sha256(p.read_bytes()).hexdigest(), "pages": pages, "kept_pages": list(range(1, pages + 1))})
    app = create_app(tmp_path / "cache", TOKEN)
    app.state.queue.load_manifest(rows)
    client = TestClient(app, base_url="http://master", headers={"Authorization": f"Bearer {TOKEN}"})
    return app, client, tmp_path


def test_worker_processes_the_whole_queue_and_cleans_up(rig):
    app, client, tmp = rig
    w = Worker(client, "w1-p0", tmp / "work", fake_parse, image_tag="img:1", heartbeat_s=60)
    assert w.run() == {"done": 3, "failed": 0}
    s = app.state.queue.status()
    assert s["counts"] == {"pending": 0, "leased": 0, "done": 3, "failed": 0} and s["pages"]["done"] == 9
    assert list((tmp / "work").iterdir()) == []                       # no PDF, output or archive left behind
    assert (tmp / "cache" / "docling" / "b" / "blocks.jsonl").exists()
    assert {x["worker_id"] for x in s["workers"]} == {"w1-p0"}


def test_max_tasks_stops_the_loop(rig):
    app, client, tmp = rig
    w = Worker(client, "w1-p0", tmp / "work", fake_parse, image_tag="img:1")
    assert w.run(max_tasks=2) == {"done": 2, "failed": 0}
    assert app.state.queue.status()["counts"]["pending"] == 1


def test_a_parse_error_is_reported_and_the_next_task_still_runs(rig):
    app, client, tmp = rig
    calls = []
    def flaky(pdf, kept, out, **kw):
        calls.append(len(kept))
        if len(calls) == 1:
            raise RuntimeError("bad pdf")
        return fake_parse(pdf, kept, out, **kw)
    w = Worker(client, "w1-p0", tmp / "work", flaky, image_tag="img:1")
    n = w.run()
    assert n["failed"] == 1 and n["done"] == 3                         # the failed file went back to pending (attempt 1 of 2) and was parsed on the retry
    assert app.state.queue.status()["counts"]["done"] == 3


def test_a_corrupted_download_is_not_parsed(rig):
    app, client, tmp = rig
    app.state.queue.db.execute("UPDATE task SET sha256='0'*64".replace("'0'*64", "'" + "0" * 64 + "'"))
    seen = []
    w = Worker(client, "w1-p0", tmp / "work", lambda *a, **k: seen.append(1), image_tag="img:1")
    n = w.run(max_tasks=1)
    assert n["failed"] == 1 and not seen


def test_runs_of_groups_contiguous_pages():
    assert runs_of([3, 4, 5, 9]) == [(3, 5), (9, 9)] and runs_of([]) == [] and runs_of([2, 1]) == [(1, 2)]


def test_ocr_runs_cover_only_the_pages_without_a_text_layer():
    assert plan_runs([1, 2, 3, 4, 5, 9], {1, 2, 4, 5, 9}) == [(1, 2, False), (3, 3, True), (4, 5, False), (9, 9, False)]
    assert plan_runs([7, 8], set()) == [(7, 8, True)] and plan_runs([], set()) == []


def test_long_runs_are_cut_so_one_convert_call_never_holds_a_whole_book_in_memory():
    runs = plan_runs(list(range(1, 31)), set(range(1, 31)), max_pages=12)
    assert runs == [(1, 12, False), (13, 24, False), (25, 30, False)]
    assert all(b - a + 1 <= 12 for a, b, _ in plan_runs(list(range(1, 145)), set(range(1, 145))))
