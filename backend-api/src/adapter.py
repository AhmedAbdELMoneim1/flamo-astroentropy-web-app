"""flameo_tools output -> what the screen and the model get (pure functions, no I/O).

Rule: the adapter only SELECTS and TRIMS. It never computes a new number. Every number in its output is in the
flameo answer it was given; the only exceptions are the row / series counts in a "12 of N rows" footer (N is the
length of the original list) and the request_id.

    to_dashboard(d)  flameo show_view JSON  -> Dashboard for view.open
    to_answer(a)     flameo tool answer     -> Answer for answer.show (adds request_id, metric, pillar)
    to_ranking(a)    rank_investigations    -> the ranking panel object
    to_model(a)      flameo tool answer     -> the small dict the voice model gets back

Limits (CONTRACT.md): < 8000 bytes per packet, table <= 6 columns and <= 12 rows, gaps <= 3, cards <= 3,
charts <= 2, series <= 3 and points <= 12 per series, cell text <= 80 characters, ranking <= 8 rows.
"""

from __future__ import annotations

import re
import copy
import json
import logging
import uuid

logger = logging.getLogger("adapter")

LIMITS = {"kpis": 4, "charts": 2, "series": 3, "points": 12, "rows": 12, "cols": 6, "gaps": 3, "cards": 3, "cell": 80, "bytes": 8000, "ranking": 8}

CUSTOM_HEADLINE = "All PSI tests (not filtered to your conditions)"
CUSTOM_GAP = "Coverage is rated only for the ISS, Moon base and spacesuit atmospheres."
O2P_REF = {"id": "o2_vs_pressure", "type": "scatter", "ref": "/api/charts/o2_vs_pressure"}

# columns shown per tool (<= 6). View tables use the view's key column + the first fields (see _view_columns).
TOOL_COLUMNS = {
    "scenario_coverage": ["psi", "n", "o2_min", "o2_max", "p_min", "p_max"],
    "rank_agents": ["agent", "psi", "tests", "pct_min", "pct_max", "with_extinction_d"],
    "rank_materials": ["investigation", "material", "direction", "n", "values", "o2"],
    "get_findings": ["finding", "wording", "psis"],
    "compare": ["item", "a", "b"],
    "get_investigation": ["field", "tests", "table", "document", "assumed", "paper"],
    "search_text": ["psi", "src", "page", "text"],
    "gaps": ["psi", "field", "n_tests", "n_missing", "status"],
    "get_test": ["field", "value", "trust", "source"],
    "list_papers": ["title", "findings", "psis", "doi"],
}

# which category a tool answer belongs to (decisions Round 3 section 3.5); None = stay where the astronaut is
VIEW_PILLAR = {"ignition": "prevention", "materials": "prevention", "flame_spread": "flammability", "smoke": "detection", "suppression": "suppression"}
FIXED_PILLAR = {"rank_materials": "prevention", "rank_agents": "suppression"}
Y_PILLAR = (("spread", "flammability"), ("particle", "detection"), ("smoke", "detection"), ("extinction", "suppression"), ("diluent", "suppression"))

NO_PASSAGE = "No passage in the documents, papers or cards matches that."


def request_id() -> str:
    return uuid.uuid4().hex[:8]


# ───────────────────────────── helpers ─────────────────────────────
def cut_text(s, n: int = LIMITS["cell"]):
    """Display only: cut a long cell at a word boundary with an ellipsis. Speech is never cut."""
    if not isinstance(s, str) or len(s) <= n:
        return s
    head = s[: n - 1]
    if " " in head and s[n - 1] != " ":
        head = head.rsplit(" ", 1)[0]
    return head.rstrip(" ,;:.") + "…"


def pillar_for(a: dict) -> str | None:
    tool = a.get("tool")
    if tool == "show_view" or "view" in a and "key_points" in a:
        return VIEW_PILLAR.get(a.get("view"))
    if tool == "rank_investigations":
        return a.get("pillar")
    if tool in FIXED_PILLAR:
        return FIXED_PILLAR[tool]
    if tool == "get_findings":
        y = (a.get("question") or "").lower().split(",")
        y = y[1] if len(y) > 1 else ""
        return next((p for k, p in Y_PILLAR if k in y), None)
    return None


