"""Parameters from the question text (Round 10 §10.1 item 1): the scope is used even when Gemini passes nothing."""
import pytest

from src.paper_rag.extract import Extractor, merge
from tests.conftest import DB
from tests.helpers import needs_db

pytestmark = needs_db


@pytest.fixture(scope="module")
def X(): return Extractor(DB)


@pytest.mark.parametrize("q,expect", [
    ("What oxygen level allows steady flames in the BRE tests?", {"psi": "PSI-20"}),
    ("What oxygen does the space station cabin have?", {"scenario": "iss"}),
    ("What did SPICE find about smoke points?", {"psi": "PSI-107"}),
    ("Can flames spread at 17 percent oxygen?", {"o2_pct": 17.0}),
    ("What happens at 34% O2 and 8.2 psi?", {"o2_pct": 34.0, "pressure_kpa": 56.5}),
    ("How does PMMA burn in acrylic cylinders at 70 kPa?", {"material": "PMMA", "pressure_kpa": 70.0}),
    ("How did soot change for methane flames?", {"fuel": "methane"}),
    ("What atmosphere does the Moon base habitat use?", {"scenario": "moon_base"}),
    ("What happens to flames in the spacesuit atmosphere?", {"scenario": "spacesuit"}),
    ("Compare FLEX-2 and BASS-II", {"psi": ["PSI-68", "PSI-25"]}),
    ("What did Saffire burn?", {"psi": ["PSI-100", "PSI-98", "PSI-99"]}),
    ("What did PSI-69 test?", {"psi": "PSI-69"}),
])
def test_what_the_text_says(X, q, expect):
    got = X.extract(q)
    for k, v in expect.items():
        if isinstance(v, list):
            assert sorted(got[k]) == sorted(v), (q, got)
        else:
            assert got[k] == v, (q, got)


def test_nothing_is_invented_and_english_words_are_not_experiments(X):
    assert X.extract("Why do flames go out in microgravity?") == {}
    assert "psi" not in X.extract("Use the same oxygen level for the same flame")
    assert "psi" not in X.extract("they will flex and the bass is low")            # lower-case English words
    assert X.extract("the same experiment") == {}
    assert "scenario" not in X.extract("How were laminar smoke points measured aboard the space station?")       # a place, not a condition


def test_the_models_arguments_win_and_the_source_of_each_parameter_is_recorded():
    p, src = merge({"psi": "SAME", "o2_pct": None}, {"psi": "PSI-20", "o2_pct": 26.0, "scenario": "iss"})
    assert p == {"psi": "SAME", "o2_pct": 26.0, "scenario": "iss"} and src == {"psi": "model", "o2_pct": "extracted", "scenario": "extracted"}
    assert merge({}, {}) == ({}, {})


def test_the_resolver_accepts_a_list_of_psis_and_synonyms():
    from src.paper_rag.scope import ScopeResolver
    R = ScopeResolver(DB)
    assert sorted(R.resolve(psi=["PSI-68", "PSI-25"]).psis) == ["PSI-25", "PSI-68"]
    assert R.resolve(fuel="methane").psis and "PSI-101" in R.resolve(material="polyimide" if False else "Kapton").psis
