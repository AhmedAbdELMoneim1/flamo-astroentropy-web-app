"""Parameters from the question text itself (Round 10 §10.1 item 1). Gemini almost never filled them, so the scope was never used live.

Deterministic, no model: investigation names and acronyms from the registry, oxygen and pressure values with their units, materials and fuels with
synonyms, scenario words. The model's own arguments, when given, win (`merge`); every call logs which side each parameter came from (params_source).
"""

from __future__ import annotations

import re
import sqlite3

# acronyms that are also English words: only the upper-case spelling counts ("the SAME oxygen" is not the SAME experiment)
CASE_SENSITIVE = {"same", "flex", "spice", "bass", "slice", "daft"}
MATERIAL_SYN = {"PMMA": ("acrylic", "plexiglas", "plexiglass", "polymethyl methacrylate"), "SIBAL": ("cotton-fiberglass", "cotton fiberglass", "cotton/fiberglass", "cotton fabric"),
                "Kapton": ("polyimide",), "Teflon": ("ptfe",), "Silicone": ("silicone rubber",), "Nomex": (), "Lampwick": ("lamp wick", "wick")}
FUEL_SYN = {"methane": ("methane", "ch4"), "ethylene": ("ethylene", "c2h4"), "propane": ("propane", "c3h8"), "heptane": ("heptane", "n-heptane", "c7h16"), "methanol": ("methanol",),
            "dodecane": ("dodecane", "n-dodecane"), "hydrogen": ("hydrogen",), "butane": ("butane", "c4h10")}
SCENARIO_WORDS = [(r"\b(?:iss|international space station|space station|the station|cabin|spacecraft cabin|the craft|inside the craft)\b", "iss"),
                  (r"\b(?:moon base|lunar base|lunar habitat|moon habitat|the moon|on the moon|lunar surface|habitat)\b", "moon_base"),
                  (r"\b(?:spacesuit|space suit|the suit|in the suit|eva|spacewalk)\b", "spacesuit")]
KPA = {"psia": 6.894757, "psi": 6.894757, "kpa": 1.0, "kilopascal": 1.0, "kilopascals": 1.0, "atm": 101.325, "bar": 100.0}
_O2 = [re.compile(r"(\d+(?:\.\d+)?)\s*(?:%|percent|per cent)\s*(?:of\s+)?(?:o2|o₂|oxygen)", re.I), re.compile(r"(?:o2|o₂|oxygen)[^.\d%]{0,24}?(\d+(?:\.\d+)?)\s*(?:%|percent)", re.I)]
_P = re.compile(r"(\d+(?:\.\d+)?)\s*(psia|psi|kpa|kilopascals?|atm|bar)\b", re.I)
_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9\-]*")
_PSIID = re.compile(r"\bPSI[\s\-]?(\d{1,3})\b", re.I)


class Extractor:
    def __init__(self, serving_db) -> None:
        con = sqlite3.connect(f"file:{serving_db}?mode=ro", uri=True)
        self.alias: dict[str, set[str]] = {}
        ids = set()
        for psi, name, short in con.execute("SELECT psi, name, short_name FROM psi"):
            ids.add(psi)
            names = {short or "", re.sub(r"^ACME\s+", "", short or "")}
            names |= set(re.findall(r"\(([A-Za-z][A-Za-z0-9\-]+)\)", name or ""))
            for part in re.split(r"\s*/\s*", short or ""):
                names.add(re.sub(r"^ACME\s+", "", part))
            for n in names:
                n = n.strip()
                if n and " " not in n:                       # single tokens: BRE, SAME-R, FLEX-2, Saffire-III, E-FIELD ...
                    self.alias.setdefault(n.lower(), set()).add(psi)
        saf = {p for k, v in self.alias.items() if k.startswith("saffire") for p in v}
        self.alias["saffire"] = saf
        self.ids = ids
        mats, fuels = set(), set()
        import json
        for m, f in con.execute("SELECT materials, fuels FROM investigation"):
            mats |= set(json.loads(m or "{}"))
            fuels |= set(json.loads(f or "{}"))
        self.materials = {w.split()[0]: w for w in mats}      # "SIBAL Fabric" -> key SIBAL
        con.close()

    # ── pieces ──────────────────────────────────────────────────────────────
    def psis(self, text: str) -> list[str]:
        out: list[str] = []
        for m in _PSIID.finditer(text):
            pid = f"PSI-{int(m.group(1))}"
            if pid in self.ids and pid not in out:
                out.append(pid)
        for m in _TOKEN.finditer(text):
            tok = m.group(0).rstrip("-")
            low = tok.lower()
            hit = self.alias.get(low)
            if not hit and low.endswith("-"):
                continue
            if hit and low in CASE_SENSITIVE and tok != tok.upper():
                continue
            if hit and low == "same" and re.search(r"\bthe\s+same\b", text[max(0, m.start() - 6): m.end()], re.I):
                continue
            for p in sorted(hit or ()):
                if p not in out:
                    out.append(p)
        return out

    @staticmethod
    def o2(text: str) -> float | None:
        for rx in _O2:
            m = rx.search(text)
            if m:
                return float(m.group(1))
        return None

    @staticmethod
    def pressure_kpa(text: str) -> float | None:
        m = _P.search(text)
        return round(float(m.group(1)) * KPA[m.group(2).lower()], 1) if m else None

    def material(self, text: str) -> str | None:
        low = text.lower()
        for canon, syns in MATERIAL_SYN.items():
            if re.search(r"(?<![a-z])" + re.escape(canon.lower()) + r"(?![a-z])", low) or any(s in low for s in syns):
                return canon
        for key in self.materials:
            if re.search(r"(?<![A-Za-z])" + re.escape(key) + r"(?![A-Za-z])", text, re.I) and len(key) > 3:
                return key
        return None

    @staticmethod
    def fuel(text: str) -> str | None:
        low = text.lower()
        for canon, syns in FUEL_SYN.items():
            if any(re.search(r"(?<![a-z0-9])" + re.escape(s) + r"(?![a-z0-9])", low) for s in syns):
                return canon
        return None

    @staticmethod
    def scenario(text: str) -> str | None:
        """A scene word narrows the search only when the question is about the atmosphere ("aboard the space station" is a place, not a condition)."""
        if not re.search(r"\b(?:atmospheres?|oxygen|o2|pressure|conditions?|environment|air)\b", text, re.I):
            return None
        for rx, sid in SCENARIO_WORDS:
            if re.search(rx, text, re.I):
                return sid
        return None

    def extract(self, text: str) -> dict:
        """{psi?, o2_pct?, pressure_kpa?, material?, fuel?, scenario?}: only what the text says."""
        out: dict = {}
        ps = self.psis(text)
        if ps:
            out["psi"] = ps if len(ps) > 1 else ps[0]
        for k, v in (("o2_pct", self.o2(text)), ("pressure_kpa", self.pressure_kpa(text)), ("material", self.material(text)), ("fuel", self.fuel(text)), ("scenario", self.scenario(text))):
            if v is not None:
                out[k] = v
        return out


def merge(model: dict, extracted: dict) -> tuple[dict, dict]:
    """The model's own arguments win. Returns (params, params_source {name: 'model' | 'extracted'})."""
    params, src = {}, {}
    for k in dict.fromkeys([*extracted, *model]):
        if model.get(k) not in (None, ""):
            params[k], src[k] = model[k], "model"
        elif k in extracted:
            params[k], src[k] = extracted[k], "extracted"
    return params, src
