"""Emergency classification (Round 10): 5 real reports must trigger, 5 hypothetical questions must not, 3 clear phrases must clear."""
import pytest

from src.emergency import banner, classify, is_arabic

REAL = ["I smell burning plastic in the cabin", "There's smoke coming from the avionics rack", "Fire in the galley!", "The laptop is overheating and smoking",
        "I see flames near the oxygen panel", "في حريق في الكابينة", "أشم رائحة حرق"]
HYPOTHETICAL = ["What should I do if a fire happens inside the suit?", "What happens if there is a fire in the cabin?", "How do I use the fire extinguisher?",
                "Can I use water on a fire on the ISS?", "How do fires behave in microgravity?", "ماذا أفعل لو حصل حريق داخل البدلة؟", "كيف أتصرف إذا اشتعلت النار؟"]
CLEAR = ["There is no fire, I was only asking.", "False alarm, it's out now", "The fire is out", "مفيش حريق، كنت بسأل بس", "إنذار كاذب"]


@pytest.mark.parametrize("t", REAL)
def test_real_reports_trigger(t): assert classify(t) == "now", t


@pytest.mark.parametrize("t", HYPOTHETICAL)
def test_hypothetical_questions_never_trigger(t): assert classify(t) in ("hypothetical", "unknown"), t


@pytest.mark.parametrize("t", CLEAR)
def test_clear_phrases_clear(t): assert classify(t) == "clear", t


def test_if_i_smell_is_ambiguous_so_the_agent_asks_once():
    assert classify("What should I do if I smell burning plastic in the cabin?") == "ambiguous"
    assert classify("") == "unknown" and classify(None) == "unknown"


def test_the_banner_follows_the_location_and_the_chat_language():
    b = banner("fire inside the spacesuit", "I smell smoke in my suit")
    assert b["location"] == "suit" and b["steps"] == ["Alert the crew and ground control", "Follow your EVA emergency procedure"] and b["lang"] == "en"
    c = banner("smoke from the rack", "there's smoke from the rack")
    assert c["location"] == "cabin" and len(c["steps"]) == 5 and "Isolate power to the affected equipment" in c["steps"]
    a = banner("حريق في البدلة", "في حريق في البدلة")
    assert a["lang"] == "ar" and a["location"] == "suit" and all(is_arabic(s) for s in a["steps"]) and is_arabic(a["footer"])
