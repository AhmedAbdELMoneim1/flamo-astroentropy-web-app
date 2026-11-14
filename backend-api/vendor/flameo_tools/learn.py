"""Round 15 P1: the learning and test-level tools (explain, interpret_conditions, get_test, compare_tests, list_papers).

Same rules as tools.py: stdlib only, every number is read from serving.db (or computed here, with its formula, and counted in `facts`), speak[] holds spoken sentences only,
nothing is rated safe or dangerous and nothing is ranked beyond what the data says. The glossary (`glossary.json`) is a DRAFT until the team reviews it: every entry carries its status.
"""
import json
import os
import re

from . import queries as Q
from . import units as U
from . import tools as T
from .tools import Facts, _ans, _fuel, _kpi, _list, _nm, _pl, _tbl, _unknown, r3

GLOSSARY_PATH = os.path.join(os.path.dirname(__file__), "glossary.json")
_GLOSS = {}


def glossary():
    """term -> entry (loaded once). Aliases map to the same entry."""
    if not _GLOSS:
        try:
            with open(GLOSSARY_PATH, encoding="utf-8") as f:
                data = json.load(f)
        except OSError:
            data = {"entries": []}
        _GLOSS["entries"] = data.get("entries", [])
        _GLOSS["index"] = {}
        for e in _GLOSS["entries"]:
            for k in [e["term"], *e.get("aliases", [])]:
                _GLOSS["index"][_key(k)] = e
    return _GLOSS


def _key(s):
    return re.sub(r"[^a-z0-9]+", " ", str(s).lower().replace("₂", "2")).strip()


def find_term(text):
    """The glossary entry a question is about (exact term or alias, then the longest alias found inside the text), or None."""
    g = glossary()
    k = _key(text)
    if k in g["index"]:
        return g["index"][k]
    best = None
    for alias, e in g["index"].items():
        if re.search(r"(?<![a-z0-9])" + re.escape(alias) + r"(?![a-z0-9])", k) and (best is None or len(alias) > len(best[0])):
            best = (alias, e)
    return best[1] if best else None


# ---------------------------------------------------------------- explain
def explain(term):
    """What is this concept / what does this word mean? ("What is ignition?", "What is a cool flame?", "What does spread rate mean?", "Explain opposed flow").
    Argument: term = the word or phrase to explain (any wording; the glossary matches its aliases).
    Returns the plain definition, why it matters for fire safety in space, one example from the findings of the papers (with its source), and the glossary source.
    The glossary is a draft until the team has reviewed it (status in the answer). It gives no number of its own; it is not a rating of safety."""
    c = T.con()
    q = f"explain({term})"
    e = find_term(term)
    if not e:
        return _ans("explain", q, [f"The glossary has no entry for '{term}'."], gaps=[f"no glossary entry for {term}"], found=False, glossary={"term": term, "status": "no entry"})
    F = Facts()
    speak = [F.t(e["definition"])]
    if e.get("why_in_space"):
        speak.append(F.t(e["why_in_space"]))
    refs, example = [], None
    pat = e.get("finding_regex") or re.escape(e["term"])
    try:
        cards = Q.cards(c, terms=pat, limit=40)
    except Exception:
        cards = []
    cards = [x for x in cards if 40 <= len(x["statement"]) <= 260 and not re.search(r"\b(safe|safer|safest|unsafe)\b", x["statement"], re.I)]
    cards.sort(key=lambda x: (x["wording"] is None, len(x["statement"])))
    if cards:
        k = cards[0]
        example = {"finding": k["finding_id"], "statement": k["statement"], "wording": k["wording"], "psis": k["psis"], "page": k["page"]}
        speak.append(f"For example, {k['wording'] or 'the authors report'}: {F.t(k['statement'].rstrip('.'))}.")
        refs.append(k["finding_id"])
    src = e.get("source") or {}
    if src.get("src_id"):
        refs.append(src["src_id"])
    kp = [_kpi("glossary", "glossary status", e.get("status", "draft, to review"), "the definition is a draft until the team reviews it", "draft")]
    return _ans("explain", q, speak, F, kp, [], None, [], refs=refs, found=True, example=example,
                glossary={"term": e["term"], "aliases": e.get("aliases", []), "status": e.get("status", "draft, to review"), "source": src, "diagram": e.get("diagram"), "related": e.get("related", [])},
                meaning=e.get("why_in_space"))


