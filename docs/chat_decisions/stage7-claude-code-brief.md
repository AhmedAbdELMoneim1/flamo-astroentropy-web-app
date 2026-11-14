# Stage 7 — Claude Code brief: real data in the Flamo agent + dashboard

_Decisions: `chat_decisions/stage7-decisions.md` (Rounds 0–3, all DECIDED). When this brief and the decisions file disagree, the decisions file wins. Use cases and demo script: project doc `claude/stage7-use-cases.md` (copy it into `chat_decisions/` if you need it on disk)._

## 0. Before you start
- **Disk space.** The computer was too full for a shell on 2026-11-08 (up to 17 GB needed). Check `df -h ~` first and stop if there is not room for `npm install` + a `uv` environment.
- **Two repos:**
  - Agent + frontend: `~/Desktop/nasa-multi-agents-stages/AstroEntropy` (GitHub `0xMotazMohamed/Astro-Entropy`, base `main` @ `c8093ae`, which only changed frontend scenes / `FlameApp.jsx` / `FlameDashboard.jsx` and added `envParam.js` since `6309d84`). Work on a new branch `stage7-real-data`. Never push to `main`.
  - Data tools: `~/Desktop/nasa-multi-agents-stages/s1/s0-results/psi_stage1` (`flameo_tools/`, `local_data/serving.db`, `reports/`). Change only what Part A lists.
- **Rules carried over:**
  - No LLM / API calls by you. The voice tests in `VOICE_TEST.md` are run by a person.
  - Never print or store key values (`.env`).
  - The team has no combustion expertise. Scientific wording comes only from `flameo_tools` answers and the fixed texts in the decisions file.
  - Every number on screen or spoken comes from a `flameo_tools` answer. Never "safest", never a Mars number, never an extinguisher amount, never spacesuit "coverage".
- **Two stop points:** after Part A (STOP 1) and at the end (STOP 2). Write the reports listed there and wait for the chat.

## Part A — `flameo_tools` changes (in `psi_stage1`), then STOP 1
These are Stage 6-style changes: config / registry + golden questions; `serving.db` data unchanged. Back up `serving.db` before rebuilding.

1. **`rank_investigations(pillar=None, scenario=None)`**: decisions Round 3 §3.4 R1.
   - Add the tier column (A / B / C / M) to `config/psi_registry.yaml` from `psi-registry-tiers.md`, if missing. The tiers are final (D3-1).
   - Pillar → registry words: prevention → "Prevention"; flammability → "Fire behavior" or "Environment"; detection → "Detection"; suppression → "Suppression".
   - Lexicographic sort:
     1. tier;
     2. flight before ground;
     3. tests near the scenario (from `scenario_coverage`), or tests in the data when no scenario is given;
     4. accepted cards, flight first.
   - Output: a `ranking` list `[{rank, psi, name, tier, pillars, tests, tests_label, findings}]` (`tests` = the bar value, a real count; `tests_label` = "n tests near the ISS cabin" or "no oxygen / pressure recorded"), plus `table`, `speak`, `gaps` (the line "This ranks relevance to the question; it does not rate how safe anything is."), `source`, `facts`.
   - Register it in `REGISTRY` / `tool_specs()` with a docstring and examples in `router_examples.yaml`.
   - Spacesuit: never the word "coverage". Use the oxygen-rich-flames wording.
2. **Partial gravity text:** `partial_gravity_text` gets the sourced line "Such data is expected in the future, for example from the LUCI and FM2 experiments." (source `challenge-details.txt`). Decisions §3.7.
3. **g13 / g14 first line:** "The data does not rate one agent as best; these are the diluents the experiments varied." Decisions Round 1 item 8.
4. **Goldens g30+:**
   - `rank_investigations` for each pillar × `iss`, for each scenario with no pillar, and for the spacesuit;
   - the updated g13, g14 and g15.
   - Shared negative checks apply: no spoken zero counts, no "1 PSIs", no "safest / safer", no "coverage" for the spacesuit.
5. **Review prints**, into `reports/stage7/review_prints.md`, as speak + kpis + gaps (+ ranking / table head) for each:
   - all 15 `show_view(view, scenario)` (5 views × iss / moon_base / spacesuit) + `show_view(view)` for the 5 views (custom conditions);
   - `query_data("ignition_time_by_material")` and `query_data("smoke_particle_size")`;
   - `search_text` for the 12 free questions in decisions Round 2 (the keywords listed there);
   - every new `rank_investigations` golden;
   - the byte size of each `show_view` JSON and the row / column / gap / series counts (input for the adapter limits).
6. Rebuild with `--verify`, run the full suite, and update the README (§ tools, § add a tool).

