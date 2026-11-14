"""Round 14 §14.7 step 1: the understand step (entities + intent + context) against >= 60 questions from the replays. Needs only serving.db (FLAMEO_DB)."""
import os
from pathlib import Path

import pytest
import yaml

from src import rag
from src.router.session import Session
from src.router.understand import understand

CASES = yaml.safe_load((Path(__file__).parent / "golden" / "router_understand.yaml").read_text(encoding="utf-8"))
ext = rag.extractor() if os.getenv("FLAMEO_DB") else None
pytestmark = pytest.mark.skipif(ext is None, reason="FLAMEO_DB not set")


def test_there_are_at_least_sixty_questions():
    assert len(CASES) >= 60


@pytest.mark.parametrize("c", CASES, ids=[c["q"][:48] for c in CASES])
def test_understand(c):
    u = understand(c["q"], Session(psi=c.get("ctx_psi")), ext, c.get("screen_scenario"))
    assert u.primary == (c["primary"] or "ask"), (u.intents, u.entities())
    if c.get("confirm"):
        assert u.confirm
    if c.get("go_back"):
        assert u.go_back
    got = u.entities()
    for k, v in c["e"].items():
        if k == "psi":
            assert set(v) <= set(got.get("psi", [])), (k, got)
        elif k == "fields":
            assert set(v) <= set(got.get("fields", [])), (k, got)
        elif k == "pillar":
            assert u.pillar == v
        elif k == "topic":
            assert u.topic == v
        else:
            assert got.get(k) == v, (k, got)