# ---------------------------------------------------------------- interpret_conditions
def _o2_word(o2, ref, tol):
    return "about the same as" if abs(o2 - ref) <= tol else ("more than" if o2 > ref else "less than")


def interpret_conditions(o2_pct, pressure_psi=None, pressure_kpa=None, material=None):
    """What does this oxygen level / these conditions mean? ("What does 18 percent oxygen mean?", "Is 39.8 percent at 14.8 psi dangerous?", "What is 34 percent oxygen like?").
    Arguments: o2_pct = oxygen in percent; pressure_psi (or pressure_kpa) = total pressure (the ISS cabin's 14.7 psi when none is given); material = optional.
    Puts the value in context: against the ISS cabin, the Moon base and the spacesuit atmosphere, against the tested range, with the oxygen partial pressure (computed, formula shown),
    the tests near it and what they recorded, the closest evidence from the papers, and an honest coverage note. It never rates the conditions safe or dangerous."""
    c = T.con()
    cf = Q.cfg(c)
    tol = cf["groups"]["tol"]
    if pressure_psi is None and pressure_kpa is None:
        pressure_psi = next((s["p_psi"] for s in cf["scenarios"].values() if s.get("p_psi") and s["label"].startswith("ISS")), 14.7)
        assumed_p = True
    else:
        assumed_p = False
    n = T.nearest_tests(o2_pct, pressure_psi=pressure_psi, pressure_kpa=pressure_kpa, material=material)
    if not n.get("conditions"):
        return {**n, "tool": "interpret_conditions"}
    cond, F = n["conditions"], Facts()
    F.items = list(n.get("facts", []))
    o2, p = cond["o2_pct"], cond["pressure_psi"]
    scen = {s["id"]: s for s in n.get("scenarios", [])}
    iss, moon, suit = scen.get("iss"), scen.get("moon_base"), scen.get("spacesuit")
    # 1. where the value sits
    where = [f"{F.n(o2)} percent oxygen is {_o2_word(o2, iss['o2_pct'], tol['o2_pts'])} the {F.n(iss['o2_pct'])} percent of the ISS cabin" if iss else f"{F.n(o2)} percent oxygen"]
    if moon and abs(o2 - moon["o2_pct"]) <= tol["o2_pts"]:
        where[0] += f", and close to the Moon base habitat's {F.n(moon['o2_pct'])} percent"
    elif suit and o2 > moon["o2_pct"] + tol["o2_pts"] if moon else False:
        where[0] += f", and above the Moon base habitat's {F.n(moon['o2_pct'])} percent"
    po2 = n.get("po2", {})
    if po2.get("value_psi") is not None and iss:
        where[0] += f"; at {F.n(p)} psi that is an oxygen partial pressure of {F.n(po2['value_psi'])} psi, against {F.n(iss['po2_psi'])} psi in the ISS cabin"
    where[0] += "."
    # 2. what the nearby tests recorded
    near_line = (n.get("speak") or [""])[0]
    # 3. the closest evidence from the papers (the oxygen-effect lines the data already holds)
    ox = T.oxygen_effect(None, material)
    ev = [x for x in ox.get("speak", []) if "authors report" in x or x.startswith("From ")]
    band17 = next((x for x in ev if "17 percent oxygen" in x or "XO2 = 17%" in x), None)
    bre = next((x for x in ev if "26 %" in x), None)
    cool = next((x for x in ev if "0.4" in x or "cool flame" in x.lower()), None)
    evidence = (band17 or bre) if o2 < 23 else (cool if (o2 >= 40 and cool) else (bre or band17))
    if evidence:
        F.items.append({"text": evidence})
    # 4. the coverage note: always said, in one clause
    lvl = Q.level(c, n.get("n_near", 0), n.get("n_psis", 0))
    rg = n.get("ranges", {})
    outside = rg.get("o2_min") is not None and not (rg["o2_min"] <= o2 <= rg["o2_max"])
    if n.get("n_near", 0):
        cov = f"Coverage here is {lvl.lower()}: {_pl(F.i(n['n_near']), 'test')} in {_pl(F.i(n['n_psis']), 'investigation')}" + ("" if not n.get("n_spread") else f", {F.i(n['n_spread'])} with a spread rate") + "."
    else:
        cov = f"No PSI test ran this close; the tested ambient oxygen range is {F.n(rg['o2_min'])} to {F.n(rg['o2_max'])} percent." if rg.get("o2_min") is not None else "No PSI test ran this close."
    if outside:
        cov = f"This is outside the tested ambient oxygen range of {F.n(rg['o2_min'])} to {F.n(rg['o2_max'])} percent. " + cov
    meaning = evidence or n["speak"][0]
    speak = [where[0], near_line, evidence or cov]
    if evidence:
        speak.append(cov)
    d = dict(n)
    d.update({"tool": "interpret_conditions", "question": f"interpret_conditions({o2_pct}, {pressure_psi if pressure_psi is not None else pressure_kpa}, {material})", "speak": speak[:4], "facts": F.items,
              "interpretation": {"where": where[0], "nearby": near_line, "evidence": evidence, "coverage_level": lvl, "coverage_note": cov, "pressure_assumed": assumed_p,
                                 "outside_tested_range": bool(outside)},
              "meaning": meaning, "coverage_note": cov})
    d["gaps"] = list(dict.fromkeys(d.get("gaps", []) + ([f"pressure not stated: the ISS cabin's {F.n(p)} psi was used"] if assumed_p else [])))
    d["sources"] = d.get("sources") or []
    return T._clean(d)


