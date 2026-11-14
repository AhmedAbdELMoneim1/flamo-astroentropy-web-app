"""The composer and the checker (Round 6 §6.4, Round 7 §7.4, Round 8 §8.2).

Numbered excerpts in, JSON out: at most 3 sentences, each tagged with the excerpt numbers it uses. The CHECKER keeps a sentence only if
  1. it cites at least one excerpt that exists,
  2. every number in it appears in the raw_text of a cited excerpt whose text is NOT model-generated (generated: false),
  3. it contains no "safe / safest / unsafe" wording and no "dangerous above X" threshold.
A dropped slot falls back to an extractive sentence from the best excerpt. The checker is pure code: it never calls a model.
Models: Gemini (gemini-3.5-flash-lite, the model that works on these keys), then Groq, then the extractive answer.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re

import httpx

from src.paper_rag.chunks import is_junk
from src.paper_rag.keypool import KeyPool, is_quota_error
from src.paper_rag.stores.vector_db.providers.PGvectorProvider import RetrievedDocument

logger = logging.getLogger("composer")
GEMINI_MODEL = "gemini-3.5-flash-lite"
GROQ_MODEL = "qwen/qwen3.8-27b"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
MAX_SENTENCES = 3

SYSTEM = """You answer ONE question about NASA microgravity combustion and spacecraft fire safety from numbered excerpts of papers and NASA documents.
Rules:
- Use ONLY the excerpts. Write at most 3 short sentences. Every sentence lists the numbers of the excerpts it uses.
- Keep every number, unit and name exactly as written in the excerpts. Never compute, round, convert or add a number.
- Say what the authors or the experiment report; never generalise beyond an excerpt.
- Never say that anything is safe, safer, safest or unsafe, and never state a level above or below which something is dangerous.
- Each sentence must make sense on its own, as a direct answer: no "this", "they", "all three" or other words that point to text you did not include.
- If the excerpts only give background and do not answer the question, return an empty list.
- Do not write excerpt numbers inside the sentence text.
Return JSON only: {"sentences":[{"text":"...","chunks":[1,2]}]}"""

FORBIDDEN = [
    (re.compile(r"\b(safe|safer|safest|unsafe)\b", re.I), "forbidden word: safe/unsafe"),
    (re.compile(r"\b(dangerous|hazardous)\s+(above|below|over|under|beyond|at|when|if|once)\b", re.I), "forbidden: a danger threshold"),
    (re.compile(r"\b(above|over|below|under|beyond|exceeds?)\b[^.]{0,40}\b(is|are|becomes?|gets?)\s+(dangerous|hazardous|unsafe)\b", re.I), "forbidden: a danger threshold"),
]
# a model that has no answer sometimes writes the refusal as a sentence instead of returning an empty list
REFUSAL = re.compile(r"\b(excerpts?|text|documents?|passages?|sources?)\b[^.]{0,40}\b(do(es)? not|don't|doesn't|cannot|can't|no)\b[^.]{0,30}\b(specify|state|say|mention|provide|contain|describe|address|answer|include)", re.I)
NUM = re.compile(r"(?<![\w.])\d[\d,]*(?:\.\d+)?")


def numbers_in(text: str) -> set[str]:
    """Numbers as digits only ("1,200" -> "1200", "30.0" stays "30.0"; "30" and "30.0" are different strings: no re-rounding is allowed)."""
    return {n.replace(",", "").rstrip(".") for n in NUM.findall(text or "")}


def check_sentences(sentences: list[dict], chunks: list[RetrievedDocument]) -> list[dict]:
    """Each sentence {text, chunks:[1-based]} -> the same dict plus kept (bool) and reason (why it was dropped, '' when kept)."""
    out = []
    for s in sentences[:MAX_SENTENCES]:
        text = str(s.get("text", "")).strip()
        cites = [c for c in s.get("chunks", []) if isinstance(c, int) and 1 <= c <= len(chunks)]
        reason = ""
        if not text:
            reason = "empty sentence"
        elif REFUSAL.search(text):
            reason = "the model says the excerpts do not answer"
        elif not cites:
            reason = "no citation"
        else:
            for rx, why in FORBIDDEN:
                if rx.search(text):
                    reason = why
                    break
            if not reason:
                allowed = set()
                for c in cites:
                    d = chunks[c - 1]
                    if not d.metadata.get("generated", False):          # a figure summary can be cited for what a figure shows, never as the source of a number
                        allowed |= numbers_in(d.chunk_text)
                missing = sorted(numbers_in(text) - allowed)
                if missing:
                    reason = "number not in the cited text: " + ", ".join(missing[:3])
        out.append({"text": text, "chunks": cites, "kept": not reason, "reason": reason})
    return out


def excerpts(chunks: list[RetrievedDocument], limit: int = 1100) -> str:
    rows = []
    for i, d in enumerate(chunks, 1):
        m = d.metadata
        where = f"{m.get('title') or m.get('src_id')}" + (f", page {m['page']}" if m.get("page") else "")
        rows.append(f"[{i}] ({where})\n{d.chunk_text[:limit]}")
    return "\n\n".join(rows)


def _sentences_of(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+(?=[A-Z0-9])", re.sub(r"\s+", " ", text)) if s.strip()]


def extractive(chunks: list[RetrievedDocument], n: int = 1, limit: int = 320) -> list[dict]:
    """The best excerpt's first clean sentence(s): verbatim text, so its numbers are the source's own."""
    out = []
    for i, d in enumerate(chunks, 1):
        if d.metadata.get("generated"):
            continue
        body = re.sub(r"^\[[^\]]*\]\s*", "", d.chunk_text.split("\nContext:")[0].split("\nEvidence:")[0])
        for s in _sentences_of(body):
            if len(s) >= 40 and not is_junk(s) and (s[0].isupper() or s[0].isdigit()):
                out.append({"text": s[:limit].rsplit(" ", 1)[0] + ("…" if len(s) > limit else "") if len(s) > limit else s, "chunks": [i], "kept": True, "reason": ""})
                break
        if len(out) >= n:
            break
    return out


class Composer:
    def __init__(self, gemini: KeyPool | None, groq: KeyPool | None, http: httpx.AsyncClient | None = None) -> None:
        self.gemini, self.groq = gemini, groq
        self.http = http or httpx.AsyncClient(timeout=httpx.Timeout(4, connect=2))
        self._clients: dict[int, object] = {}
        self.last_key: str | None = None

    async def _gemini(self, prompt: str) -> str:
        from google import genai
        from google.genai import types
        lease = await self.gemini.acquire(units=1, tokens=1800, timeout=0.5)
        self.last_key = self.gemini.label(lease.index)
        c = self._clients.get(lease.index) or self._clients.setdefault(lease.index, genai.Client(api_key=lease.key))
        try:
            r = await c.aio.models.generate_content(model=GEMINI_MODEL, contents=prompt, config=types.GenerateContentConfig(
                system_instruction=SYSTEM, temperature=0.1, max_output_tokens=500, response_mime_type="application/json"))
        except Exception as e:  # noqa: BLE001
            if is_quota_error(e):
                self.gemini.report_quota_error(lease, e)
            raise
        return r.text or ""

    async def _groq(self, prompt: str) -> str:
        lease = await self.groq.acquire(units=1, tokens=1800, timeout=0.5)
        self.last_key = self.groq.label(lease.index)
        r = await self.http.post(GROQ_URL, headers={"Authorization": f"Bearer {lease.key}"}, json={
            "model": GROQ_MODEL, "temperature": 0.1, "max_tokens": 500, "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}]})
        if r.status_code == 429:
            self.groq.report_quota_error(lease, httpx.HTTPStatusError("429", request=r.request, response=r))
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"] or ""

    @staticmethod
    def parse(raw: str) -> list[dict]:
        m = re.search(r"\{.*\}", raw, re.S)
        d = json.loads(m.group(0)) if m else {}
        out = []
        for s in d.get("sentences", []):
            if isinstance(s, dict):
                out.append({"text": s.get("text", ""), "chunks": [int(x) for x in s.get("chunks", []) if str(x).isdigit()]})
        return out

    async def compose(self, question: str, chunks: list[RetrievedDocument], timeout: float) -> tuple[list[dict], dict]:
        """(sentences before the check, info {provider, key, reason}). Tries Gemini, then Groq; the caller falls back to extractive."""
        prompt = f"Question: {question}\n\nExcerpts:\n{excerpts(chunks)}"
        info = {"provider": None, "key": None, "reason": ""}
        loop = asyncio.get_event_loop()
        deadline = loop.time() + max(0.0, timeout)          # one shared deadline: the budget holds even when the first provider is slow
        providers = [(n, f, p) for n, f, p in (("gemini", self._gemini, self.gemini), ("groq", self._groq, self.groq)) if p is not None]
        for i, (name, fn, pool) in enumerate(providers):
            left = deadline - loop.time()
            if left < 0.4:
                info["reason"] += f"{name}: no time left; "
                continue
            share = left * 0.65 if i < len(providers) - 1 else left      # the first provider may not use everything: the second needs a chance
            try:
                raw = await asyncio.wait_for(fn(prompt), timeout=share)
                sents = self.parse(raw)
                info.update(provider=name, key=self.last_key)
                return sents, info
            except Exception as e:  # noqa: BLE001
                info["reason"] += f"{name}: {type(e).__name__}; "
                logger.warning("composer %s failed: %s", name, type(e).__name__)
        return [], info
