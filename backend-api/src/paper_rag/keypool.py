"""Round-robin pool over the numbered API keys of one provider (GEMINI_API_KEY_1..13, GROQ_API_KEY_1..6).

- every use is checked against per-key limits (requests, tokens per minute; requests per day) so nothing is sent faster than allowed;
- a 429 / quota error puts that key on cooldown (retry-after, else 60 s) and the call moves to the next key;
- logs and stats show only the key's index ("gemini#4"); a key value is never printed, logged or stored here.

The pool counts *units*: for embeddings the free tier counts every text of a batch as one request, so a batch of 90 texts is 90 units.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger("keypool")


@dataclass(frozen=True)
class Limits:
    rpm: int = 100          # units per minute
    tpm: int = 30_000       # tokens per minute
    rpd: int = 1_000        # units per day (0 = unlimited)


class _Key:
    __slots__ = ("index", "_value", "cooldown_until", "events", "day_units", "day", "requests", "tokens", "n429", "cooled_s")

    def __init__(self, index: int, value: str) -> None:
        self.index, self._value = index, value
        self.cooldown_until = 0.0
        self.events: deque = deque()   # (t, units, tokens) of the last 60 s
        self.day_units, self.day = 0, time.strftime("%Y-%m-%d")
        self.requests = self.tokens = self.n429 = 0
        self.cooled_s = 0.0

    def __repr__(self) -> str:        # never the value
        return f"<key #{self.index}>"


@dataclass
class Lease:
    index: int
    key: str = field(repr=False)
    units: int = 1
    tokens: int = 0


def env_limits(prefix: str, default: Limits) -> Limits:
    g = lambda name, d: int(os.getenv(f"{prefix}_{name}", d))  # noqa: E731
    return Limits(g("RPM", default.rpm), g("TPM", default.tpm), g("RPD", default.rpd))


def retry_after_seconds(exc: BaseException, default: float = 60.0) -> float:
    """Seconds to wait from an API error: a Retry-After header, 'retryDelay': '42s' or 'retry in 42.03s' in the message."""
    headers = getattr(getattr(exc, "response", None), "headers", None) or {}
    for k in ("retry-after", "Retry-After"):
        if k in headers:
            try:
                return float(headers[k])
            except ValueError:
                pass
    m = re.search(r"retry(?:Delay|[^0-9]{0,12})['\": ]*([0-9]+(?:\.[0-9]+)?)\s*s", str(exc), re.I)
    return float(m.group(1)) + 1 if m else default


def is_quota_error(exc: BaseException) -> bool:
    s = f"{getattr(exc, 'status_code', '')} {getattr(exc, 'code', '')} {exc}".lower()
    return "429" in s or "resource_exhausted" in s or "rate limit" in s or "quota" in s


class KeyPool:
    def __init__(self, name: str, keys: dict[int, str], limits: Limits = Limits(), clock=time.monotonic, state_file: Path | None = None) -> None:
        if not keys:
            raise ValueError(f"no {name} keys found")
        self.name, self.limits, self._clock = name, limits, clock
        self._keys = [_Key(i, v) for i, v in sorted(keys.items())]
        self._next = 0
        self._lock = asyncio.Lock()
        self._state = state_file
        self._load_state()

    @classmethod
    def from_env(cls, name: str, limits: Limits | None = None, **kw) -> "KeyPool":
        """name = 'GEMINI' reads GEMINI_API_KEY_1.. (and a single GEMINI_API_KEY as #0)."""
        keys = {int(m.group(1)): v for k, v in os.environ.items() if v and (m := re.fullmatch(rf"{name}_API_KEY_(\d+)", k, re.I))}
        if not keys and os.getenv(f"{name}_API_KEY"):
            keys = {0: os.environ[f"{name}_API_KEY"]}
        return cls(name.lower(), keys, limits or env_limits(f"{name}_POOL", Limits()), **kw)

    def __len__(self) -> int:
        return len(self._keys)

    def label(self, index: int) -> str:
        return f"{self.name}#{index}"

    # ── limits ────────────────────────────────────────────────────────────────
    def _roll(self, k: _Key, now: float) -> None:
        while k.events and now - k.events[0][0] >= 60:
            k.events.popleft()
        today = time.strftime("%Y-%m-%d")
        if k.day != today:
            k.day, k.day_units = today, 0

    def _wait_for(self, k: _Key, units: int, tokens: int, now: float) -> float:
        """0 if the key can take this request now, else seconds until it can (inf = not today)."""
        self._roll(k, now)
        lim = self.limits
        if lim.rpd and k.day_units + units > lim.rpd:
            return float("inf")
        wait = max(0.0, k.cooldown_until - now)
        used_u, used_t = sum(e[1] for e in k.events), sum(e[2] for e in k.events)
        if used_u + units > lim.rpm or used_t + tokens > lim.tpm:
            # the earliest moment enough old events have left the 60 s window
            need_u, need_t, t_free = used_u + units - lim.rpm, used_t + tokens - lim.tpm, now
            freed_u = freed_t = 0
            for t, u, tk in k.events:
                freed_u, freed_t, t_free = freed_u + u, freed_t + tk, t + 60
                if freed_u >= need_u and freed_t >= need_t:
                    break
            wait = max(wait, t_free - now)
        return wait

    async def acquire(self, units: int = 1, tokens: int = 0, timeout: float | None = None) -> Lease:
        """Reserve `units` on the next key that can take them; waits (never sends faster than the limits)."""
        units = min(units, self.limits.rpm)  # a request larger than a minute's budget is capped to it
        tokens = min(tokens, self.limits.tpm)
        deadline = None if timeout is None else self._clock() + timeout
        while True:
            async with self._lock:
                now = self._clock()
                best, best_wait = None, float("inf")
                n = len(self._keys)
                for step in range(n):
                    k = self._keys[(self._next + step) % n]
                    w = self._wait_for(k, units, tokens, now)
                    if w == 0:
                        best, best_wait = k, 0.0
                        self._next = (self._next + step + 1) % n
                        break
                    best_wait = min(best_wait, w)
                if best is not None:
                    best.events.append((now, units, tokens))
                    best.day_units += units
                    best.requests += units
                    best.tokens += tokens
                    self._save_state()
                    return Lease(best.index, best._value, units, tokens)
            if best_wait == float("inf"):
                raise RuntimeError(f"all {self.name} keys reached their daily limit")
            if deadline is not None and self._clock() + best_wait > deadline:
                raise TimeoutError(f"no {self.name} key free within {timeout}s")
            await asyncio.sleep(min(best_wait, 5.0) + 0.01)

    def soonest_wait(self, units: int = 1, tokens: int = 0) -> float:
        """Seconds until some key could take this request (0 = now, inf = all keys are out for the day). Lets a caller pick another provider instead of waiting."""
        now = self._clock()
        return min(self._wait_for(k, min(units, self.limits.rpm), min(tokens, self.limits.tpm), now) for k in self._keys)

    def report_quota_error(self, lease: Lease, exc: BaseException | None = None, default: float = 60.0) -> float:
        """A 429: this key rests for retry-after (else `default`) seconds; the units it reserved are given back."""
        k = next(k for k in self._keys if k.index == lease.index)
        wait = retry_after_seconds(exc, default) if exc is not None else default
        k.cooldown_until = max(k.cooldown_until, self._clock() + wait)
        k.n429 += 1
        k.cooled_s += wait
        k.requests = max(0, k.requests - lease.units)
        logger.warning("%s: 429, cooling down %.0fs", self.label(k.index), wait)
        return wait

    def stats(self) -> dict:
        return {
            "pool": self.name,
            "keys": {self.label(k.index): {"requests": k.requests, "tokens": k.tokens, "n429": k.n429, "cooldown_s": round(k.cooled_s)} for k in self._keys},
            "n429": sum(k.n429 for k in self._keys),
        }

    # ── the daily counter survives restarts (counts only, never a key) ───────
    def _load_state(self) -> None:
        if not self._state or not self._state.exists():
            return
        try:
            d = json.loads(self._state.read_text())
            if d.get("day") == time.strftime("%Y-%m-%d"):
                for k in self._keys:
                    k.day_units = int(d.get("units", {}).get(str(k.index), 0))
        except Exception:
            logger.warning("could not read the key pool state", exc_info=True)

    def _save_state(self) -> None:
        if not self._state:
            return
        try:
            self._state.parent.mkdir(parents=True, exist_ok=True)
            self._state.write_text(json.dumps({"day": time.strftime("%Y-%m-%d"), "units": {str(k.index): k.day_units for k in self._keys}}))
        except Exception:
            pass
