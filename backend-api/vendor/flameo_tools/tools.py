"""Intent tools (layer 3): thin functions that combine queries.py helpers and shape the JSON. Each docstring is written for the agent's router.
speak[] holds spoken sentences only: display labels and units come from config/serving.yaml (copied into serving.db), never raw field names or formulas."""
import json
import os
import re
from collections import defaultdict

from . import queries as Q
from . import units as U
from .shapes import VERSION

_PATH = os.environ.get("FLAMEO_DB", "local_data/serving.db")
_CON = {}
SOURCE_LABEL = "Flame in Freefall serving.db (PSI tables, documents, papers; trust shown per value)"
NO_BEST_AGENT = "The data does not rate one agent as best; these are the diluents the experiments varied."
NO_TESTS_DIVIDER = "No tests at these conditions"
GAP_RELEVANCE = "This ranks relevance to the question; it does not rate how safe anything is."
GAP_SAFETY = "spread rate alone does not rate fire safety; limits come from the authors' findings"


def configure(path):
    """Point the tools at a serving.db file."""
    global _PATH
    _PATH = str(path)


def con():
    if _PATH not in _CON:
        _CON[_PATH] = Q.connect(_PATH)
    return _CON[_PATH]


class Facts:
    """Collects every number / free text that speak[] uses, so the voice may say only what the JSON also carries."""

    def __init__(self):
        self.items = []

    def n(self, x, nd=3):
        if x is None:
            return "not stated"
        v = float(f"{x:.{nd}g}") if abs(x) < 1000 else round(x)
        self.items.append({"value": v})
        return Q.fmt(x, nd)

    def i(self, x):
        self.items.append({"value": x})
        return str(x)

    def p(self, kpa):
        """A pressure in psi (Round 11 §11.6): the data's kPa converted by units.to_psi, shown as "6.2 psi"."""
        v = U.to_psi(kpa)
        self.items.append({"value": float(U.fmt_psi(v))})
        return f"{U.fmt_psi(v)} psi"

    def t(self, s):
        self.items.append({"text": s})
        return s


def _fix(x):
    """Grammar safety net for every spoken / displayed string: '1 PSIs', '1 tests', '1 of them have'."""
    if isinstance(x, str):
        x = re.sub(r"\b1 PSIs\b", "1 PSI", x)
        x = re.sub(r"\b1 tests\b", "1 test", x)
        x = re.sub(r"\b1 of (them|those) have\b", r"1 of \1 has", x)
        x = re.sub(r"\b1 test points\b", "1 test point", x)
        x = re.sub(r"\b1 groups\b", "1 group", x)
        x = re.sub(r"\b1 (paper )?findings\b", r"1 \1finding", x)
        x = re.sub(r"\b1 cells\b", "1 cell", x)
        return x
    if isinstance(x, list):
        return [_fix(i) for i in x]
    return x


DOC_CATS = r"(?:Reports|Science Documents|Engineering Documents|Analyzed Data|Raw Data|Presentations|Reference Data|Calibration)"


def clean_title(raw, c=None):
    """ONE label for a document or paper wherever it is shown (speak prefix, table, Sources). A paper title stays as it is. A PSI document file name
    "PSI-20_Reports_Dissertation-PD-revised_" becomes "ACME BRE Reports: Dissertation PD revised" (investigation + category + the cleaned name; underscores, versions and dates cut)."""
    if not raw:
        return raw
    t = str(raw).strip()
    m = re.match(rf"^(PSI-\d+)[_ ]({DOC_CATS})[_ ](.+)$", t)
    if not m:
        return re.sub(r"_+", " ", t).strip()
    psi, cat, rest = m.groups()
    name = psi
    try:
        r = (c or con()).execute("SELECT short_name FROM psi WHERE psi=?", (psi,)).fetchone()
        name = (r[0] if r and r[0] else psi)
    except Exception:
        pass
    rest = re.sub(r"_+", " ", rest)
    rest = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", rest)                      # FinalReport -> Final Report
    rest = re.sub(r"(?<=[a-z]{3})-|-(?=[a-z]{3})", " ", rest)             # Dissertation-PD-revised -> Dissertation PD revised (BASS-II, E-FIELD, s-Flame keep their hyphen)
    rest = re.sub(r"\b(?:19|20)\d{6}\b|\b(?:19|20)\d{4}\b|\bv\d+(?:\.\d+)*\b", " ", rest)  # dates and version suffixes
    rest = re.sub(r"\s+", " ", rest).strip(" -_")
    return f"{name} {cat}: {rest}" if rest else f"{name} {cat}"


def _clean(d):
    U.convert_answer(d)                                   # psi first (Round 11 §11.6)
    d["speak"] = _fix(d.get("speak", []))
    d["gaps"] = _fix(d.get("gaps", []))
    for k in d.get("kpis", []):
        k["label"], k["basis"] = _fix(k["label"]), _fix(k["basis"])
    if "key_points" in d:
        d["key_points"] = _fix(d["key_points"])
    return d


def _src(refs):
    return {"label": SOURCE_LABEL, "mock": False, "refs": [r for r in dict.fromkeys(refs)][:30]}


SOURCE_LABEL_BY_KIND = {"sensor_file": "Sensor data", "paper": "Paper", "document": "NASA document", "card": "Finding", "table": "Experiment table", "challenge": "NASA Space Apps challenge text"}


def _paper_title(c, pid):
    """The title of a paper / document id as the source table has it (cleaned), never the raw DOI or doc: id (Round 10 §10.2)."""
    r = c.execute("SELECT title FROM source WHERE src_id=?", (str(pid),)).fetchone() if pid else None
    return clean_title(r["title"], c) if r and r["title"] else (clean_title(str(pid), c) if pid else "")


def _sources(refs, limit=6):
    """sources[] of an answer (Round 6.3): one entry per cited document, paper, finding or experiment table, from the serving.db `source` table.
    A link exists only when pipeline.db has one (paper DOI, NASA PSI download); an experiment table has none. Numbered 1..n like the superscripts on screen."""
    try:
        c = con()
        have = c.execute("SELECT 1 FROM sqlite_master WHERE name='source'").fetchone()
    except Exception:
        return []
    if not have:
        return []
    out, seen = [], set()
    for ref in dict.fromkeys(refs or []):
        ref = str(ref)
        if ref.startswith("PSI-") or ref in ("iss", "moon_base", "spacesuit"):
            key = f"table:{ref}" if ref.startswith("PSI-") else None
        elif re.fullmatch(r"[A-Z]{1,3}[-_][A-Za-z0-9_\-]+", ref) and not ref.startswith("F-"):
            t = c.execute("SELECT psi FROM test WHERE test_id=?", (ref,)).fetchone()          # a test id: its investigation's experiment table
            key = f"table:{t['psi']}" if t else None
        else:
            key = ref
        if not key or key in seen:
            continue
        page = None
        if key.startswith("S6-REF"):                                   # a quote-checked reference: its document and page
            rf = c.execute("SELECT src_id, page FROM reference WHERE ref_id=?", (key,)).fetchone()
            if not rf or not rf["page"]:
                continue
            key, page = rf["src_id"], rf["page"]
            if key in seen:
                continue
        r = c.execute("SELECT * FROM source WHERE src_id=?", (key,)).fetchone()
        if not r:
            continue
        seen.add(key)
        f = None
        if r["kind"] == "card":
            f = c.execute("SELECT page, wording, paper_id FROM finding WHERE finding_id=?", (key,)).fetchone()
            page = f["page"] if f else None
        s = {"n": len(out) + 1, "src_id": key, "kind": r["kind"], "label": SOURCE_LABEL_BY_KIND.get(r["kind"], r["kind"]), "title": r["title"], "page": page, "psis": [r["psi"]] if r["psi"] else [],
             "link": f"https://doi.org/{r['doi']}" if r["doi"] else r["download_url"], "link_kind": "doi" if r["doi"] else ("nasa_psi_download" if r["download_url"] else None),
             "viewable": bool(r["local_path"])}
        if r["local_path"]:                                           # a NASA document (or a finding taken from one): the viewer opens its local copy at the page
            s["doc_id"] = key if r["kind"] == "document" else str(f["paper_id"]).replace("doc:", "") if f else None
        if r["kind"] == "card" and f:
            s["evidence"] = f["wording"]
        same = next((o for o in out if (o["title"], o["page"], o["link"]) == (s["title"], s["page"], s["link"])), None)     # two findings of one paper page are one source
        if same:
            continue
        out.append(s)
        if len(out) >= limit:
            break
    return out


def _ans(tool, question, speak, F=None, kpis=None, charts=None, table=None, gaps=None, refs=None, **extra):
    d = {"version": VERSION, "tool": tool, "question": question, "speak": speak, "kpis": kpis or [], "charts": charts or [], "table": table, "gaps": gaps or [],
         "source": _src(refs or []), "sources": _sources(refs or []), "facts": F.items if F else []}
    d.update(extra)
    return _clean(d)


def _kpi(id_, label, value, basis, trust, unit=""):
    return {"id": id_, "label": label, "value": value, "unit": unit, "basis": basis, "trust": trust}


def _tbl(cols, rows):
    return {"columns": [{"key": k, "label": l, **({"unit": u} if u else {})} for k, l, u in cols], "rows": rows}


def r3(x):
    return None if x is None else float(f"{x:.3g}") if abs(x) < 1000 else round(x)


def _rng(vals):
    vals = [v for v in vals if v is not None]
    return (min(vals), max(vals)) if vals else (None, None)


def _lab(c, f):
    return Q.cfg(c).get("labels", {}).get(f, {"say": f.replace("_", " ")})


UNIT_SYMBOL = {"percent": "%", "kilopascals": "kPa", "centimeters per second": "cm/s", "millimeters per second": "mm/s", "nanometers": "nm", "seconds": "s", "millimeters": "mm",
               "square millimeters per second": "mm\u00b2/s", "kelvin": "K", "milligrams per second": "mg/s", "parts per million": "ppm"}


def _flabel(c, f):
    """A field as a person reads it: "oxygen (%)", "pressure (kPa)", never O2_pct or nozzle_d_mm (Round 10 §10.2 item 6)."""
    lab = Q.cfg(c).get("labels", {}).get(f)
    if lab and lab.get("say"):
        u = UNIT_SYMBOL.get(lab.get("unit", ""), "")
        return f"{lab['say']} ({u})" if u else lab["say"]
    m = re.search(r"_(pct|mm|cm_s|kPa|mm_s|nm|s|K|ppm|mg_s)$", f)
    unit = {"pct": "%", "mm": "mm", "cm_s": "cm/s", "kPa": "kPa", "mm_s": "mm/s", "nm": "nm", "s": "s", "K": "K", "ppm": "ppm", "mg_s": "mg/s"}.get(m.group(1)) if m else None
    say = re.sub(r"_(pct|mm|cm_s|kPa|mm_s|nm|s|K|ppm|mg_s)$", "", f).replace("_", " ")
    return f"{say} ({unit})" if unit else say


def _fuel(c, name):
    return Q.cfg(c).get("fuel_names", {}).get(name, name).lower()


def _pl(n, word):
    """'1 PSI' / '3 PSIs'."""
    n = int(n)
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def _nm(c, psi):
    """Investigation name for speech: 'BASS-II (PSI-25)'."""
    r = c.execute("SELECT hardware, title, short_name FROM psi WHERE psi=?", (psi,)).fetchone()
    m = re.findall(r"\(([^()]+)\)", r["title"] or "") if r else []
    return f"{r['short_name'] or (m[-1] if m else r['hardware'])} ({psi})" if r else psi


def _list(xs):
    xs = list(xs)
    return ", ".join(xs[:-1]) + " and " + xs[-1] if len(xs) > 1 else (xs[0] if xs else "")


def _unknown(tool, question, what, value, options=()):
    return _ans(tool, question, [f"I could not match the {what} '{value}'." + (f" Known: {', '.join(options)}." if options else "")], gaps=[f"unknown {what}: {value}"])


def _lbl(s, F):
    return F.t(s["label"])


def pressure_phrase(c, ids, F):
    """Spoken pressure of a set of tests: a stated range is spoken as 'about X (lo to hi)'."""
    rows = [Q.primary_row(c, t, "pressure_kPa") for t in ids]
    rows = [r for r in rows if r and r["value_num"] is not None]
    if not rows:
        return "pressure not stated"
    if all(r["value_min"] is not None for r in rows):
        lo, hi = min(r["value_min"] for r in rows), max(r["value_max"] for r in rows)
        mid = round(sum(r["value_num"] for r in rows) / len(rows))
        plo, phi = U.fmt_psi(U.to_psi(lo)), U.fmt_psi(U.to_psi(hi))
        return f"pressure about {F.p(mid)}" + (f" ({plo} to {phi})" if plo != phi else "")
    lo, hi = min(r["value_num"] for r in rows), max(r["value_num"] for r in rows)
    return f"pressure {F.n(lo)} kilopascals" if lo == hi else f"pressure {F.n(lo)} to {F.n(hi)} kilopascals"


def _req(s, F):
    """Spoken requirement of a scenario."""
    o = f"{F.n(s['o2_pct'])} percent oxygen" if s["o2_pct"] else ""
    p = (f"{F.n(s['p_psi'])} psi" if s["p_psi"] else f"{F.n(s['p_kpa'])} kilopascals") if s["p_kpa"] else ""      # the challenge's own psi number
    if s["region"]:
        return "at least " + o + (" and at most " + p if p else "")
    return o + (" and " + p if p else "")


# ---------------------------------------------------------------- get_investigation
def _narrative(c, pid, F, cf):
    """Round 16: the spoken order for Saffire (config `narrative`): objective, samples / conditions, counted outcomes, then the top 1-2 findings (flight first). Words come from the data, counts from SQL."""
    nar = cf.get("narrative") or {}
    if pid not in (nar.get("psis") or []):
        return None
    p = c.execute("SELECT objectives, flight_ground FROM psi WHERE psi=?", (pid,)).fetchone()
    lines = []
    if p and p["objectives"]:
        lines.append(f"{_nm(c, pid)}: " + re.sub(r"\s+", " ", p["objectives"]).strip())
    rows = c.execute("SELECT t.test_id, t.native_id, m.value_text mat, e.value_text em, b.value_text b1g FROM test t LEFT JOIN value m ON m.test_id=t.test_id AND m.field='material' AND m.is_primary=1 "
                     "LEFT JOIN value e ON e.test_id=t.test_id AND e.field='end_mode' AND e.is_primary=1 LEFT JOIN value b ON b.test_id=t.test_id AND b.field='burn_1g_outcome' AND b.is_primary=1 "
                     "WHERE t.psi=? AND t.is_doc_test=0 AND t.counted=1 ORDER BY t.native_id", (pid,)).fetchall()
    mats = {}
    for r in rows:
        mats[r["mat"] or "unknown"] = mats.get(r["mat"] or "unknown", 0) + 1
    iv = c.execute("SELECT conditions FROM investigation WHERE psi=?", (pid,)).fetchone()
    cond = json.loads(iv["conditions"]) if iv else {}
    bits = []
    if mats:
        bits.append(_list(f"{F.i(n)} {F.t(m)}" for m, n in list(mats.items())[:4]) + " " + ("samples" if len(rows) > 1 else "sample"))
    for key, lab, u in (("o2_ambient", "oxygen", "percent"), ("flow_cm_s", "flow", "centimeters per second")):
        r = cond.get(key)
        if r:
            bits.append(f"{lab} {F.n(r[0])}" + (f" to {F.n(r[1])}" if r[1] != r[0] else "") + f" {u}")
    pr = cond.get("pressure_kPa")
    if pr:
        bits.append("a pressure of " + F.p(pr[0]))
    if bits:
        lines.append(f"The {_nm(c, pid)} tests burned " + "; ".join(bits) + ".")
    ow = nar.get("outcome_words") or {}
    ns = [r for r in rows if r["em"] == "no_spread"]
    nn = [r for r in rows if r["em"] == "pmma_consumed_nomex_not_ignited"]
    if ns or nn:
        parts = []
        if ns:
            mm = {}
            for r in ns:
                mm[r["mat"]] = mm.get(r["mat"], 0) + 1
            full = len([r for r in ns if str(r["b1g"]).strip().lower() == "complete"])
            parts.append(_list(f"{F.i(n)} {F.t(m)}" for m, n in mm.items()) + f" {'samples' if len(ns) > 1 else 'sample'} {ow.get('no_spread', 'did not spread')}" + (f"; {F.i(full)} of them burned completely in the 1-g test" if full else ""))
        if nn:
            parts.append(f"the Nomex part of {_pl(F.i(len(nn)), 'sample')} did not ignite")
        lines.append(f"Outcomes recorded in the {_nm(c, pid)} table: " + "; ".join(parts) + ".")
    elif rows and all(r["em"] == "not_recorded" for r in rows):
        lines.append(f"The data does not record how the flames ended in {_nm(c, pid)}.")
    terms = re.compile(nar.get("card_terms") or "$^", re.I)
    cards = c.execute("SELECT f.finding_id, f.statement, f.wording, f.flight, f.claim_type FROM finding f JOIN finding_psi p ON p.finding_id=f.finding_id WHERE p.psi=? ORDER BY f.finding_id", (pid,)).fetchall()
    cards = sorted(cards, key=lambda r: (-r["flight"], 0 if terms.search(r["statement"]) else 1, 0 if r["claim_type"] in ("comparison", "observation") else 1, r["finding_id"]))
    top = [r for r in cards if r["statement"]][:2]
    for r in top:
        lines.append(f"{r['wording']}: {F.t(r['statement'].rstrip('.'))}.")
    return lines, ([nar["objective_doc"]] if nar.get("objective_doc") else []) + [r["finding_id"] for r in top]


def _family_overview(c, cf, name, psis, q):
    """"What is Saffire?" / "What did Saffire find?": the flights in one short answer (objective once, the flights with their test counts, the counted outcomes, the top findings), only the sources' words."""
    F = Facts()
    nar = cf["narrative"]
    parts = [_narrative(c, p, F, cf) for p in psis]
    speak = []
    first = next((x[0][0] for x in parts if x and x[0]), None)
    if first:
        speak.append(re.sub(r"^[^:]*: ", "", first, count=1).replace("The objectives of this investigation were to:", "The objectives of the Saffire experiments were to:", 1))
    flights = []
    for p in psis:
        n = c.execute("SELECT COUNT(*) FROM test WHERE psi=? AND is_doc_test=0 AND counted=1", (p,)).fetchone()[0]
        flights.append(f"{_nm(c, p)} with {_pl(F.i(n), 'test')}")
    flights_line = f"The data holds {_list(flights)}."
    outc = next((l for x in parts if x for l in x[0] if l.startswith("Outcomes recorded in the")), None)
    terms = re.compile(nar.get("card_terms") or "$^", re.I)
    ph = ",".join("?" * len(psis))
    cards = c.execute(f"SELECT DISTINCT f.finding_id, f.statement, f.wording, f.flight, f.claim_type FROM finding f JOIN finding_psi p ON p.finding_id=f.finding_id WHERE p.psi IN ({ph}) ORDER BY f.finding_id", psis).fetchall()
    cards = sorted(cards, key=lambda r: (-r["flight"], 0 if terms.search(r["statement"]) else 1, 0 if r["claim_type"] in ("comparison", "observation") else 1, r["finding_id"]))[:2]
    speak += [f"{r['wording']}: {F.t(r['statement'].rstrip('.'))}." for r in cards]      # voice speaks the first three: objective, then the top findings
    speak += [x for x in (outc, flights_line) if x]
    kp = [_kpi("n_tests", "table tests", sum(c.execute("SELECT COUNT(*) FROM test WHERE psi=? AND is_doc_test=0 AND counted=1", (p,)).fetchone()[0] for p in psis), "tests of the three flights", "table")]
    return _ans("get_investigation", q, speak, F, kp, table=None, gaps=[], refs=list(psis[:1]) + ([nar["objective_doc"]] if nar.get("objective_doc") else []) + list(psis[1:]) + [r["finding_id"] for r in cards], family=name, psis=list(psis))