# ---------------------------------------------------------------- get_test / compare_tests
SHOW = ["fuel", "material", "thickness_mm", "O2_pct", "pressure_kPa", "flow_cm_s", "O2_measured_pct", "flow_measured_cm_s", "flow_direction", "flame_type", "spread_rate_mm_s", "end_mode", "burn_1g_outcome", "ignition_power_W", "flames_ignited", "cool_flame", "hot_ignition", "soot_onset",
        "ignition_time_s", "burn_time_s", "burn_length_cm", "flame_length_mm", "extinction_d_mm", "particle_size_nm", "tad_K", "fuel_rate_mg_s", "fuel_frac_pct", "diluent"]
_SKIP = ("camera_ids", "figure_id", "description")


def _resolve_tests(c, ref, psi=None):
    ref = str(ref).strip()
    r = c.execute("SELECT t.*, p.flight_ground fg FROM test t JOIN psi p ON p.psi=t.psi WHERE t.test_id=?", (ref,)).fetchone()
    if r:
        return [r]
    q = "SELECT t.*, p.flight_ground fg FROM test t JOIN psi p ON p.psi=t.psi WHERE upper(t.native_id)=upper(?) AND t.duplicate_of IS NULL"
    a = [ref]
    pid = Q.resolve_psi(c, psi) if psi else None
    if pid:
        q += " AND t.psi=?"
        a.append(pid)
    return c.execute(q + " ORDER BY t.counted DESC, (p.flight_ground='flight') DESC, t.psi, t.test_id", a).fetchall()


def _vals(c, test_id):
    out = {}
    for r in c.execute("SELECT field, value_num, value_text, unit, trust, src_id, page FROM value WHERE test_id=? AND is_primary=1", (test_id,)):
        out[r["field"]] = dict(r)
    return out


def _show(c, v):
    """One value as a person reads it: pressure in psi, outcome words from the data's own labels. Returns (text, number or None)."""
    if v["field"] == "pressure_kPa" and v["value_num"] is not None:
        return U.fmt_psi(U.to_psi(v["value_num"])) + " psi", U.to_psi(v["value_num"])
    if v["value_num"] is not None:
        return Q.fmt(v["value_num"]) + (f" {v['unit']}" if v.get("unit") and v["unit"] not in ("%",) else (" %" if v.get("unit") == "%" else "")), v["value_num"]
    t = v["value_text"]
    if v["field"] == "end_mode":
        t = T.END_MODE_SAY.get(str(t).strip(), t)
    return str(t), None


def _outcome_words(vals):
    sr = (vals.get("spread_rate_mm_s") or {}).get("value_num")
    em = (vals.get("end_mode") or {}).get("value_text")
    return sr, (T.END_MODE_SAY.get(str(em).strip(), em) if em not in (None, "-", "", "not_recorded") else None)


