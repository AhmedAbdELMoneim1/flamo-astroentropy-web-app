"""The parsing manifest: one row per distinct PDF of tier 2, from pipeline.db (never a guessed path or URL).

  papers     decision deep / shallow with a PDF; kept pages = sections abstract, results, discussion, conclusion
  documents  category Reports (results_report) and Science Documents (overview, data_guide, paper, results_report); all pages
             (Raw Data, Engineering Documents, presentations and the rest are not indexed: numbers belong to the tools)

    FLAMEO_DB=.../serving.db .venv/bin/python scripts/rag/make_manifest.py [--queue rag_cache/queue.db]
Writes rag_cache/manifest.jsonl; with --queue it also fills the master's task queue (idempotent).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

PAPER_SECTIONS = ("abstract", "results", "discussion", "conclusion")
DOC_ROLES = {"Reports": ("results_report",), "Science Documents": ("overview", "data_guide", "paper", "results_report")}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def build(pdb: Path, psi_root: Path, docs_root: Path, log=print) -> tuple[list[dict], list[dict]]:
    p = sqlite3.connect(f"file:{pdb}?mode=ro", uri=True)
    p.row_factory = sqlite3.Row
    rows: list[dict] = []
    missing: list[dict] = []

    for r in p.execute("SELECT * FROM paper WHERE decision IN ('deep','shallow') AND pdf_path IS NOT NULL"):
        path = psi_root / r["pdf_path"]
        secs = {x[0]: x[1] for x in p.execute("SELECT page_no, section FROM paper_page WHERE paper_id=? AND section IN (%s) ORDER BY page_no" % ",".join("?" * len(PAPER_SECTIONS)), (r["paper_id"], *PAPER_SECTIONS))}
        pages = sorted(secs)
        if not path.exists():
            missing.append({"src_id": r["paper_id"], "path": str(path), "why": "pdf not on disk"})
            continue
        if path.suffix.lower() != ".pdf":
            missing.append({"src_id": r["paper_id"], "path": str(path), "why": f"not a PDF ({path.suffix}): not parsed by the PDF workers"})
            continue
        if not pages:
            continue
        doi = r["doi"] or (r["paper_id"] if r["paper_id"].startswith("10.") else None)
        rows.append({"src_id": r["paper_id"], "kind": "paper", "path": str(path), "pages": r["n_pages"], "kept_pages": pages, "title": r["title"],
                     "psis": sorted(json.loads(r["psis_json"] or "[]")), "doi": doi, "download_url": None, "doc_category": None, "doc_role": None, "also_src_ids": [], "sections": {str(k): v for k, v in secs.items()}})

    link = {}
    for x in p.execute("SELECT l.doc_id, t.accession FROM doc_link l JOIN test t ON t.test_id = l.test_id WHERE l.superseded = 0"):
        link.setdefault(x[0], set()).add(x[1])
    for cat, roles in DOC_ROLES.items():
        for r in p.execute("SELECT * FROM doc WHERE dl_status='ok' AND category=? AND doc_role IN (%s)" % ",".join("?" * len(roles)), (cat, *roles)):
            path = docs_root / r["local_path"]
            if not path.exists():
                missing.append({"src_id": r["doc_id"], "path": str(path), "why": "pdf not on disk"})
                continue
            if path.suffix.lower() != ".pdf":      # the pilot found .docx / .doc files in the document list: docling cannot give them page numbers
                missing.append({"src_id": r["doc_id"], "path": str(path), "why": f"not a PDF ({path.suffix}): not parsed by the PDF workers", "pages": r["n_pages"], "title": r["file_name"]})
                continue
            folder = re.match(r"(PSI-\d+)/", r["local_path"] or "")
            psis = set(link.get(r["doc_id"], set())) | ({folder.group(1)} if folder else set())
            rows.append({"src_id": r["doc_id"], "kind": "doc", "path": str(path), "pages": r["n_pages"], "kept_pages": list(range(1, (r["n_pages"] or 0) + 1)),
                         "title": os.path.splitext(r["file_name"] or "")[0], "psis": sorted(psis), "doi": None, "download_url": r["download_url"], "doc_category": cat, "doc_role": r["doc_role"], "also_src_ids": [], "sections": {}})

    # one row per distinct file: the same sha256 is listed once, with every PSI and id that points at it
    by: dict[str, dict] = {}
    for r in rows:
        r["sha256"] = sha256(Path(r["path"]))
        k = by.get(r["sha256"])
        if k is None:
            by[r["sha256"]] = r
            continue
        keep, other = (k, r) if k["kind"] == "paper" or r["kind"] != "paper" else (r, k)
        keep["psis"] = sorted(set(keep["psis"]) | set(other["psis"]))
        keep["also_src_ids"] = sorted(set(keep["also_src_ids"]) | {other["src_id"]} | set(other["also_src_ids"]))
        keep["download_url"] = keep["download_url"] or other["download_url"]
        keep["doc_category"] = keep["doc_category"] or other["doc_category"]
        keep["doc_role"] = keep["doc_role"] or other["doc_role"]
        keep["kept_pages"] = sorted(set(keep["kept_pages"]) | (set(other["kept_pages"]) if other["kind"] == "doc" and keep["kind"] == "doc" else set()))
        by[r["sha256"]] = keep
    out = sorted(by.values(), key=lambda r: (-len(r["kept_pages"]), r["src_id"]))
    log(f"{len(rows)} rows -> {len(out)} distinct files; {sum(r['kind'] == 'paper' for r in out)} papers, {sum(r['kind'] == 'doc' for r in out)} documents; "
        f"{sum(len(r['kept_pages']) for r in out)} kept pages; {len(missing)} missing on disk")
    return out, missing


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--queue", type=Path)
    ap.add_argument("--out", type=Path, default=ROOT / "rag_cache" / "manifest.jsonl")
    a = ap.parse_args()
    sdb = Path(os.getenv("FLAMEO_DB") or Path.home() / "Desktop/nasa-multi-agents-stages/s1/s0-results/psi_stage1/local_data/serving.db")
    pdb = Path(os.getenv("PIPELINE_DB", sdb.parent / "pipeline.db"))
    psi_root = Path(os.getenv("PSI_ROOT", sdb.parent.parent))
    docs_root = Path(os.getenv("DOCS_ROOT", Path.home() / "Desktop/nasa-multi-agents-stages/Nasa-PSIs-Data/docs"))
    rows, missing = build(pdb, psi_root, docs_root)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    (a.out.parent / "manifest_missing.json").write_text(json.dumps(missing, indent=1))
    if a.queue:
        sys.path.insert(0, str(ROOT / "docker" / "rag-master"))
        from queue_db import TaskQueue
        n = TaskQueue(a.queue).load_manifest(rows)
        print(f"queue {a.queue}: {n} tasks added")


main()
