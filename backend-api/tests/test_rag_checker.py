"""Round 9 §9.5.1: the checker accepts a number only from the raw_text of a chunk with generated: false.
Chunks here come from the real chunker, so the test covers what is actually indexed: text, a table (raw text = caption + markdown only, the model's
description lives in `text` and metadata.table_desc), a figure indexed by its caption (the authors' words: allowed) and a model-written figure summary (not allowed)."""
import asyncio
import json

from src.paper_rag import chunks as C
from src.paper_rag.composer import check_sentences
from src.paper_rag.docling_chunks import build_source_chunks
from src.paper_rag.stores.vector_db.providers.PGvectorProvider import RetrievedDocument

VOCAB = C.Vocab({"PSI-20": "ACME BRE"}, {"PSI-20": ["prevention"]}, [], [])
ROW = {"src_id": "d1", "kind": "doc", "title": "BRE report", "psis": ["PSI-20"], "doi": None, "download_url": "https://x", "doc_category": "Reports", "doc_role": "results_report",
       "kept_pages": [3], "sections": {}, "also_src_ids": []}
TABLE = "| O2 (%) | spread rate (mm/s) | material |\n|---|---|---|\n" + "".join(f"| {20 + i} | {1.1 + i / 10:.1f} | PMMA sheet {i} |\n" for i in range(12))


class Describer:
    stats = {"groq_calls": 0, "gemini_calls": 0, "groq_429": 0, "cache_hits": 0, "failed": 0}
    async def table(self, *a): return "The table shows a spread rate of 777 mm/s at 99 percent oxygen."          # a number that is NOT in the table
    async def figure(self, *a): return {"type": "line_plot", "summary": "Spread rate is 555 mm/s at 88 percent oxygen. " * 8}


def as_docs(chunks):
    return [RetrievedDocument(c["chunk_id"], c["raw_text"], 0.9, c["metadata"], c["text"]) for c in chunks]


def build(tmp_path, blocks, describer):
    (tmp_path / "figures").mkdir(exist_ok=True)
    (tmp_path / "figures" / "a.png").write_bytes(b"png-a")
    (tmp_path / "blocks.jsonl").write_text("".join(json.dumps(b) + "\n" for b in blocks))
    cs, _ = asyncio.run(build_source_chunks(ROW, tmp_path, describer, VOCAB))
    return as_docs(cs)


def test_a_number_from_the_extracted_table_is_allowed_but_one_from_the_model_description_is_not(tmp_path):
    docs = build(tmp_path, [{"type": "table", "page": 3, "table_id": 1, "caption": "Table 1. Spread rate.", "markdown": TABLE, "context": ""}], Describer())
    t = docs[0]
    assert "777" not in t.chunk_text and "777" in t.embedded_text and t.metadata["table_desc"].startswith("The table shows") and t.metadata["generated"] is False
    ok, bad = check_sentences([{"text": "At 25 percent oxygen the spread rate was 1.6 mm/s.", "chunks": [1]}, {"text": "The spread rate reached 777 mm/s.", "chunks": [1]}], docs)
    assert ok["kept"] and not bad["kept"] and "777" in bad["reason"]


def test_a_figure_indexed_by_its_caption_may_be_the_source_of_a_number_a_model_summary_may_not(tmp_path):
    blocks = [{"type": "figure", "page": 3, "fig_id": 1, "file": "figures/a.png", "caption": "Figure 4. Flame spread at 30% oxygen and 70 kPa.", "context": "The flame spread over the PMMA sheet was recorded by the video camera in the combustion chamber during the whole test and the images were compared. " * 2, "w": 500, "h": 400}]
    caption_doc = build(tmp_path, blocks, None)[0]                                   # caption mode: generated false
    assert caption_doc.metadata["generated"] is False and caption_doc.metadata["figure_text"] == "caption"
    assert check_sentences([{"text": "The figure shows flame spread at 30% oxygen and 70 kPa.", "chunks": [1]}], [caption_doc])[0]["kept"]
    (tmp_path / "b").mkdir()
    summary_doc = build(tmp_path / "b", blocks, Describer())[0]                      # description mode: generated true
    assert summary_doc.metadata["generated"] is True
    r = check_sentences([{"text": "The figure shows a spread rate of 555 mm/s.", "chunks": [1]}, {"text": "The figure shows how the spread rate changes with oxygen.", "chunks": [1]}], [summary_doc])
    assert [x["kept"] for x in r] == [False, True]                                  # cited for what it shows, never for a number


def test_numbers_must_come_from_a_CITED_chunk_not_from_another_retrieved_chunk(tmp_path):
    a = RetrievedDocument("a", "Flames burned at 26 % oxygen.", 0.9, {"generated": False})
    b = RetrievedDocument("b", "Flames burned at 30 % oxygen.", 0.9, {"generated": False})
    r = check_sentences([{"text": "Flames burned at 30 % oxygen.", "chunks": [1]}, {"text": "Flames burned at 30 % oxygen.", "chunks": [1, 2]}], [a, b])
    assert [x["kept"] for x in r] == [False, True]


def test_the_checker_never_calls_a_model_and_is_deterministic():
    docs = [RetrievedDocument("a", "Flames burned at 26 % oxygen for 40 s.", 0.9, {"generated": False})]
    s = [{"text": "Flames burned at 26 % oxygen for 40 s.", "chunks": [1]}]
    assert check_sentences(s, docs) == check_sentences(s, docs)
