# Voice-path transcript (Round 11): conditions follow the words

The real server path: the question text -> `conditions.apply_from_text` (deterministic, not Gemini) -> `conditions.set` to the screen; the model's tool call is the router golden's `oxygen_effect(scenario="moon_base")`. No LiveKit, no Gemini voice: the 'voice says' lines follow the prompt's rules.

**Astronaut:** Is 34 percent oxygen dangerous on the Moon base?

**Server sets the sliders (before any model call):** `{"oxygen_pct": 34.0, "pressure_psi": 10.2}`; `conditions.set` payload sent to the screen: `{"scenario": null, "inputs": {"oxygen_pct": 34.0, "pressure_psi": 10.2}, "source": "From your question: 34 % O₂ · rest from Moon Base / pressurized rover (scenario definition)"}`

**Tool call:** `oxygen_effect(scenario="moon_base")`

**The voice says** (first the one-time conditions note, then the speak lines):

> I set the oxygen to 34 percent; the panel shows the nearest tests.
> The intermediate oxygen concentration used on the Moon will likely be 30% or greater, with a corresponding pressure of 10.2 psi or less. Compared to Earth’s atmosphere, that’s more than a 40% increase in the oxygen concentration making materials much more flammable.
> The PSI data does not set a single safe or dangerous oxygen level; these are the conditions where the tests still burned.
> In flight compared with ground tests, the authors report: In microgravity, there is still flame spread at XO2 = 17%, while flame cannot exist in normal gravity for XO2 = 18% and below.
> From ACME BRE Reports: Dissertation PD revised, page 31: Generally, it has been found that oxygen levels of 26 % and above can allow steady flames.
> The details are on the screen.
> Do you want to see the oxygen against pressure chart?

**On screen (answer.show):** `Is 34 percent oxygen dangerous on the Moon base?`, 7 lines, 4 sources; panel data from `GET /api/nearest?o2=34&p=10.2` (flameo `nearest_tests`).
