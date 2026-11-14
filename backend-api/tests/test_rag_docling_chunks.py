"""Docling chunks: contract, generated marks, table splitting, dropping, descriptions (fake describer, no network, no docling)."""
import asyncio
import json
from pathlib import Path

import pytest

from src.paper_rag import chunks as C
from src.paper_rag.docling_chunks import build_source_chunks, split_table

VOCAB = C.Vocab({"PSI-20": "ACME BRE"}, {"PSI-20": ["prevention", "flammability"]}, ["PMMA"], ["C2H4"])
ROW = {"src_id": "10.1000/x", "kind": "paper", "title": "BRE thesis", "psis": ["PSI-20"], "doi": "10.1000/x", "download_url": None, "doc_category": None, "doc_role": None,
       "kept_pages": [3, 4], "sections": {"3": "results", "4": "discussion"}, "also_src_ids": []}
BIG_TABLE = "| O2 (%) | spread rate (mm/s) | material |\n|---|---|---|\n" + "".join(f"| {20 + i} | {1.1 + i / 10:.1f} | PMMA sheet {i} |\n" for i in range(12))
PARA = "The flame spread rate of PMMA increased with oxygen concentration in the microgravity tests at 30% oxygen and 70 kPa. "


class FakeDescriber:
    def __init__(self): self.calls = []
    async def table(self, src, key, md, cap, doc, ctx):
        self.calls.append("table"); return "A table of spread rate by oxygen level."
    async def figure(self, src, key, png, cap, doc, ctx):
        self.calls.append("figure")
        return {"type": "logo_or_decorative", "summary": "N/A"} if b"logo" in png else {"type": "line_plot", "summary": "Line plot of spread rate against oxygen. Spread rate rises from 1.2 to 3.4 mm/s as oxygen goes from 21 to 30 percent for the PMMA sheet in the microgravity tests; the normal-gravity curve lies below it at every oxygen level shown in the figure."}


def result(tmp, blocks, files=None):
    (tmp / "figures").mkdir(parents=True, exist_ok=True)
    for name, data in (files or {}).items():
        (tmp / name).write_bytes(data)
    (tmp / "blocks.jsonl").write_text("".join(json.dumps(b) + "\n" for b in blocks))
    return tmp


def run(row, tmp, blocks, files=None, describer=None):
    return asyncio.run(build_source_chunks(row, result(tmp, blocks, files), describer or FakeDescriber(), VOCAB))


def test_text_is_split_per_page_never_across_pages(tmp_path):
    blocks = [{"type": "text", "page": 3, "text": PARA * 12}, {"type": "text", "page": 4, "text": PARA * 3}]
    cs, rep = run(ROW, tmp_path, blocks)
    assert {c["metadata"]["page"] for c in cs} == {3, 4} and all(len(c["raw_text"]) <= 700 for c in cs)
    p3 = [c for c in cs if c["metadata"]["page"] == 3]
    assert len(p3) >= 3 and p3[0]["chunk_id"] == "paper:10.1000/x:p3:c1" and p3[1]["chunk_id"].endswith(":p3:c2")
    m = p3[0]["metadata"]
    assert m["type"] == "text" and m["generated"] is False and m["text_origin"] == "docling" and m["section"] == "results" and m["pillars"] == ["flammability", "prevention"]
    assert m["tags"]["materials"] == ["PMMA"] and 30.0 in m["tags"]["o2_pct"] and p3[0]["text"].startswith("[ACME BRE (PSI-20) · BRE thesis · page 3")


def test_table_raw_text_has_no_model_description_but_the_embedded_text_does(tmp_path):
    md = BIG_TABLE
    cs, _ = run(ROW, tmp_path, [{"type": "table", "page": 3, "table_id": 1, "caption": "Table 1. Spread rate.", "markdown": md, "context": "ctx"}])
    t = cs[0]
    assert t["raw_text"] == "[Table 1] Table 1. Spread rate.\n\n" + md.strip() and "A table of spread rate" not in t["raw_text"]
    assert "A table of spread rate" in t["text"] and t["metadata"]["table_desc"].startswith("A table of") and t["metadata"]["generated"] is False


def test_figure_chunks_are_marked_generated_and_logos_are_dropped(tmp_path):
    blocks = [{"type": "figure", "page": 3, "fig_id": 1, "file": "figures/a.png", "caption": "Figure 1. Spread rate.", "context": "", "w": 400, "h": 300},
              {"type": "figure", "page": 4, "fig_id": 2, "file": "figures/b.png", "caption": "", "context": "", "w": 400, "h": 300}]
    cs, rep = run(ROW, tmp_path, blocks, {"figures/a.png": b"plot", "figures/b.png": b"logo"})
    assert len(cs) == 1 and cs[0]["metadata"]["generated"] is True and cs[0]["metadata"]["type"] == "figure" and cs[0]["metadata"]["figure_file"] == "figures/a.png"
    assert "Spread rate rises" in cs[0]["raw_text"] and rep["dropped"]["figure_no_caption"] == 1


