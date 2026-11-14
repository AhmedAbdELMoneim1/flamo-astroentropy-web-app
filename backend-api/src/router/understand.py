"""Step 1 of the router (Round 14 §14.1): what is being asked, with no model.

entities: psis, material, family, field(s), scenario, o2, pressure_psi, threshold (above / below)
intent:   an ordered list; the first is the primary. The context fills "here / this / it / yes".
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from src import conditions as C
from src import flameo  # noqa: F401  (puts the vendored flameo_tools on the path)
from src.router.session import Session
from flameo_tools.learn import find_term

FIELD_WORDS = [
    (r"\b(?:oxygen|o2|o₂)\b", "oxygen"), (r"\bpressures?\b", "pressure"),
    (r"\b(?:flow(?: speed| velocity| rate)?|duct velocity|air ?speed|air ?flow|velocity)\b", "flow speed"),
    (r"\b(?:flame )?spread(?:ing)?(?: rate)?\b|\bspreads\b", "spread rate"), (r"\bthick(?:ness)?\b|\bthin(?:ner)?\b", "thickness"),
    (r"\bwidth\b|\bwide\b|\bnarrow(?:er)?\b", "width"), (r"\bparticle size\b|\bsmoke particle", "particle size"),
]
FAMILY = [("fabric", r"\bfabrics?\b|\bcloth(?:es|ing)?\b|\btextiles?\b"), ("plastic", r"\bplastics?\b")]
MATERIAL_WORDS = [("silicone", r"\bsilicon(?:e|es)?\b"), ("Teflon", r"\bteflon\b|\bptfe\b"), ("Kapton", r"\bkapton\b|\bpolyimide\b"), ("PMMA", r"\bpmma\b|\bacrylic\b|\bplexi\w*"),
                  ("SIBAL", r"\bsibal\b|\bcotton[- ]?fib\w+\b"), ("Nomex", r"\bnomex\b"), ("wax", r"\bwax\b|\bcandles?\b"), ("Lampwick", r"\blamp ?wick\b")]
SCENARIO = [("moon_base", r"\b(?:moon ?base|lunar|habitat|base(?: env\w*| atmosphere)?|moon)\b"), ("spacesuit", r"\b(?:space ?suits?|suits?|eva|spacewalk)\b"),
            ("iss", r"\b(?:iss|international space station|space ?station|space ?craft|cabin|craft)\b")]
TOPIC = [("detection", r"\bsmoke\b|\baerosol\w*|\bdetect\w*|\bparticles?\b|\bsoot\b"), ("suppression", r"\bsuppress\w*|\bextinguish\w*|\bco2\b|\bhelium\b|\bputting out\b"),
         ("prevention", r"\bignit\w*|\bprevent\w*"), ("flammability", r"\bflammab\w*|\bflame spread\b|\bspreads?\b|\bburn\w*|\bflame shape\b|\bcool flames?\b")]
PILLAR_WORDS = [("prevention", r"\bprevention\b|\bmaterials?\b|\bignition\b"), ("flammability", r"\bflammability\b|\bflame spread\b|\bfire behavio\w+\b"), ("detection", r"\bdetection\b|\bsmoke\b"), ("suppression", r"\bsuppression\b")]
PRONOUN = re.compile(r"\b(?:here|there(?!\s+(?:is|are|was|were|be|will))|it|them|this (?:experiment|experment|investigation|psi|one|instrument)|that (?:experiment|investigation|one)|these (?:samples|tests))\b", re.I)
CONFIRM = re.compile(r"^\s*(?:yes|yeah|yep|yup|ok(?:ay)?|sure|please|go on|go ahead|continue|show me|show it|do it|that one)\b[\s,.!?a-z]{0,24}$", re.I)
ORDINAL = [(r"\b(?:first|1st|one)\b", 0), (r"\b(?:second|2nd|two)\b", 1), (r"\b(?:third|3rd|three)\b", 2)]

INTENT_RULES: list[tuple[str, str]] = [
    ("navigate", r"\b(?:go back|back to|go to|let us go|let's go|open|show me the (?:view|dashboard)|switch to|take me to)\b"),
    ("compare", r"\bcompar\w+\b|\bdifference between\b|\bdiffer\b"),
    ("versus", r"\bversus\b|\bvs\.?\b"),
    ("ranges", r"\b(?:do you have|do u have|u don'?t have|you don'?t have|have you|is there any|are there any|how many)\b|\b(?:max(?:imum)?|min(?:imum)?|range|ranges|highest|lowest|largest|smallest|above|below|greater than|less than|more than|(?:over|under)\s+\d|exceed\w*|beyond)\b|[<>]\s*\d"),
    ("rank_materials", r"\b(?:most|least|safest|worst|fastest|slowest)\b[^.?]*\b(?:dangerous|flammable|hazardous|burn\w*|spread\w*)\b[^.?]*\bmaterial|\bwhich material\b[^.?]*\b(?:most|least|safest|worst|fastest)\b"),
    ("materials", r"\b(?:what|which|list|name|show)\b[^.?]*\b(?:materials?|matirials?|fabrics?|plastics?)\b[^.?]*\b(?:cover|covered|have|use|burn|burned|tested|in the data|there|here)\b|\bmaterials? (?:covered|do you|u cover)\b|\b(?:what|which)'?s? (?:materials?|matirials?)\b|\bmaterial tests\b|\bwhat materials\b"),
    ("find_tests", r"\btests? (?:with|under|of|on|using|for)\b|\bshow (?:me )?(?:the )?tests?\b|\bis (?:there )?(?:any )?\w+ (?:there|in the data|tested)\b|\bwhat'?s? tests\b|\btell me if \w+ is there\b|\bis \w+ (?:material )?there\b"),
    ("gaps", r"\bmars\b|\bpartial gravity\b|\blunar gravity\b"),
    ("offtopic", r"\bjokes?\b|\bweather\b|\bsing\b|\bsongs?\b|\bfootball\b|\bpoem\b"),
    ("coverage", r"\bnormal\b[^.?]*\b(?:oxygen|pressure)\b|\b(?:usual|typical|standard)\b[^.?]*\b(?:oxygen|pressure)\b"),
    ("passage", r"\b(?:passage|paragraph|excerpt|quote|text about|find the)\b"),
    ("danger", r"\boxygen (?:levels?|concentrations?|limits?)\b[^.?]*\b(?:flames?|fire|burn\w*|steady)\b|\b(?:flames?|fire)\b[^.?]*\boxygen (?:levels?|concentrations?)\b|\b(?:danger\w*|safe|safety|hazard\w*|risky|risk|how (?:bad|much oxygen))\b"),
    ("coverage", r"\b(?:what(?:'s| is| does)? (?:your |ur |the )?(?:data )?cover\w*|what do you (?:have|cover)|what (?:data|do u cover)|what('s| is) u cover)\b"),
    ("effect", r"\b(?:does|do|will|would|is|are)\b[^.?]*\b(?:affect|faster|slower|fastest|slowest|more|less|higher|lower|bigger|smaller|depend|matter|change|differ)\b|\bfastest\b|\bslowest\b|\baffects?\b"),
    ("rank", r"\b(?:rank\w*|best|most (?:relevant|important)|top)\b"),
    ("why", r"\b(?:why|how (?:come|does|do|did|is|are|were|was|can|could)|explain|what causes|what happens)\b"),
    ("papers", r"\bpapers?\b|\bpublications?\b|\bstud(?:y|ies)\b|\bliterature\b"),
    ("procedure", r"\bwhat should i do\b|\bwhat do i do\b|\bprocedure\b"),
    ("investigation", r"\b(?:what is|what's|tell me about|scope in|scope to|about|variables|what did)\b"),
]


TEST_ID = re.compile(r"(?<![A-Za-z0-9])(\d{4,6}[A-Za-z]\d{1,2})(?![A-Za-z0-9])")
BARE_PCT = re.compile(r"(?<![A-Za-z\d.])(\d{1,3}(?:\.\d+)?)\s*(?:%|percent(?:age)?)(?!\s*(?:of the (?:tests|data)))", re.I)
MEAN_RX = re.compile(r"\b(?:mean|means|meaning|dangerous|danger|dangers|safe|safety|hazard\w*|risky|risk|ok|okay|like|happens?|bad)\b", re.I)
DANGER_RX = re.compile(r"\b(?:dangerous|danger|safe|safety|hazard\w*|risky|risk|bad)\b", re.I)
EXPLAIN_RX = re.compile(r"\b(?:what(?:'s|s| is| are| does| do| did)?|whats|define|explain|meaning of|mean|means|tell me about|what about)\b", re.I)
LIST_REF = re.compile(r"\b(?:they|them|those|these|the first(?: one)?|first one|the second(?: one)?|second one|the third(?: one)?|third one|the best of them|best of them|top one|a random one|random one|one of them|each of them|all of them|the last one)\b", re.I)
PAPER_ASK = re.compile(r"\b(?:papers?|publications?|literature)\b", re.I)
PAPER_SAY = re.compile(r"\b(?:say|says|said|report|reports|reported|find|found|show|shows|conclude\w*|claim\w*)\b", re.I)
NEW_TYPES = ("explain", "interpret", "test", "compare_tests", "nearest", "papers")
DATA_WORDS = re.compile(r"\b(?:tests?|data|cover(?:s|ed)?|materials?|tested|range|ranges|investigations?|experiments?|how many|database)\b", re.I)
SKIP_EXPLAIN_INTENTS = {"ranges", "materials", "find_tests", "coverage", "navigate", "compare", "gaps", "offtopic", "procedure", "rank_materials", "papers", "rank", "passage"}


@dataclass
class Understanding:
    text: str
    psis: list = field(default_factory=list)
    material: str | None = None
    family: str | None = None
    fields: list = field(default_factory=list)
    scenario: str | None = None
    scenario_strict: str | None = None
    o2: float | None = None
    pressure_psi: float | None = None
    above: float | None = None
    below: float | None = None
    topic: str | None = None
    pillar: str | None = None
    outcome: str | None = None                                     # Round 16: a Saffire outcome question (did_not_burn, not_ignited, burned_completely, anchored)
    saffire_family: str | None = None                              # Round 16: "saffire" named without a flight
    umbrella: str | None = None                                    # "fire_safety": all pillars (Round 16)
    go_back: bool = False
    intents: list = field(default_factory=list)
    confirm: bool = False
    pending_choice: int | None = None
    context_used: dict = field(default_factory=dict)
    # Round 15
    qtype: str = "effect"                      # one of the 12 question types (llm_understand.QTYPES)
    qconf: float = 0.5
    alt_types: list = field(default_factory=list)
    by: str = "rules"                          # who typed it: rules | model
    term: str | None = None                    # the concept asked about (explain)
    test_ids: list = field(default_factory=list)
    list_ref: dict | None = None               # {"mode": all | first | nth | random | best, "index": n, "kind", "items": [...]}
    also_interpret: bool = False               # a pasted table row with "danger?": the test and what its conditions mean
    paper_topic: str | None = None
    model: dict | None = None                  # what the model returned (validated), for the log

    @property
    def primary(self) -> str:
        return self.intents[0] if self.intents else "ask"

    def entities(self) -> dict:
        return {k: v for k, v in {"psi": self.psis or None, "material": self.material, "family": self.family, "fields": self.fields or None, "scenario": self.scenario,
                                  "o2": self.o2, "pressure_psi": self.pressure_psi, "above": self.above, "below": self.below, "test_ids": self.test_ids or None}.items() if v not in (None, [], "")}

    def to_dict(self) -> dict:
        return {"entities": self.entities(), "intents": self.intents, "confirm": self.confirm, "context_used": self.context_used, "pending_choice": self.pending_choice,
                "understanding": {"by": self.by, "type": self.qtype, "entities": self.entities() | ({"test_ids": self.test_ids} if self.test_ids else {}) | ({"term": self.term} if self.term else {}), "confidence": round(self.qconf, 2),
                                  **({"alt_types": self.alt_types} if self.alt_types else {}), **({"model": self.model} if self.model else {})}}


def _threshold(text: str, field_word: str | None):
    m = re.search(r"\b(?:above|over|more than|greater than|exceed\w*|beyond)\s*(\d+(?:\.\d+)?)|>\s*(\d+(?:\.\d+)?)", text, re.I)
    above = float(next(g for g in m.groups() if g)) if m else None
    m = re.search(r"\b(?:below|under|less than|lower than)\s*(\d+(?:\.\d+)?)|<\s*(\d+(?:\.\d+)?)", text, re.I)
    below = float(next(g for g in m.groups() if g)) if m else None
    return above, below


SAFFIRE_PSIS = {"PSI-98", "PSI-99", "PSI-100"}
OUTCOME_RULES = [("not_ignited", r"\b(?:did ?n[o']?t|didn['\u2019]t|never|fail\w* to|not)\s+(?:\w+\s+)?ignit\w*|\bnot ignited\b"),
                 ("burned_completely", r"\bburn(?:ed|t)?\s+(?:completely|entirely|fully)\b|\bcompletely\s+(?:burn\w*|consumed)\b"),
                 ("anchored", r"\banchored\b"),
                 ("did_not_burn", r"\b(?:did ?n[o']?t|didn['\u2019]t|never|not|no)\s+(?:\w+\s+)?(?:burn|spread)\w*|\b(?:did ?n[o']?t|didn['\u2019]t)\b[^.?]*\b(?:burn|spread)\b")]      # Round 16: "which Saffire-II materials did not burn in space"
_NUM = {"1": "i", "one": "i", "i": "i", "2": "ii", "two": "ii", "ii": "ii", "3": "iii", "three": "iii", "iii": "iii"}
SAFFIRE_ALIASES: list[tuple[str, object]] = [
    (r"\b(?:spacecraft fire (?:safety )?experiment|saffire experiment|cygnus fire experiment)[\s-]*(1|one|2|two|3|three|iii|ii|i)(?![\w'’-])", lambda m: "saffire-" + _NUM[m.group(1)]),
    (r"\bspacecraft fire (?:safety )?experiments?\b|\bspacecraft fire safety demonstration\b|\bsfs demo\b|\bcygnus fire experiments?\b|\bsaffire experiments?\b", "saffire"),
]
FIRE_SAFETY = re.compile(r"\bfire[\s-]safety\b|\bspacecraft fires?\b|\bfires? (?:in|on|aboard) (?:a )?(?:spacecraft|space ?craft|space station|the iss)\b", re.I)    # Round 16 S-6: an umbrella over all four pillars, tier A leads


def understand(text: str, session: Session, ext, screen_scenario: str | None = None) -> Understanding:
    """Entities + intents + context. `ext` is the PSI/material extractor (src.paper_rag.extract.Extractor)."""
    t = (text or "").strip()
    low = t.lower()
    u = Understanding(text=t)
    low_n = low
    for rx, rep in SAFFIRE_ALIASES:                                                # Round 16 S-6: the other names of Saffire
        low_n = re.sub(rx, rep, low_n)
    norm = re.sub(r"\b(saffire|bass)[\s-]*(1|one)\b", r"\1-i", low_n)
    norm = re.sub(r"\bsaffire[\s-]*i(?![\w'’-])(?!\s+(?:want|think|mean|have|am|was|do|see|need|would|can|will|am|know|guess)\b)", "saffire-i", norm)       # "Saffire I" (roman one)
    norm = re.sub(r"\b(saffire|bass)[\s-]*(2|two|ii)\b", r"\1-ii", norm)
    norm = re.sub(r"\b(saffire)[\s-]*(3|three|iii)\b", r"\1-iii", norm)
    fixed = norm.replace("saffire-iii", "Saffire-III").replace("saffire-ii", "Saffire-II").replace("saffire-i", "Saffire-I").replace("bass-ii", "BASS-II").replace("bass-i", "BASS-I")
    fixed = re.sub(r"(?:(?<=\bis )|(?<=\babout )|(?<=\bof )|(?<=\bcompare )|(?<=\bvs )|(?<=\band )|(?<=\bwith )|(?<=\bin ))(bass|flex|spice|slice|daft)\b", lambda m: m.group(1).upper(), fixed)
    u.psis = (ext.psis(fixed) or ext.psis(t)) if ext else []
    if ext and "PSI-102" not in u.psis and re.search(r"\bSAME\b(?=\s+(?:experiment|investigation|data|smoke|aerosol|tests?))", t):
        u.psis.append("PSI-102")                           # "the SAME experiment": the upper-case acronym is the investigation
    for fam, rx in FAMILY:
        if re.search(rx, low):
            u.family = fam
    for name, rx in MATERIAL_WORDS:
        if re.search(rx, low):
            u.material = name
            break
    if not u.material and ext:
        u.material = None if u.family else None
    named_psi = bool(u.psis)
    if u.psis and set(u.psis) <= SAFFIRE_PSIS:                                    # Round 16: Saffire outcome questions and "What is Saffire?" (all three flights, short)
        for name, rx in OUTCOME_RULES:
            if re.search(rx, low_n):
                u.outcome = name
                break
        if not re.search(r"\bsaffire[\s-]*(?:1|2|3|i{1,3}|one|two|three)(?![\w'\u2019-])", norm) and not re.search(r"\bpsi[\s-]?\d+\b", low) and re.search(r"\bsaffire\b", norm):
            u.saffire_family = "saffire"
    u.fields = [name for rx, name in FIELD_WORDS if re.search(rx, low)]
    for sid, rx in SCENARIO:
        if re.search(rx, low):
            u.scenario = sid
            break
    u.scenario_strict = ext.scenario(t) if ext else None
    conds = C.parse(t)
    u.o2, u.pressure_psi = conds.get("oxygen_pct"), conds.get("pressure_psi")
    u.above, u.below = _threshold(low, None)
    # a number that is a threshold is not a stated condition ("above 25 percent oxygen")
    if (u.above is not None or u.below is not None) and u.o2 in (u.above, u.below):
        u.o2 = None
    # intents, in rule order (the first match is the primary one)
    if (CONFIRM.match(t) and len(t.split()) <= 4) or re.match(r"^\s*(?:yes|ok|okay)\b.*\b(?:data|behind it|details|show)\b", low) and len(t.split()) <= 8:
        u.confirm = True
    for name, rx in INTENT_RULES:
        if re.search(rx, low):
            u.intents.append(name)
    for pillar, rx in PILLAR_WORDS:
        if re.search(rx, low):
            u.pillar = pillar
            break
    if FIRE_SAFETY.search(low) and not u.scenario_strict and "navigate" not in u.intents:        # "fire safety" is not a danger question and not one pillar: rank every investigation (tier A leads)
        rest = FIRE_SAFETY.sub(" ", low)
        if not re.search(r"\b(?:dangerous|danger\w*|hazard\w*|risky|risk|safe)\b|oxygen", rest):
            u.intents = [i for i in u.intents if i != "danger"]
            if not u.psis:
                u.intents = [i for i in u.intents if i != "why"]
                u.pillar = None
                u.umbrella = "fire_safety"
                if "rank" not in u.intents:
                    u.intents.append("rank")
    u.go_back = bool(re.search(r"\b(?:go back|back to (?:the )?(?:last|previous)|can u back|can you go back|back to last)\b", low))
    for pillar, rx in TOPIC:
        if re.search(rx, low):
            u.topic = pillar
            break
    if "thickness" in u.fields or "width" in u.fields:
        if "ranges" not in u.intents and "effect" not in u.intents:
            u.intents.append("effect")                  # "thin vs thick": how a dimension changes the burning, not a range question
    if "versus" in u.intents:
        u.intents.remove("versus")
        if len(u.psis) >= 2:
            u.intents.insert(0, "compare")
        elif len(u.fields) >= 2 or u.fields and (u.family or u.material):
            u.intents.append("effect")                                              # "spread rate vs flow", "thin vs thick": how one quantity changes with the other
    if re.search(r"\bpsi[\s-]?\d+\b|\bscope\b", low) and not u.intents:
        u.intents.append("investigation")
    # context: "here / this / it / there" and a bare "yes"
    if not u.psis and PRONOUN.search(t) and session.psi and not u.scenario:
        u.psis, u.context_used["psi"] = [session.psi], session.psi
    if not u.psis and PRONOUN.search(t) and not session.psi and not u.scenario and screen_scenario:
        u.scenario, u.context_used["scenario"] = screen_scenario, screen_scenario
    if not u.psis and not u.scenario and u.fields and session.psi and re.search(r"\b(?:experiment|experment|investigation|psi)\b", low):
        u.psis, u.context_used["psi"] = [session.psi], session.psi
    if not u.material and not u.family and session.material and re.search(r"\b(?:it|them|those|these|that material|the same)\b", low):
        u.material, u.context_used["material"] = session.material, session.material
    if u.fields and re.search(r"\bcover(?:ed|s|age)?\b", low) and not (set(u.intents) & {"materials", "ranges", "navigate", "danger"}):
        u.intents.append("ranges")                         # "is o2 covered in 22 %?": a question about the data's range
    if "investigation" in u.intents and not named_psi and not re.search(r"\bvariables\b|\bpressure\b|\bflow\b", low):
        u.intents.remove("investigation")                                            # "what's ..." without a named investigation is just a question
    if (u.material or u.family) and re.search(r"\btests?\b", low) and not (set(u.intents) & {"find_tests", "materials", "effect", "why", "danger", "ranges", "navigate"}):
        u.intents.append("find_tests")
    if session.pending:                                   # the reply to a clarifying question
        idx = _choose(t, session.pending["options"])
        if idx is not None or "compare" in u.intents:
            u.pending_choice = idx if idx is not None else -1
    classify(u, t, low, session)
    return u


def _list_ref(low: str, session: Session) -> dict | None:
    """"they / them / the first one / the best of them / compare them / a random one" resolve against the list on screen."""
    if not session.rows or not session.rows.get("items"):
        return None
    m = LIST_REF.search(low)
    if not m:
        return None
    w = m.group(0).lower()
    mode, idx = "all", None
    if "random" in w:
        mode = "random"
    elif "first" in w or "top" in w:
        mode, idx = "nth", 0
    elif "second" in w:
        mode, idx = "nth", 1
    elif "third" in w:
        mode, idx = "nth", 2
    elif "last" in w:
        mode, idx = "nth", -1
    elif "best" in w:
        mode, idx = "nth", 0
    return {"mode": mode, "index": idx, "kind": session.rows["kind"], "items": session.rows["items"]}


def _fuzzy_term(low: str):
    """A typo'd concept word ("iginition", "extinguishment" mis-heard): the closest single-word glossary alias, only when it is very close."""
    import difflib

    from flameo_tools.learn import glossary
    idx = glossary()["index"]
    singles = [k for k in idx if " " not in k and len(k) >= 6]
    for w in re.findall(r"[a-z]{6,}", low):
        m = difflib.get_close_matches(w, singles, n=1, cutoff=0.84)
        if m:
            return idx[m[0]]
    return None


