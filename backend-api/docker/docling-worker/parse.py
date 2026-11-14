"""Docling parsing of one PDF (the docling half of the team's chunk_data.py, without Groq). No API call, no key.

- a page without a text layer is OCR'd; pages with a text layer are not;
- only the pages the master sent (kept_pages) are parsed;
- outputs (folder `out/`): docling_<a>-<b>.json (the DoclingDocument of each page run), blocks.jsonl, figures/*.png (>= 120 px on a side), done.json
  blocks.jsonl: {"type":"text","page","text"} | {"type":"table","page","table_id","caption","markdown","context"} | {"type":"figure","page","fig_id","file","caption","context"}
"""
from __future__ import annotations

import json
import os
import time
from importlib import metadata
from pathlib import Path

MIN_IMG_SIDE = 120
CONTEXT_CHARS = 500


def runs_of(pages: list[int]) -> list[tuple[int, int]]:
    """Contiguous page runs of a sorted page list: [3,4,5,9] -> [(3,5),(9,9)]."""
    out: list[tuple[int, int]] = []
    for p in sorted(pages):
        if out and p == out[-1][1] + 1:
            out[-1] = (out[-1][0], p)
        else:
            out.append((p, p))
    return out


MAX_RUN_PAGES = int(os.getenv("MAX_RUN_PAGES", "12"))   # docling keeps every page of one convert() call in memory: long documents were OOM-killed


def plan_runs(pages: list[int], have_text: set[int], max_pages: int = MAX_RUN_PAGES) -> list[tuple[int, int, bool]]:
    """Contiguous page runs of at most `max_pages` that share the same need: (first, last, needs_ocr). OCR runs only over pages without a text layer."""
    out: list[tuple[int, int, bool]] = []
    for p in sorted(pages):
        need = p not in have_text
        if out and p == out[-1][1] + 1 and need == out[-1][2] and (out[-1][1] - out[-1][0] + 1) < max_pages:
            out[-1] = (out[-1][0], p, need)
        else:
            out.append((p, p, need))
    return out


def text_layer_pages(pdf_path: Path, pages: list[int], min_chars: int = 30) -> set[int]:
    """The pages (1-based) that carry real text (pdfium: no OCR needed there)."""
    import pypdfium2 as pdfium
    pdf = pdfium.PdfDocument(str(pdf_path))
    have = set()
    try:
        for p in pages:
            if 1 <= p <= len(pdf):
                tp = pdf[p - 1].get_textpage()
                if tp.count_chars() >= min_chars:
                    have.add(p)
                tp.close()
    finally:
        pdf.close()
    return have


def make_converter(ocr: bool, threads: int, ocr_lang: str, artifacts: str | None):
    from docling.datamodel.accelerator_options import AcceleratorDevice, AcceleratorOptions
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions
    from docling.document_converter import DocumentConverter, PdfFormatOption

    o = PdfPipelineOptions()
    o.do_ocr = ocr
    o.do_table_structure = True
    o.generate_picture_images = True
    o.images_scale = 2.0
    o.accelerator_options = AcceleratorOptions(num_threads=threads, device=AcceleratorDevice.CPU)
    if artifacts:
        o.artifacts_path = artifacts
    if ocr and ocr_lang and hasattr(o, "ocr_options") and hasattr(o.ocr_options, "lang"):
        o.ocr_options.lang = [x for x in ocr_lang.split(",") if x]
    return DocumentConverter(format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=o)})