**STOP 1.** Report: `reports/stage7/partA_report.md` (what changed, test counts, golden outputs) + `review_prints.md`. The chat reviews these prints before Part B uses them: they decide the "Ask me" chips and the demo script.

## Part B — agent (`AstroEntropy/src`)
1. **Dependency:**
   - Vendor `flameo_tools` into `AstroEntropy/vendor/flameo_tools`, with `scripts/sync_flameo.sh` to re-copy it from `psi_stage1`.
   - A start-up check logs the flameo version and fails clearly if `FLAMEO_DB` is unset or the file is missing.
   - Add `FLAMEO_DB=` to `.env.example`. `run.sh` / `run-local.sh` check it.
   - Add `*.db` to `.gitignore`; `serving.db` is never committed.
2. **`src/adapter.py`:** decisions Round 1 items 1 and 4. `to_dashboard()` / `to_answer()`:
   - limits: ≤ 6 columns (per-tool column map), 12 rows + "12 of N rows", gaps 3, cards 3, charts 2, 3 series × 12 points, cell text 80 characters;
   - keep KPI `basis` / `trust`;
   - add `request_id`, `metric`, `pillar` (Round 3 §3.5 map);
   - drop `facts` (kept server-side for the number check);
   - < 8000 bytes, else drop cards, then rows, and log it.

   The O2-vs-pressure chart is passed as `{"id":"o2_vs_pressure","type":"scatter","ref":"/api/charts/o2_vs_pressure",…}`. Pure functions.
3. **`src/tools.py`:** decisions Round 1 item 5, Round 2 code changes, Round 3 R2.
   - 9 explicit `@function_tool` wrappers: `get_investigation`, `compare`, `rank_materials`, `scenario_coverage`, `get_findings`, `rank_agents`, `gaps`, `search_text`, `rank_investigations`. Generate their docstrings from `tool_specs()` (`scripts/gen_tool_docs.py`) and add a test that they match.
   - Each wrapper: `asyncio.to_thread(flameo_tools.call, …)` → `to_answer` → `answer.show` → return `{status, matched, speak: speak[:n], first_gap, coverage/level, nearest, note}` (n = 3, 4 for spacesuit answers).
   - `search_text`: the Round 2 docstring ("Default tool for any fire, combustion or space-fire question … 3–6 English key words … never answer from memory"), and `matched:false` on "No passage … matches".
   - `show_dashboard` keeps its logic; its content comes from `show_view(view, scenario)` (custom conditions: `show_view(view)` with the "All PSI tests (not filtered to your conditions)" headline and the coverage gap line).
   - **Delete `query_data`** and its mock path.
4. **`src/categories.py`:**
   - Coverage levels at start-up from `scenario_coverage` (spacesuit: `coverage "None"` + `coverage_note {label, level}` from `level_oxygen_rich_flames`). Round 1 item 2.
   - The four new intros and three `suggestions` per category, exactly as written in Round 3 §3.2.
     - Prevention's overview uses the `materials` view.
     - Mark a chip `"pending_review": true` if STOP 1 found its output weak; the frontend hides those chips.
   - Copy changes from Round 1 item 7 (taglines, focus options); remove `background` from the briefing.
5. **`src/events.py` / `src/notify.py`:** phases, decisions Round 3 §3.3.
   - Scene arrival (`iss` / `moon_base` / `spacesuit`): call `scenario_coverage` + `rank_investigations(None, scenario)`, push both, send the phase message with the tool `speak[]`.
   - Category entry: the overview + `rank_investigations(pillar, scenario)` push; the message carries `phase`, `first_visit`, the intro, `speak[0]` and the first chip.
   - New event `question.asked {text}`: deliver as a normal user turn (`generate_reply(user_input=text)`), not a `[screen]` note.
   - Silence nudge: once per category, 20 s after a first-visit entry with no user speech or tap. It is cancelled by any speech, tap or agent turn.
   - Keep the existing `[screen]` path for other taps.
6. **`src/prompts.py`:** a full rewrite of the guidance sections; the persona and safety lines stay.
   - The answer order (Round 2: steps 0–7 and the rules) and the phase table (Round 3 §3.3).
   - Speak only `speak[]` lines (the first 3; 4 for spacesuit), keep every number, end with the phase's one action.
   - The "not covered" templates (§3.7).
   - The never-say list (Round 1 item 7).
   - At most 10 router examples.
   - Remove: "Being a guide / give insight / what to do about it", all demo-data lines, the hard-coded coverage words.
   - Keep the prompt short: the 5-second `generate_reply` wait applies.
