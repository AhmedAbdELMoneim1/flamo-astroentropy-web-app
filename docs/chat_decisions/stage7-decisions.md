# Stage 7 — decisions (integration: Flameo agent + frontend ⇄ serving.db / flameo_tools)

_The single place for chat decisions in Stage 7. Claude Code applies every item marked **DECIDED**. Items marked **PROPOSED** are not applied until the team confirms them; this file is then updated in place. New rounds are appended at the end. Use cases and the demo script: `claude/stage7-use-cases.md`._

## Round 0 (2026-11-08)
- Sources read: the kickoff; the Stage 6 handoff and decisions (Rounds 0–5c); `flameo_tools/README.md`; `reports/stage6/{stage6_final, handoff_for_integration, round5_spacesuit}.md`; `moataz-agent/{CONTRACT,HANDOFF}.md`, `src/{tools,data,prompts,categories}.py`, `frontend/src/{CategoryView,AnswerPanel}.jsx`, `widgets/ChartCard.jsx`.
- Paths: `psi_stage1` = `/home/ahmed/Desktop/nasa-multi-agents-stages/s1/s0-results/psi_stage1` (the `s0` copy elsewhere is older; do not use it).
- **Agent + frontend = the `Astro-Entropy` repo, branch `main`** (GitHub `0xMotazMohamed/Astro-Entropy`; local clone `/home/ahmed/Desktop/nasa-multi-agents-stages/AstroEntropy`, commit `6309d84`; pulled to `c8093ae` on 2026-11-08 18:38, frontend-only changes: scenes, `FlameApp.jsx`, `FlameDashboard.jsx`, new `envParam.js` URL scenario). Claude Code works there, not in `~/Desktop/moataz-agent` (an older copy).
- `main` vs `moataz-agent`: the agent is renamed "Flamo"; `src/notify.py` sends every tap as a `[screen]` user turn (`interrupt()` + `generate_reply(user_input=…)`); `prompts.py` adds a "Being a guide / give insight" section and `first_visit` intros; the frontend is `frontend/src/coreSolution/` (`FlameApp`, `FlameDashboard`, `adapters.js`). `adapters.js` already clips to kpis 4 / charts 2 / series 3 / points 12 / rows 12 / gaps 3 and maps unknown coverage to "COVERAGE N/A". `tools.py` (`show_dashboard`, `query_data` with 5 mock metrics) is the same apart from `first_visit`.
- `flameo_tools` and `serving.db` do not change unless an item says so. Such a change is a Stage 6 config / registry change plus a golden question (README §6).
- Ops: the computer's disk is too full for the local shell (it needs up to 17 GB free). Free space before Claude Code works there.

## Round 1 — the 7 mismatches (kickoff §3) + one more: DECIDED (2026-11-08 18:07, user: "yes" to all proposals as written; "Alternative (not proposed)" lines are rejected)

### 1. Size limits → an adapter in the agent, plus one contract change for the O2-vs-pressure chart
Facts:
- The contract allows: < 8000 bytes, table ≤ 6 columns / ≤ 12 rows, gaps ≤ 3, charts 1–3 series of ≤ 12 points.
- `flameo_tools` returns: tables ≤ 20 rows with up to 11 columns (rank_agents); gaps up to 6 (g22); KPI `basis` strings up to ~250 characters; `cards[]`.
- The O2-vs-pressure scatter has 8 series and about 675 points (round5 §chart). On `main`, `coreSolution/adapters.js` draws at most 3 series × 12 points and turns a bar chart into a ranking, sorted by value (`ranking`). That sort must not be used for flameo bars: Stage 6 forbids rankings outside one comparable group.

Proposal:
- **New `src/adapter.py`** with `to_dashboard(d)` and `to_answer(a)`. Pure functions, unit-tested. The adapter never computes a new number; it only selects:
  - table: keep `table_key` and the columns listed per view / tool in an adapter map (≤ 6); first 12 rows in flameo's order; footer "12 of N rows" when cut (N from the original table).
  - cell text over 80 characters is cut at a word boundary with "…" (display only; speak is never cut). Example: g20 `test_end`.
  - gaps: the first 3, in flameo's order (the first gap is the answer when there is one).
  - cards: the first 3, with `statement`, `wording`, `evidence_basis`, `paper`, `page` (no quote).
  - KPIs: keep `basis` and `trust` (the handoff says show both); the frontend shows them as a tooltip / sub-line.
  - Charts: ≤ 2; bar / line ≤ 12 points per series and ≤ 3 series (the first ones), with "showing 12 of N".
  - Check: `len(json.dumps(x)) < 8000`. If it fails, drop cards, then table rows, from the end, and log it.
- **The O2-vs-pressure scatter is a static chart, not packet data.** It does not depend on the question. `api.py` serves it once at `GET /api/charts/o2_vs_pressure`, built at start-up from flameo's own chart (`scenario_coverage("spacesuit").charts`, unchanged, all points). The Dashboard / Answer carries `{"id":"o2_vs_pressure","type":"scatter","ref":"/api/charts/o2_vs_pressure","title":…}`. The frontend fetches by `ref` and draws all series (≥ 8 colours; hollow markers for the burner stream; labelled scenario points). Contract change: charts may carry `ref` instead of `series`.
- Alternative (not proposed): bin the points into an O2 × P grid. Rejected: it creates counts that flameo did not produce.

### 2. Spacesuit coverage → coverage comes from flameo; two labels for the spacesuit
Facts:
- `categories.py` hardcodes iss High, moon_base Medium, spacesuit Low. The prompt says "Spacesuit … Coverage Low".
- On `main`, `coreSolution/adapters.js` maps coverage through `COVERAGE_BADGE` (High / Medium / Low; anything else → "COVERAGE N/A").
- Real data: iss High (221), moon_base Medium (51), spacesuit atmosphere None, `level_oxygen_rich_flames` Medium. The ground rule is never to say "spacesuit coverage".

Proposal:
- `categories.py` reads the coverage levels at start-up from `scenario_coverage(...)` (`level`; and for the spacesuit `level_oxygen_rich_flames`). No hardcoded levels.
- Contract: `coverage` ∈ `"High" | "Medium" | "Low" | "None" | null`. `"None"` = a named scenario with no tests. `null` = custom conditions. New optional `coverage_note`:
  - `{"label": "Oxygen-rich flames (burner stream, not the atmosphere)", "level": "Medium"}`, sent for the spacesuit only.
- Badge text:
  - normal: "Data coverage: High".
  - spacesuit: "Spacesuit atmosphere: none tested", plus a second chip "Oxygen-rich flames (burner stream): Medium". Never "Data coverage: None".
- Prompt scenario line for the spacesuit: "no test in this atmosphere; the nearest data are oxygen-rich burner flames (ACME CFI-G and Flame Design). Never call it coverage."

### 3. Extra scenarios → three buttons stay; the others are voice-only, shown as answer cards
Facts:
- The challenge path is Earth → Moon base → spacesuit, the three UI buttons.
- Real data adds `exploration_10_2`, `exploration_8_2` and `high_o2`; Mars / partial gravity are gaps only. Exploration 8.2 lies inside the Moon region.

Proposal:
- The UI keeps `iss`, `moon_base` and `spacesuit` as the only scenario buttons and state values.
- The other scenarios are voice-only. The tools answer them by name (`scenario_coverage("exploration_8_2")`, `gaps("Mars")`), and the answer appears in the answer panel (`answer.show`). `DashboardState.scenario` does not change.
- The `gravity` input: see item 6.
- flameo's `gaps` view gets no tab. "What don't we know?" → `gaps()` → answer panel.

### 4. Answer fields → the adapter adds `request_id`, keeps the flameo fields
- Add `request_id` (8 hex, new per call).
- Set `metric`: the mock metric for a `query_data` call, otherwise the tool name.
- Keep `tool`, `question`, `version`, `speak`, `source` (with `refs`). Unknown keys are ignored by the frontend (contract: additive).
- Drop `facts` from the packet: it is for the number check, and the agent keeps it server-side.
- `source.mock` is false, so `MockBadge` hides. Remove the "Mock: …" notice and the "say once it is demo data" prompt line.
- **Dashboard → `view.open`**: `headline` / `key_points` from flameo; `dashboard` = `to_dashboard(show_view(...))`.

