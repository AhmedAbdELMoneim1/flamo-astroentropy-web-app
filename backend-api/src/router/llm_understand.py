"""Round 15 §15.1 item 1: the understanding model.

One small model call (Gemini Flash-Lite, then Groq; JSON; temperature 0; 0.6 s) classifies the question into one of the 12 question types and reads the entities.
The rules in understand.py stay as the fallback (no keys, a timeout, bad JSON, ROUTER_MODEL=0) and as the source of the names: the model's entities are accepted
only when they exist in the vocabulary (a PSI the data knows, a material word, a field, a scenario, a test-id shape, a glossary term). The model never decides an
emergency or a navigation: those stay with the rules.

Keys come from the existing KeyPools (the composer's); a key value is never printed or logged, only its index.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re

import httpx

logger = logging.getLogger("understand")
GEMINI_MODEL = "gemini-3.5-flash-lite"
GROQ_MODEL = "qwen/qwen3.8-27b"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
TIMEOUT_S = float(os.getenv("ROUTER_MODEL_TIMEOUT", "1.3"))      # measured on the free tier: Groq 0.3-1.5 s (p50 about 1.0 s), Gemini Flash-Lite 0.4-0.7 s when its quota is free
SURE = 0.85                                                      # the model is asked only when the rules are not sure (or the text is not English / is long)

QTYPES = ("emergency", "procedure", "explain", "interpret", "test", "compare_tests", "nearest", "catalogue", "papers", "effect", "ranking", "navigation")
MODEL_TYPES = tuple(t for t in QTYPES if t not in ("emergency", "navigation"))        # the rules own the safety-critical ones

SYSTEM = """You classify ONE question to a fire-safety copilot that answers from NASA microgravity combustion data (tests, findings, papers). Return JSON only.
Types:
- explain: what a concept or word means ("what is ignition", "what does spread rate mean")
- interpret: what an oxygen or pressure value means, or whether conditions are dangerous ("what does 18 percent oxygen mean")
- test: about one named test id ("tell me about test 19115A1", a pasted table row)
- compare_tests: compare two tests or two investigations
- nearest: tests near a value ("tests at 40 percent oxygen")
- catalogue: what materials, ranges or counts exist in the data
- papers: which papers or sources
- effect: does X change Y, why, how, what happens
- ranking: which experiments matter most
- procedure: what to do if a fire starts (hypothetical)
- emergency: a fire or smoke is happening right now
- navigation: go back, open a screen, off-topic chat
JSON: {"type":"...","confidence":0.0-1.0,"alt_type":null,"psi":[],"material":null,"family":null,"fields":[],"scenario":null,"o2":null,"pressure_psi":null,"test_ids":[],"term":null,"refers_to_list":false,"language":"en"}
fields is a subset of: oxygen, pressure, flow speed, spread rate, thickness, width, particle size. scenario is iss, moon_base or spacesuit. family is fabric or plastic.
Copy names, ids and numbers exactly from the question; never invent one; use null or [] when absent. The question may be in any language, with typos or speech errors."""


class Understander:
    def __init__(self, composer) -> None:
        self.c = composer

    async def _gemini(self, prompt: str) -> str:
        from google import genai
        from google.genai import types
        from src.paper_rag.keypool import is_quota_error
        lease = await self.c.gemini.acquire(units=1, tokens=700, timeout=0.2)
        self.last_key = self.c.gemini.label(lease.index)
        cl = self.c._clients.get(lease.index) or self.c._clients.setdefault(lease.index, genai.Client(api_key=lease.key))
        try:
            r = await cl.aio.models.generate_content(model=GEMINI_MODEL, contents=prompt, config=types.GenerateContentConfig(
                system_instruction=SYSTEM, temperature=0.0, max_output_tokens=300, response_mime_type="application/json"))
        except Exception as e:  # noqa: BLE001
            if is_quota_error(e):
                self.c.gemini.report_quota_error(lease, e)           # that key rests; the next call takes another
            raise
        return r.text or ""

    async def _groq(self, prompt: str) -> str:
        lease = await self.c.groq.acquire(units=1, tokens=700, timeout=0.2)
        self.last_key = self.c.groq.label(lease.index)
        r = await self.c.http.post(GROQ_URL, headers={"Authorization": f"Bearer {lease.key}"}, json={
            "model": GROQ_MODEL, "temperature": 0, "max_tokens": 300, "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}]})
        if r.status_code == 429:
            self.c.groq.report_quota_error(lease, httpx.HTTPStatusError("429", request=r.request, response=r))
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"] or ""

    @staticmethod
    def parse(raw: str) -> dict | None:
        m = re.search(r"\{.*\}", raw or "", re.S)
        try:
            d = json.loads(m.group(0)) if m else None
        except ValueError:
            return None
        return d if isinstance(d, dict) else None

    async def classify(self, text: str, ctx: dict | None = None, timeout: float = TIMEOUT_S) -> dict:
        """{"out": dict | None, "by": "gemini" | "groq" | None, "key": "gemini#4" | None, "ms": int, "why": str}. Never raises."""
        import time
        t0 = time.monotonic()
        prompt = (f"Context (the screen / the last answer): {json.dumps(ctx, ensure_ascii=False)}\n" if ctx else "") + f"Question: {text}"
        info = {"out": None, "by": None, "key": None, "ms": 0, "why": ""}
        providers = [(n, f) for n, f, p in (("gemini", self._gemini, self.c.gemini), ("groq", self._groq, self.c.groq)) if p is not None]
        deadline = t0 + timeout
        for i, (name, fn) in enumerate(providers):
            left = deadline - time.monotonic()
            if left < 0.15:
                info["why"] += f"{name}: no time left; "
                continue
            try:
                raw = await asyncio.wait_for(fn(prompt), timeout=left * (0.7 if i < len(providers) - 1 else 1))
                out = self.parse(raw)
                if out:
                    info.update(out=out, by=name, key=getattr(self, "last_key", None))
                    break
                info["why"] += f"{name}: bad JSON; "
            except Exception as e:  # noqa: BLE001
                info["why"] += f"{name}: {type(e).__name__}; "
        info["ms"] = round((time.monotonic() - t0) * 1000)
        return info


BG_SYSTEM = """Define ONE term for a student in a single plain sentence of at most 30 words, as general background on combustion or spacecraft fire safety.
No digits and no numbers, no claim about any data or experiment, never the words safe, unsafe, safest or dangerous. If you do not know the term, return an empty sentence.
Return JSON only: {"sentence": "..."}"""
BAD_BG = re.compile(r"\d|\b(?:safe|safer|safest|unsafe|dangerous|mars)\b", re.I)


async def _background(self, term: str, timeout: float = 1.2) -> str | None:
    """D15-1: one sentence of general background (labelled by the caller as "not from the PSI data"), no numbers; checked in code. None when the model is off or the sentence breaks a rule."""
    import time
    deadline = time.monotonic() + timeout
    for name, fn, pool in (("gemini", self._bg_gemini, self.c.gemini), ("groq", self._bg_groq, self.c.groq)):
        if pool is None or time.monotonic() > deadline - 0.2:
            continue
        try:
            raw = await asyncio.wait_for(fn(f"Term: {term}"), timeout=deadline - time.monotonic())
        except Exception:  # noqa: BLE001
            continue
        d = self.parse(raw) or {}
        sent = re.sub(r"\s+", " ", str(d.get("sentence", ""))).strip()
        if sent and len(sent.split()) <= 40 and not BAD_BG.search(sent):
            return sent
    return None


async def _bg_gemini(self, prompt: str) -> str:
    from google import genai
    from google.genai import types
    lease = await self.c.gemini.acquire(units=1, tokens=500, timeout=0.2)
    cl = self.c._clients.get(lease.index) or self.c._clients.setdefault(lease.index, genai.Client(api_key=lease.key))
    r = await cl.aio.models.generate_content(model=GEMINI_MODEL, contents=prompt, config=types.GenerateContentConfig(
        system_instruction=BG_SYSTEM, temperature=0.0, max_output_tokens=120, response_mime_type="application/json"))
    return r.text or ""


async def _bg_groq(self, prompt: str) -> str:
    lease = await self.c.groq.acquire(units=1, tokens=500, timeout=0.2)
    r = await self.c.http.post(GROQ_URL, headers={"Authorization": f"Bearer {lease.key}"}, json={
        "model": GROQ_MODEL, "temperature": 0, "max_tokens": 120, "response_format": {"type": "json_object"},
        "messages": [{"role": "system", "content": BG_SYSTEM}, {"role": "user", "content": prompt}]})
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"] or ""


Understander.background, Understander._bg_gemini, Understander._bg_groq = _background, _bg_gemini, _bg_groq

_U = None
_override = False


def set_understander(u) -> None:
    """Tests inject a fake (or None to switch the model off)."""
    global _U, _override
    _U, _override = u, True


def get() -> Understander | None:
    global _U, _override
    if _override:
        return _U
    if os.getenv("ROUTER_MODEL", "1") == "0":
        return None
    if _U is None:
        try:
            from src import rag
            c = rag.get().composer if rag.available() and getattr(rag.get(), "composer", None) is not None else None
            if c is None:
                from src.paper_rag.factory import composer_pools
                c = composer_pools()
            _U = Understander(c) if (c.gemini or c.groq) else None
        except Exception as e:  # noqa: BLE001
            logger.info("understanding model unavailable (%s): the rules answer", type(e).__name__)
            _U = None
        if _U is None:
            _override = True
    return _U
