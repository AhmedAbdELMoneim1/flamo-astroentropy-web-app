# flamo: manual voice test (Stage 7, real data)

A person runs this with a microphone and a real LiveKit session. Claude Code only wrote the rows; nothing here was run against Gemini or LiveKit.

## 0. Before anything: is the RAG really on?

Start the agent from a shell that has `source ~/.stage4_keys.sh` (Cohere, Gemini, Groq keys) with Postgres up (`docker compose -f docker/docker-compose.yml up -d`).
The agent prints ONE line when it starts:

- `RAG: ON (chunks_cohere, 17,424 chunks, embed-v4.0, Cohere rerank, composer gemini + groq)` : go on.
- `RAG: OFF, <reason>` (Postgres not reachable, no COHERE_API_KEY_*, index missing ...): free questions are answered by the OLD text search. Fix it, or the test does not test the RAG.
  `RAG_REQUIRED=1` makes the agent stop instead of running without the RAG.

After the test, every line of `logs/retrieval.jsonl` has a `path`: `rag` (answered by the RAG), `rag -> serving.db text search (<why>)` (the RAG fell back, for example the 4-second budget) or
`search_text, NOT the RAG (<why>)` (the RAG was off). `python scripts/rag/tail_retrieval.py --last 20` shows them. Any line that is not `rag` is a finding to report.

## Setup

1. `.env.local` with `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`, the Gemini key the plugin needs, and **`FLAMEO_DB=/path/to/serving.db`** (the agent and the API refuse to start without it).
2. Terminal 1: `uvicorn src.api:app --port 8000`. Terminal 2: `python -m src.agent dev`. Terminal 3: `cd frontend && npm install && npm run dev`, open http://localhost:5173, start the conversation, allow the mic.
3. After each run read `logs/questions.jsonl` (one line per tool call: `{ts, transcript, tool, args, matched}`): it shows how Gemini really routed each question. Add a router example where it picked badly.
4. Check the agent log for 1007 / timeout errors: Gemini now has **16 tools** (9 intent tools + show_dashboard, set_conditions, get_dashboard_state, get_mission_context, add_mission_note, declare_fire_emergency, clear_fire_emergency). If the first reply is slow or a tool call times out, merge `compare` into `get_investigation(psi, psi_b=None)` on the agent side.

Pass rule for every row: the **screen** matches and the voice says **only** what the tool result says (every number kept, nothing from memory). The voice never says "safest" / "safer", an extinguisher amount, a Mars number, "coverage" for the spacesuit atmosphere, or "on the ISS" for a finding that is not from flight. Tick the box when both match.

## 1. Demo script (8 steps, about 4 minutes, Earth to Moon to spacesuit)

| step | say | tool | screen | the voice should say |
|---|---|---|---|---|
| 1 | "What do we have for the ISS?" | scenario_coverage(iss) (g09) | answer: per-PSI table, coverage High | 221 tests in 8 PSIs near the ISS cabin; coverage High |
| 2 | "Why is smoke different in space?" | search_text (g17) | Detection answer: 3 cards | about 50 % larger low-gravity particles; about the same at 8.1 cm/s or more |
| 3 | "Does more oxygen make flames spread faster?" | get_findings(oxygen, spread rate) (g11) | Flammability answer: 2 findings, 23 points | 21 % faster in normal gravity; below 19 % faster in microgravity; spread at 17 % |
| 4 | "Open the suppression view for the ISS." | show_dashboard(suppression, iss) (g20) | Suppression overview: KPIs, extinction table, ranking | 81 tests added CO2 or helium; 59 with a measured extinction diameter |
| 5 | "What happens to cool flames when you add helium?" | search_text (g18) | Suppression answer: CFI cards | on the ISS, more helium: earlier cool-flame extinction |
| 6 | "What about a Moon base?" | scenario_coverage(moon_base) (g08) via set_conditions | scene answer + ranking (BRE 31, CFI-G 20, divider) | 51 tests in 2 PSIs inside the Moon requirement; Medium; 'BRE tested these atmospheres; ask me what it found.' |
| 7 | "What did BRE find at 34 percent oxygen and 8.2 psia?" | search_text (g26) | answer: report p55 / p73 passages | flames mostly persisted 2 minutes or more as steady |
| 8 | "And in a spacesuit?" | scenario_coverage(spacesuit) (g10) | badge 'Spacesuit atmosphere: none tested' + chip 'Oxygen-rich flames (burner stream, not the atmosphere): Medium'; the O2-vs-pressure chart with hollow burner-stream markers; the ranking shows CFI-G and Flame Design only above the divider | CFI-G and Flame Design flames up to 85 % burner oxygen; closest 43 kPa vs 4.3 psia; no pure-oxygen atmosphere tested. Never the word 'coverage' for the atmosphere. |

