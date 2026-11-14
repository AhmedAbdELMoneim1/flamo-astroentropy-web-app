"""The document viewer endpoint: only documents of the serving.db `source` table, only .pdf files inside the docs root, never a path from the request."""
import sqlite3

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def env(tmp_path, monkeypatch):
    root = tmp_path / "docs"
    (root / "PSI-20").mkdir(parents=True)
    (root / "PSI-20" / "aaaaaaaaaaaa.pdf").write_bytes(b"%PDF-1.4 fake")
    (root / "PSI-20" / "bbbbbbbbbbbb.docx").write_bytes(b"docx")
    (tmp_path / "secret.pdf").write_bytes(b"%PDF secret")
    db = tmp_path / "serving.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE source(src_id TEXT PRIMARY KEY, kind TEXT, title TEXT, psi TEXT, doi TEXT, download_url TEXT, local_path TEXT, doc_category TEXT)")
    con.executemany("INSERT INTO source VALUES(?,?,?,?,?,?,?,?)", [
        ("aaaaaaaaaaaa", "document", "t", "PSI-20", None, "https://x", "PSI-20/aaaaaaaaaaaa.pdf", "Reports"),
        ("bbbbbbbbbbbb", "document", "t", "PSI-20", None, "https://x", "PSI-20/bbbbbbbbbbbb.docx", "Reports"),
        ("cccccccccccc", "document", "t", "PSI-20", None, "https://x", "../secret.pdf", "Reports"),
        ("dddddddddddd", "paper", "t", "PSI-20", "10.1/x", None, None, None)])
    con.commit(); con.close()
    monkeypatch.setenv("DOCS_ROOT", str(root))
    monkeypatch.setenv("FLAMEO_DB", str(db))
    return root, db


def test_a_known_document_is_served_inline_and_everything_else_is_404(env):
    from src.docs import local_pdf
    assert local_pdf("aaaaaaaaaaaa").name == "aaaaaaaaaaaa.pdf"
    for bad in ("bbbbbbbbbbbb",      # not a PDF
                "cccccccccccc",      # a path that leaves the docs root
                "dddddddddddd",      # a paper: DOI link only
                "eeeeeeeeeeee",      # unknown
                "../secret", "aaaaaaaaaaaa/../..", "AAAAAAAAAAAA", "", "aaaaaaaaaaa"):
        assert local_pdf(bad) is None, bad


def test_the_endpoint_streams_the_pdf_with_inline_disposition(env):
    from src.api import app
    c = TestClient(app)
    r = c.get("/api/docs/aaaaaaaaaaaa")
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf" and r.headers["content-disposition"] == "inline" and r.content.startswith(b"%PDF")
    for bad in ("bbbbbbbbbbbb", "cccccccccccc", "dddddddddddd", "..%2Fsecret", "zzzz"):
        assert c.get(f"/api/docs/{bad}").status_code == 404
