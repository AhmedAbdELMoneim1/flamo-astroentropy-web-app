"""Catalog: coverage from the data, intros and chips exactly as decided."""
import pytest

from src import categories, flameo
from tests.helpers import needs_db

pytestmark = needs_db


@pytest.fixture(scope="module", autouse=True)
def _db():
    from tests.conftest import DB

    flameo.init(DB)
    categories.load_coverage(flameo.call)


def test_coverage_comes_from_flameo_not_from_code():
    S = categories.SCENARIOS
    assert S["iss"].coverage == flameo.call("scenario_coverage", scenario="iss")["level"] == "High"
    assert S["moon_base"].coverage == flameo.call("scenario_coverage", scenario="moon_base")["level"] == "Medium"
    suit = flameo.call("scenario_coverage", scenario="spacesuit")
    assert S["spacesuit"].coverage == "None" and S["spacesuit"].coverage_note == {"label": categories.OXYGEN_RICH_NOTE_LABEL, "level": suit["level_oxygen_rich_flames"]}
    assert S["iss"].coverage_note is None
    src = open(categories.__file__, encoding="utf-8").read()
    assert 'coverage="High"' not in src and 'coverage="Low"' not in src


def test_catalog_carries_notes_and_fixed_texts():
    c = categories.public_catalog()
    suit = next(s for s in c["scenarios"] if s["id"] == "spacesuit")
    assert suit["coverage"] == "None" and suit["coverage_note"]["level"] == "Medium"
    assert c["texts"]["gaps_title"] == "Open questions: not in the data yet"
    assert c["texts"]["gaps_footer"] == "Gaps like these show where new experiments or papers are needed."
    assert c["texts"]["gravity"] == "Microgravity (PSI has no partial-gravity data)"
    assert c["texts"]["no_coverage"] == "Spacesuit atmosphere: none tested"
    assert set(c["conditions"]) == {"oxygen_pct", "pressure_psi"}


def test_prevention_overview_is_materials_and_ignition_stays_reachable():
    assert categories.find_view("prevention").id == "materials"
    assert categories.find_view("prevention", "ignition").id == "ignition"
    assert categories.PILLARS["prevention"].overview_view == "materials"


def test_intros_and_chips_as_decided():
    P = categories.PILLARS
    assert P["prevention"].intro.startswith("Prevention is about what can catch fire. The flight tests burned fabrics and plastics such as SIBAL, Nomex and PMMA")
    assert P["detection"].intro.startswith("Smoke is usually the first warning. SAME and SAME-R")
    for p in P.values():
        assert len(p.suggestions) == 3 and not any(ch.isdigit() for ch in p.intro), p.id
    texts = {p: [c.text for c in P[p].suggestions] for p in P}
    assert texts["prevention"] == ["Which experiments matter most for prevention?", "Compare BASS and BASS-II", "What is BRE?"]
    assert texts["flammability"][0] == "Does fire spread faster in space?" and texts["flammability"][1] == "What is a cool flame?"
    assert texts["detection"][1] == "Which experiments matter most for detection?"
    assert texts["suppression"] == ["Which gases did the experiments add?", "What happens to cool flames with helium?", "How much CO2 puts a fire out?"]
    assert "Rank materials by flame spread" not in sum(texts.values(), [])


def test_same_chip_is_pending_review_and_hidden():
    from src.content import chips_for

    same = next(c for c in categories.PILLARS["detection"].suggestions if c.text == "What did SAME measure?")
    assert same.pending_review is True
    assert "What did SAME measure?" not in chips_for("detection") and len(chips_for("detection")) == 2
    assert len(chips_for("suppression")) == 3
