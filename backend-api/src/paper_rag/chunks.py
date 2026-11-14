"""The chunk contract of Round 7 §7.3 / §7.7, shared by every builder (tier 1 from serving.db, tier 2 from docling).

A chunk is {chunk_id, text, raw_text, metadata}:
  raw_text  what the screen shows and what the checker reads (for generated text: see `generated`)
  text      what is embedded: a short header + the text (+ the model's table description, tables only)
"""

from __future__ import annotations

import hashlib
import re
import unicodedata

# Round 4 §4.3 junk (the same pattern as flameo_tools.tools.JUNK) + bullets / pipes
JUNK = re.compile(r"DOI|Received|Accepted|Article history|www\.|Vol\.|et al\.?,? *\(?\d{4}|\.{4,}|(?:\. ){3,}|Department of|University,|Univ\.,|@\w+\.|Symposium|^[A-Z][a-z]+, [A-Z]\., ", re.I)
MIN_CHARS = 200
MAX_DIGIT_RATIO = 0.40

PILLARS = {"prevention": r"Prevention", "flammability": r"Fire behavior|Environment", "detection": r"Detection", "suppression": r"Suppression"}


def pillars_of(registry_text: str | None) -> list[str]:
    return [p for p, rx in PILLARS.items() if re.search(rx, registry_text or "", re.I)]


def norm_text(s: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", s or "")).strip()


def text_hash(s: str) -> str:
    return hashlib.sha1(norm_text(s).lower().encode()).hexdigest()[:16]


def digit_ratio(s: str) -> float:
    s = re.sub(r"\s", "", s)
    return sum(c.isdigit() for c in s) / len(s) if s else 0.0


def is_junk(s: str) -> bool:
    return bool(JUNK.search(s)) or s.count("•") >= 3 or s.count("|") >= 2


def drop_reason(raw: str, *, verified: bool = False, table: bool = False) -> str | None:
    """Why a chunk is dropped (None = keep). `verified` items (cards, profiles, references) are short by nature and never dropped for length;
    tables are mostly numbers by nature and are exempt from the digit rule."""
    if not verified and len(raw) < MIN_CHARS:
        return "too_short"
    if not verified and not table and is_junk(raw):
        return "junk"
    if not verified and not table and digit_ratio(raw) > MAX_DIGIT_RATIO:
        return "mostly_numbers"
    return None


# ── tags ──────────────────────────────────────────────────────────────────────
_NUM = r"(\d+(?:\.\d+)?)"
O2_A = re.compile(_NUM + r"\s*(?:%|percent|per cent)\s*(?:O2|O₂|oxygen)", re.I)
O2_B = re.compile(r"(?:O2|O₂|oxygen)[^.\d%]{0,25}" + _NUM + r"\s*(?:%|percent)", re.I)
P_RX = re.compile(_NUM + r"\s*(psia|psi|kpa|kilopascals?|atm|bar)\b", re.I)
KPA = {"psia": 6.894757, "psi": 6.894757, "kpa": 1.0, "kilopascal": 1.0, "kilopascals": 1.0, "atm": 101.325, "bar": 100.0}


def _uniq(xs):
    out = []
    for x in xs:
        if x not in out:
            out.append(x)
    return out


def tags(text: str, materials: list[str] = (), fuels: list[str] = (), wording: str = "") -> dict:
    """Values mentioned in the text (by regex) and the vocabulary of the investigations. For filtering only: never shown or spoken."""
    t = text or ""
    o2 = _uniq([float(m) for m in O2_A.findall(t)] + [float(m) for m in O2_B.findall(t)])
    pr = P_RX.findall(t)
    low = f"{wording} {t}".lower()
    micro = bool(re.search(r"microgravity|micro-gravity|low[- ]gravity|reduced gravity|\bon the iss\b|\bflight\b|µg|\bug\b", low))
    normal = bool(re.search(r"normal[- ]gravity|1 ?g\b|earth gravity|ground[- ]based|drop tower", low))
    return {
        "o2_pct": o2,
        "pressure": _uniq([f"{v} {u}" for v, u in pr]),
        "pressure_kpa": _uniq([round(float(v) * KPA[u.lower()], 1) for v, u in pr]),
        "materials": [m for m in materials if re.search(r"(?<![A-Za-z])" + re.escape(m) + r"(?![A-Za-z])", t, re.I)],
        "fuels": [f for f in fuels if re.search(r"(?<![A-Za-z0-9])" + re.escape(f) + r"(?![A-Za-z0-9])", t)],
        "gravity": "both" if micro and normal else "micro" if micro else "normal" if normal else None,
    }


def header(label: str, title: str, page, where: str) -> str:
    parts = [label, title, f"page {page}" if page else None, where]
    return "[" + " · ".join(p for p in parts if p) + "]"


def make(chunk_id: str, raw: str, hdr: str, meta: dict, *, embedded_extra: str = "") -> dict:
    raw = norm_text(raw) if "\n" not in raw else raw.strip()
    meta = {**meta, "chunk_id": chunk_id, "text_hash": text_hash(raw)}
    return {"chunk_id": chunk_id, "text": f"{hdr}\n{embedded_extra or raw}".strip(), "raw_text": raw, "metadata": meta}


def dedupe(chunks: list[dict]) -> tuple[list[dict], int]:
    """Exact duplicates (normalised text hash): keep the first and merge the PSIs / pillars of the others into it."""
    seen: dict[str, dict] = {}
    out, dropped = [], 0
    for c in chunks:
        h = c["metadata"]["text_hash"]
        if h in seen:
            k = seen[h]["metadata"]
            k["psis"] = sorted(set(k.get("psis", [])) | set(c["metadata"].get("psis", [])))
            k["pillars"] = sorted(set(k.get("pillars", [])) | set(c["metadata"].get("pillars", [])))
            dropped += 1
        else:
            seen[h] = c
            out.append(c)
    return out, dropped


# ── registry vocabulary (labels, pillars, materials, fuels) from serving.db ──────
class Vocab:
    def __init__(self, label: dict, pillars: dict, materials: list, fuels: list) -> None:
        self.label, self.pillars, self.materials, self.fuels = label, pillars, materials, fuels

    def names(self, psis: list[str]) -> str:
        return ", ".join(f"{self.label.get(x, x)} ({x})" for x in psis[:3])

    def pillars_for(self, psis: list[str]) -> list[str]:
        return sorted({p for x in psis for p in self.pillars.get(x, [])})

    @classmethod
    def from_serving(cls, serving_db) -> "Vocab":
        import json
        import sqlite3
        con = sqlite3.connect(f"file:{serving_db}?mode=ro", uri=True)
        psi = con.execute("SELECT psi, name, short_name, pillars FROM psi").fetchall()
        mats, fuels = set(), set()
        for m, f in con.execute("SELECT materials, fuels FROM investigation"):
            mats |= set(json.loads(m or "{}"))
            fuels |= set(json.loads(f or "{}"))
        return cls({k: (sn or n) for k, n, sn, _ in psi}, {k: pillars_of(pl) for k, _, _, pl in psi},
                   sorted(mats, key=len, reverse=True), sorted(fuels, key=len, reverse=True))