def get_investigation(psi):
    """What is this investigation / what did it test? Use for questions such as "What is BRE?", "What did PSI-69 test?", "Tell me about FLEX".
    Argument: psi = a PSI id ("PSI-20"), a number, or a hardware / experiment name ("BRE", "BASS-II").
    Returns tests, condition ranges (ambient oxygen kept apart from burner-stream oxygen), fuels, materials, outcomes measured and how much of each field is filled by trust level.
    Never invents conditions that are not in the data; never compares PSIs (use compare)."""
    c = con()
    cf = Q.cfg(c)
    q = f"get_investigation({psi})"
    fam = ((cf.get("narrative") or {}).get("families") or {}).get(str(psi).strip().lower())
    if fam:
        return _family_overview(c, cf, str(psi).strip().lower(), fam, q)
    pid = Q.resolve_psi(c, psi)
    if not pid:
        return _unknown("get_investigation", q, "PSI", psi)
    p = c.execute("SELECT * FROM psi WHERE psi=?", (pid,)).fetchone()
    iv = c.execute("SELECT * FROM investigation WHERE psi=?", (pid,)).fetchone()
    cond, fuels, mats, outs, fill = json.loads(iv["conditions"]), json.loads(iv["fuels"]), json.loads(iv["materials"]), json.loads(iv["outcomes"]), json.loads(iv["fill"])
    F = Facts()
    kind = "a flight investigation" if p["flight_ground"] == "flight" else "a ground-based investigation"
    speak = [f"{p['title']} ({pid}) is {kind}."]
    nv = _narrative(c, pid, F, cf)
    if nv:
        speak = nv[0] + [x for x in speak] ; nv_refs = nv[1]
    else:
        nv_refs = []
    if p["pillars"] and not nv:
        speak.append("According to the project registry it addresses " + F.t(p["pillars"]) + ".")
    if p["derived_from"]:
        speak.append(f"It builds on {p['derived_from'].replace(',', ' and ')}.")
    n_doc, n_dop = iv["n_doc_tests"], cond.get("doc_points_with_o2_and_p", 0)
    speak.append(f"The data holds {F.i(iv['n_tests'])} table tests" + (f" plus {F.i(n_doc)} test points taken from documents; {F.i(n_dop)} of those document points have both oxygen and pressure." if n_doc else "."))
    for key, lab, u in (("o2_ambient", "Ambient oxygen", "percent"), ("o2_oxidizer_stream", "Oxygen in the burner stream (not the atmosphere)", "percent"), ("pressure_kPa", "Pressure", "kilopascals"), ("flow_cm_s", "Flow speed", "centimeters per second")):
        r = cond.get(key)
        if r:
            speak.append(f"{lab} ranges from {F.n(r[0])} to {F.n(r[1])} {u}.")
    missing = [lab for key, lab in (("pressure_kPa", "pressure"), ("flow_cm_s", "flow speed")) if not cond.get(key)] + (["oxygen"] if not cond.get("o2_ambient") and not cond.get("o2_oxidizer_stream") else [])
    if missing:                                     # Round 13 §13.2 item 4: a field the investigation does not record is said, not "not covered"
        speak.append(f"The data does not record {_list(missing)} for {pid}.")
    if fuels:
        speak.append("Fuels: " + _list(_fuel(c, f) for f in list(fuels)[:4]) + ".")
    if mats:
        speak.append("Materials: " + _list(list(mats)[:4]) + ".")
    ph = [_lab(c, o)["say"] for o in outs[:5]]
    if ph:
        speak.append("It records " + _list(ph) + ".")
    kp = [_kpi("n_tests", "table tests", iv["n_tests"], f"{iv['n_tests']} table tests of {iv['n_tests'] + n_doc} test points", "table"),
          _kpi("n_doc", "document test points", n_doc, f"{n_dop} of {n_doc} document points have oxygen and pressure", "document")]
    rows_ = [{"field": _flabel(c, f), "tests": v.get("n"), "table": v.get("table", 0), "document": v.get("document", 0), "assumed": v.get("assumed", 0), "paper": v.get("paper", 0)} for f, v in fill.items() if f in outs or f in cond]
    gaps = [f"{pid} has no pressure values in the data."] if cond.get("pressure_kPa") is None else []
    return _ans("get_investigation", q, speak, F, kp, table=_tbl([("field", "field", ""), ("tests", "test points", ""), ("table", "from table", ""), ("document", "from documents", ""), ("assumed", "assumed", ""), ("paper", "reported in paper", "")], rows_[:20]),
                gaps=gaps, refs=[pid] + nv_refs, objectives=p["objectives"], varied=json.loads(iv["varied"]), fixed=json.loads(iv["fixed"]))


# ---------------------------------------------------------------- compare
MATWORDS = ["PMMA", "SIBAL", "cotton", "fiberglass", "Nomex", "silicone", "Kapton", "Teflon", "Ultem", "Pyrell"]


def compare(psi_a, psi_b):
    """Compare two investigations side by side ("Compare BASS and BASS-II", "How do FLEX and CFI differ?").
    Arguments: psi_a, psi_b (ids or names). Returns a side-by-side table (hardware family, fuels / materials, oxygen / pressure / flow ranges, outcomes measured, tests, what each builds on) and says what overlaps and what is missing.
    It never ranks one PSI above the other; "not directly comparable" is said only about numeric ranking claims."""
    c = con()
    q = f"compare({psi_a}, {psi_b})"
    a, b = Q.resolve_psi(c, psi_a), Q.resolve_psi(c, psi_b)
    if not a or not b:
        return _unknown("compare", q, "PSI", psi_a if not a else psi_b)
    I = {k: c.execute("SELECT * FROM investigation WHERE psi=?", (k,)).fetchone() for k in (a, b)}
    P = {k: c.execute("SELECT * FROM psi WHERE psi=?", (k,)).fetchone() for k in (a, b)}
    C = {k: json.loads(I[k]["conditions"]) for k in (a, b)}
    O = {k: json.loads(I[k]["outcomes"]) for k in (a, b)}
    FU = {k: [_fuel(c, f) for f in json.loads(I[k]["fuels"])] for k in (a, b)}
    MA = {k: list(json.loads(I[k]["materials"])) for k in (a, b)}
    MW = {k: {w for w in MATWORDS if any(w.lower() in m.lower() for m in MA[k])} for k in (a, b)}
    F = Facts()

    def rg(k, key):
        r = C[k].get(key)
        return f"{Q.fmt(r[0])} to {Q.fmt(r[1])}" if r else ""
    rows_ = [{"item": "hardware", "a": P[a]["hardware"], "b": P[b]["hardware"]}, {"item": "hardware family", "a": P[a]["hardware_family"], "b": P[b]["hardware_family"]},
             {"item": "builds on", "a": P[a]["derived_from"], "b": P[b]["derived_from"]}, {"item": "fuels", "a": ", ".join(FU[a][:4]), "b": ", ".join(FU[b][:4])},
             {"item": "materials", "a": ", ".join(sorted(MW[a])) or ", ".join(MA[a][:3]), "b": ", ".join(sorted(MW[b])) or ", ".join(MA[b][:3])},
             {"item": "ambient oxygen (percent)", "a": rg(a, "o2_ambient"), "b": rg(b, "o2_ambient")}, {"item": "pressure (kilopascals)", "a": rg(a, "pressure_kPa"), "b": rg(b, "pressure_kPa")},
             {"item": "flow speed (centimeters per second)", "a": rg(a, "flow_cm_s"), "b": rg(b, "flow_cm_s")}, {"item": "outcomes recorded", "a": ", ".join(_lab(c, o)["say"] for o in O[a][:5]), "b": ", ".join(_lab(c, o)["say"] for o in O[b][:5])},
             {"item": "table tests", "a": I[a]["n_tests"], "b": I[b]["n_tests"]}, {"item": "pillars (registry)", "a": P[a]["pillars"], "b": P[b]["pillars"]}]
    rows_ = [r for r in rows_ if r["a"] not in (None, "") or r["b"] not in (None, "")]
    na, nb_ = _nm(c, a), _nm(c, b)
    speak = [f"{na} has {F.i(I[a]['n_tests'])} table tests; {nb_} has {F.i(I[b]['n_tests'])}."]
    fam_a, fam_b = P[a]["hardware_family"], P[b]["hardware_family"]
    if fam_a and fam_a == fam_b:
        speak.append(f"Both run on the same hardware family: {fam_a}.")
    elif fam_a and fam_b:
        speak.append(f"They use different hardware: {fam_a} and {fam_b}.")
    sm = sorted(MW[a] & MW[b])
    sf = sorted(set(FU[a]) & set(FU[b]))
    if sm:
        speak.append("Both burned " + _list(sm) + ".")
    elif sf:
        speak.append("Both burn " + _list(sf) + ".")
    so = [o for o in O[a] if o in O[b]]
    if so:
        speak.append("Both record " + _list(_lab(c, o)["say"] for o in so[:4]) + ".")
    elif O[a] and O[b]:
        speak.append("They record different outcomes.")
    for key, lab, u in (("o2_ambient", "ambient oxygen", "percent"), ("pressure_kPa", "pressure", "kilopascals")):
        ra, rb = C[a].get(key), C[b].get(key)
        if ra and rb:
            lo, hi = max(ra[0], rb[0]), min(ra[1], rb[1])
            speak.append(f"Their {lab} ranges overlap from {F.n(lo)} to {F.n(hi)} {u}." if lo <= hi else f"Their {lab} ranges do not overlap.")
    gaps = []
    for k, nm in ((a, na), (b, nb_)):
        for key, lab in (("o2_ambient", "oxygen"), ("pressure_kPa", "pressure")):
            if not C[k].get(key) and not (key == "o2_ambient" and C[k].get("o2_oxidizer_stream")):
                speak.append(f"{nm} has no {lab} values in the data.")
                gaps.append(f"{nm} has no {lab} values in the data")
    shared = Q.rows(c, "SELECT g.group_id, g.outcome_field, g.fuel_class, g.n_tests FROM comparable_group g WHERE g.psis LIKE ? AND g.psis LIKE ? ORDER BY g.group_id", (f"%{a}%", f"%{b}%"))
    if shared:
        speak.append(f"{_pl(F.i(len(shared)), 'comparable group')} hold tests of both, so numbers can be compared inside them.".replace("groups hold", "groups hold") if len(shared) != 1 else "One comparable group holds tests of both, so numbers can be compared inside it.")
    else:
        gaps.append("no comparable group holds tests of both PSIs, so no numeric ranking across them")
    kp = [_kpi("n_a", f"{a} tests", I[a]["n_tests"], f"{I[a]['n_tests']} table tests", "table"), _kpi("n_b", f"{b} tests", I[b]["n_tests"], f"{I[b]['n_tests']} table tests", "table"),
          _kpi("shared", "shared comparable groups", len(shared), f"{len(shared)} groups hold tests of both", "table")]
    return _ans("compare", q, speak, F, kp, table=_tbl([("item", "item", ""), ("a", f"{P[a]['hardware']} {a}", ""), ("b", f"{P[b]['hardware']} {b}", "")], rows_), gaps=gaps, refs=[a, b] + [s["group_id"] for s in shared[:8]])


# ---------------------------------------------------------------- spacesuit (Round 5 / 5b)
def _tests_ov(c, where="1=1", args=()):
    """Eligible tests with primary O2 and pressure: (test_id, psi, role, o2, p_kpa, p_trust)."""
    return c.execute("SELECT t.test_id, t.psi, t.o2_role, o.value_num o2, p.value_num p, p.trust pt, t.native_id FROM test t JOIN value o ON o.test_id=t.test_id AND o.field='O2_pct' AND o.is_primary=1 "
                     "JOIN value p ON p.test_id=t.test_id AND p.field='pressure_kPa' AND p.is_primary=1 WHERE " + Q.ELIGIBLE + " AND COALESCE(t.flags,'') NOT LIKE '%doc_internal_conflict%' AND o.value_num IS NOT NULL AND p.value_num IS NOT NULL AND " + where, args).fetchall()


def closest_tested(c, F=None):
    """Round 5 / 5b: how far along the path Earth -> Moon base -> spacesuit PSI got. Parts: oxygen-rich inverse flames (burner stream, listed first because the challenge names CFI-G),
    the tested atmosphere corner nearest the spacesuit, the same oxygen partial pressure (not equivalent). The atmosphere level stays None."""
    cf = Q.cfg(c)
    sp = cf["spacesuit"]
    kpa_psia = cf["conversions"]["kpa_per_psia"]
    # a. burner-stream (oxidizer stream) flames
    st = _tests_ov(c, "t.o2_role='oxidizer_stream'")
    bands = []
    for b in sp["bands_pct"]:
        rows = [r for r in st if r["o2"] >= b]
        per = []
        for psi in sorted({r["psi"] for r in rows}):
            L = [r for r in rows if r["psi"] == psi]
            ps = [r["p"] for r in L]
            per.append({"psi": psi, "n": len(L), "o2_max": max(r["o2"] for r in L), "p_min_kpa": min(ps), "p_max_kpa": max(ps), "p_min_psia": min(ps) / kpa_psia, "p_max_psia": max(ps) / kpa_psia})
        ps_all = [r["p"] for r in rows]
        bands.append({"o2_min_pct": b, "n": len(rows), "psis": len({r["psi"] for r in rows}), "per_psi": per, "p_min_kpa": min(ps_all) if rows else None, "p_max_kpa": max(ps_all) if rows else None})
    hi = [r for r in st if r["o2"] >= min(sp["bands_pct"])]
    low = min(hi, key=lambda r: r["p"]) if hi else None
    top = max(hi, key=lambda r: r["o2"]) if hi else None
    lvl_n = len(hi)
    lvl_p = len({r["psi"] for r in hi})
    b_top = [r for r in st if r["o2"] >= max(sp["bands_pct"])]
    low_top = []
    if b_top:
        pm = min(r["p"] for r in b_top)
        low_top = [{"psi": r["psi"], "test": r["native_id"], "o2_pct": r["o2"], "p_kpa": r["p"], "p_psia": r["p"] / kpa_psia} for r in sorted(b_top, key=lambda r: (r["p"], r["native_id"])) if r["p"] <= pm * 1.01]
    rich = {"lowest_pressure_tests_top_band": low_top, "label": sp["challenge"]["label"], "source": "challenge-details.txt: " + sp["challenge"]["quote"], "bands": bands, "n_tests": lvl_n, "psis": lvl_p, "level": Q.level(c, lvl_n, lvl_p), "max_o2_pct": top["o2"] if top else None,
            "lowest_pressure": {"psi": low["psi"], "test": low["native_id"], "o2_pct": low["o2"], "p_kpa": low["p"], "p_psia": low["p"] / kpa_psia} if low else None, "trust": "table + document"}
    # b. the tested atmosphere corner (Moon base requirement) and the highest ambient oxygen
    mb = [r for r in _tests_ov(c, "t.o2_role='ambient'") if r["o2"] >= 30 and r["p"] <= 70.3 and r["pt"] != "assumed"]
    amb = [r for r in _tests_ov(c, "t.o2_role='ambient'") if r["pt"] != "assumed"]
    corner = None
    if mb:
        pmin = min(r["p"] for r in mb)
        at = [r for r in mb if abs(r["p"] - pmin) <= 0.01 * pmin]
        o2c = max(r["o2"] for r in at)
        corner = {"o2_pct": o2c, "p_kpa": pmin, "n_at_corner": len([r for r in at if r["o2"] == o2c]), "psi": sorted({r["psi"] for r in at if r["o2"] == o2c})}
    per = []
    for psi in sorted({r["psi"] for r in mb}):
        L = [r for r in mb if r["psi"] == psi]
        per.append({"psi": psi, "n": len(L), "o2_min": min(r["o2"] for r in L), "o2_max": max(r["o2"] for r in L), "p_min": min(r["p"] for r in L), "p_max": max(r["p"] for r in L)})
    o2max = max(r["o2"] for r in amb)
    hi_amb = [r for r in amb if r["o2"] >= cf["high_o2"]["ambient_min_pct"]]
    atm = {"region": "ambient oxygen at least 30 percent and pressure at most 70.3 kilopascals (the Moon base requirement)", "n_tests": len(mb), "psis": sorted({r["psi"] for r in mb}), "per_psi": per, "corner": corner,
           "highest_o2_in_region": max(r["o2"] for r in mb) if mb else None, "lowest_p_in_region": min(r["p"] for r in mb) if mb else None,
           "highest_ambient_o2_pct": o2max, "n_ambient_at_least_40": len(hi_amb), "psis_ambient_at_least_40": len({r["psi"] for r in hi_amb}), "trust": "table + document", "wording": "the closest tested conditions"}
    # c. same oxygen partial pressure (labelled, not equivalent)
    tgt = sp_point = cf["scenarios"]["spacesuit"]
    ppt = tgt["o2"] * tgt["p_kpa"] / 100
    pp = [r for r in amb if r["o2"] * r["p"] / 100 >= ppt]
    same = {"o2_partial_pressure_kpa": ppt, "n_tests": len(pp), "psis": sorted({r["psi"] for r in pp}), "o2_min": min((r["o2"] for r in pp), default=None), "o2_max": max((r["o2"] for r in pp), default=None),
            "p_min": min((r["p"] for r in pp), default=None), "p_max": max((r["p"] for r in pp), default=None), "trust": "computed (oxygen percent x pressure from table / document values)",
            "wording": "the same or a higher oxygen partial pressure, but at a lower oxygen fraction and higher total pressure; not the spacesuit atmosphere; never ranked or extrapolated"}
    refs = [dict(r) for r in c.execute("SELECT ref_id, kind, quote, src_id, page, title FROM reference WHERE kind IN ('direction','hardware','challenge','eva') ORDER BY ref_id")]
    return {"oxygen_rich_flames": rich, "closest_atmosphere": atm, "same_o2_partial_pressure": same, "references": refs}


