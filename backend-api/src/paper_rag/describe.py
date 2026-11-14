"""Model descriptions of tables and figures (the team's prompts from chunk_data.py, unchanged).

Groq key pool first (the team's model, which the Groq models.list offers: qwen/qwen3.8-27b), Gemini key pool when Groq is exhausted.
Every item is cached in rag_cache/desc/<safe src_id>.desc.jsonl so a run resumes where it stopped. Logs show key indexes only.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import json
import logging
import re
from pathlib import Path

import httpx

from src.paper_rag.keypool import KeyPool, is_quota_error

logger = logging.getLogger("describe")

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "qwen/qwen3.8-27b"          # in the Groq models.list of 2026-11-08 (the team's model)

IMAGE_PROMPT = """You are a combustion scientist and spacecraft fire-safety analyst. Analyze this figure from a
scientific paper on microgravity combustion (flame spread, droplet burning, smoldering, soot, flammability,
fire detection or suppression in reduced gravity).

Reply in EXACTLY this format:

TYPE: <line_plot | bar_chart | scatter_plot | contour_or_heatmap | flame_image | schematic_or_apparatus | flammability_map | table_image | microscopy_or_sample | photo | logo_or_decorative>
SUMMARY:
<A self-contained summary used BOTH for search indexing and as the only source a reader sees.
Include:
1. What the figure shows: title, axes (variable names and units), legend/series, panels (a, b, c...).
2. Experimental conditions if visible: gravity level (microgravity / partial-g / normal-g), O2 concentration,
   pressure, flow velocity, fuel/material and geometry (e.g. thin sheet, cylinder, droplet), ignition source,
   facility or platform (ISS, drop tower, parabolic flight, sounding rocket, Saffire, ...).
3. Every readable value with its label (or a compact Markdown table for charts/tables).
4. Observed behavior: trends, maxima/minima, comparisons between gravity levels or conditions, and flame
   features (shape, size, color, blue/yellow, soot, extinction, spread rate, flammability limit, quenching).
5. One sentence on the fire-safety implication ONLY if the figure or caption supports it.>

Rules:
- Never invent numbers, units or conditions. Write '?' for unreadable values and 'not stated' for missing conditions.
- Do not mix up gravity levels: state which curve/image belongs to which condition.
- Keep symbols, units and equations as they appear (e.g. cm/s, kPa, vol% O2, µg).
- If the image is only a logo, journal banner or decoration, write TYPE: logo_or_decorative and SUMMARY: N/A.

Paper: {doc}
Caption: {caption}
Context: {context}"""

TABLE_PROMPT = """Below is a table from a scientific paper on microgravity combustion and fire safety.
Write a SHORT description (max 3 sentences) that helps a search engine find this table:
what it contains, how it is organized (meaning of rows/columns, materials or fuels, test conditions such as
gravity level, O2 concentration, pressure, flow velocity, sample geometry), the units, the platform or
facility if it appears in the context, and one key takeaway (e.g. which condition gives the highest spread
rate or the lowest flammability limit).

Rules:
- Use ONLY information present in the table, caption or context. If a unit, condition or column meaning is not
  stated, say it is not stated. Do not guess.
- Do NOT list all the values (the full table is attached separately).
- Keep symbols, units and material names exactly as written.
- Same language as the table.

Paper: {doc}
Context before the table: {context}
Caption: {caption}