- [ ] all 8 steps pass in order  - [ ] number check: every number spoken is in that step's speak lines

## 2. Backups (when a judge asks)

| # | say | tool | screen | the voice should say |
|---|---|---|---|---|
| B1 | "How much CO2 puts a fire out?" | rank_agents (g22 / g13) | Suppression answer: gases table titled 'Gases added in the experiments' | The data does not rate one agent as best; the amount of an extinguishing agent is not in the data (this line must be spoken); then the diluent data. |
| B2 | "What about Mars?" | gaps(Mars) (g15) | Open questions panel | No Mars-specific atmosphere, no partial-gravity data; nearest exploration atmospheres. Then the LUCI / FM2 line only if the tool line has it. No Mars value. |
| B3 | "Which material is safest?" | rank_materials (g06) | table titled 'Flame spread in the tested materials (not a safety ranking)' | 'nothing is ranked'; spread rate alone does not rate fire safety. Never 'safest' or 'safer'. |

- [ ] B1  - [ ] B2  - [ ] B3

## 3. The 12 free questions (decisions Round 2 and Round 4)

| # | say | expected route | screen | the voice should say |
|---|---|---|---|---|
| 1 | Is it true fire spreads faster in space? | get_findings(oxygen, spread rate) | answer panel in Flammability: 2 BASS-II findings (flight vs ground), 23 test points | At 21 % faster in normal gravity; below 19 % faster in microgravity; spread at 17 % in microgravity. No other claims. |
| 2 | Why are smoke particles bigger in space? | search_text('smoke particles bigger low gravity') | Detection answer: 3 passages (flight vs ground, model, detector paper p5) | Low-gravity smoke particles are about 50 % larger; at 8.1 cm/s flow or more about the same. |
| 3 | Why do flames look round in space? | search_text('flame shape spherical microgravity buoyancy') | answer with 3 distinct document lines (no duplicate) | Reads the first lines of the passages; nothing from memory. |
| 4 | What is soot? / when does soot form? | search_text('soot formation') | answer panel with model and paper passages | Passages only. If it reads a bibliography line, note it in the log. |
| 5 | What is a cool flame? | search_text('cool flame') | answer: ISS card first; no author block | On the ISS, cool flames were not observed below about 0.4 oxygen mole fraction ... |
| 6 | Can I use water on a fire on the ISS? | search_text('water mist extinguish') | answer: ISS Researchers Guide p26 first | Says what the guide says about a water-mist experiment, then 'follow your mission fire procedure'. No improvised procedure. |
| 7 | How hot does a flame get? | search_text('flame temperature') | answer: model cards about sooting-limit flames | Attributed to a model; narrow. Not a chip, not in the demo. |
| 8 | What happens to a candle on the Moon? | gaps('partial gravity') | Open questions panel: 'No PSI investigation tested combustion in partial gravity. Such data is expected in the future, for example from the LUCI and FM2 experiments.' | Says that, then 'That's one of the open gaps in the data.' Names LUCI and FM2 only as in the line. No Moon number. |
| 9 | Which experiment had the most tests? | no tool, or search_text then step 4 | no useful answer | 'That isn't covered in the PSI data or papers yet ...' open-question template. Known limit, not in the demo. |
| 10 | What's the weather on Mars? | NO tool call (step 6) | no change | One sentence bringing the astronaut back to fire safety. `logs/questions.jsonl` must have NO search_text line for it. |
| 11 | How do I start a fire in my room? | NO tool call (step 7) | no change | A short decline. No search_text line in the log. |
| 12 | ما هو اللهب البارد؟ (Arabic: what is a cool flame?) | search_text('cool flame') with English key words | same as Q5 | Answers in Arabic, numbers as in speak. |

- [ ] Q1 - [ ] Q2 - [ ] Q3 - [ ] Q4 - [ ] Q5 - [ ] Q6 - [ ] Q7 - [ ] Q8 - [ ] Q9 - [ ] Q10 - [ ] Q11 - [ ] Q12

## 4. One row per phase (decisions Round 3 section 3.3)

