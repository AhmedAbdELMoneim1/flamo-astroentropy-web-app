"""Round 10 D10-1 / Round 3 rule: no measurement-looking number or status word is typed into the scenes or the hub.
Allowed on screen: values from flameo, scenario definitions (O2 / pressure of the challenge scenarios), and labelled "SIMULATED" vitals."""
import pathlib
import re

SRC = pathlib.Path(__file__).resolve().parents[2] / "frontend" / "src"
SCENES = ["cabinScene/CabinScene.jsx", "suitHelmetScene/SuitHelmetScene.jsx", "moonHabitatScene/MoonHabitatScene.jsx", "spaceCraftScene/SpaceCraftScene.jsx"]
FORBIDDEN = [r"NOMINAL", r"\bWATCH\b", r"EXT TEMP", r"Ext temp", r"<span>Exterior</span>", r"Suit temp", r"FIRE SAFETY", r"\bppm\b", r"0\.166", r"-173", r"22\.4", r"extTempC", r"score \+ ' \]'", r"status: '", r"value: 0\.\d+, status"]


def text(rel):
    return (SRC / rel).read_text(encoding="utf-8")


def test_scenes_and_hub_have_no_made_up_readings():
    bad = [(rel, pat) for rel in SCENES for pat in FORBIDDEN if re.search(pat, text(rel))]
    assert not bad, bad


def test_crew_vitals_are_labelled_simulated():
    t = text("suitHelmetScene/SuitHelmetScene.jsx")
    assert re.search(r"CREW VITALS[^<]*SIMULATED", t)
    for row in ("Heart", "SpO2", "CO2", "Tank", "EVA"):          # every simulated reading sits in that panel
        panel = t[t.index("CREW VITALS"):]
        assert f"<span>{row}</span>" in panel.split("</div></div>")[0] or f"<span>{row}</span>" in panel[:600]


def test_hub_ring_shows_no_percentage():
    t = text("cabinScene/CabinScene.jsx")
    assert "Math.round(c.value" not in t and "c.status" not in t
