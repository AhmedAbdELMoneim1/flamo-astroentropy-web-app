"""Tier 1 chunks from serving.db: the cards, the investigation profiles, the challenge text, the references.

    FLAMEO_DB=.../serving.db .venv/bin/python scripts/rag/build_chunks_tier1.py
Writes rag_cache/tier1/chunks.jsonl, report.json (counts, drops by reason) and sample20.md (20 random chunks to review).
"""
from __future__ import annotations

import json
import os
import random
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.paper_rag import chunks as C  # noqa: E402

OUT = ROOT / "rag_cache" / "tier1"
CHALLENGE = Path(os.getenv("CHALLENGE_TEXT", "/home/ahmed/Desktop/nasa-space-apps-2026/assign-ai-tasks/Data-Classifications-Tests/Langgraph/third_run_loop/1-get-importand-docs/challenge-details.txt"))
HEADINGS = ["Background", "Objectives", "Potential Considerations", "Other investigations in PSI", "Hardware", "Spacesuits and oxygen concentration", "Partial-gravity data"]


def rows(con, sql, *a):
    cur = con.execute(sql, a)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def sentences_fit(text: str, limit: int) -> str:
    """The text cut at a sentence end below `limit` characters (whole text if it already fits)."""
    text = C.norm_text(text)
    if len(text) <= limit:
        return text
    cut = text[:limit]
    k = max(cut.rfind(". "), cut.rfind("? "), cut.rfind("! "))
    return cut[: k + 1] if k > limit * 0.5 else cut.rsplit(" ", 1)[0] + "…"