TABLE:
{table}"""


def safe(src_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", src_id)


def to_data_url(png: bytes, max_side: int = 1200) -> str:
    from PIL import Image
    img = Image.open(io.BytesIO(png)).convert("RGB")
    img.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=88)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def to_jpeg(png: bytes, max_side: int = 1200) -> bytes:
    """A figure as a JPEG of at most `max_side` pixels (the extracted PNGs are 2x scale and very large: that made the free-tier calls fail)."""
    from PIL import Image
    img = Image.open(io.BytesIO(png)).convert("RGB")
    img.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def parse_figure(raw: str) -> dict:
    t = re.search(r"TYPE:\s*(\S+)", raw)
    s = re.search(r"SUMMARY:\s*(.*)", raw, re.S)
    return {"type": t.group(1).strip().lower() if t else "unknown", "summary": (s.group(1).strip() if s else raw).strip()}


class Describer:
    """describe_table / describe_figure with a cache, Groq first and Gemini as the fallback. `stats` counts calls per provider."""

    def __init__(self, groq: KeyPool | None, gemini: KeyPool | None, cache_dir: Path, *, gemini_model: str = "gemini-3.5-flash-lite", http: httpx.AsyncClient | None = None) -> None:
        self.groq, self.gemini, self.cache_dir, self.gemini_model = groq, gemini, cache_dir, gemini_model
        self.max_wait_s = 20.0
        self._gem_sem = asyncio.Semaphore(int(__import__('os').getenv('DESCRIBE_GEMINI_PARALLEL', '10')))   # the free generation model answers 429 to bursts: few calls at once
        self.http = http or httpx.AsyncClient(timeout=httpx.Timeout(90, connect=15))
        self.stats = {"groq_calls": 0, "gemini_calls": 0, "groq_429": 0, "cache_hits": 0, "failed": 0}
        self._gem_clients: dict[int, object] = {}
        cache_dir.mkdir(parents=True, exist_ok=True)

    # ── cache ────────────────────────────────────────────────────────────────
    def _file(self, src_id: str) -> Path:
        return self.cache_dir / f"{safe(src_id)}.desc.jsonl"

    def _load(self, src_id: str) -> dict[str, dict]:
        f, out = self._file(src_id), {}
        if f.exists():
            for line in f.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    d = json.loads(line)
                    out[d["key"]] = d
        return out

    def _store(self, src_id: str, key: str, value: dict) -> None:
        with self._file(src_id).open("a", encoding="utf-8") as f:
            f.write(json.dumps({"key": key, **value}, ensure_ascii=False) + "\n")

    # ── providers ────────────────────────────────────────────────────────────
    async def _groq(self, messages: list, max_tokens: int, tokens_est: int) -> str:
        last: BaseException | None = None
        for _ in range(5):
            lease = await self.groq.acquire(units=1, tokens=tokens_est)
            try:
                r = await self.http.post(GROQ_URL, headers={"Authorization": f"Bearer {lease.key}"}, json={"model": GROQ_MODEL, "messages": messages, "temperature": 0.1, "max_tokens": max_tokens})
                if r.status_code == 429:
                    self.stats["groq_429"] += 1
                    self.groq.report_quota_error(lease, httpx.HTTPStatusError("429", request=r.request, response=r))
                    continue
                r.raise_for_status()
                self.stats["groq_calls"] += 1
                return (r.json()["choices"][0]["message"]["content"] or "").strip()
            except httpx.HTTPError as e:
                last = e
                await asyncio.sleep(2)
        raise RuntimeError(f"groq failed: {type(last).__name__}")

    async def _gemini(self, prompt: str, image: bytes | None) -> str:
        from google import genai
        from google.genai import types
        last: BaseException | None = None
        for _ in range(5):
            lease = await self.gemini.acquire(units=1, tokens=1500 if image else 800)
            try:
                c = self._gem_clients.get(lease.index) or self._gem_clients.setdefault(lease.index, genai.Client(api_key=lease.key))
                parts = [prompt] + ([types.Part.from_bytes(data=to_jpeg(image), mime_type="image/jpeg")] if image else [])
                r = await c.aio.models.generate_content(model=self.gemini_model, contents=parts, config=types.GenerateContentConfig(temperature=0.1, max_output_tokens=800))
                self.stats["gemini_calls"] += 1
                return (r.text or "").strip()
            except Exception as e:  # noqa: BLE001
                last = e
                if is_quota_error(e):
                    m = re.search(r"Quota exceeded for metric[^\n]{0,200}", str(e))
                    logger.warning("gemini describe quota: %s", (m.group(0) if m else str(e)[:160]).replace("\n", " "))
                    self.gemini.report_quota_error(lease, e)
                else:
                    await asyncio.sleep(2)
        raise RuntimeError(f"gemini failed: {type(last).__name__}")

    async def _ask(self, prompt: str, image: bytes | None, max_tokens: int) -> str:
        # Groq is the first choice, but never wait long for it: when every Groq key is cooling down, Gemini takes the item
        if self.groq is not None and (self.gemini is None or self.groq.soonest_wait(1, 1500 if image else 900) <= self.max_wait_s):
            try:
                content = [{"type": "text", "text": prompt}] + ([{"type": "image_url", "image_url": {"url": to_data_url(image)}}] if image else [])
                return await self._groq([{"role": "user", "content": content if image else prompt}], max_tokens, 1500 if image else 900)
            except Exception as e:  # noqa: BLE001
                logger.warning("groq unavailable (%s): falling back to gemini", e)
        if self.gemini is None:
            raise RuntimeError("no description provider available")
        async with self._gem_sem:
            return await self._gemini(prompt, image)

    # ── public ───────────────────────────────────────────────────────────────
    async def table(self, src_id: str, key: str, markdown: str, caption: str, doc_title: str, context: str) -> str:
        cached = self._load(src_id).get(key)
        if cached:
            self.stats["cache_hits"] += 1
            return cached["desc"]
        try:
            desc = await self._ask(TABLE_PROMPT.format(doc=doc_title, context=context, caption=caption, table=markdown[:6000]), None, 400)
        except Exception:  # noqa: BLE001
            self.stats["failed"] += 1
            desc = ""                                         # the table is still indexed, without a description
        else:
            self._store(src_id, key, {"kind": "table", "desc": desc})
        return desc

    async def figure(self, src_id: str, key: str, png: bytes, caption: str, doc_title: str, context: str) -> dict:
        cached = self._load(src_id).get(key)
        if cached:
            self.stats["cache_hits"] += 1
            return {"type": cached["type"], "summary": cached["summary"]}
        try:
            info = parse_figure(await self._ask(IMAGE_PROMPT.format(doc=doc_title, caption=caption, context=context), png, 650))
        except Exception:  # noqa: BLE001
            self.stats["failed"] += 1
            return {"type": "unknown", "summary": ""}
        self._store(src_id, key, {"kind": "figure", **info})
        return info


def item_key(kind: str, *parts) -> str:
    return kind + ":" + hashlib.sha1("|".join(str(p) for p in parts).encode()).hexdigest()[:16]
