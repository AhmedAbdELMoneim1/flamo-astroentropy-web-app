# Stage 7 — use-case plan (2026-11-08)

_The question bank for the Flameo agent on real data, per pillar × scenario, with the demo script. Every "today's answer" is the real `speak[]` / KPI output in `psi_stage1/reports/stage6/stage6_final.md` §8 (goldens g01–g29). A row with no golden says so; its answer is not known until Claude Code prints it._

**Strength:**
- **strong**: flight data or a flight-vs-ground finding, or many tests, and a clear answer.
- **thin**: few tests, one PSI, or a list with no ranking; true, but narrow.
- **none**: the honest answer is "not in the data", with a pointer to the nearest data (still worth showing).
- **unchecked**: no golden exists, so the output has never been reviewed.

## 1. Coverage at a glance (pillar × scenario)
| pillar / view | ISS | Moon base | Spacesuit | Exploration 8.2 / 10.2 | Mars / partial g |
|---|---|---|---|---|---|
| Prevention: ignition | unchecked (11 ignition-time tests in all) | unchecked | unchecked | — | none |
| Prevention: materials | thin (6 rows, no ranking) | none → ISS 72 tests (g21) | unchecked | — | none |
| Flammability: flame spread | thin (27 tests, 4 PSIs; 19 near ISS) | none → ISS (g05) | unchecked | — | none |
| Flammability: findings (any scenario) | strong (g11 flight vs ground; g18 cool flames on the ISS) | | | | |
| Detection: smoke | strong finding (g17); view unchecked; particle size 10 tests (PSI-101) | unchecked | unchecked | — | none |
| Suppression | strong (g20: 81 added-agent tests) | unchecked (Moon has 0 same-O2/P diluent tests, so expect "none + nearest") | unchecked | — | none |
| Scenario coverage | strong (g09: 221 tests, 8 PSIs, High) | strong-medium (g08: 51 tests, 2 PSIs, Medium) | strong honest gap (g10 / g29) | medium (g26: BRE only) | none (g15) |

Notes:
- 10 of the 15 view × scenario dashboards have no golden. `test_golden_checks.py` runs the negative checks on all of them, but nobody has read the outputs. Claude Code prints all 15 for the chat to review before the demo (§4).
- Exploration 8.2 psia (34 %, 56.5 kPa) lies **inside** the Moon base region (≥ 30 %, ≤ 70.3 kPa). Exploration 10.2 psia (26.5 %) lies outside it.

## 2. Question bank
`speak` is quoted or shortened. Numbers are exactly as in the golden.

### Scenario / cross-cutting
| # | question | tool + args | today's answer | strength | golden |
|---|---|---|---|---|---|
| S1 | What do we have for the ISS? | `scenario_coverage(scenario="iss")` | 221 tests in 8 PSIs within 3 points O2 / 10 % pressure; all state nitrogen or air (92 stated once per PSI); High; +74 nearby; 81 more with He / CO2 diluent not counted | strong | g09 |
| S2 | Tests near the Moon base atmosphere? | `scenario_coverage(scenario="moon_base")` | 51 tests in 2 PSIs inside "at least 30 % O2, at most 70.3 kPa" (BRE 31, CFI-G 20); Medium; +26 nearby; O2 partial pressure 16.8–21.1 kPa | strong (medium coverage) | g08, g25 |
| S3 | Anything for the spacesuit? / closest experiment to spacesuit? | `scenario_coverage(scenario="spacesuit")` | ACME inside-out flames, burner O2 up to 85 %: 79 CFI-G + 52 Flame Design tests at ≥ 80 %; closest pressure 2 Flame Design flames, 85 % at 43 kPa (6.2 psia) vs 4.3 psia; chamber held nitrogen and fuel gas; highest atmosphere O2 40 %; BRE 34 % / 8.2 psia = EVA-prep atmosphere, authors: higher O2 + lower P → more stable flames | strong (honest gap) | g10, g16, g28, g29 |
| S4 | What did BRE find at 34 % oxygen and 8.2 psia? | `search_text(query="34 percent oxygen at 8.2 psia", psi="PSI-20")` + `scenario_coverage("exploration_8_2")` | BRE final report p55: at 27 % / 10.2 psia and 34 % / 8.2 psia "the flames mostly persisted for 2 minutes or more as steady"; 29 tests in 1 PSI, Medium | strong finding, thin breadth | g26 |
| S5 | Is there anything at 85 % oxygen? | `scenario_coverage(scenario="high_o2")` | 24 tests with ambient O2 ≥ 40 % in 2 PSIs; burner-stream O2 reaches 85 % in 186 inverse-flame tests (not the atmosphere) | strong (labelled) | g27 |
| S6 | What don't we know for Mars? | `gaps(scenario="Mars")` | No Mars atmosphere, no partial-gravity data; nearest: exploration atmospheres (16 tests at 10.2 psia, 29 at 8.2 psia) | none (honest) | g15 |
| S7 | Custom O2 / pressure (slider) | — | today: gaps-only dashboard (decision item 6) | none | — |