def extract_blocks(doc, keep: set[int], fig_dir: Path, stats: dict) -> list[dict]:
    """The team's extract_blocks, minus the model calls: text per page, tables as markdown, figures as files."""
    from docling_core.types.doc import DocItemLabel, PictureItem, SectionHeaderItem, TableItem, TextItem, TitleItem

    blocks, buf, buf_page, recent, n_tbl, n_fig = [], [], None, [], 0, 0
    page_of = lambda it: it.prov[0].page_no if getattr(it, "prov", None) else None  # noqa: E731
    ctx = lambda: " ".join(recent[-3:])[-CONTEXT_CHARS:]  # noqa: E731

    def flush():
        nonlocal buf, buf_page
        if buf:
            blocks.append({"type": "text", "page": buf_page, "text": "\n\n".join(buf)})
        buf, buf_page = [], None

    for item, _ in doc.iterate_items():
        page = page_of(item)
        if page is not None and page not in keep:
            continue
        if isinstance(item, TableItem):
            flush()
            md = item.export_to_markdown(doc=doc)
            if md.strip():
                n_tbl += 1
                blocks.append({"type": "table", "page": page, "table_id": n_tbl, "caption": (item.caption_text(doc) or "").strip(), "markdown": md, "context": ctx()})
        elif isinstance(item, PictureItem):
            flush()
            t0 = time.monotonic()
            img = item.get_image(doc)
            if img is not None and min(img.size) >= MIN_IMG_SIDE:
                n_fig += 1
                fig_dir.mkdir(parents=True, exist_ok=True)
                fn = f"p{page}_f{n_fig}.png"
                img.save(fig_dir / fn)
                blocks.append({"type": "figure", "page": page, "fig_id": n_fig, "file": f"figures/{fn}", "caption": (item.caption_text(doc) or "").strip(), "context": ctx(), "w": img.size[0], "h": img.size[1]})
            stats["figure_export_s"] += time.monotonic() - t0
        elif isinstance(item, TextItem):
            if item.label in (DocItemLabel.PAGE_FOOTER, DocItemLabel.CAPTION):
                continue
            txt = item.text.strip()
            if not txt:
                continue
            recent.append(txt)
            if isinstance(item, (TitleItem, SectionHeaderItem)):
                txt = "## " + txt
            if buf_page is not None and page != buf_page:
                flush()
            if buf_page is None:
                buf_page = page
            buf.append(txt)
    flush()
    return blocks


def parse_pdf(pdf_path: Path, kept_pages: list[int], out: Path, *, threads: int, ocr_lang: str = "en", artifacts: str | None = None, worker_id: str = "", image_tag: str = "", sha256: str = "") -> dict:
    """Parse the kept pages of one PDF into `out/`. Returns done.json's content."""
    t_all = time.monotonic()
    out.mkdir(parents=True, exist_ok=True)
    keep = set(kept_pages)
    have_text = text_layer_pages(pdf_path, kept_pages)
    stats = {"parse_s": 0.0, "ocr_parse_s": 0.0, "figure_export_s": 0.0}
    converters: dict[bool, object] = {}
    blocks: list[dict] = []
    ocr_pages = 0
    for a, b, need_ocr in plan_runs(kept_pages, have_text):
        ocr_pages += (b - a + 1) if need_ocr else 0
        conv = converters.get(need_ocr) or converters.setdefault(need_ocr, make_converter(need_ocr, threads, ocr_lang, artifacts))
        t0 = time.monotonic()
        res = conv.convert(str(pdf_path), page_range=(a, b))
        stats["ocr_parse_s" if need_ocr else "parse_s"] += time.monotonic() - t0
        doc = res.document
        (out / f"docling_{a}-{b}.json").write_text(json.dumps(doc.export_to_dict(), ensure_ascii=False), encoding="utf-8")
        blocks += extract_blocks(doc, keep, out / "figures", stats)
    with (out / "blocks.jsonl").open("w", encoding="utf-8") as f:
        for r in blocks:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    done = {
        "pages_done": len(kept_pages), "ocr_pages": ocr_pages, "n_text": sum(b["type"] == "text" for b in blocks), "n_tables": sum(b["type"] == "table" for b in blocks),
        "n_figures": sum(b["type"] == "figure" for b in blocks), "seconds": {k: round(v, 2) for k, v in stats.items()}, "seconds_total": round(time.monotonic() - t_all, 2),
        "docling_version": metadata.version("docling"), "image_tag": image_tag or os.getenv("IMAGE_TAG", ""), "worker_id": worker_id, "sha256": sha256, "threads": threads, "ocr_lang": ocr_lang,
    }
    (out / "done.json").write_text(json.dumps(done, indent=1), encoding="utf-8")
    return done