### 5. Tools exposed to Gemini → 8 explicit intent wrappers + `show_dashboard`; drop `query_data`
Facts:
- Gemini Live blocks while a tool call is pending.
- A long system prompt plus tool list slows the first reply (the plugin's fixed 5-second `generate_reply` wait).
- flameo calls take milliseconds to a few tenths of a second.

Proposal:
- **Register 8 agent tools**, one per intent: `get_investigation`, `compare`, `rank_materials`, `scenario_coverage`, `get_findings`, `rank_agents`, `gaps`, `search_text`.
  - Each is an explicit `@function_tool` with typed arguments and the flameo docstring (copied from `tool_specs()` by a small generator script, and checked in a test so they cannot drift).
  - Each call: `asyncio.to_thread(flameo_tools.call, …)` → `to_answer` → `answer.show` → return to the model.
- **`show_dashboard` stays** (the view / pillar logic, `conditions.set`, state). Its content now comes from `show_view(view, scenario)`. flameo's `show_view` is not registered separately.
- **Drop `query_data`** and the flameo `get_dashboard` / `query_data` wrappers from the model's tool list. Routing by "metric" adds a guess step that the intent tools make unnecessary. The 5 mock metrics map to tools: ignition time → `show_dashboard("prevention", "ignition")` (the view; output not reviewed yet, use cases P1 / P2), material ranking → `rank_materials`, spread vs oxygen → `get_findings`, smoke particle size → `search_text` / `get_findings`, extinguisher amount → `rank_agents`.
- **What the model gets back** (small): `{status, speak: speak[:n], first_gap, level / coverage, nearest, note}` with `n` from item 8. Never the table, charts or cards.
- The prompt adds at most 10 router examples from `router_examples.yaml`. The rest is left to the docstrings.
- Total tools for Gemini: 8 intent + `show_dashboard`, `set_conditions`, `get_dashboard_state`, `get_mission_context`, `add_mission_note`, `declare_fire_emergency`, `clear_fire_emergency` = 15. Check in the `VOICE_TEST.md` 1007 / timeout count. If the first reply is slow, merge `compare` into `get_investigation(psi, psi_b=None)` (agent side only).
- Alternative (not proposed): keep `query_data(metric)` and route inside it. Fewer tools, but it covers 5 of the ~25 bank questions.

### 6. Custom conditions → all-data view + the user's point on the O2-vs-pressure chart; no new numbers
Facts:
- flameo has no tool for an arbitrary (O2, pressure) point; `scenario_coverage` takes named scenarios.
- Computing "nearest tests" in the agent would create numbers flameo did not produce.

Proposal (demo):
- Custom conditions → `show_view(view, scenario=None)` (all PSI data, as in g19), headline prefixed "All PSI tests (not filtered to your conditions)". Also the static O2-vs-pressure chart with the user's point drawn by the frontend from `inputs` (no new number). One gap: "Coverage is rated only for the ISS, Moon base and spacesuit atmospheres."
- `coverage` null. The voice says no number for custom conditions.
- Inputs that promise filtering that does not exist:
  - `gravity`: lunar / martian → the gap "No PSI investigation tested combustion in partial gravity" (from flameo `gaps`).
  - `airflow_cm_s` and `material`: hide in the demo (no tool uses them).
- Later, optional: a flameo tool `nearest_tests(o2_pct, pressure_kpa)` using the Stage 6 near / nearby tolerances. Stage 6 registry change + 2 goldens. Not before the demo.

### 7. Unsupported mock metrics → UI copy and the prompt promise only what the data has
- With item 5, `extinguisher_amount` and `material_ranking` are no longer tool arguments. The questions still reach `rank_agents` / `rank_materials`, which already say "not in the data" / "nothing is ranked" (g22, g06).
- Copy changes in `categories.py` (taglines, `focus_options`, background) and the `show_dashboard` docstring:
  - suppression: tagline → "How flames die out, and which gases the experiments added to stop them"; focus_options drop "extinguishers", "water mist", "limits"; add "added carbon dioxide / helium", "extinction".
  - materials: tagline → "How fast flames spread on tested materials" (drop "which burn faster, slower, or self-extinguish": no ranking, no limiting O2); drop focus "ranking".
  - `background` strings are general text, not data. **Remove them from the briefing** (changed at the Round 3 close, for consistency with A-1: the voice uses no general background in any answer).
- The prompt adds a never-say list: "safest / safer", an extinguisher amount, a Mars number, spacesuit "coverage", "on the ISS" for non-flight findings.

### 8. (new) How much of `speak[]` the voice says
Facts:
- Ground rule: 1–3 sentences.
- Goldens have up to 9 speak lines. The spacesuit answer is 4 lines by decision (Round 5c).
- The handoff says not to strip the mandatory caveats.

Proposal:
- The voice says `speak[:3]` (`speak[:4]` for spacesuit answers) and points to the screen. The screen shows all lines.
- Add a check in the agent tests: for each golden, every mandatory caveat (the "No … in the PSI data" sentence, "nothing is ranked", "not supported by the PSI data", the spacesuit lines) is in the spoken prefix.
- Known failure to fix in flameo (Stage 6 wording + golden): g13 / g14 "Which suppressant works best?" has no line saying the data does not rate one agent as best. Add it as line 1.

## Round 2 — a random question: what the agent does and how it queries: DECIDED (2026-11-08 18:07, user)

### What happens today (`main` @ 6309d84)
1. **No router code.** Gemini Live hears the audio and decides by itself (native function calling) whether to call a tool, using the system prompt and the tool docstrings. The tools are `show_dashboard`, `set_conditions`, `get_dashboard_state`, `query_data`, `get_mission_context`, `add_mission_note` and `declare_fire_emergency` / `clear_fire_emergency`.
2. **A data question** → `query_data(metric)`, the closest of 5 mock metrics → a dict lookup (`ANSWERS[metric]`). If no metric fits, the prompt says: "say there is no data view for that yet and offer the closest metric".
3. **A free question** ("why do flames look round in space?") → no tool fits, so **Gemini answers from its own knowledge.** The prompt's "Give insight, not just data … say in plain words what they mean for the crew's safety and what to do about it" pushes it to add advice from no source. The number rule ("only numbers from `kpis` / `speak`") does not cover claims without numbers.
4. **Off-topic and unsafe questions:** the prompt says nothing, apart from "only give fire-safety guidance for safe and lawful purposes".
5. **There is no query language anywhere.** The "query" is Gemini choosing a tool and its arguments.

This breaks ground rule §5 of the kickoff (scientific wording from the data and documents, never guessed) as soon as a question falls outside the tools.

### Proposal A: an answer ladder (the prompt + tool docstrings carry it; code enforces it where it can)
The model takes the first step that fits. One tool call per question.

| step | kind of question | example | action | the voice says |
|---|---|---|---|---|
| 0 | active fire / smoke / smell now | "I smell burning" | `declare_fire_emergency` first, always | the fixed first steps only |
| 1 | screen / navigation | "open smoke", "switch to Moon base", "go back" | `show_dashboard` / `set_conditions` / `get_dashboard_state` | from `speak[]` / kpis |
| 2 | a question one intent tool answers | "what is BRE?", "which suppressant works best?" | that tool (Round 1 item 5) | `speak[]` |
| 3 | **any other fire, combustion or space-fire question** | "why are flames round in space?", "what is soot?" | **`search_text(query=3–6 English key words, psi if named)`** | the cards / passages in `speak[]` ("the authors report …", "From <document>, page N: …") |
| 4 | step 3 found nothing (`matched: false`) | "how hot does a flame get on the Moon?" | no second guess from memory | the "open research question" template (Round 3 §3.7), then offer one topic the data does cover (from the pillar list) |
| 5 | mission, log | "note that I checked the extinguisher" | existing tools | — |
| 6 | off-topic | "what's the weather on Mars?" | no tool | one sentence back to fire safety |
| 7 | unsafe / harmful | "how do I start a fire in my room?" | no tool | a short decline |

Rules on top of the ladder:
- **Missing scenario:** use the scenario on screen and say which one ("for the ISS, …"). Ask only when nothing can fill the gap ("compare them" with nothing named before).
- **Follow-up** ("and on the Moon?"): the same tool again with the changed argument.
- **Language:** the voice answers in the astronaut's language (prompt rule). `search_text` keywords are always English, because the corpus is English. Numbers stay as in `speak[]`.
- **Fire-response questions** ("can I use water on an ISS fire?"): if `search_text` finds nothing, the answer is step 4 plus "follow your mission fire procedure". Never an improvised procedure.
- **A-1 DECIDED (Round 3 §3.6):** step 4 is "not covered", with no background sentence, worded as an open research question (templates in §3.7).

### How the query runs (no text-to-SQL)
```
astronaut speaks
  → Gemini Live picks ONE function call {name, args} from the docstrings (+ ≤ 10 router examples in the prompt)
  → agent wrapper: asyncio.to_thread(flameo_tools.call, name, **args)
  → flameo_tools: fixed, parameterised SQL / FTS5 on serving.db (read-only), a few ms
  → Answer JSON (speak[], kpis, table, cards, gaps, facts)
  → adapter → answer.show to the screen (always, even if the voice fails)
  → model gets {status, matched, speak[:3], first_gap, coverage / level, nearest}
  → the voice says those lines in its own words, every number kept
```
How `search_text` matches (read from `flameo_tools/tools.py`):
- It keeps words longer than 2 letters that are not stopwords.
- It runs an FTS5 search with AND, and with OR if AND finds nothing. Results are ranked.
- It keeps a passage only if its best sentence holds at least half of the words. It takes up to 2 cards first, then up to 3 sentences from documents.
- Otherwise it says "No passage in the documents, papers or cards matches that."

A full spoken sentence therefore matches worse than a few key words, so the docstring must ask for **3–6 key English words**. A one-word query ("soot") matches anything with that word.

### Code changes (for Claude Code)
1. **`prompts.py`:**
   - Replace "For a data question … call `query_data` with the closest metric …" with the ladder (steps 0–7 and the rules), in short lines.
   - **Remove** "Give insight, not just data … what to do about it". Keep "offer ONE next step", worded as another question the data can answer, never advice.
   - Remove the demo-data lines once real data is in (Round 1 item 4).
2. **`search_text` wrapper:**
   - Docstring: "Default tool for any fire, combustion or space-fire question that no other tool answers. Pass 3–6 English key words (nouns and the effect asked about), plus `psi` if an investigation is named. Never answer such a question from memory."
   - Return `matched: false` when the answer is "No passage … matches".
3. **One retry:** when `matched` is false, the model may call `search_text` once more with synonyms (each call takes milliseconds, so it is safe with Gemini's pending-tool blocking). After that, step 4.
4. **Question log:** each turn appends `{ts, transcript, tool, args, matched}` to `logs/questions.jsonl`, with no audio and no keys. This lets the team see real routing in `VOICE_TEST.md` runs and add router examples where Gemini picks badly.
5. **Offline check:** run `search_text` for the 12 free questions below and print `speak[]` for the chat to review. Good outputs become goldens g30+; misses decide whether a question is step 4 or needs a router example.

### Free-question test set (route expected; answer not yet known unless a golden is named)
| question | expected route | known today |
|---|---|---|
| Is it true fire spreads faster in space? | `get_findings(oxygen, spread rate)` | g11: below 19 % O2 faster in microgravity |
| Why are smoke particles bigger in space? | `search_text("smoke particles bigger low gravity")` | g17 |
| Why do flames look round in space? | `search_text("flame shape spherical microgravity buoyancy")` | — |
| What is soot? / when does soot form? | `search_text("soot formation")` | — |
| What is a cool flame? | `search_text("cool flame")` | g18 (PSI-39) |
| Can I use water on a fire on the ISS? | `search_text("water mist extinguish")` → likely step 4 + "follow your mission fire procedure" | — |
| How hot does a flame get? | `search_text("flame temperature")` | — (numbers only if in a passage) |
| What happens to a candle on the Moon? | `gaps("partial gravity")` | "No PSI investigation tested combustion in partial gravity" |
| Which experiment had the most tests? | no tool → step 4 | — |
| What's the weather on Mars? | step 6 | — |
| How do I start a fire in my room? | step 7 | — |
| ما هو اللهب البارد؟ (Arabic: "what is a cool flame?") | `search_text("cool flame")`, answer in Arabic | g18 |

## Round 3 — finalize: no hardcoded content, category entry, voice per phase, ranking: DECIDED (2026-11-08 18:04; decisions in 3.6, wording in 3.7)

### 3.0 What is hardcoded on `main` today (all of it goes)
| where | hardcoded | problem with real data |
|---|---|---|
| `frontend/src/coreSolution/FlameDashboard.jsx` `CONFIG.cats` | per-category table columns (heatFlux, delay, obscuration, timeToAlarm, limit, timeToOut …), sliders (heat flux, thickness, smoke concentration, particle size), chart axes ("Ignition delay vs heat flux", "Obscuration vs particle size", "Time to out vs limiting O2") | none of these fields are in `serving.db` |
| same, suppression `chips` | "Water mist .55, Nitrogen .75, CO2 .9" `suppress` values | invented effectiveness numbers |
| same, `rankingTitle` | "Easiest to ignite", "Fastest-burning materials", "Densest smoke sources", "Most effective suppressants" | rankings the data cannot make (Stage 6: no ranking across PSIs, never "safest") |
| same, `buildDemoData()` | random rows, random ranking scores, random **"Risk ranking"** across categories | random numbers on screen |
| same, "AI interpretation / HOW TO READ IT / SAFETY TAKEAWAY" | filled from `key_points` / gaps, or demo text | "safety takeaway" invites advice nobody checked |
| `coreSolution/adapters.js` | bar chart → `ranking` sorted by value | turns any bar chart into a ranking |
| `src/categories.py` `intro` | e.g. materials: "which materials catch fire quickly, which burn slowly and which put themselves out"; suppression: "extinguishing agents, shutting down airflow, and the limits and risks of each" | promises data that is not there |
| `src/categories.py` coverage, `src/mock_data.py`, the prompt's demo-data lines | mock | replaced (Round 1 items 2 and 4) |

**Rule for the final build:** every number, ranking, chart and table on screen comes from a `flameo_tools` answer. The only fixed text left: category names, written intros (3.2) and suggested questions (3.2), all reviewed and with no numbers.

### 3.1 One dashboard layout for every category, filled from real data
Every category (Prevention, Flammability, Detection, Suppression) uses the same panels. A panel with nothing to show is hidden (the existing `secOn` logic).

| panel | replaces | filled from |
|---|---|---|
| **Summary strip** | summary | scenario name + data-level badge (Round 1 item 2) + the first KPI of the current content |
| **Most relevant investigations** | "Easiest to ignite" etc. and "Risk ranking" | `rank_investigations(pillar, scenario)` (3.4). Always shown for the category. |
| **Chart** | fixed axes | the content's `charts[0]` with its own axes and title. The O2-vs-pressure chart comes by `ref` (Round 1 item 1). |
| **Data table** | fixed columns | the content's `table`, through the adapter |
| **What the authors report** | "AI interpretation" | `cards[]` / card lines in `speak[]`, with evidence wording ("on the ISS, the authors report …"). This is the "interprets" part of the challenge, taken from the sources. |
| **Open questions: not in the data yet** (3.7) | "Safety takeaway" + "Data gaps" | `gaps[]` (first 3), with the footer from 3.7 |
| **Ask me** (new) | — | 3 suggested questions as chips (3.2). A tap sends the question as if spoken. |

Two states per category:
- **Overview** (on entry): `show_view(<category view>, scenario)` + `rank_investigations(pillar, scenario)`.
- **Answer** (after a question): the answer's KPIs, chart, table, cards and gaps replace the overview panels; the ranking panel stays; a chip "Back to <category> overview".

Sliders and chips:
- Keep only oxygen and pressure (they set custom conditions, Round 1 item 6).
- Remove heat flux, thickness, smoke concentration, particle size, flow and gravity sliders, and the material and suppressant chips: no tool uses them.
- Gravity is shown as fixed text: "Microgravity (PSI has no partial-gravity data)".

### 3.2 Category entry (first visit and later visits)
Prevention has two backend views (`ignition`, `materials`). The category overview uses `materials`; ignition is reached by a question until its output is reviewed (use cases P1).

| category | overview content | intro (spoken on the first visit; no numbers) | "Ask me" chips (golden-backed) |
|---|---|---|---|
| Prevention | `show_view("materials", sc)` + ranking | "Prevention is about what can catch fire. The flight tests burned fabrics and plastics such as SIBAL, Nomex and PMMA in BASS, BASS-II and the Saffire experiments. Ask me about a material, an investigation, or how oxygen changes burning." | "Rank materials by flame spread" (g06) · "Compare BASS and BASS-II" (g03) · "What is BRE?" (g01) |
| Flammability & Fire Behavior | `show_view("flame_spread", sc)` + ranking | "This is how a fire behaves once it starts. The flight tests measured how fast flames spread, and how that changed with oxygen and air flow. Ask me, for example, whether fire spreads faster in space." | "Does fire spread faster in space?" (g11) · "What is a cool flame?" (g18) · "Show me the flame spread data" (g19) |
| Detection | `show_view("smoke", sc)` + ranking | "Smoke is usually the first warning. SAME and SAME-R measured the smoke from overheated spacecraft materials on the station. Ask me why smoke is different in space." | "Why are smoke particles bigger in space?" (g17) · "What is SAME-R?" (no golden yet) · "How does particle size change with oxygen?" (g12, honest "no finding") |
| Suppression | `show_view("suppression", sc)` + ranking | "This is about putting a fire out. FLEX and CFI burned fuel droplets while carbon dioxide or helium was added to the chamber. Ask me which gases the experiments tried, or what happens to cool flames." | "Which gases did the experiments add?" (g13) · "What happens to cool flames with helium?" (g18) · "How much CO2 puts a fire out?" (g22, honest "not in the data") |

Every name and material in the intros is in the registry or a golden (g03, g06, g13, g18; registry rows PSI-101 / PSI-102). The intros replace `View.intro` in `categories.py`. Chips: a new `suggestions[]` in the `view.open` payload (from `categories.py`). A tap sends a new event `question.asked {text}`, which the agent delivers as a normal user turn (not a `[screen]` note).

### 3.3 Voice experience per phase: the agent always says what it shows and what to do next
Principle: each phase ends with one clear action for the astronaut ("pick a topic", "ask me …", "tap a question"). Numbers only from the tool result of that phase.

| phase | trigger | screen | the voice says |
|---|---|---|---|
| 1. Opening | session start | opening scene | "Hi, I'm Flamo. I answer from NASA's microgravity fire experiments. Pick one of the four topics on the screen, or just ask me a question." (once per session) |
| 2. Spacecraft (ISS) | scene / scenario `iss` | spacecraft scene; overall ranking `rank_investigations(None, "iss")` | `scenario_coverage(iss)` speak[0] (221 tests, 8 PSIs) + "Coverage is High." + "Pick a topic, or ask me something." |
| 3. Moon habitat | scenario `moon_base` | habitat scene + overall ranking | g08 speak[0–1] (51 tests in 2 PSIs inside the requirement; Medium) + "BRE tested these atmospheres; ask me what it found." |
| 4. Spacesuit | scenario `spacesuit` | suit scene + O2-vs-pressure chart | g10 speak[0] and [2] (CFI-G / Flame Design up to 85 % burner oxygen; no pure-oxygen atmosphere tested) + "The chart shows how far the suit is from every tested condition." |
| 5. Category entry, first visit | tap or voice | overview (3.1) | the intro (3.2) + overview speak[0] + "For example, ask me: <chip 1>." |
| 6. Category entry, later visits | tap or voice | overview | overview speak[0] + "Ask me anything about <category>." |
| 7. After an answer | any question tool | answer state | speak[:3] (Round 1 item 8) + "The details are on the screen." + one follow-up from a fixed table per tool (e.g. after `scenario_coverage` → "Do you want the most relevant investigations for it?"; after `search_text` → "Do you want the data behind it?") |
| 8. Not covered | `matched: false` / "No …" answer | "Open questions" panel | the §3.7 template for that kind of gap + one chip-style offer |
| 9. Custom conditions | oxygen / pressure slider | all-data overview + the user's point on the chart | silent while sliding; once settled: "These are custom conditions. Data is rated only for the ISS, Moon base and suit; the chart shows where your point sits among the tested conditions." |
| 10. Emergency | fire reported | alert banner | unchanged: fixed first steps, one at a time |
| 11. Silence after entry (optional, D3-3) | 20 s without speech after phase 5 | — | once per category: "You can tap a question, or ask me something like <chip 2>." |
| 12. Misheard / error | — | — | unchanged ("Sorry, could you say that again?"); after a reconnect: "I lost the connection for a moment, I'm back." |

Code:
- `events.py` builds the scene / category messages with the phase name and the tool `speak[]`.
- `prompts.py` gets one table "phase → what to say → the action to end with", replacing "Being a guide / give insight" (Round 2).

### 3.4 Ranking (the challenge's "summarizes, **ranks**, and interprets … investigations")
The challenge asks to rank **investigations** by relevance ("Identify investigations most relevant to the fire safety needs of habitable crew environments … spacecraft, space stations, bases … pressurized rovers"). It does not ask for a material safety ranking, which Stage 6 rules out anyway. So:

**R1. New flameo tool `rank_investigations(pillar=None, scenario=None)`** (Stage 6 registry change + goldens; `serving.db` content unchanged):
- **Candidates:** PSIs whose registry "Pillars / questions" text names the pillar:
  - prevention → "Prevention"
  - flammability → "Fire behavior" or "Environment"
  - detection → "Detection"
  - suppression → "Suppression"

  No pillar → all PSIs.
- **Sort, lexicographic, each key shown on the row** (no weighted score, so no invented number):
  1. the relevance tier from the registry (A > B > C > M);
  2. flight before ground;
  3. tests near the scenario (from `scenario_coverage`), or tests in the data when no scenario is given;
  4. accepted findings (cards) for the PSI, flight cards first.
- **Row:** rank, investigation name ("FLEX (PSI-69)"), tier, the pillar words, tests near the scenario (or "no oxygen / pressure recorded"), findings. **Bar length = tests near the scenario** (a real count, labelled "[n tests]"). Never a 0–100 score.
- **speak:** "For Suppression near the ISS cabin, the most relevant investigations are … ranked by the registry tier, then by tests near the scenario." Gap line: "This ranks relevance to the question; it does not rate how safe anything is."
- **Goldens:** one per pillar for `iss`, one per scenario with no pillar, and the spacesuit (never "coverage").
- If `config/psi_registry.yaml` lacks the tier column, add it from `psi-registry-tiers.md` (config change).

**R2. Where it shows:**
- In each category: the "Most relevant investigations" panel (3.1).
- On each journey scene (phases 2–4): the overall ranking for that scenario.
- By voice: "Which experiments matter most for the Moon base?" → `rank_investigations(scenario="moon_base")`. This is router step 2, and it is registered with the other intent tools (Round 1 item 5).

**R3. What is not ranked:**
- Materials: `rank_materials` stays a comparison table, titled "Flame spread in the tested materials (not a safety ranking)".
- Suppression gases: `rank_agents` stays a list, titled "Gases added in the experiments".
- The frontend never sorts a bar chart into a ranking: remove the bar → `ranking` path in `adapters.js`. `ranking` comes only from `rank_investigations`.
- Remove the cross-category "Risk ranking".

### 3.5 Per question: what the dashboard shows
Each answer carries `pillar` (fixed map per tool; `null` for `search_text`, `compare`, `get_investigation`, `gaps`). If it differs from the category on screen, the frontend switches to that category and opens the answer state there (D3-2).

| tool | pillar | panels filled |
|---|---|---|
| `scenario_coverage` | — (journey) | summary (level badge), table per PSI, ranking for the scenario, O2-vs-P chart for the spacesuit |
| `rank_investigations` | its argument | ranking panel |
| `get_investigation` | — | summary KPIs, table of fields (test points per field) |
| `compare` | — | side-by-side table, gaps |
| `rank_materials` | prevention | comparison table (not a ranking), gaps, authors' cards |
| `get_findings` | from `y` (spread → flammability, particle size → detection, extinction → suppression) | authors' cards, table, KPI |
| `rank_agents` | suppression | table of gases, KPIs, gaps |
| `gaps` | — | gaps panel, table |
| `search_text` | — | authors' cards / passages (document title, page) |
| `show_dashboard` → `show_view` | the view's pillar | the overview |

### 3.6 Team decisions (2026-11-08 18:04, user)
- **D3-1 DECIDED: the registry tiers are final.** `rank_investigations` uses the A / B / C / M tiers from `psi-registry-tiers.md` as its first sort key. The row label reads "relevance tier (from the official PSI description)".
- **D3-2 DECIDED: the dashboard follows the question.** When an answer's `pillar` differs from the category on screen, the frontend switches to that category and opens the answer state.
- **D3-3 DECIDED: silence nudge yes**, once per category (phase 11).
- **A-1 DECIDED: "not covered", with no background sentence, worded as an open research question** (3.7).

### 3.7 "Not covered" is worded as an open research question (A-1)
The voice never fills a gap from memory, and never ends on a flat "no". A gap is presented as a place where research is still needed. This fits the challenge's aim of showing what the data can and cannot answer.

Spoken templates (fixed text, no numbers; the agent picks one by the kind of gap):
- **No passage matched** (Round 2 step 4): "That isn't covered in the PSI data or papers yet. It's an open question; answering it would need new experiments or papers on it. I can tell you about <offer> instead."
- **A metric the data does not hold** (extinguisher amount, material ranking, limiting oxygen across materials): flameo's own "not supported / nothing is ranked" line, then "The experiments didn't measure that directly, so it's still a gap for future research. Here is what they did measure."
- **A scenario with no tests** (spacesuit atmosphere, Mars, partial gravity): flameo's own gap line, then "That's one of the open gaps in the data."
  - For partial gravity only, add the sourced line from `challenge-details.txt`: "Such data is expected in the future, for example from the LUCI and FM2 experiments."
  - Put this line in flameo's `partial_gravity_text` (Stage 6 config change + the golden g15 must-contain), not in the prompt. No other future experiment may be named unless a source names it.

Screen:
- Rename the gaps panel "**Open questions: not in the data yet**".
- Each gap keeps flameo's text. The panel footer reads: "Gaps like these show where new experiments or papers are needed."

Never:
- say or imply that a study "is planned" or "is under way" without a source;
- guess why the gap exists;
- apologise repeatedly.

One short, motivating sentence, then the offer.

## Round 4 — STOP 1 review (Part A prints): DECIDED (2026-11-08, chat review of `reports/stage7/review_prints.md` + `partA_report.md`; the user confirms it by sending Claude Code the "continue" message)

**Accepted:**
- `rank_investigations` as built for pillar rankings, and the `for_scenario` key in place of `scenario` (the frontend reads `for_scenario`).
- The LUCI / FM2 line, the g13 / g14 first line, goldens g30–g40, and the rebuild (469 tests pass).

The items below are fixed before or in Part B.

### 4.1 Scenario rankings: "has tests here" comes before the tier (rankings with no pillar only)
Problem: with tier first, rankings for a scenario put tier-A investigations with no tests there above those that have them:
- g35 Moon base ranks FLEX and BASS-II (no tests near the Moon base) above CFI-G (20 tests);
- g39 spacesuit ranks FLEX first with no burner-stream tests at all.

Rule, for `rank_investigations(scenario=…)` **without a pillar** (journey scenes, "which experiments matter most for the Moon base?"):
1. **Ranked group:** PSIs with at least one test near the scenario. For the spacesuit: at least one burner-stream test at 80 % O2 or more. Sorted by tier, flight, tests near the scenario, findings, as before.
2. **Unranked list below a divider** "No tests at these conditions", in tier order with no rank number. It holds the PSIs that have no tests there, and those with "no oxygen / pressure recorded" (label kept on the row).

The tiers stay final (D3-1); this only adds a "has data here" key in front of them for scenario-level rankings.

**Pillar rankings are unchanged** (tier first, tests as the tie-break). g30–g33 read well: Detection → SAME, SAME-R first; Suppression → FLEX, BASS, CFI.

Expected after the fix (goldens updated):
- g35 Moon base: BRE (31), CFI-G (20), then the divider;
- g36 / g37: BRE only;
- g38 high_o2: the PSIs with ambient ≥ 40 % tests;
- g39 spacesuit: CFI-G and Flame Design, with the "not the atmosphere" line;
- g34 ISS: the PSIs with near tests (BASS-II, FLEX, BRE, Saffire-I / II, CFI …), then the divider (SAME, SAME-R, BASS … "no oxygen / pressure recorded").

speak line 1 for a scenario ranking names only ranked PSIs. If the ranked group is empty: "No investigation has tests near the <scenario>", plus the §3.7 template.

Grammar: "1 test", not "1 tests" (`tests_label`). Add the shared negative check.

### 4.2 `show_view` gap and speak noise (Stage 6 wording bug, fix in `flameo_tools`)
- **Drop internal lines from `gaps[]`:**
  - "chart '…' has no points near <id>";
  - "no test rows for this view near <id>";
  - the bare "no tests near <id>".

  They are developer messages. Keep them in a separate `debug[]` key if useful; never show or speak them.
- **Doubled words:** fix "near the the spacesuit atmosphere atmosphere" (the label is wrapped twice), and "at the the spacesuit atmosphere oxygen and pressure".
- **De-duplicate** `gaps[]` (exact text).
- **All-zero sentence:** when every metric of a view is zero near a scenario, speak one sentence, "No <view label> tests near the <scenario label> in the PSI data." (e.g. "No flame spread tests near the Moon base habitat atmosphere in the PSI data."), instead of listing joined metric names ("a measured flame spread rate, flame spread rate and flame spread tests"). The nearest pointer stays.
- **New shared negative checks** on speak, gaps and KPI labels:
  - no doubled word ("the the", "atmosphere atmosphere");
  - no raw scenario ids (`moon_base`, `spacesuit`, `iss` as words);
  - no "chart '" and no "test rows".

### 4.3 `search_text` quality (fix in `flameo_tools`)
Seen in Q1, Q3, Q4, Q5, Q6, Q8 and Q9:
- **Copies:** the same sentence comes from 3 PSIs' copies of one document (Q6 ×3, Q3 p33 / p44, Q9 ×3). Keep the first; list the other PSIs in the table row only.
- **Junk passages:** drop a passage if its chosen sentence:
  - contains "DOI", "Received", "Accepted", "Article history", "www.", "Vol.", "et al." followed by a year, dot leaders (`.....`), an affiliation ("Department of", "University," …) or 3 or more "•" bullets; or
  - is a page-1 author / title block.

  Then take the next qualifying passage.
- **Sentence start:** the spoken sentence must start with a capital letter or a digit. When the best sentence starts mid-sentence ("that for all the diameters …"), use the next full sentence in that passage, or skip the passage.
- **Order:** cards first (as now). Document lines only fill up to 3, and never repeat a card's content.
- **Goldens:**
  - Q3 "flame shape spherical microgravity buoyancy" (no duplicate lines);
  - Q5 "cool flame" (line 3 is not the author block);
  - Q6 "water mist extinguish" (one line, the ISS Researchers Guide p26).
  - Each with must-not-contain: "DOI", "Received", "Department of", a repeated sentence.

### 4.4 Routing (prompt + `router_examples.yaml`)
- **Off-topic and unsafe questions** (ladder steps 6–7) are decided **before any tool call**. The prompt says so explicitly: "Never call `search_text` for an off-topic or unsafe question." Reason: `search_text` returns false matches for Q10 (a GPS weather line) and Q11 (room-fire papers); `matched` cannot catch these.
- **Router examples:**
  - "Does fire spread faster in space?" / "Is it true fire spreads faster in space?" → `get_findings(x="oxygen", y="spread rate")` (Q1; the strong flight-vs-ground answer);
  - "What happens to a candle on the Moon?" / "fire on the Moon / Mars" → `gaps("partial gravity")` (Q8);
  - "Which experiments matter most for <scenario / topic>?" → `rank_investigations`.
- **Q9** ("which experiment had the most tests?") stays step 4: a known limit, not used in the demo.
- **Q7** ("how hot does a flame get?") answers from model cards about sooting-limit flames. It is correctly attributed but narrow: not a chip, not in the demo.

### 4.5 Detection overview uses all tests, not the scenario
- `show_view("smoke", "iss")` has no particle-size data: the SAME / SAME-R records have no oxygen or pressure values, so they never fall "near" a scenario. Only `show_view("smoke")` shows the 10 PSI-101 particle sizes.
- The Detection category overview therefore always uses `show_view("smoke")` (no scenario), with this fixed line on screen (no numbers): "Smoke tests are shown for all conditions: the SAME and SAME-R records have no oxygen or pressure values."
- The ranking panel still uses `rank_investigations("detection", scenario)`.

### 4.6 Adapter details (Part B)
- **Zero KPIs:** hide a KPI whose value is 0 when a gap or speak line already states the absence (selection only, no new number). Example: suppression at the Moon base, "0 of 0 tests".
- **Rankings:** at most 8 rows in the panel, with the footer "8 of N investigations" (N from `ranking`), keeping the 4.1 divider if it falls inside the 8. Drop the `table` of a `rank_investigations` answer: it duplicates `ranking`.
- **Spacesuit KPI `basis`** (221 characters): show it as a tooltip, full text, not cut.

### 4.7 "Ask me" chips (replaces the chips in Round 3 §3.2)
| category | chip 1 | chip 2 | chip 3 |
|---|---|---|---|
| Prevention | "Which experiments matter most for prevention?" (g30) | "Compare BASS and BASS-II" (g03) | "What is BRE?" (g01) |
| Flammability | "Does fire spread faster in space?" (g11 / Q1 via `get_findings`) | "What is a cool flame?" (Q5, after 4.3) | "Show me the flame spread data" (g19) |
| Detection | "Why are smoke particles bigger in space?" (g17) | "Which experiments matter most for detection?" (g32) | "What did SAME measure?" (`get_investigation("SAME")`, `pending_review` until printed in Part B) |
| Suppression | "Which gases did the experiments add?" (g13) | "What happens to cool flames with helium?" (g18) | "How much CO2 puts a fire out?" (g22, honest gap) |

Changes from Round 3 §3.2:
- "Rank materials by flame spread" is replaced: its answer is a "nothing is ranked" line, and the word "rank" invites a ranking the data cannot make.
- "What is SAME-R?" becomes "What did SAME measure?"; SAME is the detection investigation ranked first.
- "How does particle size change with oxygen?" (g12, "no finding") is replaced by the detection ranking.

The intros (Round 3 §3.2) are unchanged.

### 4.8 Before Part B
Claude Code applies 4.1–4.3 in `psi_stage1` (back up first, rebuild with `--verify`, full suite), reprints sections 1, 3 and 4 of `review_prints.md` as `review_prints_v2.md`, and adds `get_investigation("SAME")`. Then it continues with Parts B–D without another stop, unless a new golden fails. STOP 2 is unchanged.

## Round 5 — STOP 2 review: DECIDED (2026-11-08, chat review of `chat_decisions/stage7_report.md` + `reports/stage7/review_prints_v2.md`; the user confirms it by sending Claude Code the Round 5 message)

**Accepted:**
- Round 4 as applied: scenario rankings with the divider (g35 Moon base: BRE 31, CFI-G 20; g39 spacesuit: CFI-G, Flame Design), the gap cleanup, the search fixes, goldens g01–g43 (475 tests).
- Parts B–D: 108 Python tests, 17 vitest, build green, hard-code grep empty, the largest packet 6565 bytes.
- The caveat pull-forward in `adapter.to_model` for g06 / g13 / g14.
- Deviations 1, 2, 4, 5, 7 and 8 in the report:
  - 16 tools;
  - the sqlite lock in the agent;
  - one `answer.show` for scene + ranking;
  - 3 lines for g43;
  - pillar + spacesuit rankings stay tier-first;
  - ignition reached by a question.

### 5.1 `search_text`: only cards are spoken when there are two or more
- In `review_prints_v2.md`, Q5 "cool flame" (a Flammability chip) has two good cards, but its third line is a figure caption ("Flame structure of the high pressure lean cool flame for DME/air mixture at =0.2 and P = 20 atm …"). Q3's third line has OCR errors ("bum", "t~om").
- Rule in `adapter.to_model`: when a `search_text` answer has two or more card lines, the voice gets **only the card lines**. Document lines stay on screen (the "What the authors report" panel and the table). With fewer than two cards, the current behaviour stays.
- Selection only. Add a test with the Q5 output.

### 5.2 Greeting covers the default category (report deviation 3)
- The page opens on Flammability by itself, and that entry is silent. The opening line (phase 1) therefore ends with the category on screen: "Hi, I'm Flamo. I answer from NASA's microgravity fire experiments. You're on <category>; for example, ask me: <chip 1>. Or pick another topic." One utterance, no collision.
- The default category stays "not visited", so its intro plays when the astronaut returns to it later.

### 5.3 Grammar: "1 finding", not "1 findings"
- Seen in the `rank_investigations` rows (Saffire-III). Fix it in `flameo_tools` and add it to the shared negative check (with "1 test").

### 5.4 `flameo_tools/README.md`
- Correct the thread-safety sentence: one shared connection; callers must serialize concurrent calls (the agent uses a lock).

### 5.5 SAME chip stays hidden
- `get_investigation("SAME")` says what the data holds (8 tests, flow 5–10 cm/s, four materials, no pressure), not what SAME found.
- Detection shows two chips. Revisit only if a `search_text` card on the SAME findings is reviewed later.

### 5.6 Verify the LiveKit wiring once the Python packages are installed
- `livekit-server` (the media server) is now installed on the computer. The unverified event names need the **Python packages**: run `uv sync` in `AstroEntropy` (it installs `livekit-agents[google]~=1.8`, `fastapi` and the rest from `pyproject.toml`).
- Then:
  - check `user_input_transcribed`, `agent_state_changed` and the room `reconnected` event against the installed package source, and fix the names if they differ;
  - un-skip and run the FastAPI route test;
  - import `src/agent.py` and `src/api.py` for real.
- Still no Gemini / LiveKit session from Claude Code.

### 5.7 Then: the live voice test (a person)
- **Local server:** `livekit-server --dev`, LiveKit's development mode with its built-in development key pair, on `ws://localhost:7880`. Put the URL and the development key pair in `.env` yourself. Never paste keys into a chat.
- **Also in `.env`:** `GOOGLE_API_KEY` and `FLAMEO_DB` (the path to `serving.db`).
- **Run:** `run-local.sh`.
- **Go through `VOICE_TEST.md`:**
  - the 8 demo steps and 3 backups;
  - the 12 free questions (Q10 / Q11 must be answered with no tool call);
  - the 15 phase rows (greeting per 5.2, silence nudge, reconnect);
  - count the 1007 errors and the `generate_reply` timeouts.
- **Bring back to the chat:** `logs/questions.jsonl`, the filled `VOICE_TEST.md`, and any wrong route or wrong number.

## Round 6 — live-test feedback: dashboard polish, sources, fire-safety questions, scoped RAG: DECIDED (2026-11-08 21:48, user: "your recommendations are acceptable"; D6-1 = (a) with fallback (b), D6-2 = generated + checker, D6-3 = yes, D6-4 = as proposed; D6-5 answered in Round 7)

Evidence:
- the user's live test;
- `logs/questions.jsonl` (37 turns);
- the `experiment/ui_communication` branch at `6289b60` (RAG commits `19b7ab9`, `363ff0b`);
- `search_text` rerun on `serving.db` for the logged queries;
- `pipeline.db` (`doc.download_url`, `paper.doi`);
- `FlameDashboard.jsx` on `stage7-real-data`.

### 6.1 Dashboard polish: keep the theme, colours, fonts and background exactly as they are (no choice needed)
- **Remove every "[ … ]" wrapper** around numbers and labels in `FlameDashboard.jsx`:
  - line 107: chart bars;
  - line 304: slider values;
  - line 387: the summary big number;
  - line 391: KPI tiles;
  - lines 398–399: ranking rows.

  A value is shown as the number with its unit in small text (e.g. "221 tests", "0.012–2.6 mm/s").
- **Display audit**, with a test that renders all 20 overviews + every golden answer through the adapter and checks the text:
  - no "None", "null", "undefined" or "NaN";
  - ligatures normalised (NFKC: "ﬂ" → "fl");
  - truncation shows "…", never "~";
  - ranges as "a–b" with an en dash;
  - numbers keep their own precision (never more digits than flameo gave);
  - units with symbols: O₂, CO₂, µm, kPa, psia;
  - "1 test" / "1 finding";
  - long text wraps; nothing overflows a tile.
- **Make it attractive within the theme:**
  - KPI tiles: a large number, the label above, the basis as a muted sub-line;
  - ranking rows: rank and name on the left, the bar with its label next to it, a tier chip;
  - the answer state as one card: the question as the title, the spoken lines (each with superscript source numbers, 6.3), then key numbers, chart, table, then sources;
  - friendly empty states ("No flame spread tests near the Moon base habitat yet: see the open questions below");
  - subtle entry animation only where the theme already animates;
  - check at desktop and laptop widths.
- **Chat bug (the answer text disappears or jumps to the top):**
  - Chat bubbles are keyed only by the transcription segment id (`liveMsgs` / `upsertMessage`). If a segment id comes back in a later turn, the new text overwrites an old bubble higher up.
  - Fix:
    - reproduce first by logging segment ids and `final` flags;
    - then key each bubble by participant + segment id + turn;
    - freeze a bubble once its segment is final;
    - never move or clear earlier bubbles;
    - auto-scroll only when the user is already near the bottom.
  - Also check that a category switch (D3-2) or an answer re-render does not rebuild the voice panel and empty the chat.
  - Add a test with repeated segment ids.
- **Scene switching:** the log shows 12 `scene_arrival` calls in 30 seconds. Debounce: speak the scene line only after the scene has stayed for 1.5 s; the screen still updates at once.
- **Question log:** `transcript` is often empty or the previous utterance. Log the last final user transcript before the tool call.

### 6.2 Fire-safety questions ("what oxygen level makes the spacecraft dangerous?")
What happened:
- Four such questions went to `search_text` and came back `matched: true`.
- The passages were about the topic but none answered it (e.g. "Fire-safe atmospheres for spacecraft would be unique…").
- Gemini then used the "not covered" template.

The real answer is spread over several sourced findings that no single sentence holds:
- BASS-II flight vs ground: flames still spread at 17 % O₂ in microgravity, none at 18 % and below in normal gravity;
- BRE thesis p31: "oxygen levels of 26 % and above can allow steady flames";
- an ISS finding: flames in 21 % oxygen self-extinguished within 40 s;
- CFI-G: cool flames not observed below about 0.4 oxygen mole fraction;
- FLEX passage: below 14 % only transient combustion (droplets);
- the challenge text: the Moon base at 30 % or more is "more than a 40% increase … making materials much more flammable".

Proposal:
- **New flameo tool `oxygen_effect(scenario=None, material=None)`:** the flagship fire-safety answer. Deterministic, Stage 6-style (config + goldens):
  1. the scenario's oxygen (ISS 21 %, Moon base ≥ 30 %, suit 100 %), with the challenge sentence for the Moon base;
  2. flight findings whose x is oxygen (flight first, evidence wording);
  3. the BRE "26 % … steady flames" reference and the CFI-G cool-flame limit;
  4. the O₂-vs-pressure chart (`ref`).
  - It always carries the gap line: "The PSI data does not set a single safe or dangerous oxygen level; these are the conditions where the tests still burned."
  - Never "safe / dangerous above X".
- **Prompt:**
  - "not covered" is used only when no tool and no scoped search (6.4) returns a relevant result;
  - when results are related but partial, say what the data does show, then the gap.
- **Router examples:** "what oxygen level is dangerous", "is more oxygen dangerous", "how much oxygen makes a fire worse" → `oxygen_effect`.

### 6.3 Sources for every answer (no choice needed except D6-4)
- **flameo:** the serving build adds a `source` table from `pipeline.db`: `src_id`, `kind` (paper / document / table / card / challenge), `title`, `psi`, `doi`, `download_url` (the official NASA PSI link, present for all 1,915 documents), `local_path`.
- **Every answer carries `sources[]`**, and each speak line / card / value lists which sources it uses:
  - **Paper:** title, page, DOI → `https://doi.org/<doi>`.
  - **NASA document:** title, page, "Download from NASA PSI" (`download_url`), and "View" (6.3 viewer).
  - **Experiment table:** "<investigation> experiment table", the test ids and the row values.
    - The link: Claude Code checks whether the table file has its own entry with a URL in `pipeline.db` (`doc` / `exp_table`). If not, no link. Never build a URL by guessing.
  - **Finding (card):** the paper's DOI + page + the evidence wording (flight / ground / model).
  - **Challenge statement:** labelled "NASA Space Apps challenge text".
- **Frontend: a Sources section in the answer card**, grouped by type with an icon each, numbered to match the superscript numbers on the spoken lines.
  - DOI and NASA links open in a new tab.
  - "View" opens a side drawer with the document at the cited page (`#page=N`).
  - The ranking and overview panels show their basis as a small "from: experiment tables of N investigations" line.
- **Voice:** unchanged (it already says "From <document>, page N" / "the authors report"). It may add "the sources are on the screen" once per answer.

### 6.4 Scoped RAG (the team's idea): search only the sources the question's parameters cover
Today's `experiment/ui_communication` RAG:
- Cohere embeddings in Postgres / pgvector, hybrid vector + keyword search, Cohere rerank, then a separate Gemini model writes free text (`ask_paper_rag(question)`).
- The repo sample has 74 chunks from one paper. Metadata: type, page, title only.
- As the team says, used alone it searches everything and its text cannot be checked.

Proposal: a new agent tool `ask_sources(question, o2_pct=None, pressure_kpa=None, material=None, fuel=None, psi=None, pillar=None, scenario=None)`. Gemini fills the parameters it hears; the rest stay empty.

1. **Scope (serving.db, milliseconds).** The parameters select:
   - the PSIs: tests within ±3 points O₂ / ±10 % pressure; the material / fuel in `investigation`; a named PSI; the pillar from the registry; the scenario's coverage;
   - then their sources: cards (`finding_psi`), document pages and paper pages of those PSIs, and cards whose x / y field matches a parameter (e.g. x = O₂ when an oxygen value is given).

   The scope is reported ("3 investigations, 41 sources").
2. **Retrieve inside the scope only.**
   - With the team's RAG: re-index the chunks with `src_id`, `kind`, `psi[]`, `page` metadata, and filter the vector + keyword search to the scope's `src_id`s (a `WHERE` on the metadata) before the rerank.
   - Re-index from `serving.db` passages (5,289 document pages, 2,786 paper pages, 322 cards, split to ~800 characters), so citations match the sources table exactly.
   - Fallback: `serving.db` FTS inside the same scope.
3. **Compose (D6-2).**
   - The RAG model writes at most 3 sentences, each tagged with the chunk numbers it uses.
   - A checker keeps a sentence only if it cites a chunk and every number in it appears in a cited chunk; otherwise that slot falls back to an extractive card / sentence.
   - Its prompt adds: never state a safe or dangerous threshold, never "safest", answer only from the chunks.
   - The kept sentences become `speak[]`, with `sources[]` (6.3).
4. **Clarify (D6-3).** If the scope is empty, too broad (no parameter and a vague question) or the best rerank score is below a threshold, the tool returns `clarify` with 2–3 questions the scope does cover, built from its cards and PSIs (e.g. "Do you mean how oxygen changes flame spread on PMMA in BASS-II, or which oxygen levels BRE tested for the Moon base?"). The agent asks one short question; the answer goes to a direct tool. At most one clarifying question per user question.
5. **Time limit.** Gemini Live waits while a tool is pending, so `ask_sources` has a 4-second budget; past it, the extractive result is returned.

**Where it sits in the answer ladder (Round 2), replacing step 3:**
- A question a direct tool answers → that tool, as now (dashboard, ranking, investigation, coverage, findings, gases, gaps, `oxygen_effect`).
- Any other fire / combustion question → `ask_sources` with the parameters heard.
- `search_text` remains for "find the passage about X" and as the fallback inside `ask_sources`.
- Off-topic and unsafe questions: no tool, as now.

### 6.5 Decisions for the team
- **D6-1 RAG engine:**
  - (a) the team's RAG (pgvector + Cohere + Gemini), re-indexed from `serving.db` passages with source metadata, scoped as in 6.4, with the local FTS fallback; or
  - (b) local scoped retrieval only (no Postgres, no new keys).

  Proposed: **(a) with automatic fallback to (b)**. It needs, at the demo: Postgres running (docker), a Cohere key and the RAG Gemini key, and internet. Re-indexing about 9,000 chunks at the trial key's pace takes about 30 minutes.
- **D6-2 Answer mode inside `ask_sources`:** generated sentences with the citation-and-number checker (proposed), or extractive sentences only.
- **D6-3 Clarifying question:** yes, one at most, with 2–3 covered options (proposed), or never.
- **D6-4 Document viewer:**
  - NASA PSI documents: an in-app drawer serving the local copy through `api.py` at the cited page, plus the NASA download link (proposed).
  - Papers: DOI link only, no in-app PDF (publisher copyright).
- **D6-5 Questions for the RAG owner** (needed before Claude Code starts 6.4):
  - which files the team's pgvector DB holds today (all PSI documents and papers, or a subset; how many chunks);
  - where Postgres will run for the demo;
  - whether the Cohere and Gemini keys for the RAG are available for the demo.

### 6.6 Order of work (after D6-1 to D6-5)
1. 6.1 dashboard polish + chat bug + display audit (frontend only, can start now).
2. 6.3 sources table and `sources[]` + the Sources section and viewer.
3. 6.2 `oxygen_effect` + goldens.
4. 6.4 scoped RAG: re-index, scope, checker, clarify, fallback; then goldens for the logged fire-safety questions (the four in `questions.jsonl`).
5. Re-run all suites, the display audit and the browser check; then a second live voice test.

## Round 7 — what to RAG, and the RAG build steps: DECIDED with §7.7 (2026-11-08 21:50; built 2026-11-09)

User input:
- 6.1 is running in Claude Code;
- the team works on the RAG now;
- pgvector comes from `docker/docker-compose.yml` (the `experiment/ui_communication` branch);
- the team will do its own chunking later and add it to the data.

### 7.1 The goal of the RAG decides what goes in
The RAG answers fire-safety and combustion questions that **no direct tool answers**, from the papers and NASA documents of **only the investigations the question's parameters select** (6.4), with a source for every sentence.

Numbers about tests (O₂, pressure, spread rate, counts) stay in the function tools; the RAG never replaces them. So the RAG needs text that **explains or reports results**, not data sheets.

### 7.2 What to index (measured in `serving.db` / `pipeline.db`)
| tier | content | size | why |
|---|---|---|---|
| **1: must** | the 322 accepted findings (cards): one chunk each (statement + context quote + evidence wording) | 322 chunks | verified, short, flight / ground / model labelled: the best answer material |
| **1: must** | the 24 investigation profiles from the registry (name, objectives, hardware, fuel, key conditions, pillars) | 24 chunks | lets "what did X study" and scope questions retrieve the right PSI |
| **1: must** | the challenge text split by section, plus the 6 quote-checked references (BRE 26 %, BRE direction, EVA atmospheres, 85 % bottle) | ~15 chunks | Moon base / spacesuit / partial-gravity context; sourced |
| **2: core** | paper pages in sections abstract, results, discussion, conclusion (references pages are already excluded) | 1,440 pages, ~4.4 M characters | the authors' findings and explanations |
| **2: core** | NASA documents: Reports (final reports, theses: `results_report`) and Science Documents (`overview`, `data_guide`, `paper`) | ~2,580 pages, ~4.5 M characters | the investigations' own conclusions and the atmosphere / design rationale |
| 3: later, optional | paper intro + method pages; Engineering Documents | ~5.7 M characters | "how was it measured" and hardware questions; intros mostly cite other work (second-hand), so they rank below results |
| **no** | Raw Data documents (test sheets, logs, timing files), the experiment tables, author / title / reference blocks | — | numbers belong to the tools; sheets and logs are noise and would surface inside a scope |

Tiers 1 + 2 come to about **9,000–10,000 chunks** at ~1,000 characters.

### 7.3 Chunk contract (whoever writes the chunker must keep it)
**Text:**
- ~800–1,200 characters, split at paragraph or sentence ends;
- never across a page (the citation is a page);
- overlap one sentence;
- cards are never split.

**Embedded text** = a short header + the text, for example `[ACME BRE (PSI-20) · BRE thesis · page 31 · Reports]`. Store the raw text separately: it is what the screen shows and what the checker reads.

**Drop:**
- chunks under 200 characters;
- the junk patterns of Round 4 §4.3 (DOI, Received / Accepted, affiliations, dot leaders, reference lists, page-1 author blocks);
- mostly-number chunks (digits over 40 % of the characters);
- exact duplicates (normalised text hash): keep the first and merge their PSIs.

**Metadata (JSON, per chunk):**
- `chunk_id`: unique, readable, e.g. `card:F-P2-…`, `paper:10.1038/s41598-017-18398-4:p6:c1`, `doc:5d793e0224c1:p33:c2`, `psi:PSI-20`, `challenge:c3`;
- `kind` (card / paper / doc / investigation / challenge / reference), `src_id` (DOI, doc id or finding id), `title`, `page`;
- `section` (papers); `doc_category`, `doc_role` (documents);
- `psis[]` and their `pillars[]` (from the registry);
- cards only: `evidence_basis`, `wording`, `flight`, `x_field`, `y_field`;
- `tags`: `o2_pct[]`, `pressure[]` (values mentioned in the text, by regex), `materials[]`, `fuels[]` (vocabulary from `investigation.materials` / `fuels`), `gravity` (micro / normal / both, from wording);
- for the Sources panel (6.3): `doi` or `download_url`; plus `text_hash`.

**Source of the text:**
- The fastest path that keeps citations exact is the page texts already in `serving.db` (`passage`), which carry `src_id` and page.
- If the team's own parser (markdown from the PDFs) gives cleaner text, use it on the **same files** listed in `pipeline.db` (`doc.local_path` → `doc_id`, `paper.pdf_path` → DOI), and keep page numbers. The metadata contract is the same either way.

### 7.4 Changes to the team's RAG code (`src/paper_rag`)
- **Table:**
  - `chunk_id` from `VARCHAR(20)` to `TEXT`;
  - add an HNSW index on the vector (cosine) and a GIN index on `metadata`.
- **Scoped search:** both `search_by_vector` and `search_by_keyword` take a scope (`src_ids[]` and / or `psis[]`) and add `WHERE metadata->>'src_id' = ANY(:ids) OR metadata->'psis' ?| :psis`. They return the metadata with each row.
- **Config:** `env_file="src\paper_rag\.env"` is a Windows path and fails on Linux; use a path built from `__file__`.
- **Indexing:**
  - resumable (skip chunk ids already in the table);
  - batch 90;
  - the trial-key pause stays configurable;
  - embed the header + text with `input_type=document`, queries with `input_type=query`.
- **Generation:** the free-text `ask()` is replaced by the composer of 6.4:
  - numbered chunks in, JSON out: up to 3 sentences, each with chunk numbers;
  - the checker keeps a sentence only if it cites a chunk and every number in it is in the cited chunk(s), and drops any "safe / safest / dangerous above" wording;
  - the extractive fallback covers dropped slots.

### 7.5 The build steps, in order
| # | step | who | done when |
|---|---|---|---|
| 1 | Confirm 7.2 (tiers 1 + 2) and 7.3 (chunk contract) | team | this round is accepted |
| 2 | Start pgvector: `docker compose -f docker/docker-compose.yml up -d`, with `docker/env/.env.postgres` and `src/paper_rag/.env` filled from the examples by the team (never in a chat) | team | `create extension vector` works |
| 3 | Bring the RAG code from `experiment/ui_communication` into `stage7-real-data` (`src/paper_rag`, `docker/`, deps); apply 7.4 table / search / config changes | Claude Code | unit tests for scoped SQL pass on the local Postgres |
| 4 | `scripts/build_rag_chunks.py`: tiers 1 + 2 from `serving.db` + `pipeline.db` → `src/paper_rag/data/chunks.jsonl` with the 7.3 metadata; report counts per kind, the dropped counts by reason, and 20 random chunks for review. The team's chunker can replace the text later with the same contract. | Claude Code (team reviews the 20) | the counts and samples are reviewed in the chat |
| 5 | Index: embed + insert, resumable; HNSW + GIN indexes | Claude Code runs it; the team's Cohere key | the row count = the chunk count |
| 6 | **Retrieval check before any generation:** ~30 eval questions (the goldens, the 4 logged oxygen questions, Q1–Q12, the use cases) with the expected PSI / source; measure hit@5 inside the scope vs without the scope; tune the chunk header, size and filters | Claude Code; the chat reviews | hit@5 ≥ 80 % in scope, and a clear gain over no scope |
| 7 | Scope function (6.4 step 1) + `ask_sources` tool: scope → filtered hybrid search → Cohere rerank → composer + checker → `speak[]` + `sources[]`; clarify when the scope is empty or the best score is low; 4-second budget; local `serving.db` FTS fallback when Postgres or Cohere is down or slow | Claude Code | tool tests with fakes, plus a real run on the 30 eval questions |
| 8 | Prompt and router: ladder step 3 → `ask_sources`; "not covered" only when `ask_sources` also finds nothing; router examples | Claude Code | the agent-path tests pass |
| 9 | Goldens + checks: the eval set's best answers become goldens; the number check and the forbidden-words check on every `ask_sources` answer | Claude Code | all suites green |
| 10 | Live voice test #2 with the RAG on, Postgres running, keys in `.env` | team | `questions.jsonl` + notes back to the chat |

`oxygen_effect` (6.2) and the sources work (6.3) do not depend on the RAG; they run in parallel after 6.1.

### 7.6 Still open (the team answers before step 4)
- Cohere key: trial or production? A trial key's pause makes step 5 take about 35 minutes for ~10,000 chunks; check the key's monthly limit first.
- Chunk text for the first index: `serving.db` page texts now (proposed: fastest, exact pages), or wait for the team's parser?

### 7.7 Updates from the team (2026-11-08 23:12–23:17): `claude/stage7-rag-claude-code-prompt.md` v3 overrides 7.3–7.5 where they differ
- PDF text comes only from the team's `chunk_data.py` (docling), with its splitter (600 / 100 characters, tables split by rows with the header repeated); the `serving.db` page-text index is dropped. Tier 1 (cards, profiles, challenge text, references) still comes from `serving.db`.
- All the other §7.3 rules stay: never across a page, the drop rules, dedupe, and the full metadata.
- Model-written figure and table descriptions are marked; numbers are accepted only from non-generated `raw_text`.
- Embeddings: a Gemini embedding model (13-key pool) instead of Cohere. Rerank: Cohere only if a key exists; otherwise rank fusion.
- Parsing runs in Docker: 1 master (the main laptop) and 4 workers that pull tasks and PDFs over the LAN; threads are set in each `.env`; no API keys on the workers.
- Pilot on 5 PDFs with the master + 1 worker, then STOP for review.

## Round 8 — review of the RAG build report (`stage7_rag_report.md`, 2026-11-09 04:40): DECIDED (applied 2026-11-09)

**Accepted:**
- Part A–D and P as built: the master / worker queue, the Windows worker, the OCR-per-page fix and the 12-page runs for big files;
- the figure pre-filter rules; the `ref:<id>` fix; the removal of the team's `generation.py` and `indexing.py`.

### 8.1 Answers to the report's questions
1. **One index: Cohere (`chunks_cohere`, embed-v4.0, 1024).** It is complete today and uses the same provider as the reranker.
   - Freeze the Gemini table `chunks`: no more Gemini embedding calls. Delete it after the live test.
   - The query embedding must come from the same model, so there is no Gemini fallback inside the vector search. When Cohere fails or is slow, use the `serving.db` FTS fallback.
2. **Word files:** first list the 10 with their PSI and category.
   - Docling reads `.docx` natively. Convert the 8 `.docx` on the main laptop (no Docker needed), with `page: null` and the nearest heading as `section`; the Sources panel cites the section.
   - Skip the 2 `.doc` unless a PSI has no other report.
   - Low priority: after `ask_sources`.
3. **Figures: index by caption now, no model summary.**
   - About 1,800 captioned, unique, filtered figures, with `raw_text` = the caption + up to 300 characters of the context before it, `type: figure`, `generated: false` (the caption is the authors' text, so its numbers are allowed).
   - Model summaries (phase 2) are optional, off the critical path. When added, they go in `text` / `metadata.fig_summary` with `generated: true` and never into `raw_text`.
4. **The 4 giant files:** keep them (tier 2 reports and theses). Check their drop rate: if over 50 % of their chunks are dropped as junk / numbers, or they repeat another file (same title), report it.
5. **Cohere trial quota is fine for the demo.** 9 keys × 1,000 calls per endpoint per month is about 9,000 questions at 1 embed + 1 rerank each.
   - Budget the eval runs (≤ 300 calls a run) and log calls per key.
   - Trial keys are meant for evaluation and prototypes, which fits a hackathon demo.

### 8.2 Other review points
- **Table labels:** docling's own table number can disagree with the caption. Use the caption's label ("Table 12 …") as the chunk label, and keep `table_id` for internal use only.
- **The eval must test PDF retrieval.** Tier 1 alone cannot show a gain from the scope.
  - Add ~12 questions whose answer is in a parsed PDF page, with the expected `src_id` + page. Draw them from the use cases and the logged questions: for example, BRE thesis p31 on 26 % O₂, the FLEX transient combustion below 14 %, a SAME smoke result, a Saffire flame-spread result.
  - Report hit@5 scoped vs unscoped on the full Cohere index, with and without rerank.
  - Target unchanged: ≥ 80 % in scope and a clear gain over no scope.
- **"When is oxygen dangerous" goes to `oxygen_effect` (Round 6 §6.2), not to the RAG.** These questions are not RAG misses; keep them in the eval only as a check that the scope finds the 17 % / 26 % chunks. The report does not say whether 6.2 (`oxygen_effect`) and 6.3 (sources) are built: state their status.
- **The composer model:** `gemini-3.5-flash-lite` (it works on these keys), then the Groq model, then the extractive answer, all inside the 4-second budget. At live volume (a few questions a minute) the free generation quota is enough; log the key index and fallback reason.

### 8.3 Order of work from now
1. Finish the last 4 files and the Cohere index (24 files left). Then index the figures by caption (8.1.3).
2. Expand the eval (8.2) and run it on the full Cohere index: with / without scope, with / without rerank.
3. **Build `ask_sources` and the retrieval log (Part E + F)**:
   - scope → filtered hybrid search on `chunks_cohere` → Cohere rerank → composer + checker → `speak[]` + `sources[]`;
   - clarify on an empty or weak scope; 4-second budget; FTS fallback;
   - `logs/retrieval.jsonl` + console summary + `tail_retrieval.py`.
4. The checker rule (numbers only from `raw_text` with `generated: false`) + tests.
5. Prompt and router (ladder step 3 → `ask_sources`), goldens, the number / forbidden-word checks.
6. `oxygen_effect` and sources (6.2, 6.3), if not built.
7. Then the `.docx` files (8.1.2); phase-2 figure summaries only if quota allows.
8. Live voice test #2.

STOP after step 3: report 5 real `logs/retrieval.jsonl` entries (2 answered, 1 clarify, 1 fallback, 1 oxygen question) and the eval table.

## Round 9 — review of the Round 8 STOP (ask_sources + eval): DECIDED (applied 2026-11-09)

**Accepted:**
- Cohere only; figures by caption; table labels from the caption; giant files kept (drop rates 22–33 %);
- `ask_sources` + `logs/retrieval.jsonl` as built, with the 4 bug fixes (failed rerank labelled, a refusal counted as "not covered", one shared deadline, the Cohere TPM pacing);
- pgvector iterative scan for scoped search.

**Answer to "tune retrieval before step 4?": yes, one bounded tuning pass (≤ 2 hours, ≤ 300 Cohere calls a run), no re-chunking and no re-embedding. Then step 4 whatever the result.**

### 9.1 Fix the eval first (the metric is part of the problem)
- **RAG set only:** questions a direct tool answers ("What did BRE study?" → `get_investigation`, "which oxygen level is dangerous" → `oxygen_effect`, rankings, coverage) leave the RAG eval. They become router goldens in step 5. Report n for the RAG set.
- **Answer-key metric:**
  - each RAG question gets an answer key: 1–3 short phrases or numbers from the expected chunk (e.g. "26 %" + "steady flames");
  - a hit = some top-5 chunk's `raw_text` holds the key (any page of the right source);
  - keep doc-level and the strict page as extra columns.
- **Add 5–8 RAG questions** so the set has ≥ 25 (use cases, Q1–Q12 free questions, the logged questions); verify each key against real chunk text.

### 9.2 Diagnose the scope before changing it
For every question where scoped < free, report whether the expected chunk was **inside the scope**:
- **outside** → a resolver bug: e.g. a named PSI must bring its papers (`finding_psi` / the paper → PSI map) and its documents; material / fuel synonyms ("PMMA" / "acrylic", "cotton-fiberglass" / "SIBAL"); fix it;
- **inside but ranked low** → a retrieval issue (9.3).

The rule stays: with no parameter heard, the search is unscoped.

### 9.3 Retrieval changes allowed (no new embeddings)
- **Two lanes:**
  - the top 3 tier-1 chunks (cards, references, challenge) + the top 40 PDF chunks, merged before the rerank, so the verified cards are not drowned by 17,000 PDF chunks;
  - the card keeps its evidence wording in the answer.
- **Rerank input** = the chunk header (investigation · document · page · section) + `raw_text`; top 50 candidates into the rerank.
- **Weak-score cutoff:** set from the eval's score distribution (the best rerank score of hits vs misses); report the chosen value and how many questions it sends to clarify.

### 9.4 Targets and what happens after
- **Target:** answer-key hit@5 ≥ 80 % on the RAG set in scope, and scoped ≥ free.
- If the time box ends below target, stop tuning, record the numbers, and go on: the composer + checker still refuses to answer when the chunks don't support it.

### 9.5 Then, in order (replaces Round 8 §8.3 steps 4–8)
1. The checker tests (numbers only from `raw_text` with `generated: false`).
2. **Register `ask_sources` as an agent tool** + the prompt and router (ladder step 3 → `ask_sources`; "not covered" only when it also finds nothing; clarify asked once) + router goldens (incl. the 9.1 tool questions) + the number / forbidden-word checks.
3. **6.2 `oxygen_effect`** (the "what oxygen level is dangerous" family; entry 4 of the log shows it is needed).
4. **6.3 sources on the screen:** the `source` table in `serving.db` from `pipeline.db`, `sources[]` on every tool answer, the Sources section in the answer card, the document viewer (the local copy at `#page=N`) and the DOI / NASA links.
5. The `.docx` files; the 80-page BRE document only if laptop-m has the RAM (the BRE thesis already covers BRE). Phase-2 figure summaries only if quota allows.
6. Live voice test #2.

STOP after item 4 with:
- the eval table (before / after tuning);
- 3 voice-path transcripts from the agent tests (one `ask_sources` answer, one clarify, one `oxygen_effect`);
- a screenshot of an answer card with Sources.

### 9.6 Quota
- Cohere: 1,500+ embed calls used today. Finish without another re-embed; each eval run ≤ 300 calls.
- Before the demo, report calls left per key. 9 keys × 1,000 per endpoint per month; trial keys are for evaluation, which fits the demo.

## Round 10 — chat browser test of the live app (2026-11-09 17:30–17:50): DECIDED (applied; D10-1 = vitals "simulated", fire-safety readings and outside temperature removed)

**Test setup:**
- the built-in browser at 1440×900, typed chat only (no microphone);
- 5 questions on the free Gemini key;
- `logs/questions.jsonl` and `logs/retrieval.jsonl` read after the test;
- plus the user's own screenshot.

**What worked:**
- "How were laminar smoke points measured aboard the space station?" → `ask_sources`: one cited sentence (SPICE), superscript ¹, about 2 s.
- "What is BRE?" → `get_investigation`.
- The Sources section shows the DOI and NASA PSI links and VIEW.

### 10.1 Routing and RAG (fix first)
1. **Gemini never passes the scope parameters.**
   - Every `ask_sources` call in the logs has `params: {}` and an empty scope, so the scoped search is never used live.
   - **Fix:** `ask_sources` extracts the parameters from the question text itself, deterministically, before the scope:
     - PSI names and acronyms from the registry (BRE, SAME, FLEX, Saffire, SPICE, CFI …);
     - O₂ % and pressure values with units;
     - materials and fuels from the investigation vocabulary, with synonyms;
     - scenario words (ISS / station / cabin, Moon base / habitat, suit / spacesuit / EVA).
   - Gemini's arguments, when given, win. Log `params_source: model | extracted`.
2. **Oxygen questions go to `oxygen_effect` too broadly.**
   - "What oxygen level allows steady flames in the BRE tests?" → `oxygen_effect(iss)`. Its first 3 spoken lines are the ISS 21 % definition, the "no single safe level" line and BASS-II 17 %; the BRE 26 % line is 5th, so it is never spoken.
   - **Fix (router):** a question that names an investigation (or a specific test condition) goes to `ask_sources` with that PSI.
     - `oxygen_effect` is only for general "how much oxygen is dangerous / is more oxygen worse" questions.
     - Router goldens for both.
3. **`oxygen_effect` line order:** the most relevant flight finding comes first, then the BRE 26 % reference, then the "no single safe or dangerous level" gap line, then the scenario definition. The definition line ("ISS cabin has 21 percent oxygen …") must not be among the first 3 spoken lines.
4. **"What happens to flames in the suit?" → `oxygen_effect(spacesuit)`.** It spoke the BASS-II 17 % line, which says nothing about a 100 % O₂ suit.
   - **Fix:**
     - suit questions → `scenario_coverage("spacesuit")` (g10: burner-stream tests up to 85 %, no pure-oxygen atmosphere tested; 4 lines);
     - or `oxygen_effect(spacesuit)` must start with the burner-stream lines and never use the low-oxygen findings.
5. **"Why are flames round in space?" fell back twice (4 s budget used up, `vector: []`) and the fallback showed junk.**
   - The FTS matched "round" as in mission "round 2", returning news-calendar text from 3 final reports.
   - The voice said "not covered", but the screen showed the 3 junk passages as an answer.
   - **Fixes:**
     - (a) **Find where the 3.3 s went.** Log a time per stage: embed, vector, keyword, rerank, composer. The key pool must never sleep inside the budget: when a key is pacing, take another key, or go to the fallback at once.
     - (b) **Query rewrite before retrieval:** `ask_sources` adds the key terms (flame shape → spherical, buoyancy, microgravity) from a small synonym table. Gemini's `question` stays as asked.
     - (c) **The FTS fallback uses the Round 4 §4.3 junk filter**, plus: drop calendar / news text (dates like "September 19, 2018", "Week of", "Station Gets Ready", URLs) and require at least 2 query terms other than stopwords in the sentence.
     - (d) **When the outcome is not_found or the fallback has nothing relevant, the screen shows the "open question" state** (gap card + the offer), never passages. Screen and voice must agree.
6. **The "not covered" offer** named "suppression" while the user was on Flammability. Offer a chip of the category on screen.
7. **Voice drops the attribution.** The spoken line "while flame cannot exist in normal gravity…" lost "the authors report". The prompt must keep the evidence prefix ("the authors report", "on the ISS, the authors report") when speaking a finding.
8. **Question log:** typed questions log `transcript: ""`. Log the typed text too (`source: typed | voice`).

### 10.2 Answer card and sources
1. **The answer title shows a raw call:** "OXYGEN_EFFECT(ISS, NONE)". The title must be the user's question (or the tool's headline), never the function name.
2. **Raw source names:**
   - the table's source column shows `doc:fa457b0458af`, a bare DOI and the file name "PSI-20 Reports Dissertation-PD-revised";
   - the Sources list shows "PSI-20_Reports_Dissertation-PD-revised_" and, for the fallback, "NASA document or paper, page 95" grouped under "Paper (3)" although they are NASA documents;
   - **Fix:** one `source_label(src_id)` used everywhere (speak prefix, table, Sources): the paper title / document title from `pipeline.db`. If a document has no title, use "<investigation> <category>: <cleaned file name>" (underscores → spaces, version suffixes cut). The group follows the real kind.
3. **Notation in spoken / shown text:** "XO2 = 17%" → show as is on screen (the authors' words) but the voice says "17 percent oxygen" (it already does). OK; no change.
4. **The ranking panel is stale.** Every answer kept the Flammability / ISS ranking ("70 tests near the ISS cabin"), even for SPICE, the suit and "what is BRE".
   - **Fix:**
     - the answer state shows the ranking only when the answer is a ranking or a scenario answer;
     - for a single-PSI answer, show that investigation's row;
     - for the suit, use the suit ranking.
5. **The dashboard does not scroll to the new answer** (it stayed mid-page in the old ranking). Scroll the dashboard to the top of the answer card on each `answer.show`.
6. **The data table for `get_investigation` shows raw field names** (`O2_pct`, `flames_ignited`, `nozzle_d_mm`, `pressure_kPa`), wrapped mid-word.
   - Use the field labels flameo already has for KPIs (oxygen (%), pressure (kPa) …).
   - No mid-word wrap.
   - One scrollbar only (the table has its own nested scroll).

### 10.3 Charts
1. **Ticks are not round numbers:** O₂ 18 / 19.1 / 20.1 / 21.1 / 22.2, pressure 29.6 / 148.8 / 268.1 / 387.4 / 506.6, oxygen 12 / 34 / 56 / 78 / 100. Use "nice" ticks (1, 2, 2.5, 5 × 10ⁿ steps) and pad the domain to them. The last x tick ("22.2") is clipped at the right edge.
2. **The y-axis title overlaps the top tick** ("spread rate (mm/s)" over "2.1"; "oxygen (%)" over "100", and the spacesuit label over both). Rotate the y title or put it above the axis, left-aligned, with a margin.
3. **Scenario labels collide** on the O₂-vs-pressure chart: "Exploration 8.2 psia", "Moon base habitat (requirement corner)", "Exploration 10.2 psia" and "ISS cabin" overlap; "the spacesuit atmosphere" overlaps the axis title.
   - Use short labels with leader lines and simple collision avoidance (or a numbered marker + legend).
   - Consider a log x-axis for pressure, because most points sit at 30–110 kPa and the chart is squeezed to the left.
4. **The scatter is clipped to 12 points** ("showing 12 of 17 points") while the KPI says 19 tests.
   - The 12-point limit was for bar / line charts (Round 1); scatter charts show all points.
   - Explain the 19 vs 17 (2 tests have no O₂?) in the footer: "17 of 19 tests have an oxygen value".
5. **Point colours** look the same (orange) at this size although the fills are green / orange / blue. Make the markers larger (r ≥ 4), use full opacity and a dark stroke, and match the legend swatches.
6. **The legend shows "PSI-25 / PSI-98 / PSI-99";** use the names ("BASS-II (PSI-25)").

### 10.4 Overview and other UI
1. **The summary big number "19 / Flame spread rate"** reads as a rate. Label it "19 tests with a spread rate", or drop the big number when it repeats the first KPI.
2. **The "Data coverage: High" badge** wraps next to the title (the "Data" / "coverage: High" split). Put it on its own line under the title, or `white-space: nowrap`.
3. **Tier chips** sit inline on some ranking rows and on a new line on others. Use a fixed name column with the chip inline, and ellipsis for long names.
4. **The ranking bar label is cut at the right edge** ("70 tests near the ISS cabi…", seen in the user's screenshot). Reserve the label width, or put the label inside or under the bar.
5. **Hardcoded numbers still on screen (break the Round 3 rule):**
   - the hub's ring gauges: Prevention 82 % "NOMINAL", Flammability 64 % "WATCH", Detection 47 % "ALERT", Suppression 88 % "NOMINAL";
   - the scene HUD: "PAPER [ 91 ]", "O2 30% · 10.2 PSI", "SUIT ATMOSPHERE O2 100 % / PRESSURE 4.30 PSI", "EXT TEMP -173 °C", "SUIT TEMP 22.4 °C", "GRAVITY 0.166 G", "FIRE SAFETY NOMINAL / SMOKE 0 PPM".
   - **Fix:**
     - remove the hub gauges' percentages and status words, or replace them with real counts from flameo (e.g. "8 investigations · 221 tests near the ISS");
     - HUD values that are scenario definitions (Moon base 30 % / 10.2 psia, suit 100 % O₂) come from flameo's scenario config with their source; decorative telemetry (ext temp, vitals, smoke ppm) is removed or labelled "simulated" (D10-1);
     - remove the last "[ … ]" bracket ("PAPER [ 91 ]").
6. **The parameters panel** shows "Custom conditions" on first load while the Craft (ISS) scene is selected, until the data loads; show the scenario name from the start.
7. **Chat bubbles** are narrow (about 20 characters a line) and the user bubble scrolls out of view while the answer streams. Widen the bubbles to the panel width, and keep auto-scroll at the bottom while streaming (Round 6.1 rule).

### 10.7 Second chat test (2026-11-09 17:45–18:00): 8 general, emergency, Arabic and follow-up questions, plus the user's Arabic screenshot

**Worked well:**
- **"What should I do if I smell burning plastic in the cabin?"** → emergency banner with the 5 fixed steps; voice: "Alert the crew and ground control, and follow your mission fire procedure." The next turn ("false alarm …") cleared it.
- **"Which material is the most dangerous to have in a spacecraft?"** → `rank_materials`, "nothing is ranked"; the dashboard switched to Prevention (D3-2).
- **"How do smoke detectors work differently in microgravity?"** → `ask_sources`, 2.9 s (embed 0.6, db 0.5, rerank 0.7, compose 1.2): 2 cited sentences, 5 sources with quotes.
- **"Is it safe to keep 34 percent oxygen in the Moon base?"** → `oxygen_effect(moon_base)`; it starts with the challenge sentence (30 % or more, 10.2 psi, "more than a 40 % increase") and never says "safe".
- **"And what about a base on Mars?"** → `gaps(Mars)`: the exploration atmospheres + the LUCI / FM2 line.
- **"Tell me a joke about astronauts"** → no tool, back to fire safety.

**Bugs (add to 10.1–10.4):**
1. **The voice answered from memory, and the screen disagreed** (the user's screenshot).
   - The Arabic question about the craft's normal oxygen was misheard (mixed Spanish / Arabic transcript) and routed to `oxygen_effect(high_o2)`; the screen showed "High oxygen … 40 %".
   - The voice said "about 21 % at a pressure of about 14.7 psi", from memory: 14.7 psi is in no `speak[]` line (flameo says 101.3 kPa).
   - When the user said "the screen says 40 %", the voice made up an explanation.
   - **Fix:**
     - prompt: speak only from the tool result just returned; if it doesn't answer the question, say so and call the right tool (`scenario_coverage("iss")` for "the oxygen in the craft");
     - router example: "what's the normal oxygen in the craft / station / cabin" → `scenario_coverage(iss)`;
     - unit conversions are new numbers: never say psi for a kPa value unless a line has it;
     - an agent test that every number in the spoken text appears in the tool's `speak[]` (with Arabic digits and number words normalised).
2. **A hypothetical question triggered a fire emergency.**
   - "What should I do if a fire happens inside the suit?" (Arabic) → `declare_fire_emergency("fire inside the spacesuit")`. The banner showed the cabin steps (isolate power, stop ventilation, extinguisher), which don't fit a suit, in English while the chat was Arabic.
   - **Fix:**
     - the emergency is only for a fire / smoke / smell reported as happening now ("I smell…", "there's smoke", "fire in the …"). "What should I do if…", "what happens if…", "how do I…" are questions → the answer is "follow your mission fire procedure" plus `ask_sources` for what the data says.
     - If unsure, ask once: "Is there a fire right now?"
     - The banner steps come from a per-location table (cabin / suit); if no source gives suit steps, the suit banner says only "Alert the crew and ground control; follow your EVA emergency procedure".
     - The banner text follows the chat language.
3. **The emergency banner never clears after "There is no fire, I was only asking."**
   - It stayed over the dashboard for the next 3 answers and covered the top of each answer card.
   - **Fix:**
     - "no fire / false alarm / it's out / I was only asking" → `clear_fire_emergency`;
     - the banner has a dismiss (×) button that sends `emergency.cleared`;
     - the banner must not cover the answer card (push the content down, or dock it in the voice panel).
4. **"Can I use water on a fire on the ISS?" called no tool.**
   - The voice said "not covered … follow your mission fire procedure" without searching. The corpus has an ISS Researchers Guide passage on water mist (Round 4 §4.3 Q6).
   - **Fix:** ladder step 3 is mandatory: call `ask_sources` before any "not covered". Add a router golden.
5. **The tool order reads as a ranking.**
   - After "which material is most dangerous", the voice said "nothing is ranked", then read the fastest spread rate first (Saffire-III 2.32 mm/s).
   - **Fix:** after a "most / least dangerous / safest" question, the voice says the "nothing is ranked" line and the "what they did measure" sentence, but reads no single material's value; the table on screen is ordered by investigation, not by value.
6. **Emergency calls are missing from `questions.jsonl`.** Log every tool call, including `declare_fire_emergency` and `clear_fire_emergency`, plus the turns with no tool (`tool: null`).
7. **Answer titles again show the call:** "RANK_MATERIALS(SPREAD_RATE, NONE)", "GAPS(MARS)" (10.2.1).
8. **The `gaps` table shows raw scenario ids** ("exploration_10_2") next to the label; drop the id column.
9. **The Mars answer repeats its gap** in the body and under "Open questions"; show it once.
10. **Source numbers jump** (1, 4 under Paper; 2, 3, 5 under NASA document). Number in reading order inside one list, or keep the groups but renumber the superscripts to match.
11. **The scene chips stay on "Craft"** when an answer is about the Moon base or the suit. Keep the chip as the user set it, but show the answer's scenario on the answer card ("for the Moon base habitat").

**Tests to add:**
- router goldens for the 8 questions above + the user's Arabic question;
- the "spoken numbers ⊆ tool numbers" check;
- an emergency test set: 5 real reports (must trigger), 5 hypothetical questions (must not), 3 clear phrases (must clear).


### 10.5 Decision for the team
- **D10-1: the scene HUD telemetry** (ext temp, crew vitals, smoke ppm, suit temp). (a) Remove it. (b) Keep it as decoration labelled "simulated". Proposed: (b) for the vitals look, (a) for any fire-safety number ("FIRE SAFETY NOMINAL", "SMOKE 0 PPM"), because those read as data.

### 10.6 Order and STOP
1. 10.7 items 1–4 (voice from memory, false emergency, stuck banner, no tool before "not covered"), and 10.1 items 1, 2, 5 (scope extraction, router, latency + fallback filter + screen / voice agreement); then 10.1 items 3, 4, 6–8 and 10.7 items 5–11.
2. 10.2 (answer card, source labels, stale ranking, scroll, table labels).
3. 10.3 charts.
4. 10.4 UI and the hardcoded numbers (after D10-1).

**Tests:**
- router goldens for the 5 questions above;
- a test that a not_found answer renders no passages;
- a display test for tick values and label collisions (no overlapping label boxes);
- the hardcode grep extended to the hub and the HUD.

**STOP with:**
- screenshots at 1440×900 of: the Flammability overview, the O₂-vs-pressure chart, the BRE 26 % answer, the suit answer, and a not-covered answer;
- the 5 questions' `retrieval.jsonl` lines.

## Round 11 — interactive "your conditions" view (user feedback, 2026-11-09 17:53): DECIDED (applied; D11-1 = yes, D11-2 = (a))

**Problem (user):**
- Asking about 34 % O₂ does not move the oxygen slider; the conditions panel stays at the scenario values.
- Moving the sliders changes almost nothing on the dashboard.
- All charts are fixed summaries (rankings, data tables). There is no view that answers "where am I, and what does the evidence say about fire here?"

**Rule kept:** no invented danger zones and no "safe / dangerous above X". The view shows the user's point among the **real tests** and the **sourced markers**; every number comes from flameo or a cited source.

### 11.1 Conditions follow the conversation (two-way)
- **When a question names conditions,** the agent calls `set_conditions` before (or with) the answer tool, and the sliders, the scenario chip and the panel update:
  - "34 percent oxygen" → O₂ 34;
  - "at 10.2 psi" → pressure 10.2 psi (§11.6);
  - "on the Moon base" → the Moon base scenario.
- **The source of the values is shown:** a label "From your question: 34 % O₂" or "Moon base habitat (scenario definition)".
- **Deterministic:** the same extractor as Round 10 §10.1.1 sends `conditions.set` from the server, so it doesn't depend on Gemini remembering to call the tool.
- **The voice says it once:** "I set the oxygen to 34 percent; the panel shows the nearest tests."

### 11.2 New flameo tool `nearest_tests(o2_pct, pressure_kpa, material=None)` (Stage 6 change + goldens)
- **Tests "near" the point:** the Stage 6 tolerances (±3 O₂ points, ±10 % pressure). Return:
  - the count of tests and PSIs;
  - the rows (investigation, test id, material / fuel, O₂, pressure, flow, outcome: spread rate, burned / extinguished, flame type);
  - flight before ground.
- **When no test is near:** the nearest tested points (their own O₂ / pressure values, not a computed distance) and the gap line "No PSI test at these conditions; the nearest tests are …".
- **Material filter** when the user named one.
- **`speak[]`** e.g. "Near 34 percent oxygen and 8.2 psi there are N tests in M investigations; in K of them the flame spread."
  - Outcomes are counted, never rated. N, M and K are counts flameo returns.
- **Fast** (one SQL query), callable two ways:
  - by the agent, as a voice tool;
  - by the frontend through REST (`GET /api/nearest?o2=&p=`), so a slider move costs **no Gemini call**.

### 11.3 New panel "Your conditions and the evidence" (dashboard, all categories)
Shown on every overview and answer, above the category content, and refreshed 0.5 s after a slider stops.

1. **Oxygen ladder** (a vertical scale from 0 to 100 % O₂).
   - **The user's marker,** moving with the slider.
   - **Scenario markers (scenario definitions):** ISS 21 %, Moon base 30 % or more, Exploration 26.5 % / 34 %, spacesuit 100 %.
   - **Evidence markers, each clickable to its source:**
     - "flames still spread at 17 % in microgravity" (BASS-II flight vs ground, DOI p6);
     - "26 % and above can allow steady flames" (BRE thesis p31);
     - "cool flames not seen below about 40 %" (CFI-G, DOI p7).
   - **Tested range:** the band where the PSI tests have O₂ values.
   - **Neutral colours:** no red / green zones. Caption from the challenge text: "more oxygen makes materials much more flammable".
2. **The map:** the O₂-vs-pressure scatter (10.3 fixes), with the user's point live and the tests within tolerance highlighted.
3. **What happened in the nearest tests:** the `nearest_tests` rows as a compact list (material, conditions, outcome) with a count, e.g. "N tests near your point in M investigations".
4. **Spread rate at your oxygen:** the spread-rate-vs-O₂ chart with a vertical line at the user's O₂.
   - Inside the tested range: the points near the line are highlighted.
   - Outside it: "No spread-rate tests at 34 % O₂; the tested range is 17.9–22.2 %." No extrapolated line, ever.
5. **Buttons:**
   - "Compare with ISS / Moon base / suit": puts the scenario markers on the map and the counts side by side;
   - "Ask Flamo about these conditions": sends "What does the data say at 34 percent oxygen and 8.2 psi?" as a question.

**Voice:** silent while the sliders move (Round 3 phase 9). The panel update is the feedback.

### 11.4 Decisions for the team
- **D11-1: show the oxygen partial pressure (pO₂ = O₂ fraction × pressure)?**
  - It is what flammability depends on together with the O₂ %: the suit is 100 % O₂ at 4.3 psi (pO₂ 4.3 psi) against the ISS at 21 % × 14.7 psi (≈ 3.1 psi).
  - But it is a computed number. If yes, flameo computes it (config + golden) with the formula shown on screen ("computed: 34 % × 8.2 psi"); the adapter still never computes.
  - Proposed: **yes, in flameo**, shown as a secondary axis / label, never spoken unless asked.
- **D11-2: where the panel goes.**
  - (a) Replace the right "Parameters" panel with a taller "Your conditions" panel (sliders + ladder + nearest-tests count), with the map and spread chart at the top of the dashboard.
  - (b) A new dashboard tab "My conditions".
  - Proposed: **(a)**, because it is always visible and reacts at once.

### 11.6 Units: psi first, as in the challenge text (user, 2026-11-09 17:56)
The challenge gives pressures in psi: Earth 14.7 psi, the Moon base 10.2 psi or less, the spacesuit 100 % O₂ at 4.3 psi. The exploration atmospheres are 10.2 / 8.2 psia. The data stores kPa (some tables atm).

- **Display and voice use psi first,** kPa second in small text: "10.2 psi (70.3 kPa)". The voice says only the psi value ("10.2 psi"), unless the user asks in kPa. This covers:
  - the pressure slider (range 0–16 psi, step 0.1, ticks at 4.3 / 8.2 / 10.2 / 14.7);
  - the KPIs, tables, chart axes, the map, `nearest_tests` and the ladder captions;
  - spoken lines.
- **Scenario values are the challenge's own numbers** (14.7, 10.2, 8.2, 4.3 psi), not conversions of kPa.
- **flameo converts data values** (1 psi = 6.894757 kPa; 1 atm = 14.696 psi) in one helper, `to_psi()`.
  - Keep the source's precision: one decimal for psi, no more digits than the source value has.
  - Each converted value carries `unit_from: "kPa"`, so the source value stays visible in the table and the tooltip.
  - The adapter and frontend still compute nothing; they show what flameo returns.
- **Rule change to Round 10 §10.7 item 1:** "never say psi for a kPa value unless a line has it" now means the psi must come from flameo's `to_psi()`, never from Gemini. The spoken-number check still applies.
- **D11-1 (pO₂)** is shown in psi too, for example ISS ≈ 3.1 psi and the suit 4.3 psi, with the formula.
- **Goldens:** update the speak lines that say kilopascals (g08, g10, g16, the `oxygen_effect` goldens) to psi first, and add one golden that checks "4.3 psi" for the suit and "10.2 psi" for the Moon base.
- **Typed or spoken input:** "10 psi", "70 kPa", "0.7 atm" all set the slider in psi.

### 11.5 Order and STOP (after Round 10)
1. `to_psi()` and psi-first display (§11.6), then `nearest_tests` in flameo + goldens (in range, out of range, material filter, the suit).
2. The REST route and the conversation → conditions binding (11.1).
3. The panel (11.3) with the Round 10 chart fixes.
4. Tests:
   - the slider → REST → panel;
   - "34 percent oxygen" → sliders at 34;
   - no number on the panel that isn't in a flameo answer or a cited source (extend the display audit).

**STOP with:** screenshots at 1440×900 for 21 % at 14.7 psi (ISS), 34 % at 8.2 psi, 100 % at 4.3 psi (suit), and a point with no nearby tests; plus the voice transcript of "Is 34 percent oxygen dangerous on the Moon base?"

## Round 12 — review of the Round 10 / 11 STOPs, before the live test (2026-11-09 19:40): PROPOSED

**Accepted:** Rounds 10 and 11 as built (commit `ec17eb5`; 312 Python + 64 frontend tests, 506 in psi_stage1).

Reviewed screenshots:
- `round10/3-bre-26-percent` (clean title, one cited sentence, clean source label);
- `round11/2-34pct-8.2psi` and `3-suit-100pct-4.3psi` (the map with the user's point, the log-psi axis, numbered scenario markers, "29 tests near your point in 1 investigation", "No PSI test at these conditions" for the suit, pO₂ with its formula);
- `round11_voice_transcript.md`.

**Answer to "live test now or fix first?": fix the 5 small items below first (≈ 1–2 hours), then the live test.** Items 1 and 2 change what the demo says.

1. **A rerank timeout must not change the answer.**
   - Today a Cohere rerank timeout made the same question answer in one run and come back "not covered" in another.
   - **Fix:**
     - the rerank has its own deadline (about 1.2 s); on a timeout, use the fusion order and **still compose**;
     - log `rerank: "timeout → fusion"`;
     - warm up one embed + one rerank call when the agent starts;
     - run the eval twice with the rerank forced off: the answered / not-covered split must be the same in both runs.
2. **Conditions answers speak the conditions, briefly.** In the 34 % Moon base transcript the voice reads the one-time note + 4 long lines, including the BASS-II 17 % line (irrelevant at 34 %) and "XO2 = 17%" spelled out.
   - **Fix:** when the question set conditions (§11.1), the spoken answer is the note + at most 3 lines, in this order:
     1. the challenge / scenario line;
     2. the `nearest_tests` line ("Near 34 percent oxygen and 8.2 psi there are 29 tests in 1 investigation…");
     3. the evidence line closest to the user's O₂: BRE 26 % for 26–40 %, BASS-II 17 % only for O₂ below 23 %, CFI-G "cool flames" for 40 % and above.
   - The "no single safe or dangerous level" line stays on screen. Notation like "XO2 = 17%" is spoken as "17 percent oxygen".
3. **The oxygen ladder is unreadable** in the right panel: numbered markers 1, 4–7 stack on top of each other near 21–34 % and the scale is about 2 cm tall.
   - **Fix:**
     - move the ladder into the dashboard's "Where you are" section next to the map, full height;
     - or make it a horizontal bar under the sliders, with marker labels in a list underneath and no stacked numbers.
   - The right panel keeps the sliders, the source label, pO₂, the nearest-tests count and the two buttons.
4. **psi_stage1 is not under version control,** and its changes (units, `nearest_tests`, goldens, the rebuilt `serving.db`) exist only there and in the vendored copy.
   - **Fix:** `git init` in psi_stage1 (local only, no remote), with a `.gitignore` for `local_data/*.db`, the backups and `logs/`; commit the current state.
   - Add a line to the AstroEntropy README saying which commit of psi_stage1 the vendored `flameo_tools` comes from.
5. **The end-to-end slider test is missing.** The chat tests it in the browser on the running app (§12.1); no extra code test is needed now.

### 12.2 Live browser test on the running app (2026-11-09 19:35–19:50): add to Round 12, fix with items 1–4

**Setup:**
- the chat drove the running app (built-in browser, 1440×900, typed, no microphone);
- read `questions.jsonl` and the network log.

**Worked:**
- "Is 34 percent oxygen dangerous on the Moon base?":
  - the server set the sliders to 34 % / 10.2 psi before the model;
  - pO₂ 3.5 psi with its formula;
  - "9 tests near your point in 1 investigation";
  - the answer card has the question as its title and the scenario line "Atmosphere: Moon base habitat atmosphere".
- "Does fabric burn faster when the air flows against the flame or with it?" → `get_findings(flow, spread rate)`:
  - the voice said, with the attribution, that in the Saffire experiments concurrent flame spread is faster than opposed;
  - the screen shows 9 findings, 24 test points from 4 PSIs and the spread-vs-flow chart.
- The hub has no more fake percentages.

**Bugs:**
6. **Moving a slider snaps back to the ISS and makes the agent talk** (the end-to-end chain of item 5 fails).
   - Raising the O₂ slider sent `GET /api/nearest?o2=56.5&p=14.7`, then a screen event "conditions_changed: … scenario: custom | coverage…" to the agent.
   - The server's condition extractor ran on that event text, found "ISS", and called `set_conditions({scenario: iss})`. The sliders jumped back to 21 % / 14.7 psi (a last call `nearest?o2=21`).
   - The same event started a Gemini turn. The voice said "These are custom conditions. Data is rated only for the ISS, Moon base, and suit…", which is a free Gemini sentence, and "rated" is wrong.
   - **Fix:**
     - the extractor runs only on the user's own words (typed or transcribed), never on `[screen]` events;
     - a slider change sends no event that makes the agent reply. The agent stays silent (Round 3 phase 9) and only stores the conditions for the next question;
     - log screen events as `source: screen`, not `typed`.
   - **Test:** a slider move → exactly one REST call per stop, no `set_conditions`, no model turn, and the sliders keep the value.
7. **The "Where you are" map stays on "LOADING CHART…" in the live app** (it worked in the test page).
   - No `/api/charts/o2_vs_pressure` request appears in the network log; the overview never fetches the chart ref.
   - **Fix:** fetch the ref on overview mount and on every conditions change.
   - **Test:** in the mounted dashboard, not only the test page.
8. **A slider change blanks the whole dashboard** ("LOADING DATA…" skeleton) for about 1 s.
   - Keep the current overview on screen and update only the "Where you are", nearest-tests and spread sections.
9. **Two LiveKit tokens per page load** (`POST /api/token` twice, `GET /api/categories` twice), which looks like a React StrictMode double mount or two connect effects.
   - If it starts two agent sessions, every question costs twice the free Gemini quota.
   - **Fix:** one connection per page (guard the effect), and check the LiveKit room has one agent participant.
10. **The conditions panel text overlaps:**
    - the source label ("From your question: 34 % O₂ · rest from Moon Base / pressurized rover (scenario definition)") runs over the "Oxygen 34 %" row;
    - the slider value goes grey and stale while dragging (it showed "21 %" while the request said 56.5).
    - **Fix:** the source label on its own wrapped line above the sliders; the value updates live while dragging.
11. **The spread-rate chart's points are all one colour with no legend** ("Spread rate at your oxygen"). Colour by investigation as in 10.3 and add the legend.
12. **The hub category rings are empty circles** now that the fake percentages are gone. Remove the rings, or fill them with a real count from flameo (e.g. the number of investigations in the pillar).

**STOP for Round 12 now also includes:**
- the slider test (item 6) passing on the running app;
- the map loading (item 7);
- one agent participant per room (item 9).


### 12.1 Then the live test, in two parts
- **(a) The chat** drives the running app in the browser:
  - typed questions: the Round 10 sets + "34 percent oxygen on the Moon base" + the emergency set;
  - slider moves, checking the panel refresh and that no Gemini call is logged;
  - then it reads `questions.jsonl` / `retrieval.jsonl`.
- **(b) The team** runs `VOICE_TEST.md` with the microphone (English + Arabic). Bring back the logs and notes.

STOP after items 1–4 and 6–12 with:
- the eval split from the two runs with the rerank forced off;
- the new 34 % Moon base transcript;
- a screenshot of the ladder.

## Round 13 — team voice / chat session review (2026-11-09 ~20:30, 45 turns) + UI screenshot: PROPOSED

The team's session transcript (`attachment.txt`) and one screenshot (Base · Flammability · Moon base answer).

**Good turns:**
- the Saffire-II paper answer (9 samples, 5 × 29 cm, the cotton-fiberglass + PMMA list);
- the BASS-II SIBAL fabric findings;
- the Moon base coverage (51 tests in 2 PSIs, "ask me what BRE found");
- the ISS coverage;
- the off-topic redirect.

The bugs fall into 9 patterns. "Turn N" below is line N of the transcript, saved as `chat_decisions/round13_session_transcript.txt` (odd lines are the user, even lines the agent, except where noted).

### 13.1 A wrong answer (fix first)
- **Turn 62–63:** "this means no test covers O₂ > 25 %?" → "I set the oxygen to 25 percent … That isn't covered in the PSI data."
  - **This is false:** the data has ambient tests at 30–40 % (BRE 30–36 %, CFI-G 33–39 %, 24 tests at ≥ 40 %) and burner streams up to 85 %.
- **Turn 56–57:** "what's the maximum O₂ the data covers?" → "not covered".
  - **Also wrong:** flameo knows the highest ambient O₂ (40 %) and the burner stream (85 %).
- **Turns 60–61** ("some tests in a looser band extend slightly higher") misread the spread-rate chart.
  - That chart only holds the tests with a spread rate (17.9–22.2 %); it is not the O₂ range of the data.
  - **Fix:**
    - the new tool in 13.2 (`data_ranges`);
    - the spread chart's caption says "only the N tests with a measured spread rate";
    - a router golden for "max / min / range of X", "is there any test above / below X".

### 13.2 Missing catalogue tools (the most common "not covered")
Turns 11–12, 42–45, 56–57, 64–69, 26–27, 24–25 ask "what is in the data", and no tool answers it. New flameo tools (Stage 6 style, goldens, `speak[]` ≤ 3 lines, a table on screen):

1. **`list_materials(scenario=None, psi=None, family=None)`:**
   - the materials with test counts and PSIs;
   - `family` from a small vocabulary: fabric (SIBAL / cotton-fiberglass, Nomex, cotton …), plastic (PMMA / acrylic, Delrin …), silicone, Teflon / Kapton, wax, gas fuels, liquid droplets (from `investigation.materials` / `fuels` and the test rows);
   - speak: "94 materials in 2,274 tests; near the ISS cabin, 42. Fabrics: SIBAL in BASS, BASS-II, Saffire-I, II, III …";
   - the counts must say their scope (all data vs near a scenario). Turns 53 vs 65 said 42 and 94 with no scope.
2. **`find_tests(material=…, psi=None, scenario=None)`:**
   - the test rows for a material ("tests with fabric", "tests under Teflon");
   - when none: name where the material appears instead ("Teflon appears in SAME smoke tests, not in flame-spread tests").
3. **`data_ranges(field, psi=None, scenario=None)`:**
   - min / max / count for O₂ (ambient and burner stream separately), pressure (psi first), flow, spread rate…;
   - "is there any test above X" is answered from it.
4. **`get_investigation` returns its fields** ("variables this PSI covers": oxygen, pressure, flow speed, spread rate … with counts) and says when a field is **not recorded** for that PSI. Turn 24–25: "Saffire-II's tests in the data have no pressure value", not "open question".

Every tool: flight before ground; the "it does not rate how safe anything is" line when relevant.

### 13.3 "Not covered" is said for the wrong reasons (8 times)
Turns 8, 12, 25, 45, 57, 63, 69, 89, 91 all used the "open question; would need new experiments" template. Three different cases must sound different:

| case | example | answer |
|---|---|---|
| a field is not recorded | Saffire-II pressure | "The Saffire-II tests in the data have no pressure value." + what they do have |
| Flamo can't map the question | "materials covered there", "thickness" | one clarifying question with real options, or `ask_sources` |
| truly no data | silicone at Moon base conditions | "No silicone test was run near the Moon base atmosphere; silicone was burned in Saffire-II (flight, ISS) and in SAME smoke tests." + the gap line |

**Rule:** the "open question / new experiments" sentence only follows a tool result whose gaps say so, after `ask_sources` also found nothing (Round 10 §10.7 item 4, still violated at turns 89 and 91).

### 13.4 Internal errors are spoken
- **Turns 79 and 89:** "I could not match the field 'duct velocity'" / "'thickness'".
  - **Fix:** tool errors never reach `speak[]`. Map them to a clarify with the real field list ("I have flow speed, oxygen, pressure and spread rate; which one?").
  - Add the synonyms: duct velocity / air speed / flow → flow speed.
- **Thickness is a real gap in the extraction.** The BASS-II material names carry it ("1 mm thick PMMA", "5 mm thick PMMA 2 cm wide"; see the Round 10 data table).
  - **Fix (flameo, Stage 6 change):** parse `thickness_mm` and `width_cm` from the material strings into fields (trust: "parsed from the test's material label"), so "thin vs thick" can be answered from data.
  - Until then, `ask_sources` (BASS-II papers discuss thickness) must run before any "not covered".

### 13.5 Follow-ups lose the subject
- **Turns 19–20 / 32–33 / 50–51:** "yes" after "Do you want the data behind it?" gives a generic O₂-vs-spread result ("No paper finding relates these two quantities"), not the data behind the SIBAL / Saffire-II / flat-samples answer.
- **Turn 34–35:** "what's dangerous here" (in Saffire-II) → generic oxygen lines.
- **Turn 86–88:** "in Saffire 2" then "thin vs thick fabric" loses Saffire-II.
- **Fix: a session context** `{psi, material, scenario, last_tool, last_args, last_view}` kept by the agent code (not Gemini's memory):
  - "yes / the data behind it / show me" reuses the last answer's scope (the same PSI / material, `find_tests` or the evidence table);
  - "here / this experiment / there" resolves to the context PSI or scenario;
  - the voice's offer must name what it will show ("Do you want the Saffire-II test data?").
- "No paper finding relates these two quantities" is never spoken alone. Say what exists ("Saffire-II has 18 tests with oxygen and spread rate; here they are").

### 13.6 The conditions extractor fires on questions about the data
- **Turn 54–55** ("I see the O₂ covered in 22 %?") and **62–63** ("no test covers O₂ > 25 %?") moved the sliders to 22 % and 25 %.
- **Fix:** set conditions only when the user states conditions for a place or a situation ("at 34 % oxygen", "with 8 psi", "on the Moon base", "if the cabin had 30 %"). Never on "covered / cover / data / maximum / above / below / range / chart / test(s) at".
- Add 10 extractor goldens (5 must set, 5 must not).

### 13.7 Clarify and compare quality
- **Turn 3–4:** "flammability of silicon in the base environment" → "SAME or Saffire-II?" The question named a material and a scenario. It should run `find_tests(material=silicone)` + the Moon base check (13.3 row 3), not ask which PSI.
- **Turn 82–83:** "prevention of fabric material" offered Saffire-I, Saffire-III and **CFI-G**. CFI-G burned gases, not fabric.
  - **Fix:** clarify options come from `list_materials(family)`: only PSIs that tested that material, at most 3, flight first.
- **Turn 84–85:** "compare between them" (3 options) compared only 2. Compare all the offered options, or say which 2 and why.
- **Turn 21–23:** the reply started with "The", stopped, then restarted (a cut first segment). Treat it as the chat-bubble / interruption bug: a dropped segment must not leave a one-word bubble.

### 13.8 Navigation and echo
- **"Go back" / "back to the last graph"** (turns 58–59, 70–71) opened the Flammability intro.
  - **Fix:** a view history stack in the frontend; `go_back` (tool or UI event) restores the previous view with its scope; a Back button next to "Back to … overview".
- **Turn 46** shows the agent's own words ("Do you want the data behind it?") as a **user** message, and turn 47 answers it: an audio echo (speaker into microphone).
  - **Fix:**
    - LiveKit noise cancellation / echo cancellation on the client track;
    - ignore user transcripts that arrive while the agent is speaking and match the agent's last sentence;
    - for the tests: headphones.
- **Turn 1–2:** the "Ask Flamo about these conditions" button got only "The details are on the screen. Please continue following the mission fire procedure." No content, and an emergency sentence with no emergency.
  - **Fix:** the button's question goes through `nearest_tests` + `oxygen_effect`; the emergency sentence is allowed only while an emergency is active.

### 13.9 UI (screenshot, Base · Flammability · Moon base coverage)
1. **A dark semi-transparent panel "No tests at these conditions" covers the right half of the dashboard** over the KPIs and the ranking bars. It is the nearest-tests / conditions section positioned absolutely (or a drawer left open) on top of the answer.
   - **Fix:** it must sit in the page flow (Round 11 §11.3), never over the answer, and close when an answer opens.
2. **Garbled text in the ranking:** "BASS-II (PSI-25)" is drawn twice, offset (two labels overlapping, like a re-render without removing the old node). Check the ranking row keys.
3. **Duplicate KPIs:** "Coverage level: Medium" and "Level counting only tests that state N₂ or air: Medium" repeat the same word. Show the second only when it differs, as one line under the first.
4. **The KPI text is cut:** "51 tests; 51 nitrogen (stated for the whole PSI); 51 with…". Wrap it or move it to the tooltip.

### 13.10 Order and STOP
1. 13.1 + 13.2 (`data_ranges`, `list_materials`, `find_tests`, fields in `get_investigation`): goldens first.
2. 13.3 + 13.4 (three "not covered" cases, no spoken errors, flow synonyms; thickness / width parsing).
3. 13.5 session context + 13.6 extractor goldens.
4. 13.7, 13.8 (history, echo guard, button), 13.9 UI.
5. Round 12 items still open.

**Test:** replay this transcript's 45 user turns as typed questions (a script through the agent path), with the expected tool and key words per turn. Turns 1, 3, 7, 11, 24, 26, 42, 44, 54, 56, 60, 62, 64, 66, 68, 76–79, 82–89 are the regression set.

**STOP with:**
- the replay table (turn → tool → first spoken line);
- a screenshot of the Moon base coverage answer (no overlay);
- the extractor and clarify goldens.

## Round 14 — the router: who answers (tools vs RAG), clarify instead of "not covered", general → specific (team, 2026-11-10 00:40): PROPOSED (the team answers D14-1)

**Team findings:**
1. The weak part is the decision "function tool or RAG".
2. Flamo says "not covered" easily and does not ask a small question to understand.
3. **A general question gets "not covered", but going deeper into the same topic finds the answer.** So the data is there; the general question is routed or scoped badly.

**Why this happens today (from the Round 10 / 13 logs):**
- **Gemini picks one of 17 tools from the prompt.** When its pick returns nothing (no matching field, an empty scope, a too-narrow filter), it says the "not covered" sentence and never tries a second path. The prompt ladder is only advice.
- **The tools answer narrow questions** (one PSI, one field pair, one scenario). A general question has no exact match, so the first tool returns empty.
- **Nothing broadens a failed question,** and nothing turns "I have data on parts of this" into a clarifying question.

### 14.1 One entry point: `answer(question)` decides on the server (D14-1)
Gemini gets one main tool, `answer(question)`, plus the few action tools it must keep: `declare_fire_emergency`, `clear_fire_emergency`, `set_conditions`, `go_back`, `show_view`. The answer tools stay in flameo, but the **server** picks them, deterministically, with the session context (Round 13 §13.5).

The server plan per question:
1. **Understand (no model):**
   - **entities:** PSI names and acronyms, materials and their family, fields and their synonyms, scenario, O₂ / pressure values;
   - **intent words:**
     - list / which / what materials → catalogue;
     - max / min / range / above / below → `data_ranges`;
     - compare / vs → compare;
     - rank / most / best → ranking;
     - why / how / explain → RAG;
     - does X affect Y / faster / slower → findings + RAG;
     - "is it dangerous / safe at …" → `oxygen_effect` + `nearest_tests`;
     - "what should I do" → procedure line + RAG;
   - plus the context: last PSI / material / scenario for "here / this / it / yes".
2. **Run in parallel** (one 4-second budget):
   - the 1–2 direct tools the intent maps to (SQL, milliseconds);
   - `ask_sources` with the extracted scope, for every question that is not a pure catalogue / navigation one.
3. **Merge:**
   - **numbers come from the tools,** and the explanation sentence comes from the RAG (cited);
   - **speak at most 3 lines,** data first; the sources lists are merged;
   - **if the tool has data and the RAG has nothing,** answer from the tool; **if the RAG has text and the tool has nothing,** answer from the RAG.
4. **If both are empty, broaden step by step** (never "not covered" first):
   - (a) drop the narrowest constraint (the field pair → the field alone; the scenario → all data; the PSI → its family), and run again;
   - (b) **facet probe:** count where the question's words do have data (pillars, PSIs, materials, fields, top RAG sources unscoped);
   - (c) **if the probe finds data:** one clarifying question with 2–3 options that have data, e.g. "I have flame-spread data for fabrics in BASS-II and Saffire, and smoke data for silicone in SAME. Which one?";
   - (d) **only if the probe and the unscoped RAG are both empty:** the "not in the data yet" answer, worded by case (Round 13 §13.3).
5. **A general question gets a general answer + drill-down:** what exists (counts, the investigations, the main finding), and 2–3 "go deeper" chips built from the probe. The deep answer the team found by going deeper is now offered in the first reply.

Gemini's job becomes:
- call `answer` with the user's words;
- speak the returned `speak[]` (or the clarifying question);
- pass the user's reply to a clarify back to `answer`.

It no longer chooses between tools, so its wrong picks stop being the cause of "not covered".

### 14.2 Clarify policy
- At most one clarifying question per turn, and only with options that have data (from the probe). Never a bare "what do you mean?".
- If the user's reply matches no option, answer the best-scoring option and say which one was chosen.
- After a clarify, the chosen option becomes the session context.
- The question is spoken short: "Which one: fabrics in BASS-II, or silicone smoke in SAME?" The options appear as chips on screen.

### 14.3 Logging the decision (for debugging)
Every turn writes a `router` object to `questions.jsonl`:
- the entities;
- the intent;
- the context used;
- the plan (tools + RAG scope);
- each branch's result (rows, chunks, latency);
- the broaden steps taken;
- the probe counts;
- the final choice and why (`answered_by: tool | rag | both | clarify | not_found`).

`tail_retrieval.py` shows it live.

### 14.4 Tests: the general → specific pairs
- **Pair set:** for each case where the team found a deep answer, a general question + its specific version. For example:
  - "what's the flammability of fabric?" ↔ "BASS-II SIBAL flame spread vs flow";
  - "what materials are covered?" ↔ "which materials did Saffire-II burn?";
  - "how dangerous is high oxygen?" ↔ "BRE oxygen 26 %";
  - "tell me about smoke" ↔ "SAME particle size";
  - "thin vs thick fabric" ↔ "BASS-II PMMA thickness".
- **Rule:** if the specific version answers, the general one must answer or clarify with that option among its choices, **never** "not covered".
- **The replay sets:** Round 10 (both sets), Round 13 (45 turns) and the logged questions, with the expected `answered_by` per turn.
- **Not-covered budget:** across the replay, "not covered" only where the probe is empty; each one is listed for review.

### 14.5 Effect on Rounds 12–13
- Round 13 §13.3 (the 3 not-covered cases), §13.5 (session context) and §13.7 (clarify options) are implemented inside `answer`.
- §13.2's new tools (`list_materials`, `find_tests`, `data_ranges`, fields) are the catalogue branch.
- §13.1's wrong answer is fixed by `data_ranges` + the never-not-covered-first rule.
- Round 12 items stay as they are.

### 14.6 Decision
- **D14-1:**
  - (a) **one `answer` tool with the server router (14.1);**
  - (b) keep Gemini choosing among the tools, with a stricter prompt plus a server-side "retry with RAG and broaden" when a tool returns empty.
- **Proposed: (a).** (b) is smaller but keeps the weakest link (Gemini's tool pick, in voice, on the free tier), and the logs show that pick is where most "not covered" start.
- Keep (b)'s retry as part of (a): `answer` never returns empty without the broaden steps.

### 14.7 Order and STOP
1. The understand step (entities + intent + context) with its own goldens (≥ 60 questions from the replays).
2. `answer` with parallel branches and the merge.
3. Broaden + facet probe + clarify (14.1 step 4, 14.2).
4. The Round 13 catalogue tools (they are branches).
5. Move the prompt to `answer` + action tools; the old tools stay callable only from the server.
6. The pair set + the replays.

**STOP with:**
- the replay table (question → `answered_by` → first spoken line), with before and after counts of "not covered";
- the pair-set results;
- 3 `router` log entries (one tool, one both, one clarify).

## Round 15 — the final plan: from a working prototype to a finished solution (2026-11-12): PROPOSED (the team answers D15-1 to D15-4)

**Inputs:**
- the team's 12-point feedback;
- the 2026-11-12 session transcript (`chat_decisions/round15_session_transcript.txt`);
- the router code as it is (`src/router/`, Round 14);
- `logs/questions.jsonl`.

**Goal of the product (the team's words, kept as the north star):** Flamo is a voice copilot that sits **side by side** with the astronaut in a simulated environment (cabin, Moon base, suit). It does two jobs equally well:
1. **Crew:** fast, calm, correct help when something happens, plus quick answers about the conditions they are in.
2. **Learners:** students, undergraduates, aerospace researchers and engineers. It explains concepts, finds the evidence, compares tests and investigations, and is honest about what the data does not cover.

Everything below serves those two jobs and makes them visible to a judge in 5 minutes.

### 15.0 What the session shows (the root causes, not the symptoms)
| what the user did | what happened | root cause |
|---|---|---|
| "what's ignition I see on screen?" / "what does O₂ = 18 % mean?" / "what does a high spread rate mean?" / "explain how spread rate affects fabric" | not covered, a vague line, or a ranking | **No "explain" path.** The router only knows data lookups; a meaning / concept question has no tool, and the RAG composer is told to say nothing beyond the chunks. |
| "tell me about test 19115A1" / pasting a table row "19150A1 C2H₄ 39.8 14.8 – danger?" | not covered / only moved the sliders | **No test-level tool.** A test id is not recognised; the pasted row was read as conditions only. |
| "I want tests at 40 %" | not covered | **No "nearest value" search.** The O₂ value went to the sliders, not to a test search. |
| "what's the best paper that appears a lot in sources?" → "I said paper" | an investigation ranking, then not covered | **No paper catalogue tool.** The word "best" matched the ranking intent. |
| "ok what do they cover?" (after FLEX) | not covered | **The follow-up lost the subject.** "they" was not resolved to the ranked list on screen. |
| Ranking answers | read the method aloud ("ranked by registry tier, flight before ground…") | Answers explain the machinery instead of the meaning. |
| Questions asked on the home screen | the voice answered, the dashboard never appeared | **The answer card is sent to a dashboard that is not mounted** on `/home`. |
| "It means that at 18 percent oxygen, the tests showed how flames behave" | a vacuous sentence | **No interpretation layer:** values are returned, never put in context (vs the ISS 21 %, vs the findings near that value). |

**Conclusion:** the remaining failures are mostly **missing question types** (explain, test lookup, nearest value, paper catalogue, interpret a value) and **missing context** (home screen, follow-ups). The data and the RAG are good enough. The plan adds those question types, a fixed answer shape, a new dashboard layout, guided scenario cards, and an evaluation that proves it.

### 15.1 Answer engine v3 (the router gets the missing question types)
**1. Understanding: rules + a small model.**
- A fast model call (Gemini Flash-Lite, falling back to Groq; ≤ 600 ms; JSON schema; temperature 0) classifies the question into one of the **12 question types** below and extracts the entities.
- The current rules stay as the fallback and as the source of names (PSI, materials, fields, test ids from the db vocabulary). The model's entities are accepted only if they exist in the vocabulary.
- Logged as `understanding: {by: model | rules, type, entities, confidence}`.

**2. The 12 question types and what answers them:**
| type | example | tools (server) |
|---|---|---|
| emergency now | "there's smoke from the rack" | `declare_fire_emergency` (fast path, no RAG) |
| procedure / what-if | "what should I do if a fire starts in the suit?" | the procedure line + `ask_sources` |
| **explain a concept** (new) | "what is ignition?", "what is a cool flame?", "what does spread rate mean?" | `explain(term)`: the glossary (15.2) + `ask_sources` + one data example |
| **interpret a value** (new) | "what does 18 % oxygen mean?", "is 39.8 % at 14.8 psi dangerous?" | `interpret_conditions(o2, p)`: where the value sits (vs the ISS / Moon base / suit / sea level) + `nearest_tests` outcomes + the closest evidence lines + the coverage note |
| **a test** (new) | "tell me about test 19115A1", a pasted table row | `get_test(test_id)`: all fields, its investigation, what the test measured, its source page; plus `similar_tests` |
| **compare tests / investigations** | "compare 19150A1 and 19115A1", "BASS vs Saffire" | `compare_tests(ids)` (new) / `compare(psi_a, psi_b)` |
| **nearest value** (new) | "tests at 40 %", "anything near 8 psi with fabric" | `nearest_tests` (it exists) used as a search, with a material filter, and returns the rows |
| data catalogue | "what materials?", "O₂ range?", "how many tests in Saffire-III?" | `list_materials`, `data_ranges`, `find_tests`, `get_investigation` (count fallback) |
| **papers** (new) | "which paper appears most?", "papers on BASS-II" | `list_papers(psi=None, topic=None)`: papers ranked by findings / citations in the sources, with DOI |
| effect / why | "does flow make fabric burn faster?", "why are flames round?" | `get_findings` + `ask_sources` (the RAG line is always kept for these) |
| relevance ranking | "which experiments matter most for prevention?" | `rank_investigations` |
| navigation / off-topic | "go back", "weather on Mars" | actions / redirect |

**3. One answer shape for every question type** (spoken ≤ 3 sentences; the screen shows all parts):
1. **Direct answer:** the one sentence that answers the question asked.
2. **Evidence:** the number, test or finding behind it, with its source.
3. **Meaning:** what it means for the crew or the learner (from the interpretation templates, glossary or RAG; never invented).
4. **Coverage note:** when coverage is low, say so in one clause, and still give what exists ("Only 3 tests reach 40 % oxygen, all burner flames, so treat this as a hint").
5. **Next step:** one offer that names what it will show ("Want the 3 tests at 40 %?").

Ranking answers drop the method sentence from speech; it stays on screen as a footnote.

**4. Vague questions: ask, but smartly.**
- A question is vague when the type confidence is < 0.6 or ≥ 2 types tie.
- Flamo asks one short question with 2–3 options **that have data** ("Do you mean what ignition is, or the ignition tests in the data?"). The options appear as chips.
- After 1 clarify, it never asks again on that turn; it takes the best option and says which.

**5. Follow-ups.**
- The session keeps the last result's **rows and list** (investigations, tests, papers on screen), not only the PSI / material.
- "they / them / these / the first one / the best of them / compare them / a random one" resolve against that list.
- Gemini is no longer the gatekeeper: every final user turn that is not an action runs `answer()` on the server, even if Gemini did not call it (Round 14 leak: about 5 of 40 turns).

**6. "Not covered" becomes rare and specific.**
- Before "not covered": the glossary, the RAG unscoped, the nearest-value search, the probe.
- When it is said, it is one of 3 worded cases (Round 13 §13.3), plus what does exist.
- **Target on the eval set: "not covered" < 5 %, every one reviewed.**

**7. Speed.**
- Understanding (≤ 0.6 s) runs in parallel with an unscoped RAG prefetch; the SQL branches run in milliseconds.
- Widening is SQL-only.
- After 1.5 s Flamo says a short filler ("Let me check the papers").
- **Target: p50 ≤ 2.5 s, p95 ≤ 4.5 s.**

**8. Adaptive retrieval depth: when the search returns too little, search wider (team, 2026-11-12 21:39).**
- **First pass (as today):**
  - vector top 40 + keyword top 40 inside the scope;
  - the rerank keeps the best 8;
  - the composer gets the chunks above the score cutoff.
- **"Too little" means any of:**
  - fewer than 10 candidates survive the scope filter;
  - fewer than 3 chunks pass the rerank cutoff;
  - the best rerank score is below the cutoff (Round 9 §9.3);
  - the composer drops every sentence (no citation / number not in chunk).
- **Second pass** (only if ≥ 1.5 s are left in the budget; one pass at most), in this order until "enough":
  1. **Deeper:** vector and keyword top 120 in the same scope; rerank the best 50.
  2. **Wider scope:** one level up: the PSI → its family / pillar's PSIs; the material → its family; the scenario dropped.
  3. **Expanded query:** add the glossary synonyms and the question type's key terms (e.g. "ignition" → ignite, ignition delay, autoignition; "spread rate" → flame spread, spread velocity).
- **More context for the composer:** for each kept chunk, also pass its neighbour chunks on the same page (±1), so a sentence cut by the chunker is complete. The citation stays the kept chunk's page.
- **Logged:** `retrieval: {pass: 1 | 2, k, candidates, passing, best_score, widened: "deeper | scope | query", ms}`.
- **The eval (15.8) compares** hit@5 and the answer rate with adaptive depth on vs off. It stays on only if it improves them without breaking p95 ≤ 4.5 s.

### 15.2 Learning content: glossary and explanations (D15-1)
- **`glossary.json`:** about 40 terms a learner meets on screen (ignition, flame spread rate, opposed / concurrent flow, cool flame, extinction, soot / smoke point, LOI / oxygen index, partial pressure, microgravity vs normal gravity, burner stream vs ambient, PMMA, SIBAL, Nomex, droplet combustion, inverse flame…).
- **Each entry:**
  - a plain 1–2 sentence definition;
  - "why it matters in space" (1 sentence);
  - a PSI example (an investigation + a finding or test);
  - its source: a chunk id / paper page from the corpus, or the challenge text.
- **Built semi-automatically:** the RAG drafts from the corpus, then the team reviews and edits each entry once. It is stored with the reviewer's name and date.
- **On screen:** underlined terms in answers and on the dashboard open a small definition popover (no model call).
- **D15-1 (policy):** when neither the glossary nor the RAG has a definition, may Flamo give **one sentence of general background**, clearly labelled "general background, not from the PSI data", with no numbers? Proposed: **yes, for "what is / what does X mean" only.** Learners need it, and the label keeps the evidence rule honest.

### 15.3 Flamo's persona and the two modes (new system prompt)
**Persona:** Flamo is the crew's fire-safety copilot riding along in the simulation (cabin, Moon base, suit). It is calm, warm and precise. It speaks like a mission specialist who is also a good teacher.

**Two modes, chosen automatically, with a toggle on screen (D15-2):**
- **Crew mode** (in a scene, or an emergency / procedure / conditions question):
  - short;
  - action first;
  - numbers only from data;
  - the emergency path in under 1 second (no RAG).
- **Learn mode** (concept, why, compare, paper questions; or the toggle):
  - explains step by step;
  - gives the definition, the evidence and an example;
  - offers to go deeper;
  - may be 4 sentences;
  - the dashboard shows the "Explain" card (definition + diagram + source).
- **The evidence rules stay in both modes:** no number not in a result, no "safest", no Mars numbers, "the authors report" kept, and coverage stated honestly.

**The prompt is rewritten** around the 12 question types and the answer shape (15.1.3), with 2 example dialogues per mode. It is kept under about 1,200 words.

### 15.4 Home screen and navigation
- **An answer on the home screen opens its dashboard:** the frontend queues `answer.show` / `view.open` while no dashboard is mounted, navigates to `/solution?cat=<answer pillar>&env=<scenario>`, then replays the queued commands. The hub card of that pillar pulses for 0.5 s before the transition.
- **Route by the answer:** the answer's pillar picks the category (D3-2). A cross-pillar answer (e.g. a paper list) opens a neutral "Answer" view, not a random category.
- **Breadcrumb at the top of the dashboard:** Home › Flammability › "Is 39.8 % at 14.8 psi dangerous?" with Back (view history, Round 13 §13.8).

### 15.5 Dashboard v2: entry speed, layout and charts
**Speed:**
- The server precomputes the 4 pillars × 3 scenarios overviews at startup (12 payloads, cached, invalidated with `serving.db`'s hash).
- The hub prefetches on hover. Entry renders the cached payload at once (target < 300 ms); live parts (the nearest tests) fill in after.
- **No full-page skeleton after the first load.** Only the sections that change show a spinner.

**One layout for the middle dashboard** (all pillars and answers, top to bottom, single column, max 3 sections visible without scrolling at 1440×900):
1. **Header:** the question (or the category title on entry), a scenario chip, a coverage badge (High / Medium / Low with a one-line reason), and the mode badge (Crew / Learn).
2. **Answer card:** the 3 spoken sentences with superscript source numbers, with a "Meaning" line highlighted. For Learn mode, an "Explain" box with the glossary definition.
3. **Evidence chart:** ONE chart chosen by question type (15.5 chart rules), with a 1-line caption saying what it shows and how many tests.
4. **Where you are:** the conditions map + the oxygen ladder + nearest tests (Round 11), collapsible.
5. **Tests / findings table:** sortable; a click opens the test drawer (`get_test`).
6. **Sources:** numbered in reading order, with the viewer.

**Chart rules** (one design system: the same fonts, sizes, colours by investigation, nice ticks, psi first, a legend always, tooltips with the test id + material + conditions + outcome, and a click to open the test drawer):
| question type | chart |
|---|---|
| a value / conditions | the O₂-vs-pressure map with the user's point + scenario markers (log-psi axis) |
| an effect (X vs Y) | a scatter of Y vs X by investigation, with the finding's statement as the annotation |
| compare | side-by-side bars or a dumbbell per measurement for the 2–3 items |
| catalogue / ranges | a horizontal range bar per investigation (min–max, count) |
| ranking | ranked bars with tier chips; the method in the footnote |
| a test | a "test card" (all fields) + its position on the map + similar tests |
| explain | a small concept diagram from a fixed set (flame spread opposed vs concurrent; buoyant vs microgravity flame; ambient vs burner stream; partial pressure) |

**Interactions:**
- hover → tooltip;
- click a point / row → the test drawer;
- "Compare" checkboxes on rows → `compare_tests`;
- "Ask about this" on any card → it sends a prepared question.

### 15.6 Scenario cards: the guided "Try this" deck (for judges and new users)
Under the conditions panel (right side), a deck of cards for the **current category × scenario**. Each card is one tap. It sets the sliders / scenario if needed, and sends a prepared question or action. Six card types, each with its own icon and colour:
| card type | example (Flammability × Moon base) |
|---|---|
| Emergency drill | "Smoke from a rack in the habitat": runs the emergency flow, banner + steps, then "clear" |
| Conditions what-if | "34 % O₂ at 10.2 psi: what burned near here?" (moves the sliders) |
| Science question | "Does airflow make fabric burn faster in microgravity?" |
| Explain a concept | "What is a cool flame?" (Learn mode) |
| Compare | "BRE at 34 % vs the ISS at 21 %: what changes?" |
| Vague on purpose | "Is it dangerous here?" (shows the clarifying question with options) |

- **Content:** `scenario_cards.json`, 4 pillars × 3 scenarios × 6 types = **72 cards**, written once, each with its expected question type and key facts.
- Each card is a golden in the eval (15.8). A card that fails the eval is hidden, never shown broken.
- **Demo safety (D15-3):** the answers to the 72 cards are cached after a passing eval run. When the APIs are slow or out of quota, the card plays its cached answer (marked "cached" in the log, not on screen).

### 15.7 Voice and chat experience
- **The chat box does not open suddenly:**
  - the chat is a docked panel with a smooth height transition;
  - focusing the input never moves the layout;
  - a typing / thinking indicator shows while waiting;
  - Enter sends, Shift+Enter makes a new line;
  - chips under the input show the next-step offers.
- **Voice:**
  - echo guard (Round 13 §13.8);
  - barge-in (the user can interrupt);
  - the filler at 1.5 s;
  - one language per session unless the user switches;
  - Arabic replies keep the numbers as digits.
- **Category entry:**
  - each hub card shows real counts (investigations · tests · flight %) and "You can ask: …";
  - entering a category plays one short intro (≤ 2 sentences) and highlights the deck.

### 15.8 Evaluation: proof that the solution is solid (for the judges)
**A fixed eval set, versioned in the repo** (`eval/`), about 150 items:
- the 72 scenario cards;
- 40 real logged questions (incl. this session and Rounds 10 / 13);
- 20 general → specific pairs (Round 14);
- 15 adversarial items (vague, off-topic, unsafe, "safest", Mars numbers, a pasted table row, Arabic).

Each item has its expected question type, tool(s), key facts / numbers, source ids, and an "allowed to clarify" flag.

**Metrics (an automatic script, `eval/run.py`, run before each demo):**
| metric | how | target |
|---|---|---|
| routing accuracy | type + tool vs expected | ≥ 90 % |
| retrieval hit@5 | the expected source in the top 5 chunks | ≥ 80 % |
| citation precision | spoken / shown sentences whose cited chunk supports them (the checker + a model judge on a sample, with a human check of 30) | ≥ 95 % |
| number faithfulness | every spoken number appears in the tool / chunk text | 100 % |
| answer rate | answered or clarified with real options (not "not covered") | ≥ 95 % |
| forbidden-word checks | "safest", Mars numbers, "coverage" for the suit … | 0 violations |
| latency | p50 / p95 of `answer()` | ≤ 2.5 s / ≤ 4.5 s |

**Judge-facing proof:**
- an **"Evaluation" page in the app** (a tab on the home screen): the metric table from the last run, the date, the corpus size (papers, NASA documents, tests, findings), 5 example traces (question → understanding → tools → sources → answer), and how to rerun it;
- the same numbers in the README and the demo video.

### 15.9 Reliability for the demo
- **Health panel** (`/api/health` + a small badge): RAG ON / OFF, Postgres, Cohere / Gemini / Groq key pools (calls left), `serving.db` hash, last eval run.
- **Quotas:**
  - one Cohere embed + one rerank per question; cached embeddings for the cards;
  - Gemini Live on its own key, never shared with the composer pool.
- **Fallbacks:** RAG down → FTS; composer down → the extractive answer; Gemini Live down → the typed chat still works through `answer()` (REST), so the dashboard and cards still demo.

### 15.10 Decisions for the team
- **D15-1:** one sentence of labelled general background for "what is / what does X mean" when the glossary and the RAG have nothing. **Proposed: yes.**
- **D15-2:** Crew / Learn mode. (a) Automatic + a toggle; (b) a toggle only. **Proposed: (a).**
- **D15-3:** cached answers for the scenario cards as a demo fallback. **Proposed: yes**, refreshed by each passing eval run.
- **D15-4:** the understanding step uses a small model (Flash-Lite / Groq) with the rules as the fallback. **Proposed: yes** (the rules alone mis-type long, typo'd or Arabic questions).

### 15.11 Phases (each ends with a STOP and a review in the chat)
| phase | content | STOP evidence |
|---|---|---|
| **P1: answer engine** | 15.1 (model understanding, 5 new tools: `explain`, `interpret_conditions`, `get_test`, `compare_tests`, `list_papers`; the answer shape; follow-up lists; the server runs `answer()` on every question turn; speed; adaptive retrieval depth), 15.2 glossary draft | the replay of this session + Round 13 / 14 replays: a table question → type → tools → first spoken line; the not-covered count before / after; latency p50 / p95 |
| **P2: persona + home + chat** | 15.3 prompt + modes, 15.4 home routing + breadcrumb, 15.7 chat / voice | a screen recording: a question on the home screen opening the dashboard; Crew vs Learn answers to the same question |
| **P3: dashboard v2** | 15.5 caching, layout, chart rules, test drawer, compare | screenshots at 1440×900 for each chart type; entry time < 300 ms cached |
| **P4: scenario deck** | 15.6, 72 cards + their goldens | a screenshot of the deck per scenario; the card eval results |
| **P5: evaluation + reliability** | 15.8 eval set, `eval/run.py`, the Evaluation page, 15.9 health + fallbacks | the metric table vs targets; the Evaluation page screenshot |
| **P6: final live test** | the chat browser test + the team's voice test (English + Arabic) with headphones | the logs; the go / no-go list for the demo |

Rounds 12–14 open items are folded into P1–P3. Nothing in this round changes the data rules: every number from flameo, sources on screen, honest coverage.

### 15.12 P1 review (2026-11-12 22:50): ACCEPTED with a short P1.1 fix list before P2
**P1 result** (Claude Code report):
- 5 new tools + goldens in psi_stage1, vendored;
- replay of 87 questions: **0 "not covered"** (was 6 of 19 in the Round 15 session);
- the Round 15 transcript scores 19 / 19;
- `answer()` latency p50 1.3 s, p95 4.0 s;
- tests 481 + 164 green;
- glossary draft of 44 terms.

**Good:** the explain / test / nearest / papers / interpret question types work, and "what they cover" resolves to the 3 ranked investigations.

**P1.1 (fix before P2, about 1–2 hours):**
1. **The interpretation wording is wrong:** "18 percent oxygen is about the same as the 21 percent of the ISS cabin".
   - Rule: compare by the actual difference. "About the same" only within ±1 point; otherwise "below / above the ISS cabin's 21 %", and say by how much only if flameo returns the number.
   - Add goldens for 18 %, 21 %, 26 %, 34 %, 40 % and 100 %.
2. **The answer to "what's the best paper (appears a lot)" starts with a count** ("168 papers have findings in the data"). The first line must answer the question: the paper with the most findings (title, investigation, n findings), then the next 2, then the count.
3. **"What does the screen say?"** went to a clarify (SPICE or BASS-II).
   - Add a `screen` question type → speak the current view's `overview_speak` / answer headline from `DashboardState` (what is actually on screen).
   - Golden: on the Prevention overview → the Prevention overview line.
4. **The understanding model times out on 22 of 41 calls (1.3 s each)**, so on those turns it adds latency and gives nothing.
   - Keep it asynchronous: start the rules plan and the RAG prefetch at once, and accept the model's result only if it arrives within 0.9 s. Otherwise go on with the rules (no wait).
   - Pick the fastest available classification model from the provider's model list (Groq first), and give the understanding step its own key from the pool.
   - Report the model's success rate and the latency it adds (p50 / p95 with vs without it).
5. **Adaptive depth fires too often** (the second pass on about 38 of 59 RAG calls). Change the trigger to:
   - 0 chunks above the cutoff,
   - or fewer than 10 candidates in scope,
   - or the composer dropped every sentence.

   Drop "fewer than 3 pass the cutoff". Rerun the 30-question eval **twice** for both off and on when the Gemini quota is back; report the run-to-run spread. Keep it on only if the answer rate is ≥ off and hit@5 is within the spread.
6. **The explain example must be on topic:** use a finding as the example only if its text contains the term (or a glossary synonym). Otherwise show no example (ignition currently shows a reignition finding).
7. **Rerun the live replay after these fixes** (the BRE fix is not in the current report).
8. **Send 10 random full answers from the replay** (question, spoken lines, sources, the chunk quotes behind them) for a correctness check by the chat. 0 "not covered" is good only if the answers are right.

**Glossary (team, in parallel with P1.1):**
- the 44 terms are Claude Code's drafts from general knowledge, and 20 have no source;
- the team splits them (about 11 each across 4 people), checks each definition, adds a corpus source or marks it "general background" (D15-1), and fills `reviewer` / date;
- unreviewed terms are not spoken; the screen shows them labelled "draft".

**Other notes:**
- **Quota:** the Gemini keys hit 429 during the replay. For the demo:
  - Gemini Live gets its own key, used by nothing else;
  - the composer uses Groq first when Gemini is out;
  - the health badge (P5) shows the calls left.
- **Git:** `src/agent.py` was committed with some of the team's earlier uncommitted lines (the deploy / `LIVEKIT_PUBLIC_URL` work). The team checks that commit's diff; `src/api.py` is still uncommitted.
- **Not done in P1 and moved to P2:**
  - the voice catch-up path (Gemini skips the tool → the server's answer is spoken);
  - the 1.5 s filler.
- **Postgres:** can keep running.

**STOP for P1.1:** the new replay table (only the changed rows + totals), the model success / added latency, the adaptive on / off × 2 table, and the 10 sample answers. Then P2.

## Next
Rounds 1–6 are DECIDED; Round 7 is DECIDED with §7.7 (the team ran it); Round 8 is DECIDED (applied); Round 9 is DECIDED (applied); Rounds 10 and 11 are DECIDED (applied, ec17eb5); Round 12 is PROPOSED; Round 13 is PROPOSED; Round 14 is DECIDED (built, src/router); Round 15 (the final plan) is DECIDED (D15-1 yes, D15-2 (a), D15-3 yes, D15-4 yes); P1 done, P1.1 next (§15.12). With Round 3, Gemini gets 9 intent tools (Round 1 item 5 plus `rank_investigations`). Claude Code works from `chat_decisions/stage7-claude-code-brief.md` (project copy: `claude/stage7-claude-code-brief.md`), with the review prints listed in the use-case plan §4.