def get_test(test_id, psi=None):
    """Tell me about this test / what is test 19115A1? ("tell me about test 19115A1", a pasted table row such as "ACME Flame Design (PSI-10) 19150A1 C2H4 39.8 14.8").
    Arguments: test_id = a test id as the table writes it ("19115A1", "PSI-10_1HCd8f_19115A1"); psi = optional investigation when the same id appears in several.
    Returns every value the data holds for that test (pressure in psi first), its investigation, flight or ground, how it ended, the findings linked to it, similar tests, and the source of each value.
    When the id is not in the data it says so; it never guesses another test."""
    c = T.con()
    q = f"get_test({test_id}, {psi})"
    rows = _resolve_tests(c, test_id, psi)
    if not rows:
        return _unknown("get_test", q, "test id", test_id)
    t = rows[0]
    vals = _vals(c, t["test_id"])
    F = Facts()
    fl = "flight" if t["fg"] == "flight" else "ground"
    mat, fuel = (vals.get("material") or {}).get("value_text"), (vals.get("fuel") or {}).get("value_text")
    speak = [f"Test {F.t(t['native_id'])} is a {fl} test in {_nm(c, t['psi'])}" + (f", burning {F.t(mat)}" if mat else (f" with {F.t(_fuel(c, fuel))}" if fuel else "")) + "."]
    o2, p = vals.get("O2_pct"), vals.get("pressure_kPa")
    cond = []
    if o2 and o2["value_num"] is not None:
        cond.append(f"{F.n(o2['value_num'])} percent oxygen" + ("" if t["o2_role"] in (None, "ambient") else " in the burner stream (not the atmosphere)"))
    if p and p["value_num"] is not None:
        cond.append(F.p(p["value_num"]))
    fl_ = (vals.get("flow_cm_s") or {}).get("value_num")
    if fl_ is not None:
        cond.append(f"a flow of {F.n(fl_)} centimeters per second")
    th_ = (vals.get("thickness_mm") or {}).get("value_num")
    if th_ is not None:
        cond.append(f"a sample thickness of {F.n(th_)} millimeters")
    if cond:
        speak.append("It ran at " + _list(cond) + ".")
    sr, em = _outcome_words(vals)
    out = []
    if sr is not None and sr > 0:
        out.append(f"a flame spread rate of {F.n(sr)} millimeters per second")
    if em:
        out.append(F.t(em))
    b1g = (vals.get("burn_1g_outcome") or {}).get("value_text")
    if b1g not in (None, "", "-"):
        out.append(f"in the normal-gravity test: {F.t(b1g)}")
    cf_ = (vals.get("cool_flame") or {}).get("value_text")
    if cf_ not in (None, "", "-"):
        out.append("a cool flame" if str(cf_).lower() in ("yes", "y", "true") else ("no cool flame" if str(cf_).lower() in ("no", "n", "false") else f"cool flame: {F.t(cf_)}"))
    so = (vals.get("soot_onset") or {}).get("value_text")
    if so not in (None, "", "-"):
        out.append("soot onset" if str(so).lower() in ("yes", "y", "true") else ("no soot onset" if str(so).lower() in ("no", "n", "false") else f"soot: {F.t(so)}"))
    speak.append("The data records " + _list(out) + "." if out else "The data records no outcome for this test (no spread rate, no end mode).")
    if len(rows) > 1:
        speak.append(f"The id {F.t(t['native_id'])} also appears in {_list(_nm(c, r['psi']) for r in rows[1:3])}; ask with the investigation name for those.")
    tbl_rows = []
    for f in SHOW + sorted(k for k in vals if k not in SHOW and k not in _SKIP):
        v = vals.get(f)
        if not v or len(tbl_rows) >= 24:
            continue
        txt, num = _show(c, v)
        tbl_rows.append({"field": T._flabel(c, f).replace("(kPa)", "(psi)") if f == "pressure_kPa" else T._flabel(c, f), "value": txt, "trust": v["trust"], "source": (f"sensor file {v['src_id']}" if str(v.get("src_id") or "").endswith(".xlsx") else (f"page {v['page']}" if v.get("page") else "experiment table"))})
    pk = vals.get("pressure_kPa")
    if pk and pk.get("value_num") is not None and str(pk.get("src_id") or "").endswith(".xlsx"):          # the sensor's own unit, beside the psi row
        tbl_rows.append({"field": "Pressure measured by the sensor (kPa)", "value": f"{pk['value_num']:.1f} kPa", "trust": pk["trust"], "source": f"sensor file {pk['src_id']}, median before ignition"})
    # findings linked to the test, and similar tests (same investigation, within the nearest_tests tolerances)
    fnd = Q.rows(c, "SELECT f.finding_id, f.statement, f.wording, f.paper_id, f.page FROM finding_test ft JOIN finding f ON f.finding_id=ft.finding_id WHERE ft.test_id=? ORDER BY f.finding_id", (t["test_id"],))
    nr = Q.cfg(c)["groups"]["tol"]
    similar = []
    if o2 and p and o2["value_num"] is not None and p["value_num"] is not None:
        for r in c.execute("SELECT t2.test_id, t2.native_id, o.value_num o2, pp.value_num p FROM test t2 JOIN value o ON o.test_id=t2.test_id AND o.field='O2_pct' AND o.is_primary=1 JOIN value pp ON pp.test_id=t2.test_id AND pp.field='pressure_kPa' AND pp.is_primary=1 "
                           "WHERE t2.psi=? AND t2.test_id<>? AND t2.counted=1 AND t2.duplicate_of IS NULL AND ABS(o.value_num-?)<=? AND ABS(pp.value_num-?)<=? ORDER BY ABS(o.value_num-?), t2.native_id LIMIT 6",
                           (t["psi"], t["test_id"], o2["value_num"], nr["o2_pts"], p["value_num"], nr["p_rel"] * p["value_num"], o2["value_num"])):
            v2 = _vals(c, r["test_id"])
            s2, e2 = _outcome_words(v2)
            similar.append({"test": r["native_id"], "o2_pct": r3(r["o2"]), "p_psi": U.to_psi(r["p"]), "outcome": f"spread rate {Q.fmt(s2)} mm/s" if s2 else (e2 or "no outcome recorded")})
            F.items += [{"value": r3(r["o2"])}, {"value": U.to_psi(r["p"])}]
    if fnd:
        meaning = f"{_pl(F.i(len(fnd)), 'paper finding')} {'is' if len(fnd) == 1 else 'are'} linked to this test: " + F.t(fnd[0]["statement"].rstrip(".")) + "."
    elif similar:
        meaning = f"{_pl(F.i(len(similar)), 'other test')} in {_nm(c, t['psi'])} ran within {F.n(nr['o2_pts'])} oxygen points and {F.n(nr['p_rel'] * 100)} percent of this pressure."
    else:
        meaning = "No paper finding is linked to this test, and no other test in the investigation ran this close."
    speak.append(meaning)
    # the values the flight sensors measured (Round 16 sensor files): reported as they are, never derived into a rate or a safe level
    ms = []
    om, fm, cs = (vals.get("O2_measured_pct") or {}).get("value_num"), (vals.get("flow_measured_cm_s") or {}).get("value_num"), (vals.get("igniter_duration_s") or {}).get("value_num")
    pm = p if p and str(p.get("src_id") or "").endswith(".xlsx") else None
    if om is not None:
        ms.append(f"{F.n(om)} percent oxygen")
    if fm is not None:
        ms.append(f"a flow of {F.n(fm)} centimeters per second")
    if pm and pm.get("value_num") is not None:
        ms.append(f"a pressure of {F.p(pm['value_num'])}")
    if ms:
        line = "The flight sensors measured " + _list(ms) + " before ignition" + (f"; the igniter was on for {F.n(cs)} seconds" if cs is not None else "") + "."
        stg = [(r["stage_no"], r["value_num"]) for r in c.execute("SELECT stage_no, value_num FROM value_stage WHERE test_id=? AND field='sample_tc_peak_C' ORDER BY value_num DESC LIMIT 2", (t["test_id"],))]
        if stg:
            line += " The two hottest sample thermocouples read " + _list(f"{F.n(v)} degrees Celsius" for n, v in stg) + "."
        speak.insert(3 if len(speak) > 3 else len(speak) - 1, line)
    refs = [t["psi"]] + [f["finding_id"] for f in fnd[:3]] + [v["src_id"] for v in vals.values() if v.get("src_id") and (str(v["src_id"]).endswith(".xlsx") or str(v["src_id"]).startswith("table:"))]
    kp = [_kpi("o2", "oxygen", (o2 or {}).get("value_num"), "primary value, experiment table", "table", "%"), _kpi("p", "pressure", (p or {}).get("value_num"), "primary value, experiment table", "table", "kPa")]
    return _ans("get_test", q, speak, F, kp, [], _tbl([("field", "field", ""), ("value", "value", ""), ("trust", "trust", ""), ("source", "source", "")], tbl_rows), [], refs=refs,
                conditions={"o2_pct": (o2 or {}).get("value_num"), "pressure_psi": U.to_psi(p["value_num"]) if p and p.get("value_num") is not None else None, "o2_role": t["o2_role"]},
                test={"test_id": t["test_id"], "native_id": t["native_id"], "psi": t["psi"], "investigation": _nm(c, t["psi"]), "flight": fl == "flight", "o2_role": t["o2_role"], "n_matches": len(rows)},
                findings=[{"finding": f["finding_id"], "statement": f["statement"], "wording": f["wording"], "page": f["page"]} for f in fnd[:5]], similar_tests=similar, meaning=meaning)


