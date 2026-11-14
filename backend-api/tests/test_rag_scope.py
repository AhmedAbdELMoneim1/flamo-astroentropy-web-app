"""Scope resolver (serving.db): parameters -> investigations."""
import pytest

from src.paper_rag.scope import Scope, ScopeResolver
from tests.conftest import DB
from tests.helpers import needs_db

pytestmark = needs_db


@pytest.fixture(scope="module")
def R():
    return ScopeResolver(DB)


def test_a_named_psi_matches_exactly_before_loosely(R):
    assert R.resolve(psi="BASS").psis == ["PSI-26"] and R.resolve(psi="BASS-II").psis == ["PSI-25"]
    assert R.resolve(psi="BRE").psis == ["PSI-20"] and R.resolve(psi="PSI-69").psis == ["PSI-69"] and R.resolve(psi="FLEX").psis == ["PSI-69"]


def test_oxygen_and_pressure_tolerances(R):
    near17 = R.resolve(o2_pct=17).psis
    assert "PSI-25" in near17 and "PSI-98" not in near17                        # Saffire-I burned near 21 percent only
    assert set(R.resolve(o2_pct=17, pressure_kpa=101.3).psis) <= set(near17)


def test_several_parameters_narrow_and_report_which_selected(R):
    s = R.resolve(o2_pct=21, psi="BRE")
    assert s.psis == ["PSI-20"] and set(s.selected_by) == {"o2_pct", "psi"} and not s.widened


def test_parameters_with_nothing_in_common_widen_to_the_union(R):
    s = R.resolve(psi="SAME", o2_pct=85)
    assert s.widened and "PSI-102" in s.psis


def test_pillar_material_fuel_and_scenario(R):
    assert "PSI-102" in R.resolve(pillar="detection").psis and "PSI-69" in R.resolve(pillar="suppression").psis
    assert "PSI-101" in R.resolve(material="Kapton").psis and "PSI-69" in R.resolve(fuel="methanol").psis
    assert R.resolve(scenario="iss").psis and R.resolve(scenario="spacesuit").empty            # no test near the suit atmosphere


def test_no_parameters_is_no_scope(R):
    s = R.resolve()
    assert s.empty and s.as_filter() is None
    assert Scope(psis=["PSI-20"]).as_filter() == {"psis": ["PSI-20"], "kinds": ["challenge"]}