def _label(labels: dict | None, key: str, fallback: str) -> str:
    if labels and key in labels:
        return str(labels[key].get("say") or fallback)
    return fallback


def _cols_for_view(table: dict, key: str | None) -> list[str]:
    cols = [c["key"] for c in table["columns"]]
    if len(cols) <= LIMITS["cols"]:
        return cols
    keep = cols[: LIMITS["cols"]]
    if key and key in cols and key not in keep:
        keep = keep[: LIMITS["cols"] - 1] + [key]
    return keep


def _trim_table(table: dict | None, want: list[str] | None, key: str | None = None, labels: dict | None = None) -> dict | None:
    if not table or not table.get("rows"):
        return None
    allc = {c["key"]: c for c in table["columns"] if not c.get("hidden")}            # hidden columns carry the source kPa of a psi column (shown in small text)
    cols = [k for k in (want or []) if k in allc] if want else _cols_for_view({**table, "columns": list(allc.values())}, key)
    cols = cols[: LIMITS["cols"]] or list(allc)[: LIMITS["cols"]]
    total = len(table["rows"])
    rows = [{**{k: cut_text(r.get(k)) for k in cols}, **{k + "__kpa": r[k + "__kpa"] for k in cols if k + "__kpa" in r}} for r in table["rows"][: LIMITS["rows"]]]
    out = {
        "columns": [{"key": k, **({"unit": allc[k]["unit"]} if allc[k].get("unit") else {}), **({"unit_from": allc[k]["unit_from"]} if allc[k].get("unit_from") else {}), "label": cut_text(_label(labels, k, allc[k]["label"]), 40) if want is None else allc[k]["label"]} for k in cols],
        "rows": rows,
    }
    if total > len(rows):
        out["footer"] = f"{len(rows)} of {total} rows"
    return out


def _trim_chart(c: dict) -> dict:
    if c.get("id") == O2P_REF["id"] or c.get("ref"):
        return {**O2P_REF, "title": c.get("title", ""), "x": c.get("x", {}), "y": c.get("y", {})}
    series, shown = [], None
    for s in c.get("series", [])[: LIMITS["series"]]:
        pts = s.get("points", [])
        kept = pts if c.get("type") == "scatter" else pts[: LIMITS["points"]]      # the 12-point limit is for bar and line charts; a scatter shows every point (Round 10 §10.3 item 4)
        if len(pts) > len(kept) and shown is None:
            shown = f"{len(kept)} of {len(pts)} points"
        series.append({**{k: v for k, v in s.items() if k != "points"}, "points": kept})
    out = {**{k: v for k, v in c.items() if k != "series"}, "series": series}
    if shown:
        out["shown"] = shown
    if len(c.get("series", [])) > LIMITS["series"]:
        out["shown"] = (out.get("shown", "") + f" ({LIMITS['series']} of {len(c['series'])} series)").strip()
    return out


def _cards(cards) -> list[dict]:
    keep = ("id", "statement", "wording", "evidence_basis", "paper", "page", "psis")
    out = [{k: c[k] for k in keep if k in c} for c in (cards or [])[: LIMITS["cards"]]]
    for o, c in zip(out, cards or []):
        if c.get("paper_title"):
            o["paper"] = c["paper_title"]                 # the title on screen, never the DOI / doc: id
    return out


def _kpis(kpis, gaps, speak) -> list[dict]:
    """Keep basis and trust. A KPI that says 0 / none is hidden when a gap or speak line already states the absence."""
    stated = bool(gaps) or bool(speak and str(speak[0]).startswith("No "))
    out = [dict(k) for k in (kpis or []) if not (stated and k.get("value") in (0, "none"))]
    return out[: LIMITS["kpis"]]


def _coverage(c):
    return c if c in ("High", "Medium", "Low", "None") else None