def classify(u: Understanding, t: str, low: str, session: Session) -> None:
    """The rules' question type (Round 15 §15.1 item 2): the fallback when the model is off, and the source of the entities the model may not override."""
    I = set(u.intents)
    u.test_ids = list(dict.fromkeys(m.upper() for m in TEST_ID.findall(t)))
    if not u.o2 and not (I & {"ranges"}) and u.above is None and u.below is None and not u.test_ids:
        m = BARE_PCT.search(t)
        if m and 0 < float(m.group(1)) <= 100 and not re.search(r"\b(?:flight|ground|of the tests)\b", low):
            u.o2 = float(m.group(1))                    # "tests in 40%": the oxygen level
    u.list_ref = _list_ref(low, session) if not (u.psis or u.test_ids or u.material or u.family) else None
    qt, conf, alts = "effect", 0.5, []
    mean = bool(re.search(r"\bmean(?:s|ing)?\b", low))
    term = (find_term(t) or _fuzzy_term(low)) if not (u.psis or u.test_ids or u.scenario) else None
    if mean and re.search(r"\bwhat (?:it|that|this) mean", low) and not (term or u.o2 is not None or u.psis or u.test_ids):
        if session.last_tool == "explain" and session.last_term:
            term = find_term(session.last_term)
            u.context_used["term"] = session.last_term
        elif session.last_conditions:
            u.o2, u.pressure_psi = session.last_conditions["o2"], session.last_conditions.get("pressure_psi")
            u.context_used["conditions"] = dict(session.last_conditions)
    if u.test_ids:
        if len(u.test_ids) >= 2 and ("compare" in I or "versus" in I or re.search(r"\b(?:and|vs|versus|with)\b", low)):
            qt, conf = "compare_tests", 0.95
        else:
            qt, conf = "test", 0.95
            u.also_interpret = bool(DANGER_RX.search(low) and (u.o2 is not None or u.pressure_psi is not None))
    elif "compare" in I and len(u.psis) >= 2:
        qt, conf = "compare_tests", 0.9
    elif PAPER_ASK.search(low) and not PAPER_SAY.search(low) and not (I & {"compare"}):
        qt, conf = "papers", 0.85
        m = re.search(r"\bpapers?\s+(?:on|about|for|of|in|regarding)\s+(?:the\s+)?([a-z][a-z\- ]{2,30}?)(?:\?|$|\s+(?:in|on|from)\b)", low)
        u.paper_topic = m.group(1).strip() if m and not u.psis else None
        if u.paper_topic and (u.paper_topic in ("it", "this", "that", "here", "them", "the data", "the sources", "sources")):
            u.paper_topic = None
        if re.search(r"\b(?:best|most|top|often|alot|a lot|appear\w*|which|biggest|main)\b", low):
            u.intents = [x for x in u.intents if x not in ("rank",)]
    elif re.match(r"^\W*(?:i said |no |i mean )?papers?\W*$", low):
        qt, conf = "papers", 0.9
    elif u.o2 is not None and not (I & {"ranges", "materials", "navigate"}) and MEAN_RX.search(low) and not DATA_WORDS.search(low):
        qt, conf = "interpret", 0.9 if (mean or DANGER_RX.search(low)) else 0.7
    elif u.o2 is not None and not (I & {"ranges", "materials", "navigate", "compare"}):
        qt, conf = "nearest", 0.85
    elif term and not (I & SKIP_EXPLAIN_INTENTS) and not (u.material or u.family) and EXPLAIN_RX.search(low) and (mean or not (I & {"effect", "why"})) and not (DATA_WORDS.search(low) and not mean):
        qt, conf, u.term = "explain", 0.9, term["term"]
        if len(re.findall(r"[a-z0-9]+", low)) <= 3 and not mean and not re.search(r"\bwhat\b|\bexplain\b|\bdefine\b", low):
            conf, alts = 0.5, ["catalogue"]
    elif term and len(re.findall(r"[a-z0-9]+", low)) <= 3 and not (I & SKIP_EXPLAIN_INTENTS) and not (u.material or u.family or u.fields and False):
        qt, conf, u.term, alts = "explain", 0.5, term["term"], ["catalogue"]                      # a bare word: the concept or the data on it?
    elif mean and not (u.psis or u.material or u.family) and re.search(r"\bwhat(?:'s|s| is| does| do)\b", low) and len(low.split()) <= 9 and not DATA_WORDS.search(low):
        m = re.search(r"what(?:'s|s| is| does| do)\s+(?:a |an |the )?(.{2,40}?)\s+mean", low) or re.search(r"mean(?:s|ing)?\s+(?:of\s+)?(?:a |an |the )?(.{2,40}?)(?:\?|$)", low)
        if m:
            qt, conf, u.term = "explain", 0.8, re.sub(r"[^a-z0-9 \-]", "", m.group(1)).strip()
    elif I & {"navigate", "offtopic"}:
        qt, conf = "navigation", 0.9
    elif "procedure" in I:
        qt, conf = "procedure", 0.9
    elif I & {"ranges", "materials", "find_tests", "coverage", "gaps", "rank_materials"}:
        qt, conf = "catalogue", 0.85
    elif "investigation" in I and u.psis and not (I & {"effect", "why"}):
        qt, conf = "catalogue", 0.8
    elif (u.material or u.family) and not (I & {"effect", "why", "danger", "papers"}):
        qt, conf = "catalogue", 0.7
    elif "rank" in I or re.search(r"\bmatter\w*\b|\bwhich (?:experiments?|investigations?)\b", low) and not u.psis:
        qt, conf = "ranking", 0.85
    elif I & {"effect", "why", "danger", "passage", "investigation"}:
        qt, conf = "effect", 0.8
    if u.list_ref and qt in ("effect", "catalogue", "ranking") and not (I & {"compare"}):
        qt, conf = "catalogue", 0.8
    u.qtype, u.qconf, u.alt_types = qt, conf, alts