def _o2p_chart(c):
    """Scatter: every tested ambient (pressure, oxygen) point by PSI (top 5 + other), burner-stream points (hollow), and the scenario points."""
    cf = Q.cfg(c)
    amb = [r for r in _tests_ov(c, "t.o2_role='ambient'")]
    cnt = defaultdict(int)
    for r in amb:
        cnt[r["psi"]] += 1
    top = [p for p, _ in sorted(cnt.items(), key=lambda kv: (-kv[1], kv[0]))[:5]]
    ser = defaultdict(set)
    for r in amb:
        ser[r["psi"] if r["psi"] in top else "other"].add((round(r["p"], 1), round(r["o2"], 1)))
    series = [{"name": f"{_nm(c, p)} ambient tests" if p != "other" else "other PSIs, ambient tests", "points": [{"x": x, "y": y} for x, y in sorted(v)[:400]]} for p, v in sorted(ser.items(), key=lambda kv: (kv[0] == "other", kv[0]))]
    st = {(round(r["p"], 1), round(r["o2"], 1)) for r in _tests_ov(c, "t.o2_role='oxidizer_stream'")}
    series.append({"name": "burner stream (inverse flames), not the atmosphere", "marker": "hollow", "points": [{"x": x, "y": y} for x, y in sorted(st)[:400]]})
    pts = []
    for sid, s in cf["scenarios"].items():
        if s.get("p_kpa") and s.get("o2") and not s.get("no_data"):
            pts.append({"x": s["p_psi"], "x_kpa": s["p_kpa"], "y": s["o2"], "label": s["label"] + (" (requirement corner)" if s.get("region") else "")})      # the challenge's own psi number
    series.append({"name": "scenario points", "marker": "cross", "points": pts})
    for sr in series:                                   # tested points are stored in kPa: converted here, the source value kept as x_kpa; scenario points already carry the challenge's psi
        for pt in sr["points"]:
            if "x_kpa" not in pt:
                pt["x_kpa"], pt["x"] = pt["x"], U.to_psi(pt["x"])
    return {"id": "o2_vs_pressure", "type": "scatter", "title": "Tested ambient oxygen against pressure, with the scenario points", "x": {"label": "pressure", "unit": "psi", "unit_from": "kPa"}, "y": {"label": "oxygen", "unit": "%"}, "series": series}


def _spacesuit_answer(c, F, sid):
    """-> (speak, kpis, gaps, closest, chart, extra) for a scenario flagged closest_tested (the spacesuit)."""
    cf = Q.cfg(c)
    s = cf["scenarios"][sid]
    ct = closest_tested(c)
    rich, atm, same = ct["oxygen_rich_flames"], ct["closest_atmosphere"], ct["same_o2_partial_pressure"]
    top = max(cf["spacesuit"]["bands_pct"])
    band = next(x for x in rich["bands"] if x["o2_min_pct"] == top)
    n_by = {r["psi"]: r["n"] for r in band["per_psi"]}
    low = rich["lowest_pressure_tests_top_band"]
    nm = lambda psi: c.execute("SELECT name FROM psi WHERE psi=?", (psi,)).fetchone()[0]
    e82 = cf["scenarios"]["exploration_8_2"]
    psia = lambda kpa: round(kpa / cf["conversions"]["kpa_per_psia"], 1)
    cmax = max(r["o2_max"] for r in band["per_psi"])
    names = _list(_nm(c, p) for p in atm["psis"])
    cor = atm["corner"]
    speak = [f"The nearest PSI data to a spacesuit's {F.n(s['o2'])} percent oxygen are ACME inside-out flames on the space station, where oxygen of up to {F.n(cmax)} percent flowed from the burner: {F.i(n_by.get('PSI-159', 0))} tests in CFI-G and {F.i(n_by.get('PSI-10', 0))} in {nm('PSI-10')} at {F.i(top)} percent or more.",
             f"The closest to spacesuit pressure were {F.i(len(low))} {nm(low[0]['psi'])} flames with {F.n(max(x['o2_pct'] for x in low))} percent oxygen at {F.p(low[0]['p_kpa'])}, against the suit's {F.n(s['p_psi'])} psi.",
             f"In those tests the chamber held nitrogen and a fuel gas, so no test was run in a pure-oxygen atmosphere; the highest oxygen in a test atmosphere was {F.n(atm['highest_ambient_o2_pct'])} percent.",
             f"BRE tested the {F.n(e82['o2'])} percent oxygen, {F.n(e82['p_psi'])} psi atmosphere considered to ease spacewalk preparation, and " + cf["spacesuit"]["spoken_direction"]]
    x_o2 = max(x["o2_pct"] for x in low)
    kp = [_kpi("level", "spacesuit atmosphere", "none tested", f"No tests at {s['o2']:g} percent oxygen and {s['p_kpa']:g} kPa", "table"),
          _kpi("level_oxygen_rich_flames", "oxygen-rich flames (burner stream)", rich["level"], f"{rich['n_tests']} tests with burner-stream oxygen of at least {min(cf['spacesuit']['bands_pct'])} percent in {rich['psis']} PSIs; lowest pressure {low[0]['p_kpa']:.1f} kPa in " + ", ".join(x['test'] for x in low) + f" ({nm(low[0]['psi'])}, {x_o2:.0f} percent oxygen); the chamber held nitrogen and a fuel gas, not the atmosphere", "table + document"),
          _kpi("closest_atmosphere", "closest tested atmosphere", f"about {Q.fmt(cor['o2_pct'])} % at {Q.fmt(cor['p_kpa'])} kPa", f"{atm['n_tests']} tests with at least 30 percent oxygen and at most 70.3 kPa; the closest tested conditions, not the spacesuit", "table + document"),
          _kpi("same_o2_partial_pressure", "same oxygen partial pressure (not equivalent)", same["n_tests"], f"{same['n_tests']} ambient tests reached {same['o2_partial_pressure_kpa']:g} kPa of oxygen partial pressure at a lower oxygen fraction", "computed")]
    gaps_l = [f"No tests near {s['label']}",
              f"{same['n_tests']} tests reached the same or a higher oxygen partial pressure ({same['o2_partial_pressure_kpa']:g} kPa) at oxygen of {Q.fmt(same['o2_min'])} to {Q.fmt(same['o2_max'])} percent and {Q.fmt(same['p_min'])} to {Q.fmt(same['p_max'])} kPa total pressure; they are not the spacesuit atmosphere",
              cf["spacesuit"]["hardware_gap"], cf["partial_gravity_text"]]
    extra = {"closest_tested": ct, "level_oxygen_rich_flames": rich["level"], "nearest": {"scenario": "moon_base", "metric": "closest tested atmosphere", "n": atm["n_tests"]},
             "cards": []}
    return speak, kp, gaps_l, ct, _o2p_chart(c), extra


# ---------------------------------------------------------------- scenario_coverage
def _cov(c, sid):
    cn = {r["match_kind"]: r for r in Q.coverage_counts(c, sid)}
    z = {"n": 0, "psis": 0}
    near, nb, od = cn.get("near", z), cn.get("nearby", z), cn.get("same_o2_p_other_diluent", z)
    st = c.execute("SELECT COUNT(*), COUNT(DISTINCT psi), COALESCE(SUM(dil_basis='psi_note'),0) FROM scenario_coverage WHERE scenario=? AND match_kind='near' AND diluent IN ('N2','air')", (sid,)).fetchone()
    return near, nb, od, {"n": st[0], "psis": st[1], "note": st[2]}


def _dil(F, n, st):
    """Spoken split of the near tests by stated diluent: nitrogen or air (per test or once for the whole PSI) vs not stated."""
    if st["n"] == 0:
        return f"none of them state nitrogen or air, so the diluent gas is unstated for all {F.i(n)}"
    if st["n"] == n:
        return "all of them state nitrogen or air" + (", stated once for the whole PSI" if st["note"] == n else (f" ({F.i(st['note'])} stated once for the whole PSI)" if st["note"] else ""))
    return f"{F.i(st['n'])} state nitrogen or air" + ((", all stated once for the whole PSI" if st["note"] == st["n"] else f" ({F.i(st['note'])} of those stated once for the whole PSI)") if st["note"] else "") + f" and {F.i(n - st['n'])} do not state the diluent gas"


def _dil_basis(n, st):
    parts = [f"{st['n'] - st['note']} state N2 or air per test" if st["n"] - st["note"] else "", f"{st['note']} nitrogen (stated for the whole PSI)" if st["note"] else "", f"{n - st['n']} do not state the diluent gas" if n - st["n"] else ""]
    return f"{n} tests; " + ", ".join(x for x in parts if x)


def _by_oxygen(c, F, s):
    """A scenario with more oxygen than any tested atmosphere: say the highest ambient oxygen tested, and label burner-stream oxygen."""
    cf = Q.cfg(c)
    near, nb, od, st = _cov(c, "high_o2")
    so = c.execute("SELECT MAX(o2_pct), GROUP_CONCAT(DISTINCT psi) FROM scenario_coverage WHERE scenario='high_o2' AND match_kind='oxidizer_stream'").fetchone()
    thr = cf["high_o2"]["ambient_min_pct"]
    out = [f"The highest ambient oxygen tested is at least {F.n(thr)} percent: {F.i(near['n'])} tests in {_pl(F.i(near['psis']), 'PSI')}."]
    if so[0]:
        out.append(f"Separately, the oxygen in a burner stream reaches {F.n(so[0])} percent in inverse flames ({F.t(_list(sorted(so[1].split(','))))}); that is not an atmosphere.")
    return out, {"scenario": "high_o2", "metric": "ambient oxygen", "n": near["n"]}


def scenario_coverage(scenario):
    """Which tests are near a scenario atmosphere? ("Tests near the Moon base atmosphere?", "What do we have for the ISS / spacesuit / exploration 8.2 psia?").
    Argument: scenario = iss, moon_base, exploration_10_2, exploration_8_2, spacesuit, high_o2 (aliases accepted: Moon, ISS, spacesuit).
    Counts ambient oxygen only. Burner-stream oxygen of inverse flames is separate; He / CO2 diluent tests are listed apart, never counted. Every answer says how many near tests state nitrogen or air (per test or once for the whole PSI) and how many do not state the diluent gas.
    moon_base is a requirement (at least 30 percent oxygen, at most 70.3 kilopascals): near = inside it, nearby = within the band outside. Mars and partial gravity have no PSI data; it says so."""
    c = con()
    cf = Q.cfg(c)
    q = f"scenario_coverage({scenario})"
    sid = Q.resolve_scenario(c, scenario)
    if not sid:
        return _unknown("scenario_coverage", q, "scenario", scenario, [r["scenario"] for r in c.execute("SELECT scenario FROM scenario ORDER BY 1")])
    s = c.execute("SELECT * FROM scenario WHERE scenario=?", (sid,)).fetchone()
    if s["no_data"]:
        return gaps(sid)
    F = Facts()
    if cf["scenarios"][sid].get("closest_tested"):
        sp_speak, sp_kpis, sp_gaps, ct, chart, ex = _spacesuit_answer(c, F, sid)
        return _ans("scenario_coverage", q, sp_speak, F, sp_kpis, [chart], gaps=sp_gaps, refs=[sid] + [r["ref_id"] for r in ct["references"]], scenario=sid, level="None", level_n2_stated="None", **ex)
    near, nb, od, st = _cov(c, sid)
    if sid == "high_o2":
        so = c.execute("SELECT COUNT(*), COUNT(DISTINCT psi), MAX(o2_pct) FROM scenario_coverage WHERE scenario='high_o2' AND match_kind='oxidizer_stream'").fetchone()
        thr = cf["high_o2"]["ambient_min_pct"]
        speak = [f"With ambient oxygen of at least {F.n(thr)} percent, {F.i(near['n'])} tests in {_pl(F.i(near['psis']), 'PSI')} are in range; {_dil(F, near['n'], st)}.",
                 f"Oxygen in a burner stream, which is not the atmosphere, reaches {F.n(so[2])} percent in {F.i(so[0])} inverse-flame tests in {_pl(F.i(so[1]), 'PSI')}."]
        if nb["n"]:
            speak.append(f"{F.i(nb['n'])} more tests are within {F.n(cf['coverage']['near']['o2_pts'])} points below the threshold.")
        kp = [_kpi("ambient", "tests with ambient O2 at least 40 %", near["n"], _dil_basis(near["n"], st), "table"),
              _kpi("stream", "tests with burner-stream O2 at least 40 %", so[0], f"{so[0]} tests in {so[1]} PSIs; burner stream, not atmosphere", "table")]
        rows_ = Q.rows(c, "SELECT psi, match_kind, COUNT(*) n, MIN(o2_pct) o2_min, MAX(o2_pct) o2_max FROM scenario_coverage WHERE scenario='high_o2' GROUP BY 1,2 ORDER BY 1,2")
        return _ans("scenario_coverage", q, speak, F, kp, table=_tbl([("psi", "PSI", ""), ("match_kind", "kind", ""), ("n", "tests", ""), ("o2_min", "O2 min", "%"), ("o2_max", "O2 max", "%")], rows_),
                    gaps=[cf["high_o2"]["stream_label"]], refs=[r["psi"] for r in rows_], scenario=sid)
    lvl, lvl2 = Q.level(c, near["n"], near["psis"]), Q.level(c, st["n"], st["psis"])
    tol = cf["coverage"]["near"]
    gps, extra = [], {}
    if near["n"] == 0:
        speak = [f"No tests in the PSI data are near {_lbl(s, F)} ({_req(s, F)})."]
        if s["o2_pct"] and s["o2_pct"] >= cf["high_o2"]["ambient_min_pct"]:
            more, nr = _by_oxygen(c, F, s)
            speak += more
            extra["nearest"] = nr
        else:
            for alt in cf["nearest_covered"].get(sid, []):
                a_near = _cov(c, alt)[0]
                if a_near["n"]:
                    speak.append(f"The nearest covered scenario is {F.t(c.execute('SELECT label FROM scenario WHERE scenario=?', (alt,)).fetchone()[0])}, with {F.i(a_near['n'])} tests.")
                    extra["nearest"] = {"scenario": alt, "metric": "tests near the scenario", "n": a_near["n"]}
                    break
        gps.append(f"No tests near {s['label']}")
    else:
        how = "inside the requirement" if s["region"] else f"within {F.n(tol['o2_pts'])} points of oxygen and {F.n(tol['p_rel'] * 100)} percent of pressure"
        speak = [f"For {_lbl(s, F)} ({_req(s, F)}), {F.i(near['n'])} tests in {_pl(F.i(near['psis']), 'PSI')} are {how}; {_dil(F, near['n'], st)}.",
                 f"Coverage is {lvl}" + (f"; counting only tests that state nitrogen or air it is {lvl2}." if lvl2 != lvl else ".")]
    if nb["n"]:
        speak.append(f"A second tier adds {F.i(nb['n'])} nearby tests {'just outside the requirement' if s['region'] else 'in a looser band'}.")
    if od["n"]:
        speak.append(f"{F.i(od['n'])} more tests have the same oxygen and pressure but a helium or carbon dioxide diluent; they are not counted.")
    byp = Q.rows(c, "SELECT psi, COUNT(*) n, SUM(diluent IN ('N2','air')) n_n2_stated, MIN(o2_pct) o2_min, MAX(o2_pct) o2_max, MIN(p_kpa) p_min, MAX(p_kpa) p_max, SUM(p_trust='assumed') p_assumed FROM scenario_coverage WHERE scenario=? AND match_kind='near' GROUP BY psi ORDER BY n DESC, psi", (sid,))
    ass = sum(r["p_assumed"] or 0 for r in byp)
    pp = c.execute("SELECT MIN(ppo2_kpa), MAX(ppo2_kpa) FROM scenario_coverage WHERE scenario=? AND match_kind='near'", (sid,)).fetchone()
    if pp[0] is not None and near["n"]:
        speak.append(f"Oxygen partial pressure of the near tests ranges from {F.n(pp[0])} to {F.n(pp[1])} kilopascals.")
    kp = [_kpi("near", "tests near" + (" (inside the requirement)" if s["region"] else ""), near["n"], _dil_basis(near["n"], st) + f"; {near['n'] - ass} with pressure from a table or document, {ass} assumed", "table"),
          _kpi("psis", "PSIs", near["psis"], f"{near['psis']} PSIs", "table"), _kpi("level", "coverage level", lvl, f"on all {near['n']} near tests", "table"),
          _kpi("level_n2_stated", "level counting only tests that state N2 or air", lvl2, f"{st['n']} tests in {st['psis']} PSIs", "table")]
    return _ans("scenario_coverage", q, speak, F, kp, table=_tbl([("psi", "PSI", ""), ("n", "tests", ""), ("n_n2_stated", "of which N2 or air stated", ""), ("o2_min", "O2 min", "%"), ("o2_max", "O2 max", "%"), ("p_min", "pressure min", "kPa"), ("p_max", "pressure max", "kPa"), ("p_assumed", "assumed pressure", "")], [{k: (r3(v) if isinstance(v, float) else v) for k, v in r.items()} for r in byp[:20]]),
                gaps=gps, refs=[r["psi"] for r in byp], scenario=sid, level=lvl, level_n2_stated=lvl2, n_near=near["n"], n_n2_stated=st["n"], **extra)


# ---------------------------------------------------------------- get_findings
def get_findings(x, y, fuel=None):
    """How does Y change with X? ("How does spread rate change with oxygen?", "What affects extinction diameter?"). Arguments: x, y = field names or plain words
    (oxygen, pressure, flow, spread rate, particle size ...), fuel = optional fuel / material word.
    Returns the paper findings (each worded by its evidence basis, "on the ISS" only for flight evidence) and the supporting test points from the data, with trust per point.
    Never draws a trend line of its own."""
    c = con()
    q = f"get_findings({x}, {y}, {fuel})"
    fx, fy = Q.resolve_field(c, x), Q.resolve_field(c, y)
    if not fx or not fy:
        return _unknown("get_findings", q, "field", x if not fx else y)
    cs = Q.cards(c, x=fx, y=fy, text=fuel)
    cs.sort(key=lambda k: (not k["wording"].startswith(("On the ISS", "In flight")), k["finding_id"]))
    pts = Q.rows(c, "SELECT t.test_id, t.psi, t.native_id, t.fuel_class, a.value_num x, b.value_num y, a.trust xt, b.trust yt FROM test t JOIN value a ON a.test_id=t.test_id AND a.field=? AND a.is_primary=1 "
                    "JOIN value b ON b.test_id=t.test_id AND b.field=? AND b.is_primary=1 WHERE " + Q.ELIGIBLE + " AND a.value_num IS NOT NULL AND b.value_num IS NOT NULL ORDER BY t.test_id", (fx, fy))
    if fuel:
        fr = re.compile(fuel, re.I)
        pts = [p for p in pts if fr.search(" ".join(str((Q.primary(c, p["test_id"], f) or {}).get("value_text")) for f in ("fuel", "material")))]
    F = Facts()
    lx, ly = _lab(c, fx)["say"], _lab(c, fy)["say"]
    speak, gaps = [], []
    for k in cs[:3]:
        speak.append(f"{k['wording']}: {F.t(k['statement'])}")
    series = defaultdict(list)
    for p in pts:
        series[p["psi"]].append({"x": p["x"], "y": p["y"]})
    ch = []
    if pts:
        speak.append(f"The data holds {F.i(len(pts))} test points with both {lx} and {ly}, from {F.i(len(series))} PSIs.")
        ch = [{"id": "support", "type": "scatter", "title": f"{ly} against {lx} (test points)", "x": {"label": lx, "unit": Q.field_unit(c, fx)}, "y": {"label": ly, "unit": Q.field_unit(c, fy)},
               "series": [{"name": k, "points": v[:60]} for k, v in sorted(series.items())]}]
    else:
        gaps.append(f"no test has both {lx} and {ly} as values")
    if not cs:
        gaps.append(f"no paper finding relates {lx} to {ly}" + (f" for {fuel}" if fuel else ""))
        speak.append("No paper finding relates these two quantities." if not pts else "No paper finding relates these two quantities; only test points are available.")
    kp = [_kpi("cards", "paper findings", len(cs), f"{len(cs)} accepted cards", "paper"), _kpi("points", "test points", len(pts), f"{len(pts)} tests with both values", "mixed")]
    return _ans("get_findings", q, speak, F, kp, ch, _tbl([("finding", "finding", ""), ("wording", "evidence", ""), ("psis", "PSIs", "")], [{"finding": k["statement"], "wording": k["evidence_basis"], "psis": ",".join(k["psis"])} for k in cs[:20]]) if cs else None,
                gaps, refs=[k["finding_id"] for k in cs[:10]] + [p["test_id"] for p in pts[:10]],
                cards=[{"id": k["finding_id"], "statement": k["statement"], "wording": k["wording"], "quote": k["quote"], "evidence_basis": k["evidence_basis"], "paper": k["paper_id"], "paper_title": _paper_title(c, k["paper_id"]), "page": k["page"]} for k in cs])


