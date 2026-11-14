"""Chunks from a worker's result (blocks.jsonl + figures/), following the contract of Round 7 §7.3 and §7.7.

  text    the team's splitter (600 / 100 characters, same separators), per page block, never across a page
  table   split by rows with the header repeated; raw_text = caption + the extracted markdown ONLY; the model's description goes in
          `text` (what is embedded) and metadata.table_desc, never in raw_text
  figure  generated: true; raw_text = caption + the model's summary (a figure can be cited for what it shows, never as a number's source)
Then the drop rules (too short, junk, mostly numbers, exact duplicates).
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from langchain_text_splitters import RecursiveCharacterTextSplitter

from src.paper_rag import chunks as C
from src.paper_rag.describe import Describer, item_key

CHUNK_MODE = "caption-v1"   # recorded in the ledger: a source indexed in another mode is redone (figures by caption, tables labelled by their caption)
FIG_CONTEXT_CHARS = 300
CHUNK_SIZE, CHUNK_OVERLAP, TABLE_MAX_CHARS = 600, 100, 4000
SEPARATORS = ["\n\n", "\n", ". ", "؟ ", "! ", " ", ""]
_splitter = RecursiveCharacterTextSplitter(chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP, separators=SEPARATORS)


def split_table(md: str, max_chars: int = TABLE_MAX_CHARS) -> list[str]:
    """A small table is one part; a large one is split by rows with the header (two lines) repeated."""
    lines = md.strip().split("\n")
    if len(md) <= max_chars or len(lines) < 4:
        return [md]
    header, rows = lines[:2], lines[2:]
    h = sum(len(x) + 1 for x in header)
    parts, cur, size = [], [], h
    for r in rows:
        if cur and size + len(r) + 1 > max_chars:
            parts.append("\n".join(header + cur))
            cur, size = [], h
        cur.append(r)
        size += len(r) + 1
    if cur:
        parts.append("\n".join(header + cur))
    return parts


# Figures the worker extracts include logos, banners and hardware photos. They are dropped BEFORE any model call (the description quota is scarce):
MIN_SIDE = 150          # pixels
MAX_ASPECT = 4.0        # long thin banners
DUP_LIMIT = 3           # the same bytes 3 or more times in the corpus = a logo / page decoration


def figure_digest(path: Path) -> str | None:
    import hashlib
    try:
        return hashlib.sha1(path.read_bytes()).hexdigest()
    except OSError:
        return None


def figure_skip_reason(b: dict, digest: str | None, dup_counts: dict[str, int]) -> str | None:
    """Why a figure is not worth a description (None = describe it). No caption means a photo or a decoration, not a figure a paper or report refers to."""
    if min(b.get("w", 0), b.get("h", 0)) < MIN_SIDE:
        return "figure_small"
    if max(b["w"], b["h"]) / max(1, min(b["w"], b["h"])) > MAX_ASPECT:
        return "figure_banner"
    if digest and dup_counts.get(digest, 1) >= DUP_LIMIT:
        return "figure_repeated_image"
    if not (b.get("caption") or "").strip():
        return "figure_no_caption"
    return None


def corpus_figure_counts(cache: Path) -> dict[str, int]:
    """How often each figure image (by its bytes) occurs in all parsed files: a logo on every page shows up dozens of times."""
    import json
    from collections import Counter
    c: Counter = Counter()
    for blocks in (cache / "docling").glob("*/blocks.jsonl"):
        for line in blocks.read_text(encoding="utf-8").splitlines():
            if '"type": "figure"' in line:
                b = json.loads(line)
                d = figure_digest(blocks.parent / b["file"])
                if d:
                    c[d] += 1
    return dict(c)


import re as _re


def table_label(caption: str, table_id: int) -> str:
    """The label the authors gave the table ("Table 12"); docling's own running number can disagree with it and stays internal (metadata.table_id)."""
    m = _re.match(r"\s*(Table\s+[A-Za-z]?\d+[A-Za-z]?(?:\.\d+)?)", caption or "", _re.I)
    return m.group(1).strip() if m else f"Table {table_id}"


def base_meta(row: dict, page: int, vocab: C.Vocab) -> dict:
    return {
        "kind": row["kind"], "src_id": row["src_id"], "title": row.get("title"), "page": page, "section": (row.get("sections") or {}).get(str(page)),
        "doc_category": row.get("doc_category"), "doc_role": row.get("doc_role"), "psis": row["psis"], "pillars": vocab.pillars_for(row["psis"]),
        "doi": row.get("doi"), "download_url": row.get("download_url"), "also_src_ids": row.get("also_src_ids", []), "text_origin": "docling",
    }


def where(row: dict) -> str:
    return row.get("doc_category") or ("paper · " + (row.get("sections") or {}).get("", "")).strip(" ·") or row["kind"]