### Prevention (ignition, materials)
| # | question | tool + args | today's answer | strength | golden |
|---|---|---|---|---|---|
| P1 | Open the ignition view (ISS) | `show_view(view="ignition", scenario="iss")` | not reviewed; the gap list says ignition time exists for 11 tests | unchecked | — |
| P2 | Which material ignites fastest? | `query_data(metric="ignition_time_by_material")` | not reviewed | unchecked | — |
| P3 | Rank materials by flame spread / which is safest? | `rank_materials(metric="spread rate")` | "No comparable group … nothing is ranked." Then 6 rows: Saffire-I/II/III fabric 0.98–2.6 mm/s (1–2 tests each), BASS-II PMMA 0.012–0.144 mm/s (18 tests); gap "spread rate alone does not rate fire safety" | thin (honest) | g06, g24 |
| P4 | What is the limiting oxygen of each material? | `rank_materials(metric="limiting oxygen")` | not rankable; no flight finding; normal-gravity card "zero stretch rate limit … 13.4% O2" | none | g07 |
| P5 | Open materials for the Moon base | `show_view(view="materials", scenario="moon_base")` | No Moon tests with materials and spread rate; nearest: ISS (72 tests) | none + pointer | g21 |
| P6 | Compare BASS and BASS-II | `compare(psi_a="BASS", psi_b="BASS-II")` | 121 vs 129 tests; same MSG + SPICE flow duct; both burned Nomex, PMMA, SIBAL; BASS has no O2 or pressure values | thin | g03 |

### Flammability & fire behavior (flame spread, findings)
| # | question | tool + args | today's answer | strength | golden |
|---|---|---|---|---|---|
| F1 | How does flame spread change with oxygen? | `get_findings(x="oxygen", y="spread rate")` | BASS-II, flight vs ground: at 21 % spread is faster in normal gravity, below 19 % faster in microgravity; in microgravity flames still spread at 17 %, in normal gravity no flame at 18 % and below; 23 test points from 4 PSIs | **strong** | g11, g23 |
| F2 | What happens to cool flames when helium is added? | `search_text(query="cool flame", psi="PSI-39")` | On the ISS: more helium → earlier cool-flame extinction, larger extinction diameter (n-dodecane); CFI report p9: cool-flame extinction is controlled by chemical kinetics | **strong** | g18 |
| F3 | Show me the flame spread view | `show_view(view="flame_spread")` | 27 of 2274 tests have spread rate, 0.012–2.6 mm/s, 4 PSIs | thin | g19 |
| F4 | Which material spreads fastest at 30 % oxygen? | `rank_materials(metric="spread rate", scenario="moon_base")` | nothing ranked; no spread test near that scenario; spread tests are at 17.9–22.2 % near ISS (19 tests) | none + pointer | g05 |
| F5 | What is BRE? | `get_investigation(psi="BRE")` | flight investigation; 18 table tests + 157 document points; ambient O2 18–40 %; 57–108 kPa; ethylene and methane | strong (descriptive) | g01 |
| F6 | Compare BRE with FLEX | `compare(psi_a="BRE", psi_b="FLEX")` | different hardware; O2 overlap 18–34 %, pressure overlap 70.2–108 kPa; no numeric ranking | thin | g04 |
| F7 | Flame spread under spacesuit conditions | `show_view(view="flame_spread", scenario="spacesuit")` | not reviewed (Round 5 puts the O2-vs-P chart on every spacesuit view) | unchecked | — |

### Detection (smoke)
| # | question | tool + args | today's answer | strength | golden |
|---|---|---|---|---|---|
| D1 | Why are smoke particles bigger in space? | `search_text(query="smoke particles bigger low gravity")` | flight vs ground: low-gravity smoke ~50 % larger count mean diameter; model: very large particles (> 40 µm); smoke-detector paper p5: at flows of 8.1 cm/s or more (spacecraft ventilation range) sizes are about the same | **strong** (with nuance) | g17 |
| D2 | How does particle size change with oxygen? | `get_findings(x="oxygen", y="particle size")` | "No paper finding relates these two quantities." | none | g12 |
| D3 | Will the detector see the smoke? | `query_data(metric="smoke_particle_size")` | not reviewed; particle size exists for 10 tests (PSI-101) | unchecked (thin) | — |
| D4 | Open the smoke view (ISS) | `show_view(view="smoke", scenario="iss")` | not reviewed | unchecked | — |

