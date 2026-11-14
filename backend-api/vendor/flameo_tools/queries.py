"""Small reusable query helpers over serving.db (layer 2). No use-case logic: tools.py combines them."""
import json
import re
import sqlite3

ELIGIBLE = "t.counted=1 AND t.duplicate_of IS NULL AND COALESCE(t.flags,'') NOT LIKE '%out_of_range%'"


def connect(path):
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, check_same_thread=False)
    con.row_factory = sqlite3.Row
    return con


def cfg(con):
    return json.loads(con.execute("SELECT value FROM meta WHERE key='config_json'").fetchone()[0])


def rows(con, sql, args=()):
    return [dict(r) for r in con.execute(sql, args)]


def fmt(x, nd=3):
    if x is None:
        return "n/a"
    if isinstance(x, str):
        return x
    return f"{x:.{nd}g}" if abs(x) < 1000 else f"{x:.0f}"


def resolve_scenario(con, name):
    if not name:
        return None
    n = re.sub(r"[\s_\-]+", " ", str(name).strip().lower())
    for r in con.execute("SELECT scenario, aliases FROM scenario ORDER BY scenario"):
        ids = [r["scenario"]] + json.loads(r["aliases"])
        if n in {re.sub(r"[\s_\-]+", " ", i.lower()) for i in ids}:
            return r["scenario"]
    return None


def resolve_psi(con, name):
    n = str(name).strip().lower()
    if re.fullmatch(r"\d+", n):
        n = "psi-" + n
    for r in con.execute("SELECT psi, name, title, hardware FROM psi ORDER BY psi"):
        if n in (r["psi"].lower(), (r["name"] or "").lower(), (r["hardware"] or "").lower(), (r["title"] or "").lower()):
            return r["psi"]
    for r in con.execute("SELECT psi, title FROM psi ORDER BY psi"):
        if any(a.strip().lower() == n for a in re.findall(r"\(([^()]+)\)", r["title"] or "")):
            return r["psi"]
    hits = [r["psi"] for r in con.execute("SELECT psi, name, title FROM psi ORDER BY psi") if n in (r["title"] or "").lower() or n in (r["name"] or "").lower()]
    return hits[0] if len(hits) == 1 else None


def resolve_field(con, name):
    if not name:
        return None
    c = cfg(con)
    n = str(name).strip()
    if con.execute("SELECT 1 FROM field WHERE field=?", (n,)).fetchone():
        return n
    return c.get("field_aliases", {}).get(n.lower())


def field_unit(con, f):
    r = con.execute("SELECT unit FROM field WHERE field=?", (f,)).fetchone()
    return (r["unit"] if r else None) or ""


def values(con, field, psi=None, scenario=None, kinds=("near", "oxidizer_stream"), positive=False):
    """Primary values of a field for eligible tests, optionally restricted to the tests a scenario covers."""
    q = f"SELECT t.test_id, t.psi, t.native_id, t.o2_role, t.diluent, t.fuel_class, v.value_num, v.value_text, v.unit, v.trust, v.label, v.src_id, v.page, v.quote FROM test t JOIN value v ON v.test_id=t.test_id AND v.is_primary=1 AND v.field=? WHERE {ELIGIBLE}"
    a = [field]
    if psi:
        q += " AND t.psi=?"
        a.append(psi)
    if positive:
        q += " AND v.value_num > 0"
    if scenario:
        q += " AND t.test_id IN (SELECT test_id FROM scenario_coverage WHERE scenario=? AND match_kind IN (%s))" % ",".join("?" * len(kinds))
        a += [scenario, *kinds]
    return rows(con, q + " ORDER BY t.test_id", a)


def scope_tests(con, scenario=None, kinds=("near", "oxidizer_stream")):
    q = f"SELECT t.test_id FROM test t WHERE {ELIGIBLE}"
    a = []
    if scenario:
        q += " AND t.test_id IN (SELECT test_id FROM scenario_coverage WHERE scenario=? AND match_kind IN (%s))" % ",".join("?" * len(kinds))
        a = [scenario, *kinds]
    return [r["test_id"] for r in con.execute(q + " ORDER BY 1", a)]


def trust_text(items):
    from collections import Counter
    c = Counter(i["trust"] for i in items)
    return "+".join(f"{k}" for k, _ in sorted(c.items(), key=lambda kv: -kv[1])) if c else "none"