def compare_tests(ids):
    """Compare these tests side by side ("compare 19150A1 and 19115A1", "which of these two tests ran at higher oxygen?").
    Argument: ids = two or three test ids as the table writes them (a list, or one string separated by commas / "and").
    Returns a table with each test's investigation, flight or ground, fuel or material, oxygen, pressure (psi first), flow, spread rate and how it ended, and names the quantities that differ.
    It never ranks the tests and never says which is safer."""
    c = T.con()
    if isinstance(ids, str):
        ids = [x for x in re.split(r"\s*(?:,|;|\band\b|\bvs\.?\b|\bversus\b)\s*", ids) if x]
    q = f"compare_tests({', '.join(map(str, ids))})"
    found, missing = [], []
    for i in list(ids)[:3]:
        r = _resolve_tests(c, i)
        (found if r else missing).append(r[0] if r else i)
    if len(found) < 2:
        return _unknown("compare_tests", q, "test id", ", ".join(missing) if missing else ", ".join(map(str, ids)))
    F = Facts()
    data = [(t, _vals(c, t["test_id"])) for t in found]
    keys = [("investigation", None), ("flight / ground", None), ("fuel", "fuel"), ("material", "material"), ("oxygen (%)", "O2_pct"), ("pressure (psi)", "pressure_kPa"), ("flow (cm/s)", "flow_cm_s"),
            ("flame spread rate (mm/s)", "spread_rate_mm_s"), ("how it ended", "end_mode")]
    labels = [f"{t['native_id']}" for t, _ in data]
    rows = []
    differ = []
    for lab, f in keys:
        cells = []
        for t, v in data:
            if f is None:
                cells.append(_nm(c, t["psi"]) if lab == "investigation" else ("flight" if t["fg"] == "flight" else "ground"))
            else:
                cells.append(_show(c, {**v[f], "field": f})[0] if v.get(f) else "not recorded")
        if len(set(cells)) > 1 and not all(x == "not recorded" for x in cells):
            differ.append(lab.split(" (")[0])
        if not all(x == "not recorded" for x in cells):
            rows.append({"item": lab, **{f"t{i}": x for i, x in enumerate(cells)}})
    cols = [("item", "quantity", "")] + [(f"t{i}", labels[i], "") for i in range(len(data))]
    speak = []
    for t, v in data[:3]:
        o2, p = v.get("O2_pct"), v.get("pressure_kPa")
        bits = []
        if o2 and o2["value_num"] is not None:
            bits.append(f"{F.n(o2['value_num'])} percent oxygen")
        if p and p["value_num"] is not None:
            bits.append(F.p(p["value_num"]))
        speak.append(f"Test {F.t(t['native_id'])} ({_nm(c, t['psi'])}, {'flight' if t['fg'] == 'flight' else 'ground'}) ran at " + (_list(bits) if bits else "conditions the data does not state") + ".")
    speak.append(("They differ in " + _list(differ[:5]) + "; the data does not rank them." if differ else "They match in every recorded quantity; the data does not rank them.") + (f" No test found for {_list(map(str, missing))}." if missing else ""))
    return _ans("compare_tests", q, speak[:4], F, [], [], _tbl(cols, rows), [], refs=list(dict.fromkeys(t["psi"] for t, _ in data)), compared=[t["test_id"] for t, _ in data], differ=differ, missing=missing)


