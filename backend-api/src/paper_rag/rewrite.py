"""Query rewrite before retrieval (Round 10 §10.1 item 5b): a small synonym table adds the terms the papers use for the words people use.
Only the RETRIEVAL query changes (embedding + keyword); the composer and the log keep the question as asked."""
from __future__ import annotations

import re

RULES: list[tuple[re.Pattern, str]] = [(re.compile(p, re.I), add) for p, add in [
    (r"\b(?:flames?\s+(?:round|shape|spherical|ball)|round\s+flames?|shape\s+of\s+(?:a\s+)?flames?|why\s+are\s+flames?\s+(?:round|spherical))", "spherical flame shape buoyancy microgravity"),
    (r"\b(?:go(?:es)?\s+out|put\s+out|extinguish\w*|quench\w*)\b.*\b(?:micro\s?gravity|space|low\s+gravity)|\b(?:micro\s?gravity|space|low\s+gravity)\b.*\b(?:go(?:es)?\s+out|extinguish\w*|quench\w*)", "extinction quenching flame microgravity radiative"),
    (r"\bsmoke\s+particles?\b.*\b(?:bigger|larger|size)|\b(?:bigger|larger)\s+smoke", "smoke particle size low gravity settling"),
    (r"\b(?:burn|spread)s?\s+(?:faster|slower|quicker)", "flame spread rate oxygen microgravity"),
    (r"\bcandle\b", "candle flame microgravity buoyancy"),
    (r"\bwater(?:\s+mist)?\b.*\bfire\b|\buse\s+water\b", "water mist extinguish fire suppression"),
    (r"\bsmoke\s+detect\w*|\bdetectors?\b", "smoke detector microgravity particle size"),
    (r"\bcool\s+flames?\b", "cool flame low temperature chemistry"),
    (r"\bsoot\b", "soot volume fraction microgravity"),
]]


def rewrite(question: str) -> str:
    """The question plus the extra key terms of every rule that matches (each term once)."""
    extra: list[str] = []
    for rx, add in RULES:
        if rx.search(question):
            extra += [t for t in add.split() if t not in extra and t not in question.lower().split()]
    return f"{question} {' '.join(extra)}".strip() if extra else question