def cards(con, x=None, y=None, psi=None, claim_types=None, terms=None, text=None, limit=50):
    q = "SELECT DISTINCT f.finding_id, f.statement, f.quote, f.wording, f.evidence_basis, f.claim_type, f.paper_id, f.page, f.x_field, f.y_field FROM finding f"
    w, a = [], []
    if psi:
        q += " JOIN finding_psi fp ON fp.finding_id=f.finding_id"
        w.append("fp.psi=?")
        a.append(psi)
    if x:
        w.append("f.x_field=?")
        a.append(x)
    if y:
        w.append("f.y_field=?")
        a.append(y)
    if claim_types:
        w.append("f.claim_type IN (%s)" % ",".join("?" * len(claim_types)))
        a += list(claim_types)
    out = rows(con, q + (" WHERE " + " AND ".join(w) if w else "") + " ORDER BY f.finding_id", a)
    for pat in (terms, text):
        if pat:
            rx = re.compile(pat, re.I)
            out = [r for r in out if rx.search(r["statement"] + " " + (r["quote"] or ""))]
    for r in out:
        r["psis"] = [p["psi"] for p in con.execute("SELECT psi FROM finding_psi WHERE finding_id=? ORDER BY psi", (r["finding_id"],))]
    return out[:limit]


def coverage_counts(con, scenario):
    return rows(con, "SELECT match_kind, COUNT(*) n, COUNT(DISTINCT psi) psis FROM scenario_coverage WHERE scenario=? GROUP BY 1 ORDER BY 1", (scenario,))


def level(con, n, p):
    lv = cfg(con)["coverage"]["levels"]
    if n >= lv["high"]["tests"] and p >= lv["high"]["psis"]:
        return "High"
    if n >= lv["medium"]["tests"] or p >= lv["medium"]["psis"]:
        return "Medium"
    return "Low" if n >= 1 else "None"


def groups_for(con, outcome, scenario=None):
    q = "SELECT g.* FROM comparable_group g WHERE g.outcome_field=?"
    a = [outcome]
    if scenario:
        q += " AND EXISTS (SELECT 1 FROM comparable_member m JOIN scenario_coverage c ON c.test_id=m.test_id AND c.scenario=? AND c.match_kind='near' WHERE m.group_id=g.group_id)"
        a.append(scenario)
    return rows(con, q + " ORDER BY g.group_id", a)


def group_values(con, group_id, field):
    return rows(con, "SELECT t.test_id, t.psi, t.native_id, t.fuel_class, v.value_num, v.value_text, v.unit, v.trust, v.src_id, v.page, v.quote FROM comparable_member m JOIN test t ON t.test_id=m.test_id "
                     "JOIN value v ON v.test_id=t.test_id AND v.is_primary=1 AND v.field=? WHERE m.group_id=? ORDER BY t.test_id", (field, group_id))


def primary(con, test_id, field):
    r = con.execute("SELECT value_num, value_text, unit, trust FROM value WHERE test_id=? AND field=? AND is_primary=1", (test_id, field)).fetchone()
    return dict(r) if r else None


def primary_row(con, test_id, field):
    r = con.execute("SELECT value_num, value_min, value_max, value_text, unit, trust, flags FROM value WHERE test_id=? AND field=? AND is_primary=1", (test_id, field)).fetchone()
    return dict(r) if r else None


def nearest_with(con, sid, field, positive=True):
    """Nearest scenario (other than sid) that has data for the asked field: (scenario, label, n tests) or None. Order: config nearest_covered, then the other scenarios."""
    c = cfg(con)
    order = [x for x in c.get("nearest_covered", {}).get(sid, [])] + [r["scenario"] for r in con.execute("SELECT scenario FROM scenario WHERE no_data=0 ORDER BY scenario")]
    seen = []
    for cand in order:
        if cand == sid or cand in seen or cand == "high_o2":
            continue
        seen.append(cand)
        ids = set(scope_tests(con, cand))
        n = sum(1 for v in values(con, field, positive=positive) if v["test_id"] in ids)
        if n:
            return cand, con.execute("SELECT label FROM scenario WHERE scenario=?", (cand,)).fetchone()[0], n
    return None