# ---------------------------------------------------------------- oxygen_effect
def oxygen_effect(scenario=None, material=None):
    """What oxygen level is dangerous, and how does more oxygen change a fire? ("What oxygen level makes the spacecraft dangerous?", "Is more oxygen dangerous?", "How much oxygen makes a fire worse?").
    Arguments: scenario = optional scenario id (iss, moon_base, spacesuit, exploration_10_2, exploration_8_2, high_o2), material = optional material word (PMMA, SIBAL ...).
    Shows the oxygen of the atmosphere, the flight findings that relate oxygen to flame behaviour (flight first, each worded by its evidence basis), the BRE thesis statement on steady flames, the cool-flame limit and the oxygen-pressure chart.
    It never gives a single safe or dangerous oxygen level: the PSI data does not set one, and every answer says so."""
    c = con()
    cf = Q.cfg(c)
    oe = cf["oxygen_effect"]
    q = f"oxygen_effect({scenario}, {material})"
    sid = None
    if scenario:
        sid = Q.resolve_scenario(c, scenario)
        if not sid:
            return _unknown("oxygen_effect", q, "scenario", scenario, [r["scenario"] for r in c.execute("SELECT scenario FROM scenario ORDER BY 1")])
    F = Facts()
    speak, gaps_l, rows_, cards, refs, kp = [], [oe["gap_line"]], [], [], [], []
    sc = cf["scenarios"].get(sid) if sid else None
    definition = None
    if sc and not sc.get("no_data") and sc.get("o2") is not None:
        if sid == "moon_base":
            definition = F.t(oe["moon_quote"])             # the challenge sentence is evidence about the Moon base, not just a definition
        else:
            at = "at least " if sc.get("region") else ""
            kpa = (f" at {F.n(sc['p_psi'])} psi" if sc.get("p_psi") else f" at {F.n(sc['p_kpa'], 4)} kilopascals") if sc.get("p_kpa") else ""
            lab = _lbl(c.execute("SELECT * FROM scenario WHERE scenario=?", (sid,)).fetchone(), F)
            definition = f"{lab[0].upper() + lab[1:]} has {at}{F.n(sc['o2'])} percent oxygen{kpa}."
        kp.append(_kpi("scenario_o2", f"oxygen, {sc['label']}", sc["o2"], "scenario definition", "scenario", "%"))
        refs.append(sid)
    elif sc and sc.get("no_data"):
        gaps_l.append(cf.get("partial_gravity_text") if sid == "partial_gravity" else cf.get("mars_text"))
    mat = re.compile(re.escape(material), re.I) if material else None
    if sid == "spacesuit":
        # Round 10 §10.1 item 4: the suit is 100 % oxygen; the low-oxygen findings say nothing about it. The nearest data are oxygen-rich burner flames, and no 100 % atmosphere was tested.
        sp = cf["spacesuit"]
        stream = cf["high_o2"]["stream_label"]
        speak += [F.t(stream[0].upper() + stream[1:] + "."), F.t(sp["hardware_gap"]), F.t(oe["gap_line"]), definition]
        refs += ["S6-REF-CHALLENGE", sp["hardware"]["ref"]]
        rows_ += [{"what": sp["challenge"]["label"], "evidence": "the challenge text", "source": "NASA Space Apps challenge text"}, {"what": sp["hardware_gap"], "evidence": "the ACME design documents", "source": "ACME CDR package, page " + str(sp["hardware"]["page"])}]
    else:
        for fid in oe["findings"]:
            k = c.execute("SELECT finding_id, statement, quote, wording, evidence_basis, paper_id, page FROM finding WHERE finding_id=?", (fid,)).fetchone()
            if not k or (mat and not mat.search(k["statement"])):
                continue
            cards.append({"id": k["finding_id"], "statement": k["statement"], "wording": k["wording"], "quote": k["quote"], "evidence_basis": k["evidence_basis"], "paper": k["paper_id"], "paper_title": _paper_title(c, k["paper_id"]), "page": k["page"]})
            rows_.append({"what": k["statement"], "evidence": k["wording"], "source": f"{_paper_title(c, k['paper_id'])}, page {k['page']}"})
            refs.append(k["finding_id"])
        if material and not cards:
            gaps_l.append(f"no accepted finding relates {material} to a specific oxygen level")
        br = c.execute("SELECT quote, src_id, page, title FROM reference WHERE ref_id=?", (oe["bre_ref"],)).fetchone()
        bre_line = None
        if br and not material:
            t = clean_title(br["title"], c)
            bre_line = f"From {t}, page {br['page']}: {F.t(br['quote'])}"
            rows_.append({"what": br["quote"], "evidence": "the thesis author's words", "source": f"{t}, page {br['page']}"})
            refs.append(oe["bre_ref"])
        # Round 10 §10.1 item 3: the most relevant flight finding, then the BRE 26 % statement, then the gap line, then the scenario definition (the first three lines are what the voice says)
        if sid == "moon_base" and definition:
            speak.append(definition)
            definition = None
        for k in cards[:1]:
            speak.append(f"{k['wording']}: {F.t(k['statement'])}")
        if bre_line:
            speak.append(bre_line)
        speak.append(F.t(oe["gap_line"]))
        if definition:
            speak.append(definition)
        for k in cards[1:]:
            speak.append(f"{k['wording']}: {F.t(k['statement'])}")
    kp.append(_kpi("findings", "flight findings on oxygen", len(cards), f"{len(cards)} accepted cards", "paper"))
    return _ans("oxygen_effect", q, speak, F, kp, [_o2p_chart(c)], _tbl([("what", "what the data says", ""), ("evidence", "evidence", ""), ("source", "source", "")], rows_) if rows_ else None, gaps_l, refs=refs, cards=cards, **({"scenario": sid} if sid else {}))


# ---------------------------------------------------------------- rank_materials
def _material_cards(c, cf, solid_psis, classes):
    cs = [k for k in Q.cards(c, claim_types=cf["rank_materials"]["card_claim_types"], terms=cf["rank_materials"]["card_terms"]) if solid_psis & set(k["psis"])]
    words = {"solid:PMMA": "PMMA", "solid:fabric": "cotton|fiberglass|SIBAL|fabric|Nomex", "solid:silicone": "silicone"}
    rx = re.compile("|".join(words[x] for x in classes if x in words) or "$^", re.I)
    flight = lambda k: k["wording"].startswith(("On the ISS", "In flight"))
    cs.sort(key=lambda k: (not flight(k), not rx.search(k["statement"] + " " + (k["quote"] or "")), k["finding_id"]))
    return cs


def _spread_rows(c, sid):
    """One row = investigation x material class x flow direction (no means across varied conditions)."""
    vs = [v for v in Q.values(c, "spread_rate_mm_s") if v["value_num"] is not None]
    if sid:
        ids = set(Q.scope_tests(c, sid))
        vs = [v for v in vs if v["test_id"] in ids]
    by = defaultdict(list)
    for v in vs:
        d = (Q.primary(c, v["test_id"], "flow_direction") or {}).get("value_text")
        by[(v["psi"], v["fuel_class"], d or "")].append(v)
    return by


def rank_materials(metric="spread_rate", scenario=None):
    """Which material spreads flame faster or slower? ("Which material spreads fastest at 30 % O2?", "Rank materials by flame spread"). Arguments: metric = spread rate (the only measured metric that can be ranked), scenario = optional scenario id.
    Ranks only inside one comparable group of ONE PSI (same hardware and setup, flow direction known, oxygen / pressure / flow within tolerance; flagged cross_material_same_psi when the materials differ).
    Across PSIs it never ranks and never averages over varied conditions: one row per investigation, material class and flow direction, giving each value (3 tests or fewer) or the range and count.
    The wording is "spread faster / slower in these tests", never "safer"; spread rate alone does not rate fire safety. Limiting oxygen / flammability limits are shown only as the authors' reported findings (flight evidence first), never ranked against measured values."""
    c = con()
    cf = Q.cfg(c)
    q = f"rank_materials({metric}, {scenario})"
    m = re.sub(r"[\s_\-]+", " ", str(metric).lower())
    key = next((k for k, v in cf["metric_aliases"].items() if m in {re.sub(r"[\s_\-]+", " ", a.lower()) for a in v}), None)
    sid = Q.resolve_scenario(c, scenario) if scenario else None
    if scenario and not sid:
        return _unknown("rank_materials", q, "scenario", scenario)
    if sid in ("mars", "partial_gravity"):
        return gaps(sid)
    solid = {r[0] for r in c.execute("SELECT DISTINCT psi FROM test WHERE fuel_class LIKE 'solid%'")}
    F = Facts()
    gaps_l = [GAP_SAFETY]
    flight = lambda k: k["wording"].startswith(("On the ISS", "In flight"))

    def card_lines(lim, n):
        out = []
        if not any(flight(k) for k in lim[:n]):
            out.append("No flight finding on this is in the data; the finding below comes from a normal-gravity test.")
            gaps_l.append("no flight finding on limiting oxygen or flammability of a solid material in the data")
        out += [f"{k['wording']}: {F.t(k['statement'])}" for k in lim[:n]]
        return out
    if key != "spread_rate_mm_s":
        lim = _material_cards(c, cf, solid, [])
        speak = ["Only flame spread rate can be ranked. Limiting oxygen and ignition outcomes are not measured as numbers per material, so they are not ranked."] + card_lines(lim, 3)
        gaps_l.append(f"metric '{metric}' is not rankable; reported limits are shown as the authors' findings")
        return _ans("rank_materials", q, speak, F, gaps=gaps_l, refs=[k["finding_id"] for k in lim[:5]], cards=[{"id": k["finding_id"], "statement": k["statement"], "wording": k["wording"], "evidence_basis": k["evidence_basis"], "psis": k["psis"]} for k in lim[:10]], ranked=False)
    grs = Q.groups_for(c, "spread_rate_mm_s", sid)
    speak, rows_, ranked_any = [], [], False
    for g in grs:
        vs = [v for v in Q.group_values(c, g["group_id"], "spread_rate_mm_s") if v["value_num"] is not None]
        by = defaultdict(list)
        for v in vs:
            by[v["fuel_class"]].append(v)
        if len(by) >= 2:
            ranked_any = True
            rr = sorted(by.items(), key=lambda kv: -sum(x["value_num"] for x in kv[1]) / len(kv[1]))
            speak.append(f"In {_nm(c, g['psis'])} with {g['flow_direction']} flow at {F.t(Q.fmt(g['flow_min']))} to {F.t(Q.fmt(g['flow_max']))} centimeters per second and oxygen {F.t(Q.fmt(g['o2_min']))} to {F.t(Q.fmt(g['o2_max']))} percent, materials spread faster to slower in these tests: "
                         + "; ".join(f"{k.split(':')[-1]} {F.n(sum(x['value_num'] for x in L) / len(L))} millimeters per second over {F.i(len(L))} tests" for k, L in rr) + ".")
    by = _spread_rows(c, sid)
    tbl_rows = []
    for (psi, fcl, d), L in sorted(by.items()):
        nums = sorted(x["value_num"] for x in L)
        o2 = _rng([(Q.primary(c, x["test_id"], "O2_pct") or {}).get("value_num") for x in L])
        fl = _rng([(Q.primary(c, x["test_id"], "flow_cm_s") or {}).get("value_num") for x in L])
        span = lambda lo, hi, u: (f"{F.n(lo)} {u}" if lo == hi else f"{F.n(lo)} to {F.n(hi)} {u}")
        vtxt = ", ".join(F.n(x) for x in nums) if len(nums) <= 3 else f"{F.n(nums[0])} to {F.n(nums[-1])}"
        mat = fcl.split(":")[-1] if fcl else "unknown material"
        line = (f"{_nm(c, psi)}, {mat}, " + ((d + " flow") if d else "flow direction not recorded") + ", " + ("flow " + span(fl[0], fl[1], "centimeters per second") if fl[0] is not None else "flow not stated")
                + ", " + ("oxygen " + span(o2[0], o2[1], "percent") if o2[0] is not None else "oxygen not stated") + ", " + pressure_phrase(c, [x["test_id"] for x in L], F)
                + (f": spread {'rate' if len(nums) == 1 else 'rates'} {vtxt} millimeters per second in {_pl(F.i(len(L)), 'test')}." if len(nums) <= 3 else f": spread rates {vtxt} millimeters per second in {F.i(len(L))} tests (range, not an average)."))
        tbl_rows.append({"investigation": _nm(c, psi), "material": mat, "direction": d or "not recorded", "n": len(L), "values": vtxt, "o2": span(o2[0], o2[1], "") .strip() if o2[0] is not None else "not stated", "flow": span(fl[0], fl[1], "").strip() if fl[0] is not None else "not stated", "trust": Q.trust_text(L)})
        if not ranked_any:
            speak.append(line)
    tbl_rows.sort(key=lambda r: (r["investigation"], r["material"], r["direction"]))     # Round 10: ordered by investigation, never by value
    if not ranked_any:
        mats_ = sorted({r["material"] for r in tbl_rows if r["material"] != "unknown material"})
        n_inv_ = len({r["investigation"] for r in tbl_rows})
        speak.insert(0, "No comparable group of different materials exists in these data, so nothing is ranked.")
        if tbl_rows:                                   # Round 10 §10.7 item 5: what they DID measure (no single material's value is read out)
            speak.insert(1, f"What the experiments did measure is the flame spread of {_list(mats_)} in {_pl(F.i(n_inv_), 'investigation')}; the values are on the screen, one row per investigation.")
        gaps_l.append("not directly comparable across PSIs; inside a PSI the missing pressure, flow direction or oxygen level blocks a group")
    nearest = None
    if sid and not tbl_rows:
        spread_any = [v for v in Q.values(c, "spread_rate_mm_s") if v["value_num"] is not None]
        o2r = _rng([(Q.primary(c, v["test_id"], "O2_pct") or {}).get("value_num") for v in spread_any])
        nw = Q.nearest_with(c, sid, "spread_rate_mm_s")
        speak.append("No flame spread test is near that scenario." + (f" The flame spread tests in the data are at {F.n(o2r[0])} to {F.n(o2r[1])} percent oxygen, near the {F.t(nw[1])} atmosphere ({F.i(nw[2])} tests)." if nw and o2r[0] is not None else ""))
        gaps_l.append(f"no spread-rate tests near the {_bare(c.execute('SELECT label FROM scenario WHERE scenario=?', (sid,)).fetchone()[0])} atmosphere")
        nearest = {"scenario": nw[0], "metric": "flame spread rate", "n": nw[2]} if nw else None
    lim = _material_cards(c, cf, solid, [r["material"] for r in tbl_rows])
    speak += card_lines(lim, 2)
    kp = [_kpi("groups", "comparable groups", len(grs), f"{len(grs)} spread-rate groups" + (f" near the {_bare(c.execute('SELECT label FROM scenario WHERE scenario=?', (sid,)).fetchone()[0])} atmosphere" if sid else ""), "table"), _kpi("rows", "rows listed", len(tbl_rows), f"{sum(r['n'] for r in tbl_rows)} tests", "mixed")]
    ex = {"nearest": nearest} if nearest else {}
    return _ans("rank_materials", q, speak, F, kp, table=_tbl([("investigation", "investigation", ""), ("material", "material class", ""), ("direction", "flow direction", ""), ("n", "tests", ""), ("values", "spread rate (each value, or min to max)", "mm/s"),
                                                                ("o2", "oxygen", "%"), ("flow", "flow", "cm/s"), ("trust", "trust", "")], tbl_rows[:20]),
                gaps=gaps_l, refs=[r["investigation"] for r in tbl_rows] + [k["finding_id"] for k in lim[:3]],
                cards=[{"id": k["finding_id"], "statement": k["statement"], "wording": k["wording"], "quote": k["quote"], "evidence_basis": k["evidence_basis"], "psis": k["psis"]} for k in lim[:10]], ranked=ranked_any, **ex)


