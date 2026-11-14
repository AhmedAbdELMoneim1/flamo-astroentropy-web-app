"""Spoken numbers must come from the tool (Round 10 §10.7 item 1). The voice once said "about 21 percent at 14.7 psi" from memory: 14.7 was in no speak line.
`unsupported(spoken, allowed)` returns the numbers the voice said that no allowed text (tool lines, notification facts, the astronaut's own words) contains.
Arabic-Indic digits are normalised; number words count only before a unit or a counted noun ("twenty one percent")."""
from __future__ import annotations

import re

_DIG = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
_UNITS = r"(?:percent|psi|psia|kilopascals?|kpa|atm|seconds?|minutes?|millimeters?|centimeters?|meters?|nanometers?|micrometers?|degrees|tests?|psis|investigations?|findings?|papers?|pages?|points?)"
_ONES = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
         "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19}
_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}
_WORDNUM = re.compile(r"\b((?:(?:" + "|".join(_TENS) + r")(?:[\s\-]+(?:" + "|".join(k for k in _ONES if _ONES[k] < 10 and k != "zero") + r"))?|" + "|".join(_ONES) + r")(?:\s+hundred)?)\s+" + _UNITS + r"\b", re.I)
_NUM = re.compile(r"(?<![\w.])\d+(?:[.,]\d+)*")


def _word_value(w: str) -> int:
    parts = re.split(r"[\s\-]+", w.lower())
    v = 0
    for p in parts:
        v = v * 100 if p == "hundred" and v else v + (_TENS.get(p) or _ONES.get(p) or 0)
    return v


def numbers(text: str | None) -> set[str]:
    t = (text or "").translate(_DIG)
    out = {n.replace(",", "").rstrip(".") for n in _NUM.findall(t)}
    out |= {str(_word_value(m.group(1))) for m in _WORDNUM.finditer(t)}
    return out


def unsupported(spoken: str, allowed: list[str] | str) -> set[str]:
    """Numbers in `spoken` that appear in none of the allowed texts."""
    ok: set[str] = set()
    for a in ([allowed] if isinstance(allowed, str) else allowed):
        ok |= numbers(a)
    return numbers(spoken) - ok