def test_a_large_table_is_split_by_rows_with_the_header_repeated():
    rows = "".join(f"| {i} | {i * 2} |\n" for i in range(600))
    md = "| a | b |\n|---|---|\n" + rows
    parts = split_table(md, 1000)
    assert len(parts) > 3 and all(p.startswith("| a | b |\n|---|---|") and len(p) <= 1100 for p in parts)
    assert sum(p.count("\n| ") for p in parts) + len(parts) >= 600


def test_drop_rules_apply_to_docling_text(tmp_path):
    blocks = [{"type": "text", "page": 3, "text": "Short."}, {"type": "text", "page": 3, "text": "1 2 3 4 5 6 7 8 9 0 " * 30},
              {"type": "text", "page": 4, "text": "Journal of Fire Sciences, Received 2020. DOI 10.1000/abc " + PARA * 2},
              {"type": "text", "page": 4, "text": PARA * 2}, {"type": "text", "page": 3, "text": PARA * 2}]
    cs, rep = run(ROW, tmp_path, blocks)
    assert rep["dropped"].get("too_short") == 1 and rep["dropped"].get("mostly_numbers") == 1 and rep["dropped"].get("junk") == 1
    assert rep["dropped"].get("duplicate") == 1 and len(cs) == 1


def test_no_describer_still_indexes_tables_without_a_description(tmp_path):
    md = BIG_TABLE
    cs, _ = asyncio.run(build_source_chunks(ROW, result(tmp_path, [{"type": "table", "page": 3, "table_id": 1, "caption": "c", "markdown": md, "context": ""}]), None, VOCAB))
    assert len(cs) == 1 and cs[0]["metadata"]["table_desc"] == ""


def test_logos_banners_small_and_captionless_figures_are_skipped_before_any_model_call(tmp_path):
    from src.paper_rag.docling_chunks import figure_digest, figure_skip_reason
    good = {"w": 600, "h": 400, "caption": "Figure 2. Spread rate."}
    assert figure_skip_reason(good, "h1", {"h1": 1}) is None
    assert figure_skip_reason({**good, "w": 100}, "h1", {}) == "figure_small"
    assert figure_skip_reason({**good, "w": 2400, "h": 300}, "h1", {}) == "figure_banner"
    assert figure_skip_reason(good, "logo", {"logo": 40}) == "figure_repeated_image"
    assert figure_skip_reason(good, "two", {"two": 2}) is None                  # the same plot in two files is not a logo
    assert figure_skip_reason({**good, "caption": "  "}, "h1", {}) == "figure_no_caption"
    blocks = [{"type": "figure", "page": 3, "fig_id": i, "file": f"figures/{n}.png", "caption": c, "context": "", "w": 400, "h": 300}
              for i, (n, c) in enumerate([("a", "Figure 1. Spread rate."), ("b", ""), ("c", "Figure 3. Logo")], 1)]
    d = FakeDescriber()
    cs, rep = asyncio.run(build_source_chunks(ROW, result(tmp_path, blocks, {"figures/a.png": b"plot", "figures/b.png": b"photo", "figures/c.png": b"logo-bytes"}), d, VOCAB, dup_counts={figure_digest(tmp_path / "figures/c.png"): 30}))
    assert d.calls == ["figure"] and len(cs) == 1                                  # only the captioned, unique figure reached the model
    assert rep["dropped"]["figure_no_caption"] == 1 and rep["dropped"]["figure_repeated_image"] == 1


def test_figures_are_indexed_by_caption_with_no_model_call_and_are_not_generated(tmp_path):
    blocks = [{"type": "figure", "page": 3, "fig_id": 1, "file": "figures/a.png", "caption": "Figure 4. Flame spread rate against oxygen for PMMA at 70 kPa.", "context": "x" * 400 + " the spread rate at 30% oxygen was 3.4 mm/s.", "w": 500, "h": 400},
              {"type": "figure", "page": 3, "fig_id": 2, "file": "figures/b.png", "caption": "", "context": "ctx", "w": 500, "h": 400}]
    cs, rep = asyncio.run(build_source_chunks(ROW, result(tmp_path, blocks, {"figures/a.png": b"plot", "figures/b.png": b"photo"}), None, VOCAB))
    assert len(cs) == 1 and rep["dropped"]["figure_no_caption"] == 1
    c = cs[0]
    assert c["metadata"]["type"] == "figure" and c["metadata"]["generated"] is False and c["metadata"]["figure_text"] == "caption"
    assert c["raw_text"].startswith("[Figure] Figure 4. Flame spread rate") and "3.4 mm/s" in c["raw_text"] and len(c["raw_text"]) < 450      # caption + at most 300 characters of context


def test_a_table_is_labelled_by_its_own_caption_not_by_doclings_running_number():
    from src.paper_rag.docling_chunks import table_label
    assert table_label("Table 12: Suppressant in a radiative environment.", 11) == "Table 12"
    assert table_label("TABLE 3. Results", 1) == "TABLE 3" and table_label("Table A2 summary", 5) == "Table A2"
    assert table_label("Test matrix", 7) == "Table 7" and table_label("", 2) == "Table 2"
