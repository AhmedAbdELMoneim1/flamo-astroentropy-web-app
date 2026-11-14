"""JSON shapes (version 1) as TypedDicts + a validator. New keys are additive; the frontend ignores unknown keys."""
import re
from typing import Any, Dict, List, Optional, TypedDict

VERSION = 1


class Source(TypedDict, total=False):
    label: str
    mock: bool
    refs: List[str]


class KPI(TypedDict, total=False):
    id: str
    label: str
    value: Any
    unit: str
    basis: str
    trust: str


class Point(TypedDict):
    x: Any
    y: Any


class Series(TypedDict):
    name: str
    points: List[Point]


class Axis(TypedDict, total=False):
    label: str
    unit: str


class Chart(TypedDict, total=False):
    id: str
    type: str
    title: str
    x: Axis
    y: Axis
    series: List[Series]


class Column(TypedDict, total=False):
    key: str
    label: str
    unit: str


class Table(TypedDict, total=False):
    columns: List[Column]
    rows: List[Dict[str, Any]]


class Answer(TypedDict, total=False):
    version: int
    tool: str
    question: str
    speak: List[str]
    kpis: List[KPI]
    charts: List[Chart]
    table: Optional[Table]
    gaps: List[str]
    source: Source
    facts: List[Dict[str, Any]]


class Dashboard(TypedDict, total=False):
    version: int
    view: str
    scenario: Optional[str]
    coverage: str
    headline: str
    key_points: List[str]
    kpis: List[KPI]
    charts: List[Chart]
    table: Optional[Table]
    gaps: List[str]
    source: Source


LIMITS = {"kpis": 4, "charts": 2, "rows": 20}
NUM_RX = re.compile(r"\d+(?:[.,]\d+)?")


def _numbers(obj, skip_speak=True):
    out = set()

    def walk(o, key=None):
        if skip_speak and key == "speak":
            return
        if isinstance(o, dict):
            for k, v in o.items():
                walk(v, k)
        elif isinstance(o, (list, tuple)):
            for v in o:
                walk(v)
        elif isinstance(o, bool):
            return
        elif isinstance(o, (int, float)):
            out.add(norm(o))
        elif isinstance(o, str):
            for m in NUM_RX.findall(o):
                out.add(norm(m))
    walk(obj)
    return out


def norm(x):
    try:
        f = float(str(x).replace(",", "."))
    except ValueError:
        return str(x)
    return f"{f:.6g}"


def check_speak_numbers(ans):
    """Check 5: every number in speak[] appears in facts / kpis / table / charts / gaps of the same answer."""
    have = _numbers(ans)
    bad = []
    for s in ans.get("speak", []):
        for m in NUM_RX.findall(s):
            if norm(m) not in have:
                bad.append((s, m))
    return bad


def validate(ans, kind="answer"):
    """-> list of problems (empty = valid)."""
    p = []
    req = ["version", "speak", "source"] + (["view", "scenario", "coverage", "headline", "key_points", "kpis", "charts", "table", "gaps"] if kind == "dashboard" else ["tool", "kpis", "charts", "table", "gaps"])
    for k in req:
        if k not in ans:
            p.append(f"missing key {k}") if not (kind == "dashboard" and k == "speak") else None
    if ans.get("version") != VERSION:
        p.append("version")
    src = ans.get("source", {})
    if not isinstance(src.get("label"), str) or src.get("mock") is not False or not isinstance(src.get("refs"), list):
        p.append("source{label, mock:false, refs[]}")
    if len(ans.get("kpis", [])) > LIMITS["kpis"]:
        p.append("kpis > 4")
    if len(ans.get("charts", [])) > LIMITS["charts"]:
        p.append("charts > 2")
    t = ans.get("table")
    if t is not None:
        if len(t.get("rows", [])) > LIMITS["rows"] and kind == "dashboard":
            p.append("rows > 20")
        keys = {c["key"] for c in t.get("columns", [])}
        for r in t.get("rows", []):
            if not set(r) <= keys:
                p.append(f"row keys {set(r) - keys} not in columns")
                break
    for k in ans.get("kpis", []):
        for f in ("id", "label", "value", "basis", "trust"):
            if f not in k:
                p.append(f"kpi {k.get('id')} missing {f}")
    for c in ans.get("charts", []):
        if c.get("type") not in ("bar", "line", "scatter"):
            p.append(f"chart type {c.get('type')}")
        for s in c.get("series", []):
            if not all("x" in pt and "y" in pt for pt in s["points"]):
                p.append("chart point without x / y")
    if kind == "answer":
        for b in check_speak_numbers(ans):
            p.append(f"speak number {b[1]} not backed: {b[0][:50]}")
    return p