7. **`src/api.py`:** `GET /api/charts/o2_vs_pressure` serves flameo's own spacesuit chart (all series and points, unchanged), built once at start-up.
8. **Question log:** `logs/questions.jsonl`, one line per turn: `{ts, transcript, tool, args, matched}`. No audio, no keys. Add `logs/` to `.gitignore`.
9. **Delete `src/mock_data.py`** and every `mock` branch; `source.mock` is false everywhere.

## Part C — frontend (`frontend/src/coreSolution`)
1. **Remove all hard-coded content** (Round 3 §3.0):
   - `CONFIG.cats` columns, sliders, chips (incl. the suppressant `suppress` values), chart axes and `rankingTitle`;
   - `buildDemoData()` and the `demo` fallback;
   - the "Risk ranking" and "AI interpretation / SAFETY TAKEAWAY" sections.

   - the material / suppressant item lists (`MAT`, and the suppression list with "Dry powder" and "Foam").

   Afterwards `grep` must find no `Math.random` in data paths and none of: "Water mist", "Dry powder", "Foam", "Easiest to ignite", "Fastest-burning materials", "Densest smoke sources", "Most effective suppressants", "Risk ranking", "SAFETY TAKEAWAY", "buildDemoData".
2. **Panels** (Round 3 §3.1): summary strip, "Most relevant investigations", chart, data table, "What the authors report", "Open questions: not in the data yet" (footer "Gaps like these show where new experiments or papers are needed."), "Ask me" chips. Empty panels are hidden.
3. **`adapters.js`:**
   - Coverage badge: High / Medium / Low; spacesuit "Spacesuit atmosphere: none tested" + a second chip from `coverage_note`; never "Data coverage: None".
   - **Remove the bar → ranking sort**: `ranking` comes only from the `ranking` field of `rank_investigations`. Bar = `tests`, label = `tests_label`; no 0–100 scores.
   - Charts with `ref` are fetched from the API. The scatter draws every series (≥ 8 colours, hollow markers for "burner stream", labelled scenario points).
   - Table footer "12 of N rows".
   - Titles: `rank_materials` → "Flame spread in the tested materials (not a safety ranking)"; `rank_agents` → "Gases added in the experiments".
4. **Two states per category:** overview / answer, with a "Back to <category> overview" chip. When an answer's `pillar` differs from the category on screen, switch to that category and show the answer there (D3-2).
5. **Inputs:**
   - Only the oxygen and pressure sliders (custom conditions); the user's point is drawn on the O2-vs-pressure chart from `inputs`, with no new number.
   - Gravity as text: "Microgravity (PSI has no partial-gravity data)".
6. **"Ask me" chips** send `ui.event` `question.asked {text}`; add it to `protocol.js` and `DashboardContext.jsx`. Hide chips with `pending_review`.
7. **Keep the `main` @ `c8093ae` additions:**
   - the URL scenario parameter (`envParam.js`, `?env=iss|moonbase|spacesuit`) and the ISS / habitat / suit buttons in `FlameApp.jsx`;
   - the scenes and their preloading.

   A scenario set from the URL on page load triggers the scene-arrival phase once. The voice must not speak twice: the URL sets the scenario and the agent then joins.
8. `npm run build` passes.

## Part D — tests
1. **Adapter unit tests:**
   - every limit;
   - **no new numbers**: every number in the adapter output appears in the flameo input;
   - `request_id` / `pillar` set;
   - < 8000 bytes for all outputs in `review_prints.md`.
2. **Agent-path goldens:** run all goldens (g01–g29 + g30+) through the wrappers.
   - The spoken prefix (`speak[:3]`, 4 for spacesuit) contains each mandatory caveat (Round 1 item 8).
   - The returned payload is small (no table / charts / cards).
3. **Number check:** for each golden, every number in the spoken prefix is in that answer's `speak[]` / facts.
4. **Hard-code check:** a test that greps the frontend and agent for the strings in C1 and for `mock: true` / `"mock": True`.
5. **`VOICE_TEST.md`:** add rows. A person runs them; you only write them.
   - the 8 demo steps + 3 backups (use cases §3);
   - the 12 free questions (Round 2);
   - one row per phase (Round 3 §3.3: opening, three scenes, first and later category entry, after-answer follow-up, not covered, custom sliders, silence nudge, chip tap, category follow);
   - each row has the expected tool and the screen state.
6. Python suite + `npm run build` green.

## Part E — STOP 2
Write `chat_decisions/stage7_report.md`:
- files changed per part;
- test counts;
- the adapter's size table (before → after bytes per view);
- any golden whose spoken prefix lost a caveat;
- the `review_prints.md` items still marked `pending_review`;
- anything in the decisions file you could not apply, and why.

Commit on `stage7-real-data` (no push unless the user asks). Then stop for the chat's review.