def apply_model(u: Understanding, info: dict, ext) -> None:
    """Merge the model's answer (Round 15 §15.1 item 1). Entities are accepted only if they exist in the vocabulary and only where the rules found nothing;
    the type is taken when the model is sure (>= 0.6) and its prerequisites exist. Emergency and navigation stay with the rules."""
    out = (info or {}).get("out")
    if not out:
        u.model = {"used": False, "why": (info or {}).get("why", "")} if info else None
        return
    from src.router.llm_understand import MODEL_TYPES
    log: dict = {"by": info.get("by"), "key": info.get("key"), "ms": info.get("ms"), "raw_type": out.get("type"), "confidence": out.get("confidence")}
    try:
        conf = float(out.get("confidence"))
    except (TypeError, ValueError):
        conf = 0.0
    ok_fields = {n for _, n in FIELD_WORDS}
    acc: dict = {}
    if not u.psis and ext and isinstance(out.get("psi"), list):
        ps = [p for name in out["psi"][:3] if isinstance(name, str) for p in (ext.psis(name) or [])]
        if ps:
            u.psis, acc["psi"] = list(dict.fromkeys(ps)), list(dict.fromkeys(ps))
    if not u.material and isinstance(out.get("material"), str) and any(re.search(rx, out["material"], re.I) for _, rx in MATERIAL_WORDS):
        u.material = next(n for n, rx in MATERIAL_WORDS if re.search(rx, out["material"], re.I))
        acc["material"] = u.material
    if not u.family and out.get("family") in ("fabric", "plastic"):
        u.family = acc["family"] = out["family"]
    if not u.fields and isinstance(out.get("fields"), list):
        u.fields = acc["fields"] = [f for f in out["fields"] if f in ok_fields][:3]
    if not u.scenario and out.get("scenario") in ("iss", "moon_base", "spacesuit"):
        u.scenario = acc["scenario"] = out["scenario"]
    def num(x):
        try:
            return float(x) if not isinstance(x, bool) and x is not None else None
        except (TypeError, ValueError):
            return None
    o2m, pm = num(out.get("o2")), num(out.get("pressure_psi"))
    if u.o2 is None and o2m is not None and 0 < o2m <= 100:
        u.o2 = acc["o2"] = o2m
    if u.pressure_psi is None and pm is not None and 0 < pm < 100:
        u.pressure_psi = acc["pressure_psi"] = pm
    if not u.test_ids and isinstance(out.get("test_ids"), list):
        ids = [x.upper() for x in out["test_ids"] if isinstance(x, str) and TEST_ID.fullmatch(x.strip())]
        if ids:
            u.test_ids = acc["test_ids"] = ids
    if not u.term and isinstance(out.get("term"), str) and 2 <= len(out["term"]) <= 40:
        e = find_term(out["term"])
        u.term = acc["term"] = e["term"] if e else re.sub(r"[^A-Za-z0-9 \-]", "", out["term"]).strip().lower() or None
    t = out.get("type")
    need = {"explain": bool(u.term) and not u.psis, "interpret": u.o2 is not None, "test": bool(u.test_ids), "compare_tests": len(u.test_ids) >= 2 or len(u.psis) >= 2, "nearest": u.o2 is not None, "papers": True}
    if t in MODEL_TYPES and conf >= 0.6 and u.qtype not in ("navigation", "emergency", "procedure") and (t not in NEW_TYPES or need.get(t)):
        if t != u.qtype and not (u.qconf >= 0.9 and conf < 0.8):
            log["disagrees_with_rules"] = u.qtype
            u.qtype, u.qconf, u.by = t, conf, "model"
        else:
            u.qconf = max(u.qconf, conf) if t == u.qtype else u.qconf
            u.by = "model" if t == u.qtype else u.by
    elif t in MODEL_TYPES and conf < 0.6:
        u.qconf = min(u.qconf, conf)
        if out.get("alt_type") in MODEL_TYPES:
            u.alt_types = [out["alt_type"]]
    log["entities_added"] = acc
    u.model = log


def _choose(text: str, options: list) -> int | None:
    low = text.lower()
    for rx, i in ORDINAL:
        if re.search(rx, low) and i < len(options):
            return i
    best, bi = 0, None
    for i, o in enumerate(options):
        words = {w for w in re.findall(r"[a-z0-9\-]+", o["label"].lower()) if len(w) > 2 and w not in ("the", "and", "which", "psi")}
        score = sum(1 for w in words if re.search(r"(?<![a-z0-9])" + re.escape(w) + r"(?![a-z0-9])", low))
        if score > best:
            best, bi = score, i
    return bi