# ---------------------------------------------------------------- rank_agents
def rank_agents(fuel_class=None):
    """Which suppressant / diluent works best? ("Which suppressant works best?", "How does CO2 compare with helium?"). Argument: fuel_class = optional (liquid, gas, solid:PMMA ...).
    In these PSIs the suppression variable is the diluent in the atmosphere (carbon dioxide, helium; nitrogen is the balance gas). Per agent and PSI it returns tests with a value above zero, concentration range, oxygen / pressure range, the source of each value
    and the authors' reported effects (cards about a diluent, flight first). Extinction-diameter counts are given only for droplet PSIs and only above zero (zeros are reported with how those tests ended).
    It never computes an "amount at extinction" threshold and never ranks agents against each other. The mass or volume of an extinguisher is not in the data; it says so."""
    c = con()
    cf = Q.cfg(c)
    q = f"rank_agents({fuel_class})"
    names = {"CO2": "carbon dioxide", "He": "helium", "N2": "nitrogen level (balance gas)"}
    F = Facts()
    rows_, speak, refs, gaps = [], [], [], []
    droplet = {r[0] for r in c.execute("SELECT DISTINCT psi FROM test WHERE fuel_class='liquid'")}
    bg = cf["agents"]["background_below_pct"]
    for name, f in cf["agents"]["fields"].items():
        vs = [v for v in Q.values(c, f, positive=True)]
        if fuel_class:
            vs = [v for v in vs if v["fuel_class"] == fuel_class]
        byp = defaultdict(list)
        for v in vs:
            byp[v["psi"]].append(v)
        for psi, L in sorted(byp.items()):
            d = _rng([v["value_num"] for v in L])
            if name != "N2" and d[1] < bg:                       # an initial chamber level, not an added agent (Round 3 item 3)
                gaps.append(f"{_nm(c, psi)} records a small initial {names[name]} level (up to {Q.fmt(d[1])} percent); it is not an added agent.")
                continue
            ids = [v["test_id"] for v in L]
            o2 = [Q.primary(c, t, "O2_pct") for t in ids]
            pp = [Q.primary(c, t, "pressure_kPa") for t in ids]
            ext = sum(1 for t in ids if (Q.primary(c, t, "extinction_d_mm") or {}).get("value_num", 0) and Q.primary(c, t, "extinction_d_mm")["value_num"] > 0) if psi in droplet else None
            o2l, p_l = _rng([o["value_num"] for o in o2 if o]), _rng([p["value_num"] for p in pp if p])
            src = sorted({(v["trust"], v["src_id"] or "table") for v in L})
            rows_.append({"agent": names[name], "psi": psi, "tests": len(L), "pct_min": r3(d[0]), "pct_max": r3(d[1]), "o2_min": r3(o2l[0]), "o2_max": r3(o2l[1]), "p_min": r3(p_l[0]), "p_max": r3(p_l[1]), "with_extinction_d": ext,
                          "source": "; ".join(f"{t}:{s}" for t, s in src[:3])})
            if name != "N2":
                speak.append(f"{names[name].capitalize()} in {_nm(c, psi)}: {F.i(len(L))} tests, concentration {F.n(d[0])} to {F.n(d[1])} percent" + (f", and {F.i(ext)} of them {'has' if ext == 1 else 'have'} a measured extinction diameter above zero" if ext else "") + ".")
    speak.insert(0, NO_BEST_AGENT)
    n2rows = [r for r in rows_ if r["agent"].startswith("nitrogen")]
    if n2rows:
        speak.append("Nitrogen is the balance gas in these tests: " + _list(f"{_nm(c, r['psi'])} {F.i(r['tests'])} tests" for r in n2rows[:4]) + ".")
    zero = defaultdict(lambda: defaultdict(int))
    for v in Q.values(c, "extinction_d_mm"):
        if v["value_num"] == 0 and v["psi"] in droplet:
            zero[v["psi"]][(Q.primary(c, v["test_id"], "test_end") or {}).get("value_text") or "not recorded"] += 1
    for psi, d in sorted(zero.items()):
        n0 = sum(d.values())
        txt = f"{_nm(c, psi)}: extinction diameter recorded as 0 in the table for {F.i(n0)} tests, which ended with " + _list(f"{k.lower()} ({F.i(n)})" for k, n in sorted(d.items())) + "; these are not measured extinction diameters."
        speak.append(txt)
        gaps.append(txt)
    psis_a = {r["psi"] for r in rows_}
    xs, eff, exc = set(cf["agents"]["card_x_fields"]), re.compile(cf["agents"]["card_effect"], re.I), cf["agents"]["card_exclude"]
    cards_ = []
    for k in Q.cards(c, claim_types=["limit", "comparison", "trend", "observation"]):
        if not (psis_a & set(k["psis"])) or exc in k["statement"]:
            continue
        agent_x = k["x_field"] in xs or re.search(r"\b(helium|dilut)", k["statement"], re.I)
        if agent_x and (k["y_field"] in ("extinction_d_mm", "burning_rate_mm2_s", "cool_flame", "O2_pct", "droplet_d0_mm") or k["claim_type"] == "limit" or eff.search(k["statement"])):
            cards_.append(k)
    cards_.sort(key=lambda k: (not k["wording"].startswith(("On the ISS", "In flight")), k["finding_id"]))
    for k in cards_[:2]:
        speak.append(f"{k['wording']}: {F.t(k['statement'])}")
    speak.append("The amount of an extinguishing agent is not in the data; the diluent percentages above are what the experiments varied.")
    gaps = [NO_BEST_AGENT] + gaps + ["extinguisher mass or volume is not in the PSI data; the diluent data is the suppression information available", "no 'amount at extinction' threshold is computed: droplet tests end by burning out, not by a limit"]
    agg = defaultdict(lambda: [0, set()])
    for r in rows_:
        agg[r["agent"]][0] += r["tests"]
        agg[r["agent"]][1].add(r["psi"])
    kp = [_kpi(re.sub(r"\W+", "_", a.split(" ")[0]).lower(), f"{a} tests", n, f"{n} tests in {_pl(len(ps), 'PSI')}", "table") for a, (n, ps) in agg.items()][:4]
    return _ans("rank_agents", q, speak, F, kp, table=_tbl([("agent", "agent", ""), ("psi", "PSI", ""), ("tests", "tests above zero", ""), ("pct_min", "min", "%"), ("pct_max", "max", "%"), ("o2_min", "O2 min", "%"), ("o2_max", "O2 max", "%"), ("p_min", "pressure min", "kPa"),
                                                              ("p_max", "pressure max", "kPa"), ("with_extinction_d", "with extinction diameter above zero (droplets)", ""), ("source", "source", "")], rows_[:20]),
                gaps=gaps, refs=[r["psi"] for r in rows_] + [k["finding_id"] for k in cards_[:3]],
                cards=[{"id": k["finding_id"], "statement": k["statement"], "wording": k["wording"], "quote": k["quote"], "evidence_basis": k["evidence_basis"], "psis": k["psis"]} for k in cards_[:8]], ranked=False)


# ---------------------------------------------------------------- rank_investigations (Stage 7, decisions Round 3 section 3.4)
PILLARS = {"prevention": ("Prevention", r"Prevention"), "flammability": ("Flammability and fire behavior", r"Fire behavior|Environment"),
           "detection": ("Detection", r"Detection"), "suppression": ("Suppression", r"Suppression")}
PILLAR_ALIASES = {"fire behavior": "flammability", "fire behaviour": "flammability", "flammability and fire behavior": "flammability", "flammability & fire behavior": "flammability",
                  "flammability fire behavior": "flammability", "smoke": "detection", "smoke detection": "detection", "fire suppression": "suppression", "fire prevention": "prevention"}
TIER_ORDER = {"A": 0, "B": 1, "C": 2, "M": 3}


def rank_investigations(pillar=None, scenario=None):
    """Which investigations matter most? ("Which experiments matter most for the Moon base?", "Which investigations are most relevant to suppression?", "Rank the investigations for the ISS").
    Arguments: pillar = optional prevention | flammability | detection | suppression (the investigations whose registry description names it; none = all), scenario = optional scenario id (iss, moon_base, spacesuit ...).
    Ranks RELEVANCE, in this order: the registry tier of the investigation (A, B, C, M, from the official PSI description), flight before ground, tests near the scenario (or tests in the data), then accepted paper findings (flight findings first). The bar value is a real test count; there is no score.
    It never rates how safe anything is, never ranks materials or gases, and for the spacesuit it counts only oxygen-rich burner-stream tests (not the atmosphere)."""
    c = con()
    cf = Q.cfg(c)
    q = f"rank_investigations({pillar}, {scenario})"
    pid = None
    if pillar:
        n = re.sub(r"[\s_\-]+", " ", str(pillar).strip().lower())
        pid = n if n in PILLARS else PILLAR_ALIASES.get(n)
        if not pid:
            return _unknown("rank_investigations", q, "pillar", pillar, list(PILLARS))
    sid = Q.resolve_scenario(c, scenario) if scenario else None
    if scenario and not sid:
        return _unknown("rank_investigations", q, "scenario", scenario, [r["scenario"] for r in c.execute("SELECT scenario FROM scenario ORDER BY 1")])
    if sid in ("mars", "partial_gravity"):
        return gaps(sid)
    F = Facts()
    slab = c.execute("SELECT label FROM scenario WHERE scenario=?", (sid,)).fetchone()[0] if sid else None
    suit = bool(sid and cf["scenarios"][sid].get("closest_tested"))
    rx = re.compile(PILLARS[pid][1], re.I) if pid else None
    if suit:
        band = closest_tested(c)["oxygen_rich_flames"]["bands"][0]
        suit_n = {r["psi"]: r["n"] for r in band["per_psi"]}
        suit_min = band["o2_min_pct"]
    near_n = {r[0]: r[1] for r in c.execute("SELECT psi, COUNT(*) FROM scenario_coverage WHERE scenario=? AND match_kind='near' GROUP BY psi", (sid,))} if sid and not suit else {}
    flight_w = ("On the ISS", "In flight")
    out = []
    for p in c.execute("SELECT psi, flight_ground, tier, pillars FROM psi ORDER BY psi").fetchall():
        if rx and not rx.search(p["pillars"] or ""):
            continue
        has_op = c.execute("SELECT COUNT(*) FROM test t JOIN value o ON o.test_id=t.test_id AND o.field='O2_pct' AND o.is_primary=1 AND o.value_num IS NOT NULL "
                           "JOIN value pr ON pr.test_id=t.test_id AND pr.field='pressure_kPa' AND pr.is_primary=1 AND pr.value_num IS NOT NULL WHERE t.psi=? AND " + Q.ELIGIBLE, (p["psi"],)).fetchone()[0]
        if suit:
            tests = suit_n.get(p["psi"], 0)
            label = f"{_pl(tests, 'burner-stream test')} at {suit_min} percent oxygen or more (not the atmosphere)" if tests else f"no burner-stream tests at {suit_min} percent oxygen or more"
        elif sid:
            tests = near_n.get(p["psi"], 0)
            label = f"{_pl(tests, 'test')} near the {slab}" if tests else ("no oxygen / pressure recorded" if not has_op else f"no tests near the {slab}")
        else:
            tests = c.execute("SELECT n_tests FROM investigation WHERE psi=?", (p["psi"],)).fetchone()[0]
            label = f"{_pl(tests, 'test')} in the data" if tests else "no oxygen / pressure recorded"
        cs = Q.cards(c, psi=p["psi"], limit=500)
        n_fl = sum(1 for k in cs if k["wording"].startswith(flight_w))
        out.append({"psi": p["psi"], "name": _nm(c, p["psi"]), "tier": p["tier"], "flight": p["flight_ground"] == "flight", "pillars": p["pillars"], "tests": tests, "tests_label": label, "findings": len(cs), "findings_flight": n_fl})
    keyf = lambda r: (TIER_ORDER.get(r["tier"], 9), not r["flight"], -r["tests"], -r["findings_flight"], -r["findings"], r["psi"])
    scen_only = bool(sid and not pid)                       # Round 4 item 4.1: for a scenario ranking with no pillar, "has tests here" comes before the tier
    if scen_only:
        rk = sorted([r for r in out if r["tests"] > 0], key=keyf)
        un = sorted([r for r in out if r["tests"] <= 0], key=lambda r: (TIER_ORDER.get(r["tier"], 9), not r["flight"], -r["findings_flight"], -r["findings"], r["psi"]))
        for i, r in enumerate(rk, 1):
            r["rank"] = i
        for r in un:
            r["rank"] = None
        out = rk + un
    else:
        out.sort(key=keyf)
        for i, r in enumerate(out, 1):
            r["rank"] = i
        rk, un = out, []
    plab = PILLARS[pid][0] if pid else None
    where = (f"for {plab}" if plab else "across all topics") + (f" near the {'high-oxygen' if sid == 'high_o2' else slab} atmosphere" if slab and not suit else "")
    n = len(out)
    if not n:
        return _ans("rank_investigations", q, [f"No investigation in the registry names {plab}."], F, gaps=["no investigation names this pillar"], pillar=pid)
    slab_sp = "spacesuit atmosphere" if suit else f"{'high-oxygen' if sid == 'high_o2' else slab} atmosphere"
    if not rk:
        speak = [f"No investigation has tests near the {slab_sp}." if not suit else "No test was run in the spacesuit atmosphere, and no burner-stream test reaches 80 percent oxygen.", "That's one of the open gaps in the data.", GAP_RELEVANCE]
        gaps_l = [GAP_RELEVANCE]
    else:
        top = rk[:3]
        tail = "tests near the scenario" if sid and not suit else ("oxygen-rich burner-stream tests, which are not the atmosphere" if suit else "tests in the data")
        speak = [f"{where[0].upper() + where[1:]}, the most relevant investigation{'s are' if len(top) > 1 else ' is'} {_list(F.t(r['name']) for r in top)}, ranked by the registry tier, then flight before ground, then {tail}."]
        if suit:
            speak[0] = "No test was run in the spacesuit atmosphere. " + speak[0]
        t0 = rk[0]
        parts = [f"relevance tier {F.t(t0['tier'])}", "a flight investigation" if t0["flight"] else "a ground-based investigation"]
        if t0["tests"]:
            parts.append(f"{_pl(F.i(t0['tests']), 'test')} " + ("near the scenario" if sid and not suit else ("with oxygen-rich burner streams" if suit else "in the data")))
        if t0["findings"]:
            parts.append(f"{_pl(F.i(t0['findings']), 'paper finding')}")
        speak.append(f"{t0['name']} comes first: " + _list(parts) + ".")
        speak.append(GAP_RELEVANCE)
        gaps_l = [GAP_RELEVANCE]
    if suit:
        gaps_l.append("No tests were run in the spacesuit atmosphere; the test counts are oxygen-rich burner-stream flames, which are not the atmosphere.")
    if un:
        gaps_l.append(f"{_pl(len(un), 'investigation')} below the divider ({NO_TESTS_DIVIDER.lower()}) {'has' if len(un) == 1 else 'have'} no rank.")
    ranking = [{"rank": r["rank"], "group": "ranked" if r["rank"] else "no_tests", "psi": r["psi"], "name": r["name"], "tier": r["tier"], "pillars": r["pillars"], "tests": r["tests"], "tests_label": r["tests_label"], "findings": r["findings"]} for r in out]
    rows_ = [{"rank": r["rank"] if r["rank"] else "", "name": r["name"], "tier": r["tier"], "pillars": r["pillars"], "tests": r["tests"], "findings": r["findings"]} for r in out]
    kp = [_kpi("candidates", "investigations ranked", len(rk), f"{len(rk)} of {n} investigations " + (f"name {plab} in the registry" if plab else ("have tests at these conditions" if scen_only else "in the registry")), "table")] if rk else []
    return _ans("rank_investigations", q, speak, F, kp, table=_tbl([("rank", "rank", ""), ("name", "investigation", ""), ("tier", "relevance tier (from the official PSI description)", ""), ("pillars", "pillars (registry)", ""),
                                                                    ("tests", "tests" + (" near the scenario" if sid and not suit else ""), ""), ("findings", "paper findings", "")], rows_[:20]),
                gaps=gaps_l, refs=[r["psi"] for r in out], ranking=ranking, ranked=True, pillar=pid, for_scenario=sid, no_tests_divider=NO_TESTS_DIVIDER if un else None,
                ranked_by="registry tier, flight before ground, tests, paper findings" if not scen_only else "has tests at the scenario, then registry tier, flight before ground, tests, paper findings")


# ---------------------------------------------------------------- gaps
def gaps(scenario=None):
    """What do we NOT know? ("What don't we know for Mars?", "What is missing for the spacesuit?", "Where are the gaps?"). Argument: scenario = optional scenario id, Mars or partial gravity.
    Mars: "PSI has no Mars-specific atmosphere and no partial-gravity combustion data" plus the nearest tested atmospheres and their coverage. A scenario with more oxygen than any test: the highest ambient oxygen tested (burner-stream oxygen labelled apart).
    Without a scenario: the incomplete PSI x field cells. Never gives a Mars value."""
    c = con()
    cf = Q.cfg(c)
    q = f"gaps({scenario})"
    sid = Q.resolve_scenario(c, scenario) if scenario else None
    if scenario and not sid:
        n = str(scenario).lower()
        sid = "mars" if "mars" in n else ("partial_gravity" if "gravity" in n else None)
        if not sid:
            return _unknown("gaps", q, "scenario", scenario, [r["scenario"] for r in c.execute("SELECT scenario FROM scenario ORDER BY 1")])
    F = Facts()
    if sid == "partial_gravity":
        return _ans("gaps", q, [cf["partial_gravity_text"]], F, [], gaps=[cf["partial_gravity_text"]], scenario=sid)
    if sid == "mars":
        speak, rows_ = [cf["mars_text"]], []
        for s in cf["nearest_to_mars"]:
            near = _cov(c, s)[0]
            lab = c.execute("SELECT label FROM scenario WHERE scenario=?", (s,)).fetchone()[0]
            rows_.append({"label": lab, "near_tests": near["n"], "psis": near["psis"]})        # Round 10: no raw scenario id on screen
            speak.append(f"{F.t(lab)}: {F.i(near['n'])} tests near it, in {_pl(F.i(near['psis']), 'PSI')}.")
        return _ans("gaps", q, speak, F, [], table=_tbl([("label", "atmosphere", ""), ("near_tests", "tests near", ""), ("psis", "PSIs", "")], rows_), gaps=[cf["mars_text"], cf["partial_gravity_text"]], scenario=sid)
    if sid and cf["scenarios"][sid].get("closest_tested"):
        sp_speak, sp_kpis, sp_gaps, ct, chart, ex = _spacesuit_answer(c, F, sid)
        return _ans("gaps", q, sp_speak, F, sp_kpis, [chart], gaps=sp_gaps, refs=[sid] + [r["ref_id"] for r in ct["references"]], scenario=sid, level="None", **ex)
    if sid:
        s = c.execute("SELECT * FROM scenario WHERE scenario=?", (sid,)).fetchone()
        near, nb, od, st = _cov(c, sid)
        gp, extra = [], {}
        if near["n"] == 0:
            speak = [f"No tests in the PSI data are near {_lbl(s, F)} ({_req(s, F)})."]
            if s["o2_pct"] and s["o2_pct"] >= cf["high_o2"]["ambient_min_pct"]:
                more, nr = _by_oxygen(c, F, s)
                speak += more
                extra["nearest"] = nr
            else:
                for alt in cf["nearest_covered"].get(sid, []):
                    a_near = _cov(c, alt)[0]
                    if a_near["n"]:
                        speak.append(f"The nearest covered scenario is {F.t(c.execute('SELECT label FROM scenario WHERE scenario=?', (alt,)).fetchone()[0])}, with {F.i(a_near['n'])} tests.")
                        extra["nearest"] = {"scenario": alt, "metric": "tests near the scenario", "n": a_near["n"]}
                        break
            gp.append(f"No tests near {s['label']}")
        else:
            speak = [f"For {_lbl(s, F)}: {F.i(near['n'])} tests in {_pl(F.i(near['psis']), 'PSI')} are near it; {_dil(F, near['n'], st)}. Coverage is {Q.level(c, near['n'], near['psis'])}."]
        if od["n"]:
            gp.append(f"{od['n']} tests have the same oxygen and pressure but a different diluent gas")
            speak.append(f"{F.i(od['n'])} more tests share the oxygen and pressure but use another diluent gas, so they do not count.")
        gp.append(cf["partial_gravity_text"])
        return _ans("gaps", q, speak, F, [_kpi("near", "tests near the point", near["n"], f"{near['n']} tests", "table")] if near["n"] else [], gaps=gp, refs=[sid], scenario=sid, **extra)
    rows_ = Q.rows(c, "SELECT psi, field, n_tests, n_table, n_document, n_assumed, n_paper, n_missing, status FROM gap WHERE scope='psi_field' AND status!='complete' ORDER BY n_missing DESC, psi, field LIMIT 20")
    tot = c.execute("SELECT COUNT(*), SUM(n_missing) FROM gap WHERE scope='psi_field' AND status!='complete'").fetchone()
    speak = [f"{F.i(tot[0])} combinations of PSI and field still have missing values, {F.i(tot[1])} test fields in all."]
    return _ans("gaps", q, speak, F, [_kpi("cells", "incomplete PSI x field cells", tot[0], f"{tot[0]} cells", "table")],
                table=_tbl([("psi", "PSI", ""), ("field", "field", ""), ("n_tests", "tests", ""), ("n_table", "table", ""), ("n_document", "document", ""), ("n_assumed", "assumed", ""), ("n_paper", "paper", ""), ("n_missing", "missing", ""), ("status", "status", "")], rows_),
                gaps=[cf["partial_gravity_text"], cf["mars_text"]], refs=[])


# ---------------------------------------------------------------- search_text
STOP = ("the", "and", "are", "why", "what", "how", "does", "for", "with", "that", "this", "from")