async def build_source_chunks(row: dict, result_dir: Path, describer: Describer | None, vocab: C.Vocab, *, concurrency: int = 6, dup_counts: dict[str, int] | None = None) -> tuple[list[dict], dict]:
    """All chunks of one parsed file, and a small report {chunks by type, dropped by reason, description calls}."""
    blocks = [json.loads(l) for l in (result_dir / "blocks.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    sem = asyncio.Semaphore(concurrency)
    title = row.get("title") or row["src_id"]

    async def table_desc(b):
        if describer is None:
            return ""
        async with sem:
            return await describer.table(row["src_id"], item_key("t", b["page"], b["table_id"], b["markdown"][:200]), b["markdown"], b["caption"], title, b["context"])

    skipped: dict[str, int] = {}

    async def figure_info(b):
        if describer is None:                         # caption mode: no model call, the caption is the authors' own text
            why = figure_skip_reason(b, figure_digest(result_dir / b["file"]), dup_counts or {})
            return {"type": "skipped", "summary": "", "why": why} if why else {"type": "caption", "summary": ""}
        why = figure_skip_reason(b, figure_digest(result_dir / b["file"]), dup_counts or {})
        if why:
            skipped[why] = skipped.get(why, 0) + 1
            return {"type": "skipped", "summary": "", "why": why}
        png = (result_dir / b["file"]).read_bytes()
        async with sem:
            return await describer.figure(row["src_id"], item_key("f", b["page"], b["fig_id"], b["w"], b["h"]), png, b["caption"], title, b["context"])

    tdesc = await asyncio.gather(*(table_desc(b) for b in blocks if b["type"] == "table"))
    finfo = await asyncio.gather(*(figure_info(b) for b in blocks if b["type"] == "figure"))
    tdesc, finfo = iter(tdesc), iter(finfo)

    out, drops, counter = [], {}, {}
    prefix = f"{'paper' if row['kind'] == 'paper' else 'doc'}:{row['src_id']}"

    def add(cid, raw, hdr, meta, *, table=False, embedded_extra=""):
        why = C.drop_reason(raw, table=table)
        if why:
            drops[why] = drops.get(why, 0) + 1
            return
        t = C.tags(raw, vocab.materials, vocab.fuels)
        out.append(C.make(cid, raw, hdr, {**meta, "tags": t}, embedded_extra=embedded_extra))

    for b in blocks:
        page = b["page"]
        meta = base_meta(row, page, vocab)
        hdr = C.header(vocab.names(row["psis"]), title, page, row.get("doc_category") or "paper")
        if b["type"] == "text":
            for piece in _splitter.split_text(b["text"]):
                counter[page] = counter.get(page, 0) + 1
                add(f"{prefix}:p{page}:c{counter[page]}", piece, hdr, {**meta, "type": "text", "generated": False})
        elif b["type"] == "table":
            desc = next(tdesc)
            parts = split_table(b["markdown"])
            for i, part in enumerate(parts, 1):
                tag = f" (part {i}/{len(parts)})" if len(parts) > 1 else ""
                lab = table_label(b["caption"], b["table_id"])
                raw = f"[{lab}{tag}] {b['caption']}\n\n{part}".strip()
                emb = f"[{lab}{tag}] {b['caption']}\n{desc}\n\n{part}".strip()
                add(f"{prefix}:p{page}:t{b['table_id']}" + (f".{i}" if len(parts) > 1 else ""), raw, hdr,
                    {**meta, "type": "table", "table_id": b["table_id"], "table_desc": desc, "generated": False}, table=True, embedded_extra=emb)
        elif b["type"] == "figure":
            info = next(finfo)
            summary = (info.get("summary") or "").strip()
            if info["type"] == "caption":
                raw = f"[Figure] {b['caption']}\n{(b.get('context') or '').strip()[-FIG_CONTEXT_CHARS:]}".strip()
                add(f"{prefix}:p{page}:f{b['fig_id']}", raw, hdr, {**meta, "type": "figure", "fig_id": b["fig_id"], "figure_file": b["file"], "generated": False, "figure_text": "caption"}, table=True)
                continue
            if info["type"] == "skipped":
                drops[info["why"]] = drops.get(info["why"], 0) + 1
                continue
            if "logo_or_decorative" in info["type"] or summary in ("", "N/A"):
                drops["figure_logo_or_no_description"] = drops.get("figure_logo_or_no_description", 0) + 1
                continue
            raw = f"[Figure] {b['caption']}\n{summary}".strip()
            add(f"{prefix}:p{page}:f{b['fig_id']}", raw, hdr, {**meta, "type": "figure", "fig_id": b["fig_id"], "figure_type": info["type"], "figure_file": b["file"], "generated": True}, table=True)

    kept, ndup = C.dedupe(out)
    if ndup:
        drops["duplicate"] = ndup
    rep = {"chunks": len(kept), "by_type": {t: sum(1 for c in kept if c["metadata"]["type"] == t) for t in ("text", "table", "figure")}, "dropped": drops,
           "pages": len(row["kept_pages"]), "tokens_est": sum(len(c["text"]) // 3 for c in kept)}
    return kept, rep