def fit(obj: dict, name: str) -> dict:
    """< 8000 bytes: drop cards, then ranking rows / table rows from the end. Logs what it dropped."""
    def size():
        return len(json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    first = size()
    if first < LIMITS["bytes"]:
        return obj
    dropped = []
    if obj.get("cards"):
        obj["cards"] = []
        dropped.append("cards")
    while size() >= LIMITS["bytes"]:
        t = obj.get("table")
        if t and t["rows"]:
            t["rows"].pop()
            t["footer"] = "rows cut to fit"
            dropped.append("row")
        elif obj.get("ranking") and len(obj["ranking"]) > 3:
            obj["ranking"].pop()
            dropped.append("ranking row")
        elif obj.get("charts"):
            obj["charts"].pop()
            dropped.append("chart")
        else:
            break
    logger.warning("%s was %d bytes (limit %d): dropped %s", name, first, LIMITS["bytes"], ", ".join(dropped) or "nothing")
    return obj


# ───────────────────────────── ranking ─────────────────────────────
def to_ranking(a: dict) -> dict | None:
    """The 'Most relevant investigations' panel from a rank_investigations answer. Bar value = tests (a real count)."""
    if a.get("tool") != "rank_investigations" or not a.get("ranking"):
        return None
    rows = a["ranking"]
    keep = rows[: LIMITS["ranking"]]
    out = {
        "pillar": a.get("pillar"),
        "scenario": a.get("for_scenario"),
        "rows": [{k: r.get(k) for k in ("rank", "group", "psi", "name", "tier", "pillars", "tests", "tests_label", "findings")} for r in keep],
        "tier_label": "relevance tier (from the official PSI description)",
        "divider": a.get("no_tests_divider"),
        "note": next((g for g in a.get("gaps", []) if g.startswith("This ranks relevance")), None),
    }
    if len(rows) > len(keep):
        out["footer"] = f"{len(keep)} of {len(rows)} investigations"
    return out


# ───────────────────────────── dashboard ─────────────────────────────
def to_dashboard(d: dict, custom: bool = False, labels: dict | None = None) -> dict:
    """flameo show_view JSON -> Dashboard (kpis <= 4, charts <= 2, table <= 6 x 12, gaps <= 3, cards <= 3)."""
    gaps = list(dict.fromkeys(d.get("gaps", [])))
    headline = d.get("headline", "")
    if custom:
        headline = f"{CUSTOM_HEADLINE}. {headline}" if headline else CUSTOM_HEADLINE
        gaps = [g for g in gaps if g != CUSTOM_GAP] + [CUSTOM_GAP] if len(gaps) < LIMITS["gaps"] else gaps[: LIMITS["gaps"] - 1] + [CUSTOM_GAP]
    out = {
        "view": d.get("view"),
        "scenario": None if custom else d.get("scenario"),
        "coverage": None if custom else _coverage(d.get("coverage")),
        "headline": headline,
        "key_points": list(d.get("key_points", [])),
        "kpis": _kpis(d.get("kpis"), gaps, d.get("speak")),
        "charts": [_trim_chart(c) for c in d.get("charts", [])[: LIMITS["charts"]]],
        "table": _trim_table(d.get("table"), None, d.get("table_key"), labels),
        "gaps": gaps[: LIMITS["gaps"]],
        "cards": _cards(d.get("cards")),
        "source": {**d.get("source", {}), "mock": False},
    }
    if d.get("level_oxygen_rich_flames"):
        out["coverage_note"] = {"label": "Oxygen-rich flames (burner stream, not the atmosphere)", "level": d["level_oxygen_rich_flames"]}
    if d.get("nearest"):
        out["nearest"] = d["nearest"]
    return fit(out, f"dashboard {d.get('view')}")


# ───────────────────────────── answer ─────────────────────────────
TOOL_TITLE = {"get_investigation": "Investigation", "compare": "Comparison", "rank_materials": "Flame spread in the tested materials", "scenario_coverage": "Tests near this atmosphere",
              "get_findings": "What the papers report", "rank_agents": "Gases added in the experiments", "gaps": "What the data does not cover", "search_text": "Passages found",
              "rank_investigations": "Most relevant investigations", "oxygen_effect": "Oxygen and fire: what the tests show", "ask_sources": "Answer from the sources"}


def title_of(a: dict, question: str | None = None) -> str:
    """The answer card's title: the astronaut's question, else the tool's headline. Never the function call ("OXYGEN_EFFECT(ISS, NONE)")."""
    q = (question or "").strip()
    if q:
        return q[:140]
    own = str(a.get("question") or "")
    if own and not re.match(r"^\w+\(.*\)$", own):
        return own[:140]
    return TOOL_TITLE.get(a.get("tool", ""), "Answer")


def group_of(x: dict) -> str:
    """The Sources group of one source, by what it really is (a NASA PSI document is never filed under "Paper")."""
    k, lk = x.get("kind") or "", x.get("link_kind")
    if x.get("doc_id") or lk == "nasa_psi_download" or k in ("doc", "reference", "document"):
        return "NASA document"
    if lk == "doi" or k == "paper":
        return "Paper"
    if k in ("card", "finding"):
        return "Finding"
    if k in ("table", "profile", "investigation", "psi"):
        return "Experiment table"
    return x.get("label") if x.get("label") in ("Paper", "NASA document", "Finding", "Experiment table", "NASA Space Apps challenge text") else "Paper"


def order_sources(sources: list[dict], speak_refs: list | None = None) -> tuple[list[dict], list | None]:
    """Sources numbered in the order they are shown (grouped by kind, groups in order of first use), and the source numbers of each spoken line remapped to match."""
    groups: dict[str, list[dict]] = {}
    for x in sorted(sources, key=lambda x: x.get("n", 0)):
        x = {**x, "detail": x.get("label"), "label": group_of(x)}
        groups.setdefault(x["label"], []).append(x)
    ordered = [x for g in groups.values() for x in g]
    remap = {x["n"]: i for i, x in enumerate(ordered, 1)}
    out = [{**x, "n": remap[x["n"]]} for x in ordered]
    refs = [sorted({remap[n] for n in r if n in remap}) for r in speak_refs] if speak_refs is not None else None
    return out, refs


OPEN_QUESTION = "That isn't covered in the PSI data or papers yet. It is an open question: answering it would need new experiments or papers on it."


def to_answer(a: dict, labels: dict | None = None, offer: dict | None = None, title: str | None = None) -> dict:
    """flameo tool answer -> Answer for answer.show. facts stay on the server."""
    tool = a.get("tool", "")
    gaps = list(dict.fromkeys(a.get("gaps", [])))
    if tool == "search_text" and not matched(a):       # nothing relevant: the screen says so (an open question), it never shows passages the voice did not use
        a = {**a, "table": None, "cards": [], "speak": []}
        gaps = []
    speak_set = {str(x).strip() for x in a.get("speak", [])}
    gaps = [g for g in gaps if str(g).strip() not in speak_set]          # a line already in the body is not repeated under "Open questions" (Round 10 §10.7 item 9)
    out = {
        "request_id": request_id(),
        "metric": tool,
        "tool": tool,
        "question": title_of(a, title),
        "version": a.get("version", 1),
        "pillar": pillar_for(a),
        "speak": list(a.get("speak", [])),
        "kpis": _kpis(a.get("kpis"), gaps, a.get("speak")),
        "charts": [_trim_chart(c) for c in a.get("charts", [])[: LIMITS["charts"]]],
        "table": None if tool == "rank_investigations" else _trim_table(a.get("table"), TOOL_COLUMNS.get(tool)),
        "gaps": gaps[: LIMITS["gaps"]],
        "cards": _cards(a.get("cards")),
        "source": {**a.get("source", {}), "mock": False},
        "sources": order_sources([{k: (cut_text(v, 160) if isinstance(v, str) else v) for k, v in x.items() if k in RAG_SOURCE_KEYS} for x in a.get("sources", [])[:5]])[0],
    }
    if tool == "search_text" and not a.get("speak") and not a.get("table"):
        out.update(open_question=True, gaps=[OPEN_QUESTION], offer=offer)
    for k in ("scenario", "for_scenario", "level"):
        if a.get(k):
            out[k] = a[k]
    if a.get("level_oxygen_rich_flames"):
        out["coverage_note"] = {"label": "Oxygen-rich flames (burner stream, not the atmosphere)", "level": a["level_oxygen_rich_flames"]}
    if a.get("nearest"):
        out["nearest"] = a["nearest"]
    rk = to_ranking(a)
    if rk:
        out["ranking"] = rk
    return fit(out, f"answer {tool}")


# ───────────────────────────── what the model gets ─────────────────────────────
# Lines that must never be lost when the voice says only the first 3 (4) speak lines: the "No ... in the PSI data" sentence,
# "nothing is ranked", "not supported by the PSI data", "not in the data" (amount of an agent), "does not rate ..." (no best agent, no safety rating).
MANDATORY = ("does not set a single safe or dangerous oxygen level", "nothing is ranked", "not supported by the PSI data", "is not in the data", "does not rate", "not the spacesuit atmosphere")


def caveat_lines(speak: list[str]) -> list[str]:
    return [x for x in speak if str(x).startswith("No ") or any(m in str(x) for m in MANDATORY)]


def spoken_lines(a: dict) -> int:
    """3 sentences for the voice, 4 for a spacesuit answer (decisions Round 1 item 8)."""
    return 4 if "spacesuit" in (a.get("scenario"), a.get("for_scenario")) else 3


def matched(a: dict) -> bool:
    if a.get("tool") == "search_text":
        return not (a.get("speak") or [""])[0].startswith("No passage")
    return not any(str(g).startswith("unknown ") for g in a.get("gaps", []))


def to_model(a: dict) -> dict:
    """Small payload for the voice model: never the table, charts or cards."""
    ok = matched(a)
    speak = list(a.get("speak", []))
    if a.get("tool") == "search_text":  # Round 5 item 5.1: with two or more card lines, only the cards are spoken; document lines stay on screen
        n_cards = sum(1 for r in (a.get("table") or {}).get("rows", []) if r.get("kind") == "card")
        if n_cards >= 2:
            speak = speak[:n_cards]
    full = speak
    if a.get("tool") == "rank_materials" and speak and "nothing is ranked" in str(speak[0]):
        speak = speak[:2]            # Round 10 §10.7 item 5: "nothing is ranked" + "what they did measure"; the voice never reads one material's value (they stay on screen)
    prefix = speak[: spoken_lines(a)]
    pulled = [x for x in caveat_lines(full) if x not in prefix]  # a mandatory caveat beyond the prefix is pulled forward, never dropped
    out = {
        "status": "shown" if ok else "not_matched",
        "matched": ok,
        "speak": prefix + pulled,
    }
    if a.get("gaps"):
        out["first_gap"] = a["gaps"][0]
    for k in ("level", "level_oxygen_rich_flames"):
        if a.get(k):
            out[k if k != "level" else "coverage"] = a[k]
    if a.get("nearest"):
        out["nearest"] = a["nearest"]
    if a.get("tool") == "rank_investigations" and a.get("ranking"):
        out["top"] = [r["name"] for r in a["ranking"] if r.get("rank")][:3]
    if a.get("sources"):                      # the voice may say once that the sources are on the screen; it never gets the excerpts
        out["sources"] = [{"n": x["n"], "label": x["label"], "title": x.get("title"), "page": x.get("page")} for x in a["sources"][:4]]
    return out


# ───────────────────────────── ask_sources (the scoped RAG) ─────────────────────────────
RAG_SOURCE_KEYS = ("n", "label", "kind", "type", "title", "page", "section", "link", "link_kind", "psis", "evidence", "quote", "doc_id", "viewable")


def rag_to_answer(r: dict, pillar: str | None = None, offer: dict | None = None) -> dict:
    """answer.show packet for an ask_sources result: the question, the spoken lines, and the sources (numbered like the superscripts)."""
    sources, refs = order_sources([{k: (cut_text(v, 160) if isinstance(v, str) else v) for k, v in s.items() if k in RAG_SOURCE_KEYS} for s in r.get("sources", [])[:5]], r.get("speak_refs", []))
    return fit({
        "request_id": r["request_id"], "tool": "ask_sources", "metric": "ask_sources", "pillar": pillar, "question": r["question"], "outcome": r.get("outcome"),
        "speak": [cut_text(x, 320) for x in r.get("speak", [])[:3]], "speak_refs": (refs or [])[:3], "sources": sources,
        "clarify": r.get("clarify"), "level": None, "coverage_note": None, "kpis": [], "charts": [], "table": None, "cards": [], "gaps": [],
        **({"open_question": True, "gaps": [OPEN_QUESTION], "offer": offer} if r.get("status") == "not_found" or (not r.get("speak") and r.get("status") != "clarify") else {}),
    }, "ask_sources answer")


def rag_to_model(r: dict, next_offer: str | None = None) -> dict:
    """What Gemini gets: the lines to say, how many sources, and whether it is covered. Never the excerpts."""
    st = r["status"]
    m = {"status": st, "matched": st in ("ok", "fallback"), "speak": list(r.get("speak", []))[:3], "sources": [{"n": s["n"], "label": s["label"], "title": s.get("title"), "page": s.get("page")} for s in r.get("sources", [])[:5]]}
    if st == "clarify":
        m["clarify"] = r["clarify"]
        m["reply_guidance"] = "Ask ONLY this question, in your own words, naming the options. Do not answer. Ask it once."
    elif st in ("ok", "fallback"):
        m["reply_guidance"] = ("Say these speak lines in your own words, keep every number and name exactly, then say once that the sources are on the screen" + (" and end with next_offer." if next_offer else ".") + " Add nothing that is not in speak.")
        if next_offer:
            m["next_offer"] = next_offer
    else:
        m["not_covered"] = True
        m["reply_guidance"] = "Say that this is not covered in the PSI data or papers (an open question), then offer one topic from the four. Do not guess."
    return m


# ---------------------------------------------------------------- "Your conditions" panel (Round 11): flameo nearest_tests -> what the screen gets
CONDITIONS_ROWS = 8


def to_conditions(a: dict, source: str | None = None) -> dict:
    """GET /api/nearest: the flameo `nearest_tests` answer, trimmed. Selects only; every number (counts, psi, kPa, partial pressure and its formula) is flameo's."""
    t = a.get("table") or {"rows": []}
    rows = []
    for r in t["rows"][:CONDITIONS_ROWS]:
        rows.append({"investigation": r.get("investigation"), "test": r.get("test"), "material": r.get("material"), "o2_pct": r.get("o2_pct"), "p_psi": r.get("p_kpa"), "p_kpa": (round(r["p_kpa__kpa"], 1) if isinstance(r.get("p_kpa__kpa"), (int, float)) else r.get("p_kpa__kpa")),
                     "outcome": r.get("outcome"), "flight": r.get("flight")})
    return {
        "conditions": a.get("conditions"), "source": source,
        "n_near": a.get("n_near"), "n_psis": a.get("n_psis"), "n_spread": a.get("n_spread"), "n_flight": a.get("n_flight"),
        "speak": list(a.get("speak", []))[:2], "gaps": [cut_text(g, 200) for g in a.get("gaps", [])[:3]],
        "po2": a.get("po2"), "ranges": a.get("ranges"), "scenarios": a.get("scenarios", []), "markers": a.get("markers", []),
        "map_points": a.get("map_points", []), "spread_points": a.get("spread_points", []), "nearest_points": a.get("nearest_points", []),
        "rows": rows, "rows_total": len(t["rows"]), "rows_limit_note": f"{len(rows)} of {a.get('n_near')} tests" if (a.get("n_near") or 0) > len(rows) else None,
    }