def _sent_split(text):
    return [x.strip() for x in re.split(r"(?<=[.!?])\s+(?=[A-Z0-9(])", re.sub(r"\s+", " ", text)) if x.strip()]


def _clean_sentence(x):
    return re.sub(r"^(\d{1,3}\s+)+(?=[A-Za-z])", "", x).strip()


JUNK = re.compile(r"DOI|Received|Accepted|Article history|www\.|Vol\.|et al\.?,? *\(?\d{4}|\.{4,}|(?:\. ){3,}|Department of|University,|Univ\.,|@\w+\.|Symposium|^[A-Z][a-z]+, [A-Z]\., ", re.I)


# Stage 7 Round 10 §10.1 item 5c: calendar, mission-news and log text ("September 19, 2018", "Week of", "Station Gets Ready for Russian Cargo", URLs, GMT day logs)
CALENDAR = re.compile(r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\.?\s+\d{1,2}(?:\s*[-\u2013]\s*\d{1,2})?(?:,?\s+\d{4})?"
                      r"|\bWeek\s+(?:of|\d+)\b|Gets Ready|https?://|\bGMT\s+\d{3}\b|\bIncrement\s+\d+\b|\bnews\b|\b(?:19|20)\d{2}\s+(?:19|20)\d{2}\b", re.I)


def _junk(x, page=None):
    """Round 4 item 4.3: bibliographic, author / affiliation, table-of-contents or page-1 title-block text is never spoken. Round 10: calendar / news / log text neither."""
    if JUNK.search(x) or CALENDAR.search(x) or x.count("\u2022") >= 3 or x.count("|") >= 2:
        return True
    return bool(page == 1 and len(re.findall(r"(?<![A-Za-z])[a-z](?![A-Za-z])", x)) >= 3)


def _best_sentence(text, toks, limit=320, page=None):
    """The sentence(s) of a passage with the most query terms, cut only at a sentence end. It starts with a capital letter or a digit (a mid-sentence fragment is skipped) and is never junk."""
    ss = [_clean_sentence(x) for x in _sent_split(text)]
    good = lambda x: len(x) > 40 and len(x.split()) >= 7 and sum(ch.isdigit() for ch in x) / len(x) < 0.15 and x[0].isupper() or (len(x) > 40 and len(x.split()) >= 7 and x[:1].isdigit() and sum(ch.isdigit() for ch in x) / len(x) < 0.15)
    ss = [x for x in ss if x and good(x) and not _junk(x, page)]
    if not ss:
        return ""
    score = lambda x: sum(1 for t in toks if t.lower() in x.lower())
    i = max(range(len(ss)), key=lambda k: (score(ss[k]), -k))
    out = ss[i]
    if len(out) < 160 and i + 1 < len(ss) and len(out) + len(ss[i + 1]) <= limit:
        out += " " + ss[i + 1]
    return out


def _norm(x):
    return re.sub(r"[^a-z0-9]+", " ", x.lower()).strip()