# ---------------------------------------------------------------- list_papers
def list_papers(psi=None, topic=None):
    """Which papers are in the data / which paper appears most? ("what's the best paper that appears a lot in the sources?", "papers on BASS-II", "papers about cool flames").
    Arguments: psi = an investigation to narrow to; topic = a word the finding statements must contain.
    Lists the papers that the findings come from, most findings first, with the DOI. It counts findings; it does not rate how good a paper is, and says so."""
    c = T.con()
    pid = Q.resolve_psi(c, psi) if psi else None
    if psi and not pid:
        return _unknown("list_papers", f"list_papers({psi}, {topic})", "PSI", psi)
    sql = ("SELECT f.paper_id, COUNT(DISTINCT f.finding_id) n, COUNT(DISTINCT fp.psi) n_psi FROM finding f LEFT JOIN finding_psi fp ON fp.finding_id=f.finding_id" + (" WHERE fp.psi=?" if pid else "") + " GROUP BY f.paper_id")
    rows = Q.rows(c, sql, (pid,) if pid else ())
    if topic:
        rx = re.compile(re.escape(topic), re.I)
        keep = {r["paper_id"] for r in Q.rows(c, "SELECT paper_id, statement FROM finding") if rx.search(r["statement"])}
        rows = [r for r in rows if r["paper_id"] in keep]
    papers = []
    for r in rows:
        s = c.execute("SELECT title, doi, kind FROM source WHERE src_id=?", (r["paper_id"],)).fetchone()
        if not s or not s["title"]:
            continue
        psis = [x["psi"] for x in c.execute("SELECT DISTINCT fp.psi FROM finding f JOIN finding_psi fp ON fp.finding_id=f.finding_id WHERE f.paper_id=? ORDER BY 1", (r["paper_id"],))]
        papers.append({"paper_id": r["paper_id"], "title": T.clean_title(s["title"], c), "doi": s["doi"], "findings": r["n"], "n_psi": r["n_psi"], "psis": psis})
    papers.sort(key=lambda x: (-x["findings"], x["title"]))
    F = Facts()
    where = f" for {_nm(c, pid)}" if pid else ""
    tp = f" mentioning {topic}" if topic else ""
    if not papers:
        speak = [f"No paper{where}{tp} has a finding in the data."]
        gaps = [f"no paper finding{where}{tp}"]
    else:
        top = papers[0]
        speak = [f"{_pl(F.i(len(papers)), 'paper')}{where}{tp} {'has' if len(papers) == 1 else 'have'} findings in the data.",
                 f"The one with the most findings is {F.t(top['title'])}, with {_pl(F.i(top['findings']), 'finding')}" + (f" across {_pl(F.i(top['n_psi']), 'investigation')}" if top["n_psi"] > 1 else "") + ".",
                 "This counts findings in the sources; it does not rate how good a paper is."]
        gaps = []
    tbl = _tbl([("title", "paper", ""), ("findings", "findings", ""), ("psis", "investigations", ""), ("doi", "DOI", "")],
               [{"title": p["title"], "findings": p["findings"], "psis": ", ".join(p["psis"][:3]), "doi": p["doi"] or "no DOI"} for p in papers[:12]]) if papers else None
    return _ans("list_papers", f"list_papers({psi}, {topic})", speak, F, [_kpi("n_papers", "papers with findings", len(papers), "papers that at least one finding comes from", "table")], [], tbl, gaps,
                refs=[p["paper_id"] for p in papers[:6]], papers=papers[:12], n_papers=len(papers), scope={"psi": pid, "topic": topic},
                meaning="It counts findings in the sources; it does not rate how good a paper is.")
