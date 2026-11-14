"""When is it an emergency? (Round 10 §10.7 items 2 and 3.) Deterministic, English and Arabic, so it does not depend on Gemini's judgement.

  now          a fire / smoke / burning smell reported as happening now ("I smell burning plastic", "there's smoke from the rack", "fire in the galley")
  ambiguous    "what should I do if I smell burning plastic?": ask once "Is there a fire right now?"
  hypothetical a question about fire ("what should I do if a fire happens inside the suit?", "what happens if ...", "how do I ...")
  clear        "there is no fire", "false alarm", "it's out", "I was only asking"
Banner steps come from a per-location table (cabin / suit) in the language of the chat; no source gives suit steps, so the suit banner is short.
"""

from __future__ import annotations

import re

AR = re.compile(r"[؀-ۿ]")
I = re.I

_FIRST_PERSON_NOW = re.compile(r"(?<!\bif )\bI(?:'m| am)?\s+(?:can\s+)?(?:smell|smelling|see|seeing|hear|hearing|notice|noticed)\b", I)
_IF_I = re.compile(r"\bif\s+i\s+(?:smell|see|hear|notice)\b", I)
_HYP = re.compile(r"\b(?:what\s+(?:should|do|would|can|could|will)\s+(?:i|we|you|one)(?:\s+do)?|what\s+happens|what\s+if|how\s+(?:do|does|should|would|can|could)\b|why\s+(?:do|does)\b|can\s+i\b|could\s+i\b|should\s+i\b|is\s+it\s+(?:safe|ok)|if\s+(?:a|the|there\s+(?:is|was|were|are)|there's|some)\b|in\s+case\s+of|when\s+(?:a|there)\s+(?:is\s+)?(?:fire|smoke))", I)
_NOW = re.compile(r"(?:\bthere(?:'s|\s+is|\s+are)\s+(?:a\s+)?(?:fire|smoke|burning|flames?|sparks?)\b|\b(?:fire|smoke|flames?|sparks?)\s+(?:in|on|at|from|near|coming|inside)\b|\b(?:is|are)\s+(?:on\s+fire|smoking|burning|overheating)\b|\boverheating\b|\bsmoke\b.*\bcoming\b|\bsomething\s+is\s+burning\b|\bburning\s+(?:smell|plastic|odor|odour)\b|\bon\s+fire\b)", I)
_CLEAR = re.compile(r"(?:\bno\s+(?:fire|emergency|smoke)\b|\bthere\s+is\s+no\s+fire\b|\bfalse\s+alarm\b|\b(?:it|the\s+fire)(?:'s|\s+is|\s+has\s+been)\s+(?:out|over|gone|extinguished|put\s+out)\b|\bfire\s+is\s+out\b|\bi\s+was\s+(?:only|just)\s+asking\b|\bjust\s+asking\b|\ball\s+clear\b|\bnot\s+a\s+real\b|\bnever\s*mind\b)", I)

_AR_HYP = re.compile(r"(?:^|\s)(?:ماذا|ايه|إيه|ما\s+هو|كيف|لماذا|ليه)\b.*|\b(?:لو|إذا|اذا|في\s+حالة)\b")
_AR_NOW = re.compile(r"(?:(?:في|فيه|عندي|يوجد|شايف|أرى|ارى|أشم|اشم|شامم|أشمّ)\s+(?:حريق|دخان|نار|رائحة\s+حرق|رائحة\s+احتراق)|حريق\s+(?:في|داخل)|(?:ي|ت)حترق|سخونة\s+زائدة)")
_AR_IF_I = re.compile(r"(?:لو|إذا|اذا)\s+(?:شممت|شميت|رأيت|شفت|سمعت)")
_AR_CLEAR = re.compile(r"(?:لا\s+يوجد\s+حريق|مفيش\s+حريق|مافي\s+حريق|إنذار\s+كاذب|انذار\s+كاذب|انطفأ|انطفت|كنت\s+أسأل\s+فقط|كنت\s+بسأل\s+بس|بس\s+بسأل)")


def is_arabic(text: str | None) -> bool:
    return bool(text and len(AR.findall(text)) >= 3)


def classify(text: str | None) -> str:
    """'clear' | 'now' | 'ambiguous' | 'hypothetical' | 'unknown'."""
    t = (text or "").strip()
    if not t:
        return "unknown"
    if _CLEAR.search(t) or _AR_CLEAR.search(t):
        return "clear"
    if is_arabic(t):
        if _AR_IF_I.search(t):
            return "ambiguous"
        if _AR_HYP.search(t) and not re.search(r"(?:^|\s)(?:في|فيه)\s+(?:حريق|دخان)", t):
            return "hypothetical"
        return "now" if _AR_NOW.search(t) else "unknown"
    if _FIRST_PERSON_NOW.search(t):
        return "now"
    if _IF_I.search(t):
        return "ambiguous"
    if _HYP.search(t):
        return "hypothetical"
    return "now" if _NOW.search(t) else "unknown"


# ── banner text: per location and language ───────────────────────────────────────
CABIN_EN = ["Alert the crew and ground control", "Isolate power to the affected equipment", "Stop ventilation to the affected area", "Put on protective breathing equipment",
            "Use the extinguisher following your mission fire procedure"]
CABIN_AR = ["نبّه الطاقم ومركز التحكم الأرضي", "اعزل الطاقة عن الجهاز المتأثر", "أوقف التهوية عن المنطقة المتأثرة", "ارتدِ معدات التنفس الواقية", "استخدم طفاية الحريق وفق إجراء الحريق الخاص بالمهمة"]
SUIT_EN = ["Alert the crew and ground control", "Follow your EVA emergency procedure"]       # no source gives suit-specific steps: nothing is invented
SUIT_AR = ["نبّه الطاقم ومركز التحكم الأرضي", "اتبع إجراء الطوارئ الخاص بالسير في الفضاء"]
FOOTER = {"en": "Follow your mission fire procedure.", "ar": "اتبع إجراء الحريق الخاص بالمهمة."}


def location_of(*texts: str | None) -> str:
    return "suit" if re.search(r"\bsuit\b|\bEVA\b|spacesuit|بدلة|بدله", " ".join(t or "" for t in texts), I) else "cabin"


def banner(situation: str | None, transcript: str | None) -> dict:
    ar = is_arabic(transcript) or is_arabic(situation)
    loc = location_of(situation, transcript)
    steps = (SUIT_AR if ar else SUIT_EN) if loc == "suit" else (CABIN_AR if ar else CABIN_EN)
    title = (situation or ("حريق محتمل" if ar else "Possible fire"))[:90]
    return {"level": "emergency", "title": title, "steps": steps, "location": loc, "lang": "ar" if ar else "en", "footer": FOOTER["ar" if ar else "en"]}
