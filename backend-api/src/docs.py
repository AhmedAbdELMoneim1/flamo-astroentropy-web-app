"""The document viewer's file lookup (Round 6.3 / D6-4): a NASA PSI document is served from its LOCAL copy, found through the serving.db `source` table,
never through a path from the request. Papers have no viewer (publisher copyright): the DOI link only."""
from __future__ import annotations

import os
import re
import sqlite3
from pathlib import Path

DOC_ID = re.compile(r"^[0-9a-f]{12}$")


def docs_root() -> Path:
    return Path(os.getenv("DOCS_ROOT") or Path.home() / "Desktop/nasa-multi-agents-stages/Nasa-PSIs-Data/docs").resolve()


def local_pdf(doc_id: str, serving_db: str | None = None, root: Path | None = None) -> Path | None:
    """The PDF file of a document id, or None. Only ids of the `source` table (kind document) with a local path, only .pdf files inside the docs root."""
    if not DOC_ID.match(doc_id or ""):
        return None
    db = serving_db or os.getenv("FLAMEO_DB", "")
    if not db or not Path(db).exists():
        return None
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        row = con.execute("SELECT local_path FROM source WHERE src_id=? AND kind='document' AND local_path IS NOT NULL", (doc_id,)).fetchone()
    finally:
        con.close()
    if not row:
        return None
    base = (root or docs_root()).resolve()
    p = (base / row[0]).resolve()
    if base not in p.parents or p.suffix.lower() != ".pdf" or not p.is_file():
        return None
    return p
