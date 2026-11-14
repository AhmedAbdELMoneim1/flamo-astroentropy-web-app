"""Shared test helpers: a fake bridge, number extraction, the goldens."""
import re

import pytest
import yaml

from tests.conftest import DB, GOLDEN

needs_db = pytest.mark.skipif(not DB.exists(), reason="serving.db not found (set FLAMEO_DB)")


class FakeBridge:
    def __init__(self):
        self.sent = []

    async def send(self, cmd_type, payload, dest_identity=None):
        self.sent.append((cmd_type, payload))

    def of(self, cmd_type):
        return [p for t, p in self.sent if t == cmd_type]


NUM = re.compile(r"(?<![\w.])\d+(?:\.\d+)?")


def numbers(x) -> set[str]:
    """Every number in a string / nested structure, as written (no float conversion)."""
    if isinstance(x, str):
        return set(NUM.findall(x))
    if isinstance(x, dict):
        return set().union(*(numbers(v) for v in x.values())) if x else set()
    if isinstance(x, (list, tuple)):
        return set().union(*(numbers(v) for v in x)) if x else set()
    if isinstance(x, bool) or x is None:
        return set()
    if isinstance(x, (int, float)):
        return {str(x), f"{x:g}", str(int(x)) if float(x).is_integer() else str(x)}
    return set()


def goldens():
    if not GOLDEN.exists():
        return []
    out = []
    for g in yaml.safe_load(open(GOLDEN, encoding="utf-8")):
        for st in [g] + g.get("also", []):
            out.append((g["id"], st["tool"], st["args"]))
    return out