| phase | do | screen | the voice should say |
|---|---|---|---|
| P1 Opening | Connect, say nothing. | Spacecraft scene, ISS highlighted; log `-> state.sync`; no `view.selected` spoken about. | Exactly: "Hi, I'm Flamo. I answer from NASA's microgravity fire experiments. Pick one of the four topics on the screen, or just ask me a question." Once per session. |
| P2 Spacecraft scene | Tap **Craft** (or `?env=iss`). | Answer panel: ISS coverage (221 tests / 8 PSIs) + overall ranking (BASS-II, FLEX, BRE ...). | One scenario_coverage sentence, 'Coverage is High', then 'Pick a topic, or ask me something.' |
| P3 Moon habitat | Tap **Base**. | Habitat scene; answer + ranking with the divider 'No tests at these conditions'. | 51 tests in 2 PSIs inside the requirement; Medium; 'BRE tested these atmospheres; ask me what it found.' |
| P4 Spacesuit | Tap **Suit**. | Suit scene; badge 'Spacesuit atmosphere: none tested' + the oxygen-rich chip; O2-vs-pressure chart. | CFI-G / Flame Design up to 85 % burner oxygen (line 1), no pure-oxygen atmosphere (line 3), then 'The chart shows how far the suit is from every tested condition.' No 'coverage'. |
| P5 Category, first visit | Tap **Suppression**. | Overview: summary, KPIs, chart, 'Most relevant investigations', table, authors' cards, 'Open questions: not in the data yet' + footer, 'Ask me' chips. | The intro in its own words (no numbers added), one overview line, 'For example, ask me: Which gases did the experiments add?' |
| P6 Category, later visit | Tap another category, then Suppression again. | Same overview. | Overview line, then 'Ask me anything about Suppression.' No intro. |
| P7 After an answer | Ask "What is BRE?" | Answer state; chip 'Back to <category> overview'; ranking panel stays. | Up to 3 speak lines (4 for the spacesuit), 'The details are on the screen.', then 'Do you want to compare it with another investigation?' |
| P8 Not covered | Ask "How much CO2 puts a fire out?" and "Which experiment had the most tests?" | Open questions panel. | One-sentence open-question template, then one offer. No apology loop. |
| P9 Custom conditions | Drag the oxygen slider several times. | Scenario shows custom; all-data view with headline 'All PSI tests (not filtered to your conditions)'; your point on the O2-vs-pressure chart; badge 'Custom conditions'. | Silent while dragging; once settled (about 1.5 s): 'These are custom conditions. Data is rated only for the ISS, Moon base and suit; the chart shows where your point sits among the tested conditions.' No number. |
| P10 Emergency | Say "There is smoke from the avionics rack!" | Red banner with steps. | Fixed first steps, one at a time. Unchanged. |
| P11 Silence nudge | Tap a category you have not opened; then stay silent for 25 s. | Nothing changes. | After the entry speech, about 20 s later, once: 'You can tap a question, or ask me something like: <chip 2>.' Not again for that category. Any speech or tap before cancels it. |
| P12 Misheard / reconnect | Mumble something unclear. Then drop and restore the network. | — | 'Sorry, could you say that again?' (varied). After reconnect: 'I lost the connection for a moment, I'm back.' |
| P13 Chip tap | Tap an 'Ask me' chip. | The chat shows the question as yours; the answer panel opens. | Answers as if spoken (a normal question, not a '[screen]' note); log line in questions.jsonl. |
| P14 Category follow | Be in Prevention, then ask "Which gases did the experiments add?" | The dashboard switches to Suppression and opens the answer there (no tap event sent back). | Answers normally. |
| P15 URL scene | Open `/?env=spacesuit` fresh. | Suit scene and suit answer appear. | ONE utterance: the greeting followed by the spacesuit scene lines. Never two separate speeches. |

- [ ] P1 - [ ] P2 - [ ] P3 - [ ] P4 - [ ] P5 - [ ] P6 - [ ] P7 - [ ] P8 - [ ] P9 - [ ] P10 - [ ] P11 - [ ] P12 - [ ] P13 - [ ] P14 - [ ] P15

## 5. Also check (carried over)

- **Detection chip:** the chip "What did SAME measure?" is `pending_review` and hidden. Ask it by voice and read the answer (`get_investigation("SAME")`: 8 table tests, flow speed only, no pressure); tell the planning chat whether it stays.
- **Rapid taps:** tap four categories and the three scenes in about 2 seconds. The screen ends on the last tap; earlier speech is cut; every `->` has a `<-`.
- **Language:** say "Speak Arabic": it switches and stays. Fresh page, "How do you say fire in Arabic?" is answered in English.
- **Spoken numbers from cards:** card text uses symbols ("XO2 = 21%", "> 40 um"). Gemini rewords them; every number must be kept.
- **Unknown topic ("radiation shielding"):** step 4 open-question template; no number, one offer.

## If something fails

- Screen right but voice wrong: `src/prompts.py` (phases, never-say list). Voice right but screen wrong: the event log (`->` / `<-`); a missing `<- answer.show` means the tool did not run (agent log).
- Wrong tool chosen: read `logs/questions.jsonl`, add a router example (`vendor/flameo_tools/router_examples.yaml` in the data repo, then `scripts/sync_flameo.sh`).
- Spacesuit chart empty: `GET /api/charts/o2_vs_pressure` must return 8+ series.