def search_text(query, psi=None):
    """Free-text lookup in the documents, papers and finding cards ("Why are space smoke particles bigger?", "What does the report say about soot?"). Arguments: query (words), psi = optional.
    Cards whose statement contains the query terms come first, each spoken as its full statement with its evidence wording; document and paper passages are spoken as a whole sentence with the document title and page. It does not answer from memory and gives no numbers that are not in the text."""
    c = con()
    q = f"search_text({query}, {psi})"
    pid = Q.resolve_psi(c, psi) if psi else None
    toks = [t for t in re.findall(r"[A-Za-z0-9]+", query) if len(t) > 2 and t.lower() not in STOP]
    if not toks:
        return _unknown("search_text", q, "query", query)
    hits = []
    for op in (" AND ", " OR "):
        m = op.join(f'"{t}"' for t in toks)
        sql = "SELECT p.passage_id, p.kind, p.src_id, p.psi, p.page, p.wording, p.title, p.text, rank FROM passage_fts JOIN passage p ON p.passage_id=passage_fts.rowid WHERE passage_fts MATCH ?"
        a = [m]
        if pid:
            sql += " AND (',' || REPLACE(p.psi, ' ', '') || ',') LIKE ?"          # Round 16: match each PSI of a list exactly ("PSI-10" must not match "PSI-100")
            a.append(f"%,{pid},%")
        hits = Q.rows(c, sql + " ORDER BY rank LIMIT 300", a)
        if hits:
            break
    stem = lambda t: t.lower()[:6]
    for h in hits:
        h["sent"] = h["text"] if h["kind"] == "card" else _best_sentence(h["text"], [stem(t) for t in toks], page=h["page"])
        h["terms"] = sum(1 for t in toks if stem(t) in h["sent"].lower())
    cards_ = sorted([h for h in hits if h["kind"] == "card"], key=lambda h: (-h["terms"], h["rank"]))
    docs_ = sorted([h for h in hits if h["kind"] != "card"], key=lambda h: (-h["terms"], h["rank"]))
    need = max(2, (len(toks) + 1) // 2) if len(toks) >= 2 else 1      # Round 10: at least 2 distinct query terms in the sentence
    chosen, seen = [], []                                              # Round 4 item 4.3: cards first, then document lines; a copy of a sentence adds its PSIs to the first row and is not spoken again
    for h in [h for h in cards_ if h["terms"] >= need] + [h for h in docs_ if h["terms"] >= need]:
        nk = _norm(h["sent"])
        if not nk:
            continue
        dup = next((k for k in chosen if _norm(k["sent"]) == nk or (len(nk) > 30 and (nk in _norm(k["sent"]) or _norm(k["sent"]) in nk))), None)
        if dup is not None:
            dup["psis"] = sorted(set(dup["psis"]) | set(re.split(r"\s*,\s*", h["psi"] or "")))
            continue
        h["psis"] = sorted(set(re.split(r"\s*,\s*", h["psi"] or "")) - {""})
        if len([k for k in chosen if k["kind"] == "card"]) >= 2 and h["kind"] == "card":
            continue
        if len(chosen) < 3:
            chosen.append(h)
    F = Facts()
    speak = []
    for h in chosen:
        if h["kind"] == "card":
            speak.append(f"{h['wording']}: {F.t(h['sent'])}")
        else:
            title = clean_title(h["title"] or h["src_id"], c)
            speak.append(f"From {F.t(title)}, page {F.i(h['page'])}: {F.t(h['sent'])}")
    if not chosen:
        speak.append("No passage in the documents, papers or cards matches that.")
    return _ans("search_text", q, speak, F, [], table=_tbl([("kind", "kind", ""), ("psi", "PSI", ""), ("src", "source", ""), ("page", "page", ""), ("text", "text", "")],
                [{"kind": h["kind"], "psi": ", ".join(h["psis"]), "src": clean_title(h["title"] or h["src_id"], c), "page": h["page"], "text": h["sent"]} for h in chosen]) if chosen else None,
                gaps=[] if chosen else ["no passage matches the query"], refs=[h["src_id"] for h in chosen])


# ---------------------------------------------------------------- show_view / dashboard
def show_view(view, scenario=None, params=None):
    """Open a dashboard view ("Show me the flame spread view", "Open materials for the Moon base"). Arguments: view = ignition | materials | flame_spread | smoke | suppression | gaps; scenario = optional scenario id; params = optional dict.
    Returns the Dashboard JSON (headline, key_points, up to 4 KPIs, up to 2 charts, a table of up to 20 rows that all carry the view's key value, gaps) built from the same queries as the other tools. Every KPI states 'X of Y tests' and its trust.
    A count of tests with a diluent level or an extinction diameter counts only values above zero."""
    c = con()
    cf = Q.cfg(c)
    if view not in cf["views"]:
        return _unknown("show_view", f"show_view({view})", "view", view, list(cf["views"]))
    spec = cf["views"][view]
    sid = Q.resolve_scenario(c, scenario) if scenario else None
    if scenario and not sid:
        return _unknown("show_view", f"show_view({view}, {scenario})", "scenario", scenario)
    if sid in ("mars", "partial_gravity"):
        txt = cf["mars_text"] if sid == "mars" else cf["partial_gravity_text"]
        return _dash(view, sid, "None", spec["headline"], [txt], [], [], None, [txt] if sid == "partial_gravity" else [txt, cf["partial_gravity_text"]], [])
    F = Facts()
    gaps_l, scope, debug = [], None, []
    cov, where = "no scenario selected (all tests)", "in the data"
    if sid:
        slab = F.t(_bare(c.execute("SELECT label FROM scenario WHERE scenario=?", (sid,)).fetchone()[0]))
        near = _cov(c, sid)[0] if sid != "high_o2" else {"n": 1, "psis": 1}
        cov = Q.level(c, near["n"], near["psis"]) if sid != "high_o2" else "Ambient and burner stream shown apart"
        scope = set(Q.scope_tests(c, sid))
        where = f"near the {slab} atmosphere"
        if not scope:
            debug.append(f"no tests near {sid}")
    agent_view = view == "suppression"
    bg, hthr = cf["agents"]["background_below_pct"], cf["coverage"]["species_threshold_pct"]
    if agent_view and sid:                                    # Round 4 item 3: the added-agent tests at the scenario's oxygen and pressure
        scope = {r[0] for r in c.execute("SELECT test_id FROM scenario_coverage WHERE scenario=? AND match_kind='same_o2_p_other_diluent'", (sid,))}
        OXP = "at the oxygen and pressure of the high-oxygen scenario" if sid == "high_o2" else f"at the {slab} oxygen and pressure"
        where = OXP
        gaps_l = []
    total = len(scope) if scope is not None else len(Q.scope_tests(c))
    kpis, speak, nearest, zero = [], [], None, []
    for k in spec["kpis"]:
        f = {"o2": "O2_pct"}.get(k["field"], Q.resolve_field(c, k["field"]) or k["field"])
        pos = bool(k.get("positive"))
        vs = [v for v in Q.values(c, f, positive=pos) if scope is None or v["test_id"] in scope]
        if agent_view and f in ("CO2_pct", "He_pct"):             # an initial chamber level is not an added agent
            vs = [v for v in vs if v["value_num"] >= (bg if f == "CO2_pct" else hthr)]
        lab = _lab(c, f)
        if k["kind"] == "tests_with":
            val, basis = len(vs), f"{len(vs)} of {total} tests" + (" (value above zero)" if pos else "")
            if val:
                speak.append(f"{F.i(val)} of the {F.i(total)} tests {where} have {k['noun']}.")
        elif k["kind"] == "psis_with":
            val, basis = len({v["psi"] for v in vs}), f"{len({v['psi'] for v in vs})} PSIs, {len(vs)} tests"
            if val:
                speak.append(f"{_pl(F.i(val), 'PSI')} {where} {'has' if val == 1 else 'have'} {k['noun']}.")
        elif k["kind"] == "distinct_values":
            val, basis = len({v["value_text"] for v in vs if v["value_text"]}), f"{len(vs)} of {total} tests"
            if val:
                speak.append(f"{F.i(val)} different {k['noun']} appear in the tests {where}.")
        else:
            lo, hi = _rng([v["value_num"] for v in vs])
            val, basis = (f"{Q.fmt(lo)} to {Q.fmt(hi)}" if lo is not None else "none"), f"{len(vs)} of {total} tests"
            if lo is not None:
                speak.append(f"{lab['say'].capitalize()} ranges from {F.n(lo)} to {F.n(hi)} {lab.get('unit', '')} in {F.i(len(vs))} of the {F.i(total)} tests {where}.")
        if vs and f in ("CO2_pct", "He_pct"):
            small = sum(1 for v in vs if v["value_num"] < cf["agents"]["background_below_pct"])
            if small:
                speak.append(f"{F.i(small)} of those are initial chamber levels below {F.n(cf['agents']['background_below_pct'])} percent, not an added agent.")
        if not vs:
            zero.append((k, f, pos))
        kpis.append(_kpi(k["id"], k["label"], val, basis, Q.trust_text(vs), k.get("unit", "")))
    if agent_view:
        for psi_, mx in c.execute("SELECT t.psi, MAX(v.value_num) FROM value v JOIN test t USING(test_id) WHERE v.field='CO2_pct' AND v.is_primary=1 AND v.value_num>0 AND t.counted=1 GROUP BY t.psi HAVING MAX(v.value_num) < ? ORDER BY t.psi", (bg,)):
            gaps_l.append(f"{_nm(c, psi_)} records a small initial carbon dioxide level (up to {Q.fmt(mx)} percent); it is not an added agent.")
    if agent_view and sid:
        ext = [v for v in Q.values(c, "extinction_d_mm", positive=True) if v["test_id"] in scope]
        if scope:
            speak = [f"{OXP[0].upper() + OXP[1:]}, {F.i(len(scope))} tests added carbon dioxide or helium; {F.i(len(ext))} of them {'has' if len(ext) == 1 else 'have'} a measured extinction diameter above zero."]
        else:
            msg = f"No tests added carbon dioxide or helium {OXP}."
            alt = next((a for a in [x for x in cf["nearest_covered"].get(sid, [])] + [r[0] for r in c.execute("SELECT scenario FROM scenario WHERE no_data=0 ORDER BY 1")]
                        if a not in (sid, "high_o2") and c.execute("SELECT 1 FROM scenario_coverage WHERE scenario=? AND match_kind='same_o2_p_other_diluent' LIMIT 1", (a,)).fetchone()), None)
            speak = [msg]
            gaps_l.append(msg)
            if alt:
                n_alt = c.execute("SELECT COUNT(*) FROM scenario_coverage WHERE scenario=? AND match_kind='same_o2_p_other_diluent'", (alt,)).fetchone()[0]
                speak.append(f"The nearest scenario with added carbon dioxide or helium tests is the {F.t(c.execute('SELECT label FROM scenario WHERE scenario=?', (alt,)).fetchone()[0])} atmosphere ({F.i(n_alt)} tests).")
                nearest = {"scenario": alt, "metric": "added carbon dioxide or helium tests", "n": n_alt}
        zero = []
    if zero:                                                           # zero counts are never spoken as numbers: one gap sentence + the nearest scenario that has the data
        nouns = _list(k["noun"] for k, _, _ in zero)
        msg = f"No tests {where} have {nouns} in the PSI data."
        if len(zero) == len(spec["kpis"]) and sid:                    # Round 4 item 4.2: every metric is zero -> one sentence, not a joined list of metric names
            msg = f"No {VIEW_LABEL.get(view, view)} tests {where} in the PSI data."
        gaps_l.append(msg)
        sp = [msg]
        k0, f0, pos0 = zero[0]
        nw = Q.nearest_with(c, sid, f0, positive=pos0) if sid else None
        if nw:
            sp.append(f"The nearest tests with {k0['noun']} are near the {F.t(nw[1])} atmosphere ({F.i(nw[2])} tests).")
            nearest = {"scenario": nw[0], "metric": k0["noun"], "n": nw[2]}
        speak += sp
    if view == "suppression":
        z = defaultdict(int)
        for v in Q.values(c, "extinction_d_mm"):
            if v["value_num"] == 0 and (scope is None or v["test_id"] in scope):
                z[(Q.primary(c, v["test_id"], "test_end") or {}).get("value_text") or "not recorded"] += 1
        if z:
            n0 = sum(z.values())
            txt = (f"{F.i(n0)} tests {where} have an extinction diameter recorded as 0 in the table; they ended with " if n0 != 1 else f"1 test {where} has an extinction diameter recorded as 0 in the table; it ended with ") + _list(f"{k.lower()} ({F.i(n)})" for k, n in sorted(z.items())) + ", so 0 is not a measured extinction diameter."
            speak.append(txt)
            gaps_l.append(txt)
    charts = []
    for ch in spec["charts"][:cf["limits"]["charts"]]:
        yf = ch["y"]["field"]
        yv = {v["test_id"]: v for v in Q.values(c, yf, positive=yf == "extinction_d_mm") if v["value_num"] is not None and (scope is None or v["test_id"] in scope)}
        if ch["type"] == "scatter":
            xv = {v["test_id"]: v for v in Q.values(c, ch["x"]["field"]) if v["value_num"] is not None}
            ser = defaultdict(list)
            for t, v in sorted(yv.items()):
                if t in xv:
                    ser[v["psi"]].append({"x": xv[t]["value_num"], "y": v["value_num"]})
            sr = [{"name": k, "points": p[:60]} for k, p in sorted(ser.items())]
        elif ch.get("group") == "material":
            g = defaultdict(list)
            for t, v in yv.items():
                m = Q.primary(c, t, "material")
                if m and m["value_text"]:
                    g[m["value_text"]].append(v["value_num"])
            sr = [{"name": "mean", "points": [{"x": k, "y": round(sum(v) / len(v), 4)} for k, v in sorted(g.items())][:20]}] if g else []
        else:
            sr = [{"name": "tests", "points": [{"x": v["native_id"] or t, "y": v["value_num"]} for t, v in sorted(yv.items())][:20]}] if yv else []
        if any(s["points"] for s in sr):
            charts.append({"id": ch["id"], "type": ch["type"], "title": ch["title"], "x": ch.get("x", {}), "y": {k_: v_ for k_, v_ in ch["y"].items() if k_ != "field"}, "series": sr})
        else:
            debug.append(f"chart '{ch['title']}' has no points" + (f" near {sid}" if sid else ""))
    if spec["table"].get("gap_rows"):
        rows_ = Q.rows(c, "SELECT psi, field, n_tests, n_missing, status FROM gap WHERE scope='psi_field' AND status!='complete' ORDER BY n_missing DESC, psi, field LIMIT 20")
        table = _tbl([("psi", "PSI", ""), ("field", "field", ""), ("n_tests", "tests", ""), ("n_missing", "missing", ""), ("status", "status", "")], rows_)
        speak.append(f"The {F.i(len(rows_))} largest gaps are listed; partial gravity has no PSI data at all.")
        gaps_l += [cf["partial_gravity_text"], cf["mars_text"]]
    else:
        flds, key = spec["table"]["fields"], spec["table"]["key"]
        data = []
        for t in (scope if scope is not None else Q.scope_tests(c)):
            kv = Q.primary(c, t, key)
            if not kv or (kv["value_num"] is None and not kv["value_text"]) or (spec["table"].get("positive") and not (kv["value_num"] or 0) > 0):
                continue                                              # a view table shows only tests that carry the view's key value
            r = {"test": c.execute("SELECT psi || ' ' || COALESCE(native_id,'') FROM test WHERE test_id=?", (t,)).fetchone()[0]}
            for f in flds:
                p = Q.primary(c, t, f)
                r[f] = (r3(p["value_num"]) if p["value_num"] is not None else p["value_text"]) if p else None
            o2 = (Q.primary(c, t, "O2_pct") or {}).get("value_num")
            data.append(((c.execute("SELECT psi FROM test WHERE test_id=?", (t,)).fetchone()[0], o2 is None, o2 or 0, t), r))
        data.sort(key=lambda x: x[0])
        rows_ = [r for _, r in data[: cf["limits"]["rows"]]]
        table = _tbl([("test", "test", "")] + [(f, f, Q.field_unit(c, f)) for f in flds], rows_)
        if not rows_:
            debug.append("no test rows for this view" + (f" near {sid}" if sid else ""))
    extra_d = {}
    if sid and cf["scenarios"][sid].get("closest_tested"):            # Round 5: the spacesuit answer on every view; the O2-vs-pressure chart shows the distance from the tested region
        sp_speak, sp_kpis, sp_gaps, ct, chart, ex = _spacesuit_answer(c, F, sid)
        speak, kpis, charts = sp_speak, sp_kpis + [k for k in kpis if k["id"] not in {x["id"] for x in sp_kpis}], [chart] + charts[:1]
        gaps_l = sp_gaps + [g for g in gaps_l if g not in sp_gaps]
        extra_d = {"closest_tested": ct, "level_oxygen_rich_flames": ex["level_oxygen_rich_flames"], "nearest": ex["nearest"]}
        cov = "None"
    elif view == "gaps":
        charts = [_o2p_chart(c)]
    gaps_l = list(dict.fromkeys(gaps_l))                              # exact duplicates out (Round 4 item 4.2)
    d = _dash(view, sid, cov, spec["headline"], speak, kpis[: cf["limits"]["kpis"]], charts, table, gaps_l, [sid] if sid else [], F)
    d["debug"] = debug                                                # developer messages: never shown or spoken
    d.update(extra_d)
    if nearest:
        d["nearest"] = nearest
    d["table_key"] = spec["table"].get("key")
    return d


VIEW_LABEL = {"ignition": "ignition", "materials": "material", "flame_spread": "flame spread", "smoke": "smoke", "suppression": "added-agent", "gaps": "gap"}


def _bare(label):
    """Scenario label without a leading 'the ' and a trailing ' atmosphere', so a sentence can add its own words once."""
    label = re.sub(r"^the\s+", "", label)
    return re.sub(r"\s+atmosphere$", "", label)


def _dash(view, sid, cov, headline, key_points, kpis, charts, table, gaps_l, refs, F=None):
    d = {"version": VERSION, "view": view, "scenario": sid, "coverage": cov, "headline": headline, "key_points": key_points, "kpis": kpis, "charts": charts, "table": table, "gaps": gaps_l,
            "speak": key_points[:4], "source": _src(refs), "facts": F.items if F else []}
    return _clean(d)


def get_dashboard(view, scenario=None, inputs=None):
    """Mock-compatible wrapper: get_dashboard(view, scenario, inputs) = show_view(view, scenario, inputs). Use show_view in new code."""
    return show_view(view, scenario, inputs)


def query_data(metric, filters=None):
    """Mock-compatible wrapper: query_data(metric, filters) -> Answer JSON. Metrics: ignition_time_by_material, material_ranking, spread_vs_oxygen, smoke_particle_size, extinguisher_amount.
    Each maps to an intent tool (see config/serving.yaml mock_metrics); extinguisher_amount is not supported by the data and says so."""
    c = con()
    mm = Q.cfg(c)["mock_metrics"]
    filters = filters or {}
    if metric not in mm:
        return _unknown("query_data", f"query_data({metric})", "metric", metric, list(mm))
    m = mm[metric]
    sc = filters.get("scenario")
    if m["tool"] == "show_view":
        d = show_view(m["view"], sc)
        d.update({"tool": "query_data", "question": metric})
        d["source"]["refs"] = d["source"]["refs"] + [metric]
        return d
    if m["tool"] == "rank_materials":
        d = rank_materials(m["metric"], sc)
    elif m["tool"] == "get_findings":
        d = get_findings(m["x"], m["y"], filters.get("fuel"))
    else:
        d = rank_agents(filters.get("fuel_class"))
        if m.get("unsupported"):
            d["speak"].insert(0, "Extinguisher amount is not supported by the PSI data.")
            d["gaps"].insert(0, "extinguisher_amount (agent mass or volume) is not in the data")
    d["tool"], d["question"] = "query_data", metric
    return d


END_MODE_SAY = {"no_spread": "the flame did not spread (burn length about 0)", "full_length": "the flame burned the full sample length", "pmma_consumed_nomex_not_ignited": "the PMMA part was consumed and the Nomex part did not ignite", "anchored_at_base": "the flame stayed anchored at the base of the sample", "not_recorded": "no outcome recorded", "SE": "flame self-extinguished", "FT": "ended when the flow was terminated", "FTO": "ended when the flow was terminated"}      # phrase_tables.yaml: SE = self-extinguished with the flow on, FT = flow terminated


# ---------------------------------------------------------------- nearest_tests (Round 11 §11.2): "where am I, and what does the evidence say?"
def nearest_tests(o2_pct, pressure_psi=None, pressure_kpa=None, material=None):
    """What do the PSI tests say near these conditions? ("What does the data say at 34 percent oxygen and 8.2 psi?", "Is 34 percent oxygen dangerous?" once conditions are named).
    Arguments: o2_pct = oxygen in percent; pressure_psi (or pressure_kpa) = total pressure; material = optional material or fuel word.
    Lists the ambient-atmosphere tests within the Stage 6 tolerances (3 oxygen points, 10 percent of the pressure), flight before ground, with the outcome counted and never rated;
    when none is that close it lists the nearest tested points and says so. Also returns the oxygen partial pressure (computed: oxygen fraction times pressure, formula shown),
    the scenario atmospheres and the sourced oxygen markers. It never says safe or dangerous."""
    c = con()
    cf = Q.cfg(c)
    nr = cf["groups"]["tol"]
    cap = cf["oxygen_effect"]["nearest"]
    o2 = float(o2_pct)
    p_kpa = float(pressure_kpa) if pressure_kpa is not None else (U.to_kpa(float(pressure_psi)) if pressure_psi is not None else None)
    q = f"nearest_tests({o2_pct}, {pressure_psi if pressure_psi is not None else pressure_kpa}, {material})"
    if p_kpa is None or not (0 <= o2 <= 100) or p_kpa <= 0:
        return _unknown("nearest_tests", q, "conditions", f"{o2_pct} % at {pressure_psi if pressure_psi is not None else pressure_kpa}", [])
    p_psi = round(p_kpa / U.KPA_PER_PSI, 1)
    F = Facts()
    mat = re.compile(re.escape(material), re.I) if material else None
    # every eligible ambient test with its primary values (one query), the outcome fields beside it
    rows = c.execute("SELECT t.test_id, t.psi, t.native_id, o.value_num o2, p.value_num p, ps.flight_ground fg FROM test t "
                     "JOIN value o ON o.test_id=t.test_id AND o.field='O2_pct' AND o.is_primary=1 JOIN value p ON p.test_id=t.test_id AND p.field='pressure_kPa' AND p.is_primary=1 "
                     "JOIN psi ps ON ps.psi=t.psi WHERE t.o2_role='ambient' AND " + Q.ELIGIBLE + " AND COALESCE(t.flags,'') NOT LIKE '%doc_internal_conflict%' AND o.value_num IS NOT NULL AND p.value_num IS NOT NULL").fetchall()
    F_FIELDS = ("material", "fuel", "flow_cm_s", "spread_rate_mm_s", "end_mode", "flames_ignited", "flame_type")

    def detail(r):
        vals = {f: Q.primary(c, r["test_id"], f) for f in F_FIELDS}
        return {"psi": r["psi"], "investigation": _nm(c, r["psi"]), "test": r["native_id"], "flight": r["fg"] == "flight",
                "material": (vals["material"] or {}).get("value_text"), "fuel": (vals["fuel"] or {}).get("value_text"), "o2_pct": r["o2"], "p_kpa": r["p"],
                "flow_cm_s": (vals["flow_cm_s"] or {}).get("value_num"), "spread_rate_mm_s": (vals["spread_rate_mm_s"] or {}).get("value_num"),
                "end_mode": (vals["end_mode"] or {}).get("value_text"), "flames_ignited": (vals["flames_ignited"] or {}).get("value_num"), "flame_type": (vals["flame_type"] or {}).get("value_text")}
    allrows = [detail(r) for r in rows] if mat is None else [d for d in (detail(r) for r in rows) if mat.search(f"{d['material'] or ''} {d['fuel'] or ''}")]
    near = [d for d in allrows if abs(d["o2_pct"] - o2) <= nr["o2_pts"] and abs(d["p_kpa"] - p_kpa) <= nr["p_rel"] * p_kpa]
    near.sort(key=lambda d: (not d["flight"], d["psi"], str(d["test"])))
    n_psis = len({d["psi"] for d in near})
    spread = [d for d in near if (d["spread_rate_mm_s"] or 0) > 0]
    # the nearest tested points when nothing is within tolerance: their own values, ordered by closeness in tolerance units (the distance itself is not shown)
    nearest_pts = []
    if not near:
        seen = set()
        for d in sorted(allrows, key=lambda d: (abs(d["o2_pct"] - o2) / nr["o2_pts"] + abs(d["p_kpa"] - p_kpa) / (nr["p_rel"] * p_kpa), d["psi"], str(d["test"]))):
            k = (d["psi"], round(d["o2_pct"], 1), round(d["p_kpa"], 1))
            if k in seen:
                continue
            seen.add(k)
            nearest_pts.append(d)
            if len(nearest_pts) >= cap["nearest_n"]:
                break
    # tested ranges (all eligible ambient tests / the ones with a spread rate): the panel says "no spread-rate tests at 34 %; the tested range is ..."
    o2s = [d["o2_pct"] for d in allrows]
    sp_all = [d["o2_pct"] for d in allrows if (d["spread_rate_mm_s"] or 0) > 0]
    ranges = {"o2_min": min(o2s) if o2s else None, "o2_max": max(o2s) if o2s else None, "spread_o2_min": min(sp_all) if sp_all else None, "spread_o2_max": max(sp_all) if sp_all else None,
              "n_spread_tests": len(sp_all)}
    # oxygen partial pressure: COMPUTED here (never by the adapter or the screen), with its formula
    po2 = {"value_psi": round(o2 / 100 * p_psi, 1), "formula": f"computed: {F.n(o2)} % × {F.n(p_psi)} psi", "computed": True}
    scen = []
    for sid, s in cf["scenarios"].items():
        if s.get("p_psi") and s.get("o2") and not s.get("no_data"):
            scen.append({"id": sid, "label": s["label"], "o2_pct": s["o2"], "p_psi": s["p_psi"], "p_kpa": s["p_kpa"], "region": bool(s.get("region")),
                         "po2_psi": round(s["o2"] / 100 * s["p_psi"], 1), "formula": f"computed: {s['o2']:g} % × {s['p_psi']:g} psi"})
    markers = []
    for mk in cf["oxygen_effect"]["ladder_markers"]:
        if mk.get("finding"):
            r_ = c.execute("SELECT finding_id src, page, paper_id FROM finding WHERE finding_id=?", (mk["finding"],)).fetchone()
            ref = mk["finding"]
        else:
            r_ = c.execute("SELECT ref_id src, page, src_id paper_id FROM reference WHERE ref_id=?", (mk["ref"],)).fetchone()
            ref = mk["ref"]
        if r_:
            markers.append({"o2_pct": mk["o2"], "label": mk["label"], "page": r_["page"], "ref": ref, "source_title": _paper_title(c, r_["paper_id"])})
    # speak: counts only, outcomes never rated
    mtxt = f" with {material}" if material else ""
    speak = []
    if near:
        speak.append(f"Near {F.n(o2)} percent oxygen and {F.n(p_psi)} psi there are {_pl(F.i(len(near)), 'test')}{mtxt} in {_pl(F.i(n_psis), 'investigation')}; " + (f"in {F.i(len(spread))} of them the flame spread." if spread else "none of them recorded a spread rate."))
        fl = [d for d in near if d["flight"]]
        speak.append(f"{F.i(len(fl))} of these tests are flight tests; the rest are ground tests." if fl and len(fl) < len(near) else ("All of these are flight tests." if fl else "All of these are ground tests."))
    else:
        speak.append(f"No PSI test{mtxt} at {F.n(o2)} percent oxygen and {F.n(p_psi)} psi.")
        if nearest_pts:
            speak.append("The nearest tests are " + _list(f"{d['investigation']} at {F.n(d['o2_pct'])} percent oxygen and {F.p(d['p_kpa'])}" for d in nearest_pts[:3]) + ".")
    gaps_l = [] if near else [f"No PSI test at these conditions; the nearest tests are " + _list(f"{d['investigation']} ({F.n(d['o2_pct'])} % at {F.p(d['p_kpa'])})" for d in nearest_pts[:3])] if nearest_pts else ["No PSI test at these conditions"]
    if near and not spread:
        gaps_l.append("none of the nearby tests recorded a spread rate")
    if sp_all and not (ranges["spread_o2_min"] - 0 <= o2 <= ranges["spread_o2_max"]):
        gaps_l.append(f"No spread-rate tests at {F.n(o2)} % oxygen; the tested range is {Q.fmt(ranges['spread_o2_min'])} to {Q.fmt(ranges['spread_o2_max'])} %")
    kp = [_kpi("near_tests", "tests near your conditions", len(near), f"within {nr['o2_pts']:g} oxygen points and {nr['p_rel'] * 100:g} percent of the pressure", "table"),
          _kpi("near_psis", "investigations", n_psis, f"{n_psis} investigations", "table"),
          _kpi("po2", "oxygen partial pressure", po2["value_psi"], po2["formula"], "computed", "psi")]
    tbl_rows = [{"investigation": d["investigation"], "test": d["test"], "material": d["material"] or d["fuel"], "o2_pct": r3(d["o2_pct"]), "p_kpa": d["p_kpa"], "flow_cm_s": r3(d["flow_cm_s"]),
                 "outcome": ("spread rate " + Q.fmt(d["spread_rate_mm_s"]) + " mm/s") if (d["spread_rate_mm_s"] or 0) > 0 else (END_MODE_SAY.get(str(d["end_mode"]).strip(), d["end_mode"]) if d["end_mode"] not in (None, "-", "") else (d["flame_type"] or ("ignited" if (d["flames_ignited"] or 0) > 0 else "no flame spread recorded"))),
                 "flight": "flight" if d["flight"] else "ground"} for d in (near or nearest_pts)[:cap["max_rows"]]]
    tbl = _tbl([("investigation", "investigation", ""), ("test", "test", ""), ("material", "material / fuel", ""), ("o2_pct", "oxygen", "%"), ("p_kpa", "pressure", "kPa"), ("flow_cm_s", "flow", "cm/s"), ("outcome", "outcome", ""), ("flight", "flight / ground", "")], tbl_rows) if tbl_rows else None
    # points for the two live charts: every eligible ambient test (psi / oxygen, whether it is within tolerance) and every test with a spread rate (oxygen, rate)
    near_ids = {(d["psi"], str(d["test"])) for d in near}
    near_points = sorted({(U.to_psi(d["p_kpa"]), d["o2_pct"]) for d in near})          # only the tests within tolerance; the base map of all tests is the o2_vs_pressure chart
    near_points = [{"x": x, "y": y} for x, y in near_points]
    spread_points = [{"x": d["o2_pct"], "y": d["spread_rate_mm_s"], "near": (d["psi"], str(d["test"])) in near_ids, "investigation": d["investigation"]} for d in allrows if (d["spread_rate_mm_s"] or 0) > 0]
    d = _ans("nearest_tests", q, speak, F, kp, [], tbl, gaps_l, refs=[d["test"] for d in (near or nearest_pts)[:6] if d.get("test")], conditions={"o2_pct": o2, "pressure_psi": p_psi, "pressure_kpa": round(p_kpa, 1), "material": material},
             n_near=len(near), n_psis=n_psis, n_spread=len(spread), n_flight=len([d for d in near if d["flight"]]), nearest_points=[{k: v for k, v in x.items() if k in ("investigation", "o2_pct", "p_kpa", "test")} for x in nearest_pts],
             po2=po2, ranges=ranges, scenarios=scen, markers=markers, map_points=near_points, spread_points=spread_points)
    return d


# ---------------------------------------------------------------- Round 13 §13.2 catalogue tools (the "what is in the data" branches of the Round 14 router)
FAMILY_RX = {"fabric": r"sibal|cotton|fiberglass|nomex|aramid|fabric|cloth|textile|nylon|polyester|cellulose|\bpaper\b",
             "plastic": r"pmma|acrylic|plexi|delrin|polymethyl|polyethylene|\brod\b|\bslab\b|sphere|\bfilm\b",
             "silicone": r"silicon",
             "teflon_kapton": r"teflon|ptfe|kapton|polyimide",
             "wax": r"wax|candle|paraffin",
             "wick": r"wick",
             "dust": r"dust|aerosol"}
FAMILY_SAY = {"fabric": "fabrics", "plastic": "plastics (PMMA and similar)", "silicone": "silicone", "teflon_kapton": "Teflon and Kapton", "wax": "wax", "wick": "lampwick", "dust": "dust aerosols", "other": "other materials"}
FAMILY_WORDS = {"fabric": ("fabric", "fabrics", "cloth", "textile", "textiles", "clothing"), "plastic": ("plastic", "plastics")}


def _family_of(label):
    for f, rx in FAMILY_RX.items():
        if re.search(rx, label or "", re.I):
            return f
    return "other"


def _scope_text(c, scenario):
    if not scenario:
        return ""
    return " near the " + _bare(c.execute("SELECT label FROM scenario WHERE scenario=?", (scenario,)).fetchone()[0]) + " atmosphere"


def _material_rows(c, scenario=None, psi=None):
    """Eligible tests with a material label: (test_id, psi, native_id, material, flight_ground)."""
    q = ("SELECT t.test_id, t.psi, t.native_id, v.value_text material, ps.flight_ground fg FROM test t JOIN value v ON v.test_id=t.test_id AND v.field='material' AND v.is_primary=1 "
         "JOIN psi ps ON ps.psi=t.psi WHERE " + Q.ELIGIBLE + " AND v.value_text IS NOT NULL AND v.value_text NOT IN ('-','')")
    a = []
    if psi:
        q += " AND t.psi=?"
        a.append(psi)
    if scenario:
        q += " AND t.test_id IN (SELECT test_id FROM scenario_coverage WHERE scenario=? AND match_kind='near')"
        a.append(scenario)
    return c.execute(q, a).fetchall()


def _where_found(c, rows, F, limit=4):
    """"SAFFIRE-II (flight) and SAME (flight)": the investigations of these rows, flight first, most tests first."""
    cnt = defaultdict(int)
    fg = {}
    for r in rows:
        cnt[r["psi"]] += 1
        fg[r["psi"]] = r["fg"]
    order = sorted(cnt, key=lambda p: (fg[p] != "flight", -cnt[p], p))[:limit]
    return _list(F.t(_nm(c, p)) for p in order), order


def list_materials(scenario=None, psi=None, family=None):
    """What materials are in the data? ("what materials do you cover?", "which materials did Saffire-II burn?", "which fabrics are tested near the ISS?").
    Arguments: scenario = optional scenario id; psi = optional investigation; family = optional fabric, plastic, silicone, teflon_kapton, wax or wick.
    Gives the number of material labels and tests with the scope said (all data, one investigation or near a scenario), and for each family the main materials and the investigations that burned them, flight first."""
    c = con()
    sid = Q.resolve_scenario(c, scenario) if scenario else None
    pid = Q.resolve_psi(c, psi) if psi else None
    if (scenario and not sid) or (psi and not pid):
        return _unknown("list_materials", f"list_materials({scenario}, {psi}, {family})", "scenario" if scenario and not sid else "PSI", scenario if scenario and not sid else psi)
    F = Facts()
    rows = _material_rows(c, sid, pid)
    if family:
        rows = [r for r in rows if _family_of(r["material"]) == family]
    scope = _scope_text(c, sid) if sid else (f" in {_nm(c, pid)}" if pid else " in all the data")
    labels = {r["material"] for r in rows}
    by = defaultdict(list)
    for r in rows:
        by[_family_of(r["material"])].append(r)
    speak, tbl = [], []
    for f in [k for k in FAMILY_RX if k in by] + (["other"] if "other" in by else []):
        rs = by[f]
        names = [m for m, _ in sorted(defaultdict(int, {m: sum(1 for r in rs if r["material"] == m) for m in {r["material"] for r in rs}}).items(), key=lambda kv: (-kv[1], kv[0]))]
        where, _o = _where_found(c, rs, F)
        tbl.append({"family": FAMILY_SAY[f], "materials": ", ".join(names[:4]) + (f" and {len(names) - 4} more" if len(names) > 4 else ""), "tests": len(rs), "investigations": where})
    if not rows:
        speak.append(f"No {FAMILY_SAY.get(family, 'material')} test{scope}." if family else f"No material is recorded in the tests{scope}.")
        if family and (sid or pid):
            allr = [r for r in _material_rows(c) if _family_of(r["material"]) == family]
            if allr:
                where, _o = _where_found(c, allr, F)
                speak.append(f"{FAMILY_SAY[family][0].upper() + FAMILY_SAY[family][1:]} appear in {where}.")
    else:
        speak.append(f"{_pl(F.i(len(labels)), 'material label')} in {_pl(F.i(len(rows)), 'test')}{scope}.")
        for t in sorted(tbl, key=lambda t: -t["tests"])[:2]:
            speak.append(f"{t['family'][0].upper() + t['family'][1:]}: {', '.join(t['materials'].split(', ')[:2])} and others, in {t['investigations']}.")
    kp = [_kpi("materials", "material labels", len(labels), f"{len(labels)} labels in {len(rows)} tests{scope}", "table"), _kpi("tests", "tests with a material", len(rows), f"scope:{scope}", "table")]
    d = _ans("list_materials", f"list_materials({scenario}, {psi}, {family})", speak, F, kp, [], _tbl([("family", "family", ""), ("materials", "materials", ""), ("tests", "tests", ""), ("investigations", "investigations", "")], tbl) if tbl else None,
             [] if rows else [f"no {family or 'material'} test{scope}"], refs=[r["psi"] for r in rows][:6], scope={"scenario": sid, "psi": pid, "family": family})
    d["materials_by_family"] = {FAMILY_SAY[k]: sorted({r["material"] for r in v}) for k, v in by.items()}
    d["psis_by_family"] = {k: sorted({r["psi"] for r in v}) for k, v in by.items()}
    return d


OUTCOMES = {          # outcome word -> the stored end_mode values / 1-g outcome it means (Round 16, SF-6 / SF-7)
    "did_not_burn": {"end_mode": ["no_spread", "pmma_consumed_nomex_not_ignited"]},
    "no_spread": {"end_mode": ["no_spread"]},
    "not_ignited": {"end_mode": ["pmma_consumed_nomex_not_ignited"]},
    "burned_completely": {"burn_1g": ["complete"]},
    "anchored": {"end_mode": ["anchored_at_base"]},
    "full_length": {"end_mode": ["full_length"]},
}


def _outcome_tests(c, outcome, pid=None):
    """The tests whose stored outcome matches (end_mode values or the 1-g outcome), with their material, flight first."""
    rule = OUTCOMES[outcome]
    q = ("SELECT t.test_id, t.native_id, t.psi, p.flight_ground fg, m.value_text mat, e.value_text em, b.value_text b1g, e.quote eq FROM test t JOIN psi p ON p.psi=t.psi "
         "LEFT JOIN value m ON m.test_id=t.test_id AND m.field='material' AND m.is_primary=1 LEFT JOIN value e ON e.test_id=t.test_id AND e.field='end_mode' AND e.is_primary=1 "
         "LEFT JOIN value b ON b.test_id=t.test_id AND b.field='burn_1g_outcome' AND b.is_primary=1 WHERE t.is_doc_test=0 AND t.counted=1" + (" AND t.psi=?" if pid else "") + " ORDER BY (p.flight_ground='flight') DESC, t.psi, t.native_id")
    out = []
    for r in c.execute(q, (pid,) if pid else ()):
        if "end_mode" in rule and r["em"] in rule["end_mode"] or "burn_1g" in rule and str(r["b1g"]).strip().lower() in rule["burn_1g"]:
            out.append(r)
    return out


def _outcome_answer(c, outcome, pid, q):
    F = Facts()
    rows = _outcome_tests(c, outcome, pid)
    ow = (Q.cfg(c).get("narrative") or {}).get("outcome_words") or {}
    speak, tbl_rows, gaps_l = [], [], []
    scope = f" in {_nm(c, pid)}" if pid else ""
    if rows:
        by_psi = {}
        for r in rows:
            by_psi.setdefault(r["psi"], []).append(r)
        for psi_, rs in by_psi.items():
            parts = []
            em_based = "end_mode" in OUTCOMES[outcome] and outcome in ("did_not_burn", "no_spread", "not_ignited")
            ns = [r for r in rs if r["em"] == "no_spread"] if em_based else []
            nn = [r for r in rs if r["em"] == "pmma_consumed_nomex_not_ignited"] if em_based else []
            ot = [] if em_based else rs
            if ns:
                mm = {}
                for r in ns:
                    mm[r["mat"]] = mm.get(r["mat"], 0) + 1
                parts.append(_list(f"{F.i(n)} {F.t(m)}" for m, n in mm.items()) + f" {'samples' if len(ns) > 1 else 'sample'} " + ow.get("no_spread", "did not spread"))
            if nn:
                parts.append(f"the Nomex part of {_pl(F.i(len(nn)), 'sample')} did not ignite (the PMMA part was consumed)")
            if ot:
                what = {"burned_completely": "burned completely in the 1-g test", "anchored": "had the flame anchored at the sample base", "full_length": "burned the full sample length"}.get(outcome, "matched")
                mm = {}
                for r in ot:
                    mm[r["mat"]] = mm.get(r["mat"], 0) + 1
                parts.append(_list(f"{F.i(n)} {F.t(m)}" for m, n in mm.items()) + f" {'samples' if len(ot) > 1 else 'sample'} {what}")
            speak.append(f"In {_nm(c, psi_)}: " + "; ".join(parts) + ".")
        speak.append("This is read from the experiment table's burn length, burn time and 1-g cells and its notes.")
        for r in rows:
            tbl_rows.append({"investigation": _nm(c, r["psi"]), "test": r["native_id"], "material": r["mat"], "outcome": END_MODE_SAY.get(str(r["em"]), r["em"]), "normal gravity": r["b1g"], "flight": "flight" if r["fg"] == "flight" else "ground"})
    else:
        speak.append(f"No test{scope} has that outcome recorded in the data.")
        gaps_l.append(f"no test{scope} with that outcome")
    kp = [_kpi("n_tests", "tests found", len(rows), f"{len(rows)} tests with this outcome{scope}", "table")]
    tbl = _tbl([("investigation", "investigation", ""), ("test", "test", ""), ("material", "material", ""), ("outcome", "outcome", ""), ("normal gravity", "1-g outcome", ""), ("flight", "flight / ground", "")], tbl_rows[:25])
    return _ans("find_tests", q, speak, F, kp, [], tbl, gaps_l, refs=sorted({r["psi"] for r in rows}), n_found=len(rows), n_anywhere=len(rows), found_in=sorted({r["psi"] for r in rows}), appears_in=sorted({r["psi"] for r in rows}),
                scope={"psi": pid, "outcome": outcome})


def find_tests(material=None, psi=None, scenario=None, family=None, outcome=None):
    """Which tests burned this material? ("tests with fabric", "the tests under Teflon", "silicone tests near the Moon base").
    Arguments: material = a material word (PMMA, SIBAL, Teflon, silicone ...) or family = fabric, plastic, silicone, teflon_kapton, wax; psi / scenario narrow the search;
    outcome = did_not_burn | no_spread | not_ignited | burned_completely | anchored | full_length ("which materials did not burn / did not ignite / burned completely in Saffire-II").
    Lists the matching tests (flight first). When there are none it says where the material does appear, so 'no test here' is never 'not covered'."""
    c = con()
    sid = Q.resolve_scenario(c, scenario) if scenario else None
    pid = Q.resolve_psi(c, psi) if psi else None
    if outcome:
        if outcome not in OUTCOMES:
            return _unknown("find_tests", f"find_tests(outcome={outcome})", "outcome", outcome, options=sorted(OUTCOMES))
        return _outcome_answer(c, outcome, pid, f"find_tests({psi}, outcome={outcome})")
    if (scenario and not sid) or (psi and not pid):
        return _unknown("find_tests", f"find_tests({material}, {psi}, {scenario}, {family})", "scenario" if scenario and not sid else "PSI", scenario if scenario and not sid else psi)
    if family is None and material:
        for f, ws in FAMILY_WORDS.items():
            if material.lower() in ws:
                family = f
        if family:
            material = None
    mrx = re.compile(re.escape(material), re.I) if material else None
    what = material or FAMILY_SAY.get(family, "materials")

    def hit(r):
        return (mrx.search(r["material"]) if mrx else (family is None or _family_of(r["material"]) == family))
    F = Facts()
    rows = [r for r in _material_rows(c, sid, pid) if hit(r)]
    anywhere = [r for r in _material_rows(c) if hit(r)]
    scope = _scope_text(c, sid) if sid else (f" in {_nm(c, pid)}" if pid else "")
    speak, gaps_l, tbl_rows = [], [], []
    if rows:
        where, order = _where_found(c, rows, F)
        n_fl = len([r for r in rows if r["fg"] == "flight"])
        speak.append(f"{_pl(F.i(len(rows)), 'test')} with {F.t(what)}{scope}" + ("" if pid else f", in {where}") + ".")
        speak.append(f"{F.i(n_fl)} of them are flight tests." if 0 < n_fl < len(rows) else ("All of them are flight tests." if n_fl else "All of them are ground tests."))
        for r in sorted(rows, key=lambda r: (r["fg"] != "flight", r["psi"], str(r["native_id"])))[:25]:
            v = {f: Q.primary(c, r["test_id"], f) for f in ("O2_pct", "pressure_kPa", "flow_cm_s", "spread_rate_mm_s", "end_mode")}
            sr = (v["spread_rate_mm_s"] or {}).get("value_num")
            em = (v["end_mode"] or {}).get("value_text")
            tbl_rows.append({"investigation": _nm(c, r["psi"]), "test": r["native_id"], "material": r["material"], "o2_pct": r3((v["O2_pct"] or {}).get("value_num")), "p_kpa": (v["pressure_kPa"] or {}).get("value_num"),
                             "flow_cm_s": r3((v["flow_cm_s"] or {}).get("value_num")), "outcome": f"spread rate {Q.fmt(sr)} mm/s" if sr else (END_MODE_SAY.get(str(em).strip(), em) if em not in (None, "-", "") else "recorded"),
                             "flight": "flight" if r["fg"] == "flight" else "ground"})
    else:
        if anywhere:
            where, order = _where_found(c, anywhere, F)
            speak.append(f"No {F.t(what)} test{scope or ' with these filters'}; {F.t(what)} {'appear' if what.endswith('s') else 'appears'} in {where}.")
            gaps_l.append(f"no {what} test{scope or ' with these filters'}")
        else:
            speak.append(f"No test in the data has {F.t(what)} as its material.")
            gaps_l.append(f"no {what} in the data")
    kp = [_kpi("n_tests", "tests found", len(rows), f"{len(rows)} tests with {what}{scope}", "table")]
    tbl = _tbl([("investigation", "investigation", ""), ("test", "test", ""), ("material", "material", ""), ("o2_pct", "oxygen", "%"), ("p_kpa", "pressure", "kPa"), ("flow_cm_s", "flow", "cm/s"), ("outcome", "outcome", ""), ("flight", "flight / ground", "")], tbl_rows) if tbl_rows else None
    d = _ans("find_tests", f"find_tests({material}, {psi}, {scenario}, {family})", speak, F, kp, [], tbl, gaps_l, refs=[r["psi"] for r in (rows or anywhere)][:6], n_found=len(rows), n_anywhere=len(anywhere),
             found_in=sorted({r["psi"] for r in rows}), appears_in=sorted({r["psi"] for r in anywhere}), scope={"scenario": sid, "psi": pid, "material": material, "family": family})
    return d


def data_ranges(field, psi=None, scenario=None, above=None, below=None):
    """What range does the data cover? ("what is the maximum oxygen in the data?", "is there any test above 25 percent oxygen?", "what pressures were tested?").
    Arguments: field = oxygen, pressure, flow speed, spread rate ... ; psi / scenario narrow it; above / below = a threshold to count tests beyond.
    Oxygen is given for the ambient atmosphere and the burner stream separately; pressure in psi. It states min, max and count, never how safe a value is."""
    c = con()
    f = Q.resolve_field(c, field) if field else None
    q = f"data_ranges({field}, {psi}, {scenario}, {above}, {below})"
    if not f:
        return _unknown("data_ranges", q, "field", field, ["oxygen", "pressure", "flow speed", "spread rate"])
    sid = Q.resolve_scenario(c, scenario) if scenario else None
    pid = Q.resolve_psi(c, psi) if psi else None
    F = Facts()
    sql = ("SELECT t.test_id, t.psi, t.o2_role, v.value_num x, ps.flight_ground fg FROM test t JOIN value v ON v.test_id=t.test_id AND v.field=? AND v.is_primary=1 JOIN psi ps ON ps.psi=t.psi WHERE " + Q.ELIGIBLE +
           " AND v.value_num IS NOT NULL AND COALESCE(t.flags,'') NOT LIKE '%doc_internal_conflict%'")
    a = [f]
    if pid:
        sql += " AND t.psi=?"
        a.append(pid)
    if sid:
        sql += " AND t.test_id IN (SELECT test_id FROM scenario_coverage WHERE scenario=? AND match_kind='near')"
        a.append(sid)
    rows = c.execute(sql, a).fetchall()
    unit = Q.field_unit(c, f)
    say = _lab(c, f)["say"] if f in Q.cfg(c).get("labels", {}) else _flabel(c, f).split(" (")[0]
    scope = _scope_text(c, sid) if sid else (f" in {_nm(c, pid)}" if pid else "")
    isp = f == "pressure_kPa"

    def show(v):
        return F.p(v) if isp else f"{F.n(v)} {'percent' if unit == '%' else unit}".strip()
    groups = [("ambient " + say, [r for r in rows if r["o2_role"] != "oxidizer_stream"]), ("burner-stream " + say + " (not the atmosphere)", [r for r in rows if r["o2_role"] == "oxidizer_stream"])] if f == "O2_pct" else [(say, rows)]
    speak, trows, ranges = [], [], []
    thr_lines = []
    for lab, rs in groups:
        if not rs:
            continue
        lo, hi = min(rs, key=lambda r: r["x"]), max(rs, key=lambda r: r["x"])
        ranges.append({"label": lab, "min": lo["x"], "max": hi["x"], "n": len(rs), "min_psi": lo["psi"], "max_psi": hi["psi"]})
        same = lo["x"] == hi["x"] or (isp and round(U.to_psi(lo["x"]), 1) == round(U.to_psi(hi["x"]), 1))      # 14.88 and 14.90 psi are both "14.9 psi": no "14.9 to 14.9"
        rng = show(lo["x"]) if same else (f"{F.p(lo['x'])} to {F.p(hi['x'])}".replace(" psi to", " to", 1) if isp else f"{F.n(lo['x'])} to {show(hi['x'])}")
        speak.append(f"{lab[0].upper() + lab[1:]}{scope}: {rng} in {_pl(F.i(len(rs)), 'test')}" + ("" if same else f"; the highest is in {F.t(_nm(c, hi['psi']))}") + ".")
        trows.append({"what": lab, "min": lo["x"], "max": hi["x"], "tests": len(rs), "highest_in": _nm(c, hi["psi"])})
        for word, thr, keep in (("above", above, lambda x, t: x > t), ("below", below, lambda x, t: x < t)):
            if thr is not None:
                tv = float(thr) * U.KPA_PER_PSI if isp else float(thr)           # a pressure threshold is given in psi
                hits = [r for r in rs if keep(r["x"], tv)]
                tt = f"{F.n(float(thr))} psi" if isp else f"{F.n(float(thr))}{' percent' if unit == '%' else ' ' + unit}"
                thr_lines.append(f"{_pl(F.i(len(hits)), 'test')} {word} {tt} for {lab}" + (f", in {_pl(F.i(len({r['psi'] for r in hits})), 'investigation')}" if hits else "") + ".")
    gaps_l = []
    if not rows:
        speak.append(f"No test{scope} records {say}.")
        gaps_l.append(f"{say} is not recorded{scope}")
    speak += thr_lines[:2]
    kp = [_kpi("n", f"tests with {say}", len(rows), f"{len(rows)} tests{scope}", "table")] + [_kpi("range", r["label"], f"{Q.fmt(r['min'])} to {Q.fmt(r['max'])}", f"{r['n']} tests", "table", "kPa" if isp else unit) for r in ranges[:2]]
    tbl = _tbl([("what", "quantity", ""), ("min", "lowest", "kPa" if isp else unit), ("max", "highest", "kPa" if isp else unit), ("tests", "tests", ""), ("highest_in", "highest in", "")], trows) if trows else None
    return _ans("data_ranges", q, speak, F, kp, [], tbl, gaps_l, refs=sorted({r["psi"] for r in rows})[:6], ranges=ranges, field=f, scope={"scenario": sid, "psi": pid})


def facets(field=None, material=None, family=None, scenario=None):
    """Where does the data have something about these words? (the router's probe: counts per investigation, flight first). Not spoken as an answer.
    Arguments: field = oxygen / pressure / flow speed / spread rate / thickness ...; material or family; scenario = optional scenario id."""
    c = con()
    sid = Q.resolve_scenario(c, scenario) if scenario else None
    f = Q.resolve_field(c, field) if field else None
    cnt = defaultdict(int)
    if material or family:
        mrx = re.compile(re.escape(material), re.I) if material else None
        for r in _material_rows(c, sid):
            if (mrx.search(r["material"]) if mrx else _family_of(r["material"]) == family):
                cnt[r["psi"]] += 1
    elif f:
        q = ("SELECT t.psi, COUNT(*) n FROM test t JOIN value v ON v.test_id=t.test_id AND v.field=? AND v.is_primary=1 WHERE " + Q.ELIGIBLE + " AND v.value_num IS NOT NULL")
        a = [f]
        if sid:
            q += " AND t.test_id IN (SELECT test_id FROM scenario_coverage WHERE scenario=? AND match_kind='near')"
            a.append(sid)
        for r in c.execute(q + " GROUP BY t.psi", a):
            cnt[r["psi"]] = r["n"]
    fg = {r["psi"]: r["flight_ground"] for r in c.execute("SELECT psi, flight_ground FROM psi")}
    rows = [{"psi": p, "investigation": _nm(c, p), "n": n, "flight": fg.get(p) == "flight"} for p, n in cnt.items()]
    rows.sort(key=lambda r: (not r["flight"], -r["n"], r["psi"]))
    return {"tool": "facets", "rows": rows, "speak": [], "gaps": [], "kpis": [], "charts": [], "table": None, "facts": [], "sources": [], "source": {"refs": []}}