def main() -> None:
    sdb = Path(os.getenv("FLAMEO_DB") or Path.home() / "Desktop/nasa-multi-agents-stages/s1/s0-results/psi_stage1/local_data/serving.db")
    pdb = Path(os.getenv("PIPELINE_DB", sdb.parent / "pipeline.db"))
    s, p = sqlite3.connect(f"file:{sdb}?mode=ro", uri=True), sqlite3.connect(f"file:{pdb}?mode=ro", uri=True)
    drops, out = Counter(), []

    psi = {r["psi"]: r for r in rows(s, "SELECT * FROM psi")}
    inv = {r["psi"]: r for r in rows(s, "SELECT * FROM investigation")}
    label = {k: (v["short_name"] or v["name"]) for k, v in psi.items()}
    pil = {k: C.pillars_of(v["pillars"]) for k, v in psi.items()}
    mats, fuels = set(), set()
    for r in inv.values():
        mats |= set(json.loads(r["materials"] or "{}"))
        fuels |= set(json.loads(r["fuels"] or "{}"))
    mats, fuels = sorted(mats, key=len, reverse=True), sorted(fuels, key=len, reverse=True)
    paper = {r["paper_id"]: r for r in rows(p, "SELECT paper_id, doi, title FROM paper")}
    doc = {r["doc_id"]: r for r in rows(p, "SELECT doc_id, file_name, category, doc_role, download_url FROM doc")}

    def names(psis):
        return ", ".join(f"{label.get(x, x)} ({x})" for x in psis[:3])

    # ── cards: one chunk each, never split ───────────────────────────────────
    fpsi: dict[str, list[str]] = {}
    for r in rows(s, "SELECT finding_id, psi FROM finding_psi ORDER BY psi"):
        fpsi.setdefault(r["finding_id"], []).append(r["psi"])
    for f in rows(s, "SELECT * FROM finding ORDER BY finding_id"):
        psis = fpsi.get(f["finding_id"], [])
        raw = f["statement"].strip()
        if f["context_quote"] and C.norm_text(f["context_quote"]) != C.norm_text(raw):
            raw += f"\nContext: {f['context_quote'].strip()}"
        raw += f"\nEvidence: {f['wording']}."
        pp = paper.get(f["paper_id"], {})
        t = C.tags(raw, mats, fuels, f["wording"] or "")
        meta = {"kind": "card", "type": "text", "src_id": f["finding_id"], "paper_id": f["paper_id"], "title": pp.get("title") or f["paper_id"], "page": f["page"],
                "psis": psis, "pillars": sorted({x for q in psis for x in pil.get(q, [])}), "evidence_basis": f["evidence_basis"], "wording": f["wording"], "flight": bool(f["flight"]),
                "x_field": f["x_field"], "y_field": f["y_field"], "tags": t, "doi": f["paper_id"] if str(f["paper_id"]).startswith("10.") else None,
                "text_origin": "serving", "generated": False}
        out.append(C.make(f"card:{f['finding_id']}", raw, C.header(names(psis), pp.get("title"), f["page"], "finding · " + (f["wording"] or "")), meta))

    # ── investigation profiles ───────────────────────────────────────────────
    for k, r in psi.items():
        i = inv.get(k, {})
        bits = [f"{r['name']} ({k}), {r['flight_ground']} experiment. {r['title'] or ''}".strip()]
        for lab, v in (("Hardware", r["hardware"]), ("Fuel", r["fuel"]), ("Key conditions", r["key_conditions"]), ("Registry topics", r["pillars"])):
            if v and v.strip() not in {"—", "-", "–"}:
                bits.append(f"{lab}: {v}.")
        if i.get("materials") and i["materials"] != "{}":
            bits.append("Materials: " + ", ".join(json.loads(i["materials"])) + ".")
        if r["objectives"]:
            bits.append("Objectives: " + sentences_fit(r["objectives"], 700))
        raw = " ".join(bits)
        meta = {"kind": "investigation", "type": "text", "src_id": k, "title": r["name"], "page": None, "psis": [k], "pillars": pil[k], "tier": r["tier"],
                "tags": C.tags(raw, mats, fuels), "text_origin": "serving", "generated": False}
        out.append(C.make(f"psi:{k}", raw, C.header(label[k], "investigation profile", None, "registry"), meta))

    # ── challenge text, by section ───────────────────────────────────────────
    txt = CHALLENGE.read_text(encoding="utf-8") if CHALLENGE.exists() else ""
    if not txt:
        print("WARNING: challenge text not found:", CHALLENGE)
    sec_re = re.compile(r"^(" + "|".join(re.escape(h) for h in HEADINGS) + r")\s*$", re.M)
    parts, last, name = [], 0, "Introduction"
    for m in sec_re.finditer(txt):
        parts.append((name, txt[last:m.start()]))
        name, last = m.group(1), m.end()
    parts.append((name, txt[last:]))
    n = 0
    for name, body in parts:
        paras, cur = [x.strip() for x in re.split(r"\n+", body) if x.strip()], ""
        pieces = []
        for para in paras:                                  # paragraphs of ~800-1200 characters, never cut inside a sentence
            if cur and len(cur) + len(para) > 1200:
                pieces.append(cur)
                cur = ""
            cur = (cur + " " + para).strip()
        if cur:
            pieces.append(cur)
        for pc in pieces:
            r = C.drop_reason(pc)
            if r:
                drops["challenge:" + r] += 1
                continue
            n += 1
            meta = {"kind": "challenge", "type": "text", "src_id": "challenge-details.txt", "title": "NASA Space Apps challenge text", "page": None, "section": name, "psis": [], "pillars": [],
                    "tags": C.tags(pc, mats, fuels), "text_origin": "serving", "generated": False}
            out.append(C.make(f"challenge:c{n}", pc, C.header("NASA Space Apps challenge text", name, None, "challenge"), meta))

    # ── the quote-checked references ─────────────────────────────────────────
    for r in rows(s, "SELECT * FROM reference ORDER BY ref_id"):
        d = doc.get(r["src_id"], {})
        psis = sorted(set(re.findall(r"PSI-\d+", r["title"] or "")))
        raw = r["quote"].strip()
        meta = {"kind": "reference", "type": "text", "src_id": f"ref:{r['ref_id']}", "doc_id": r["src_id"], "title": r["title"], "page": r["page"], "psis": psis, "pillars": sorted({x for q in psis for x in pil.get(q, [])}),
                "doc_category": d.get("category"), "doc_role": d.get("doc_role"), "download_url": d.get("download_url"), "ref_id": r["ref_id"], "ref_kind": r["kind"],
                "tags": C.tags(raw, mats, fuels), "text_origin": "serving", "generated": False}
        out.append(C.make(f"ref:{r['ref_id']}", raw, C.header(None, r["title"], r["page"], "reference · " + r["kind"]), meta))

    kept, ndup = C.dedupe(out)
    drops["duplicate"] = ndup
    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / "chunks.jsonl").open("w", encoding="utf-8") as f:
        for c in kept:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    rep = {"chunks": len(kept), "by_kind": dict(Counter(c["metadata"]["kind"] for c in kept)), "dropped_by_reason": dict(drops),
           "chars": {"min": min(len(c["raw_text"]) for c in kept), "max": max(len(c["raw_text"]) for c in kept), "mean": round(sum(len(c["raw_text"]) for c in kept) / len(kept))}}
    (OUT / "report.json").write_text(json.dumps(rep, indent=2))
    random.seed(7)
    smp = random.sample(kept, 20)
    (OUT / "sample20.md").write_text("\n\n---\n\n".join(f"**{c['chunk_id']}**  \n`{c['text'].splitlines()[0]}`  \n{c['raw_text']}  \n_tags: {json.dumps(c['metadata'].get('tags'), ensure_ascii=False)}_" for c in smp))
    print(json.dumps(rep, indent=1))


main()