### Suppression
| # | question | tool + args | today's answer | strength | golden |
|---|---|---|---|---|---|
| U1 | Open the suppression view for the ISS | `show_view(view="suppression", scenario="iss")` | at ISS O2 / pressure, 81 tests added CO2 or He; 59 have a measured extinction diameter above zero; KPIs: CO2 50, He 31 | **strong** | g20 |
| U2 | Which suppressant works best? | `rank_agents()` | CO2 in FLEX: 123 tests, 5–70 %, 96 with extinction diameter; He in CFI 15 tests, He in FLEX 50 tests; nitrogen = balance gas; amount not in the data | strong data, no "best" (see note B) | g13, g14 |
| U3 | How much CO2 puts a fire out? | `query_data(metric="extinguisher_amount")` | "Extinguisher amount is not supported by the PSI data", then the diluent data | none (honest) | g22 |
| U4 | What did FLEX test? | `get_investigation(psi="PSI-69")` | 274 table tests; O2 12–34 %; 70.2–309 kPa; methanol and heptane; burning rate, extinction diameter, how each test ended | strong (descriptive) | g02 |
| U5 | Suppression for the Moon base | `show_view(view="suppression", scenario="moon_base")` | not reviewed; expect "no added-agent tests" + nearest | unchecked | — |

### Notes found while building the bank (not in the kickoff's 7 items)
- **A. Speak length.** The voice rule is 1–3 sentences, but goldens carry up to 9 speak lines (g06 / g24: 9; g01: 7; g13: 6). The spacesuit answer is 4 lines by decision (Round 5c). Proposal in the decisions file, item 8.
- **B. g13 "Which suppressant works best?"** No speak line says the data does not rank agents. The answer lists agents, which a listener may take as a ranking. Possible fix: a Stage 6 wording change plus a golden, with a first line "The data does not rate one agent as best; these are the diluents the experiments varied." Decision item 8.
- **C. Card statements are spoken verbatim with symbols:** "XO2 = 21%" (g11), "13.4% O2" (g05–g07), "> 40 um" (g17), and the "ﬂ" ligature in g17 line 3. Gemini rewords these when it speaks, and the prompt must keep the numbers. Flag for `VOICE_TEST.md`; no data change.

## 3. Demo script (8 questions, Earth → Moon → spacesuit; about 4 minutes)
Each step uses only golden-checked outputs. The voice speaks the first lines of `speak[]` (item 8); the rest is on screen.

| step | say | tool | screen | the voice should say (from speak) | why |
|---|---|---|---|---|---|
| 1 | "Flameo, what do we have for the ISS?" | scenario_coverage(iss) | answer: 221 / 8 / High, per-PSI table | 221 tests in 8 PSIs near the ISS cabin; coverage High | the data's base |
| 2 | "Why is smoke different in space?" | search_text (g17) | answer: 3 cards (flight vs ground, model, paper p5) | low-gravity smoke particles are about 50 % larger; at ventilation flows of 8.1 cm/s or more, about the same | Detection, flight finding with nuance |
| 3 | "Does more oxygen make flames spread faster?" | get_findings (g11) | answer: 2 BASS-II findings, 23 points | at 21 % faster in normal gravity; below 19 % faster in microgravity; spread at 17 % in microgravity | counterintuitive flight result |
| 4 | "Open the suppression view for the ISS." | show_dashboard → show_view(suppression, iss) (g20) | view: KPIs CO2 50 / He 31 / extinction 59, table | 81 tests added CO2 or helium; 59 with a measured extinction diameter | real dashboard |
| 5 | "What happens to cool flames when you add helium?" | search_text (g18) | answer: CFI cards | on the ISS, more helium → earlier cool-flame extinction | kickoff: cool flames after extinction |
| 6 | "What about a Moon base?" | scenario_coverage(moon_base) (g08) | answer: 51 tests, BRE 31 + CFI-G 20, Medium | 51 tests in 2 PSIs inside the Moon requirement; Medium | step toward the suit |
| 7 | "What did BRE find at 34 percent oxygen and 8.2 psia?" | search_text (g26) | answer: report p55 / p73 passages | flames mostly persisted 2 minutes or more as steady | EVA-prep atmosphere |
| 8 | "And in a spacesuit?" | scenario_coverage(spacesuit) (g10) | answer: KPI pair "atmosphere: none tested" / "oxygen-rich flames: Medium", O2-vs-P chart, gaps | CFI-G and Flame Design flames up to 85 % burner O2; closest 43 kPa vs 4.3 psia; no pure-oxygen atmosphere tested | the honest gap, visible on the chart |

**Backups**, when a judge asks: "How much CO2 puts a fire out?" (U3: not in the data, then the diluent data). "What about Mars?" (S6). "Which material is safest?" (P3: nothing is ranked; spread rate alone does not rate safety).

**Do not demo** until reviewed: P1, P2, D3, D4, F7, U5 (no golden). Step 4 stays on the ISS for the same reason: switching scenario while a view is open re-sends `show_view(view, new_scenario)`, and most of those outputs are unchecked.

## 4. What this plan needs from Claude Code
1. Print all 15 `show_view(view, scenario)` outputs plus `query_data(ignition_time_by_material)` and `query_data(smoke_particle_size)` as speak + kpis + gaps, for the chat to review. Promote the good ones to goldens g30+.
2. `VOICE_TEST.md` rows for the 8 demo steps and the 3 backups.
3. A number check per step: every number spoken is in that answer's `speak[]`.
