"""Step 1 of ask_sources (Round 6 §6.4): the parameters Gemini heard select the investigations whose sources the search may use.

  o2_pct        PSIs with counted tests within +-3 points of oxygen        pressure_kpa  within +-10 %
  material/fuel investigation.materials / fuels (and the registry fuel text)
  psi           a named investigation (id, name or short name)             pillar        the registry's pillars
  scenario      the scenario's oxygen and pressure (+-3 points, +-10 %)    (an empty parameter selects nothing)
Several parameters narrow the scope (intersection); when they share no investigation the union is used and `widened` says so.
Reads serving.db read-only (milliseconds). Never computes a number that is shown: the tolerances only decide which sources are searched.
"""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, field

from src.paper_rag.chunks import pillars_of

O2_TOL, P_TOL = 3.0, 0.10
FUEL_ALIASES = {"methane": ("ch4", "methane"), "ethylene": ("c2h4", "ethylene"), "propane": ("c3h8", "propane"), "heptane": ("heptane", "c7h16"), "butane": ("c4h10", "butane")}
MATERIAL_ALIASES = {"pmma": ("pmma", "acrylic"), "sibal": ("sibal", "cotton")}
FAMILY_MATERIALS = {"fabric": ("sibal", "cotton", "fiberglass", "nomex", "fabric", "cloth"), "plastic": ("pmma", "acrylic", "plastic", "delrin")}


@dataclass
class Scope:
    psis: list[str] = field(default_factory=list)
    selected_by: dict[str, list[str]] = field(default_factory=dict)   # which parameter selected which PSIs
    widened: bool = False                                             # the parameters shared no PSI: union used
    used: dict = field(default_factory=dict)

    @property
    def empty(self) -> bool:
        return not self.psis

    def as_filter(self) -> dict | None:
        # the challenge text names no PSI but frames every Moon base / spacesuit / partial-gravity question: it is in every scope
        return {"psis": self.psis, "kinds": ["challenge"]} if self.psis else None


class ScopeResolver:
    def __init__(self, serving_db) -> None:
        self.con = sqlite3.connect(f"file:{serving_db}?mode=ro", uri=True, check_same_thread=False)
        self.psi = {r[0]: r for r in self.con.execute("SELECT psi, name, short_name, fuel, pillars FROM psi")}
        self.inv = {r[0]: (set(json.loads(r[1] or "{}")), set(json.loads(r[2] or "{}"))) for r in self.con.execute("SELECT psi, materials, fuels FROM investigation")}
        self.scen = {r[0]: r for r in self.con.execute("SELECT scenario, o2_pct, p_kpa FROM scenario")}

    def _near(self, field: str, lo: float, hi: float) -> set[str]:
        q = "SELECT DISTINCT t.psi FROM value v JOIN test t ON t.test_id = v.test_id WHERE t.counted = 1 AND v.field = ? AND v.value_num BETWEEN ? AND ?"
        return {r[0] for r in self.con.execute(q, (field, lo, hi))}

    def named(self, text: str) -> set[str]:
        t = text.strip().lower()
        out = set()
        word = re.compile(r"(?<![a-z0-9])" + re.escape(t) + r"(?![a-z0-9])")
        for k, (_, name, short, _f, _p) in self.psi.items():
            if t == k.lower() or t in {(name or "").lower(), (short or "").lower()}:
                out.add(k)
        if out:                                    # an exact id / name wins ("BASS" is not "BASS-II")
            return out
        for k, (_, name, short, _f, _p) in self.psi.items():
            if word.search((name or "").lower()) or word.search((short or "").lower()):
                out.add(k)
        return out

    def widen(self, scope: Scope) -> Scope | None:
        """One level up (Round 15 adaptive depth, second pass): the PSI -> its pillar's PSIs, the material -> its family, the scenario dropped. None when nothing can be widened."""
        u = dict(scope.used)
        changed = False
        if u.pop("scenario", None):
            changed = True
        if u.get("psi"):
            ids = self.named(u["psi"]) if isinstance(u["psi"], str) else set()
            key = next((pl for k in sorted(ids) for pl in pillars_of(self.psi[k][4])), None) if ids else None
            if key:
                u.pop("psi")
                u["pillar"] = key
                changed = True
        m = u.get("material")
        if isinstance(m, str):
            fam = next((ws for ws in FAMILY_MATERIALS.values() if m.lower() in ws or any(m.lower() in w or w in m.lower() for w in ws)), None)
            if fam:
                u["material"] = fam
                changed = True
        if not changed:
            return None
        w = self.resolve(**u)
        w.psis = sorted(set(w.psis) | set(scope.psis))        # one level up is a superset of where we searched
        return w

    def resolve(self, *, o2_pct=None, pressure_kpa=None, material=None, fuel=None, psi=None, pillar=None, scenario=None) -> Scope:
        sel: dict[str, set[str]] = {}
        used = {k: v for k, v in dict(o2_pct=o2_pct, pressure_kpa=pressure_kpa, material=material, fuel=fuel, psi=psi, pillar=pillar, scenario=scenario).items() if v not in (None, "")}
        if o2_pct is not None:
            sel["o2_pct"] = self._near("O2_pct", o2_pct - O2_TOL, o2_pct + O2_TOL)
        if pressure_kpa is not None:
            sel["pressure_kpa"] = self._near("pressure_kPa", pressure_kpa * (1 - P_TOL), pressure_kpa * (1 + P_TOL))
        if material:
            ms = tuple(material) if isinstance(material, (tuple, list)) else MATERIAL_ALIASES.get(str(material).lower(), (str(material).lower(),))
            sel["material"] = {k for k, (mats, _) in self.inv.items() if any(m in x.lower() or x.lower() in m for x in mats for m in ms)}
        if fuel:
            fs = FUEL_ALIASES.get(str(fuel).lower(), (str(fuel).lower(),))
            sel["fuel"] = {k for k, (_, fuels) in self.inv.items() if any(f in x.lower() for x in fuels for f in fs)} | {k for k, r in self.psi.items() if any(f in (r[3] or "").lower() for f in fs)}
        if psi:
            sel["psi"] = set().union(*(self.named(x) for x in ([psi] if isinstance(psi, str) else psi)))
        if pillar:
            p = re.sub(r"[^a-z]", "", pillar.lower())
            key = next((k for k in ("prevention", "flammability", "detection", "suppression") if k.startswith(p[:5]) or p.startswith(k[:5])), None)
            sel["pillar"] = {k for k, r in self.psi.items() if key in pillars_of(r[4])} if key else set()
        if scenario and scenario in self.scen and self.scen[scenario][1] is not None:
            _, o2, p = self.scen[scenario]
            s = self._near("O2_pct", o2 - O2_TOL, o2 + O2_TOL)
            if p:
                s &= self._near("pressure_kPa", p * (1 - P_TOL), p * (1 + P_TOL))
            sel["scenario"] = s
        sel = {k: v for k, v in sel.items() if v is not None}
        if not sel:
            return Scope(used=used)
        nonempty = [v for v in sel.values() if v]
        inter = set.intersection(*nonempty) if nonempty else set()
        widened = len(nonempty) > 1 and not inter
        psis = inter if inter else set().union(*nonempty) if nonempty else set()
        return Scope(sorted(psis), {k: sorted(v) for k, v in sel.items()}, widened, used)
