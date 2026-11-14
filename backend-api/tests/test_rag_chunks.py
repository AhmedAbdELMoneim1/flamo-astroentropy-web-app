"""The chunk contract (Round 7 §7.3): drop rules, tags, dedupe, header, and the tier-1 file."""
import json
from pathlib import Path

import pytest

from src.paper_rag import chunks as C


def test_drop_rules():
    assert C.drop_reason("short text") == "too_short"
    assert C.drop_reason("x" * 250 + " DOI 10.1016/j.x") == "junk"
    assert C.drop_reason("1234 5678 " * 40) == "mostly_numbers"
    assert C.drop_reason("The flame spread slowly in the low oxygen atmosphere. " * 6) is None
    assert C.drop_reason("short", verified=True) is None                       # cards, profiles, references are short by nature
    assert C.drop_reason("1 2 3 4 5 6 7 8 9 " * 30, table=True) is None         # tables are numbers by nature


def test_tags_values_mentioned_in_the_text():
    t = C.tags("At 21% oxygen and 14.7 psi the flame spread; with 30 percent O2 at 10.2 psia it did not. In a normal-gravity test with PMMA.", ["PMMA", "Kapton"], ["C2H4"], "In a normal-gravity test, the authors report")
    assert t["o2_pct"] == [21.0, 30.0] and t["pressure"] == ["14.7 psi", "10.2 psia"] and t["pressure_kpa"][0] == 101.4
    assert t["materials"] == ["PMMA"] and t["fuels"] == [] and t["gravity"] == "normal"
    assert C.tags("in microgravity on the ISS and in normal gravity")["gravity"] == "both"


def test_dedupe_keeps_the_first_and_merges_psis():
    a = C.make("a", "Same sentence here.", "[h]", {"psis": ["PSI-1"], "pillars": ["prevention"]})
    b = C.make("b", "same  sentence here.", "[h]", {"psis": ["PSI-2"], "pillars": ["detection"]})
    out, n = C.dedupe([a, b])
    assert n == 1 and len(out) == 1 and out[0]["metadata"]["psis"] == ["PSI-1", "PSI-2"] and out[0]["metadata"]["pillars"] == ["detection", "prevention"]


def test_header_and_embedded_text_are_separate_from_raw_text():
    c = C.make("x", "The raw text.", C.header("ACME BRE (PSI-20)", "BRE thesis", 31, "Reports"), {})
    assert c["text"].startswith("[ACME BRE (PSI-20) · BRE thesis · page 31 · Reports]") and c["raw_text"] == "The raw text."


TIER1 = Path(__file__).resolve().parent.parent / "rag_cache" / "tier1" / "chunks.jsonl"


@pytest.mark.skipif(not TIER1.exists(), reason="run scripts/rag/build_chunks_tier1.py first")
def test_tier1_file_has_the_decided_counts_and_metadata():
    cs = [json.loads(l) for l in TIER1.read_text().splitlines()]
    kinds = {k: sum(1 for c in cs if c["metadata"]["kind"] == k) for k in ("card", "investigation", "challenge", "reference")}
    assert kinds["card"] == 322 and kinds["investigation"] == 24 and kinds["reference"] == 6 and 8 <= kinds["challenge"] <= 15
    assert len({c["chunk_id"] for c in cs}) == len(cs)
    for c in cs:
        m = c["metadata"]
        assert m["chunk_id"] == c["chunk_id"] and m["text_origin"] == "serving" and m["generated"] is False and "text_hash" in m and "tags" in m
        assert c["text"].startswith("[") and c["raw_text"] in c["text"].replace("\n", "\n")
    cards = [c for c in cs if c["metadata"]["kind"] == "card"]
    assert all(c["metadata"]["psis"] and c["metadata"]["wording"] and "x_field" in c["metadata"] for c in cards)
