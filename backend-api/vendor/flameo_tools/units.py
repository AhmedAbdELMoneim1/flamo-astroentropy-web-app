"""Pressure units (Stage 7 Round 11 §11.6): psi first, as in the challenge text; kPa second.

The data stores kPa. flameo converts in ONE place (`to_psi`, 1 psi = 6.894757 kPa; 1 atm = 14.696 psi) and shows psi with the source value beside it.
Scenario values are the challenge's own numbers (14.7 / 10.2 / 8.2 / 4.3 psi, config `p_psi`), never conversions.
The adapter and the frontend compute nothing: they show what this module returned.
"""
import re

KPA_PER_PSI = 6.894757
KPA_PER_ATM = 101.325
PSI_PER_ATM = 14.696
KPA_UNITS = ("kPa", "kilopascals", "kilopascal")


def to_psi(kpa, nd=1):
    """kPa -> psi, one decimal (the source never has more digits than that for a psi reading)."""
    return None if kpa is None else round(float(kpa) / KPA_PER_PSI, nd)


def to_kpa(psi):
    return None if psi is None else float(psi) * KPA_PER_PSI


def atm_to_psi(atm):
    return None if atm is None else round(float(atm) * PSI_PER_ATM, 1)


def fmt_psi(v):
    """One decimal, never "10.0": 14.7, 10.2, 4.3, 6, 0.3."""
    s = f"{v:.1f}"
    return s[:-2] if s.endswith(".0") else s


_NUM = r"(\d[\d,]*(?:\.\d+)?)"
_RANGE = re.compile(_NUM + r"(?:\s+to\s+" + _NUM + r")?\s*(kilopascals|kPa)\b")


def psi_text(s, with_kpa=True, words=False, facts=None):
    """Rewrite "70.3 kilopascals" / "57 to 108 kPa" as "10.2 psi (70.3 kPa)" / "8.3 to 15.7 psi (57 to 108 kPa)".
    with_kpa=False (the voice): "10.2 psi" only. Every psi number is appended to `facts` (a list of {"value": x}) so the spoken-number check finds it."""
    if not isinstance(s, str):
        return s

    def one(m):
        a, b, u = m.group(1), m.group(2), m.group(3)
        if u == "kPa" and words:
            return m.group(0)
        pa = to_psi(float(a.replace(",", "")))
        pb = to_psi(float(b.replace(",", ""))) if b else None
        if facts is not None:
            facts.append({"value": float(fmt_psi(pa))})
            if pb is not None:
                facts.append({"value": float(fmt_psi(pb))})
        psi = f"{fmt_psi(pa)} to {fmt_psi(pb)} psi" if b else f"{fmt_psi(pa)} psi"
        return f"{psi} ({a} to {b} kPa)" if with_kpa and b else f"{psi} ({a} kPa)" if with_kpa else psi
    return _RANGE.sub(one, s)


def convert_answer(d):
    """The psi-first pass over a finished flameo answer (called once, from `_clean`).
    speak: kilopascals -> psi only (the voice says psi); gaps / kpi text / key points: psi with the kPa value after it;
    kpis and table columns whose unit is kPa: the number becomes psi (unit "psi", `unit_from` "kPa", the source value kept in `value_from` / `<key>__kpa`)."""
    facts = d.setdefault("facts", []) if "facts" in d or d.get("speak") is not None else []
    d["speak"] = [psi_text(x, with_kpa=False, words=True, facts=facts) for x in d.get("speak", [])]
    d["gaps"] = [psi_text(x, with_kpa=True, facts=facts) for x in d.get("gaps", [])]
    if "key_points" in d:
        d["key_points"] = [psi_text(x, with_kpa=True, facts=facts) for x in d["key_points"]]
    for k in d.get("kpis", []):
        k["basis"] = psi_text(k.get("basis"), with_kpa=True, facts=facts)
        if isinstance(k.get("value"), str):
            k["value"] = psi_text(k["value"], with_kpa=True, facts=facts)
        if k.get("unit") in KPA_UNITS:
            v = k.get("value")
            if isinstance(v, (int, float)):
                k["value_from"], k["value"] = v, to_psi(v)
                facts.append({"value": k["value"]})
            elif isinstance(v, str):
                k["value"] = psi_text(f"{v} kPa", with_kpa=False, facts=facts).replace(" psi", "")
            k["unit"], k["unit_from"] = "psi", "kPa"
    t = d.get("table")
    if t:
        extra = []
        for col in t.get("columns", []):
            if col.get("unit") in KPA_UNITS:
                key, hit = col["key"], False
                for r in t.get("rows", []):
                    v = r.get(key)
                    if isinstance(v, (int, float)) and not isinstance(v, bool):
                        r[key + "__kpa"], r[key] = v, to_psi(v)
                        facts.append({"value": r[key]})
                        hit = True
                col["unit"], col["unit_from"] = "psi", "kPa"
                if isinstance(col.get("label"), str):
                    col["label"] = col["label"].replace("(kilopascals)", "(psi)").replace("(kPa)", "(psi)")
                if hit:       # the source value stays in the data as a hidden column (shown in small text next to the psi value)
                    extra.append({"key": key + "__kpa", "label": f"{col['label']} (source, kPa)", "unit": "kPa", "hidden": True})
        t["columns"] = t.get("columns", []) + extra
    for ch in d.get("charts", []):
        ax = ch.get("x")
        if isinstance(ax, dict) and ax.get("unit") in KPA_UNITS:
            ax["unit"], ax["unit_from"] = "psi", "kPa"
            for s in ch.get("series", []):
                for p in s.get("points", []):
                    if "x" in p and isinstance(p["x"], (int, float)):
                        p["x_kpa"], p["x"] = p["x"], to_psi(p["x"])
    return d
