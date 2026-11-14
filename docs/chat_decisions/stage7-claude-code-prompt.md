# Stage 7 — prompt for Claude Code (paste everything below the line)

---

You are implementing Stage 7 of our NASA Space Apps 2026 project "Flame in Freefall": the Flamo voice agent and its dashboard switch from hard-coded / mock content to real data. The planning is finished and every decision is final. Your job is to implement it exactly, test it, and stop at the two stop points.

## Where things are
- **Agent + frontend repo:** `~/Desktop/nasa-multi-agents-stages/AstroEntropy` (GitHub `0xMotazMohamed/Astro-Entropy`).
  - Base: `main` @ `c8093ae`.
  - Create a branch `stage7-real-data` from it and work only there.
  - Never push to `main`. Do not push at all unless I ask.
- **Data tools repo:** `~/Desktop/nasa-multi-agents-stages/s1/s0-results/psi_stage1`. It holds `flameo_tools/` (the 9 intent tools + 2 mock wrappers, stdlib only), `local_data/serving.db` (~35 MB, read-only) and `reports/stage6/` (the 29 golden answers in `stage6_final.md`). If it is a git repo, work on a branch `stage7` there too; if not, back up every file before you change it.
- **The three planning files you must follow**, in `AstroEntropy/chat_decisions/`:
  1. `stage7-decisions.md`: all decisions, Rounds 0–3, all DECIDED. **This file wins over everything else**, including this prompt.
  2. `stage7-claude-code-brief.md`: the work plan, Parts A–E. Follow it in order.
  3. `stage7-use-cases.md`: the question bank, the demo script and the review prints you must produce.

  If `chat_decisions/` is missing after you switch branches, stop and tell me.

## Read before you write any code
1. The three files above, completely.
2. `psi_stage1/flameo_tools/README.md` and `psi_stage1/reports/stage6/handoff_for_integration.md` (the data contract).
3. In AstroEntropy:
   - `CONTRACT.md`, `HANDOFF.md`, `VOICE_TEST.md`;
   - `src/{agent,tools,events,notify,prompts,categories,state,bridge,api,data,mock_data}.py`;
   - `frontend/src/coreSolution/{FlameApp,FlameDashboard,adapters,DashboardContext,protocol,categories,envParam}.js(x)`.

Then write me a short plan (files to change per Part, in order) before you start Part A. Do not wait for my reply to it unless something in the decisions is unclear or contradicts the code; in that case, ask before changing anything.

## Non-negotiable rules
1. **Disk first:** run `df -h ~`. If there is not enough room for the Python environment, `npm install` and a `serving.db` backup, stop and tell me.
2. **No LLM or API calls** from you. Never start the voice agent against Gemini or LiveKit. A person runs `VOICE_TEST.md`; you only write its rows.
3. **Secrets:** never print, log or commit `.env` values or keys. `serving.db` and `logs/` are never committed (add `*.db` and `logs/` to `.gitignore`).
4. **Numbers:** every number on screen or spoken comes from a `flameo_tools` answer. The adapter selects and trims, but never computes a new number. No random or demo numbers anywhere.
5. **Wording:**
   - the team has no combustion expertise; scientific text comes only from `flameo_tools` answers and the fixed texts written in the decisions file (intros, chips, phase lines, "open question" templates);
   - never write or let the agent say: "safest" or "safer", an extinguisher amount, a Mars number, spacesuit "coverage", or "on the ISS" for a finding that is not from flight.
6. **Ranking:** only `rank_investigations` produces a ranking (registry tier, then flight, then tests near the scenario, then findings; the bar shows a real test count). Materials and suppression gases are never ranked, and the frontend must never sort a bar chart into a ranking.
7. **Scope:** change `flameo_tools` only as Part A lists. `serving.db` content stays the same; you only rebuild it with `--verify`.
8. **Keep** what `c8093ae` added: the scenes, preloading, the `?env=` URL scenario (`envParam.js`) and the ISS / habitat / suit buttons.

## Order of work
### Part A — `flameo_tools`, then STOP 1
Do brief Part A items 1–6:
- `rank_investigations` + the tier column in the registry;
- the partial-gravity line naming LUCI and FM2;
- the new first line of g13 / g14;
- goldens g30+;
- `reports/stage7/review_prints.md`: all 20 `show_view` outputs (5 views × iss / moon_base / spacesuit, plus 5 with no scenario), the 2 `query_data` metrics, the 12 free questions through `search_text`, the new rankings, and the byte size and counts of each `show_view` JSON;
- rebuild with `--verify`, run the full suite, update the README.

Write `reports/stage7/partA_report.md`.

**STOP 1.** Tell me the paths of the two reports and the test counts, then wait. I will review the prints with the planning chat and tell you which "Ask me" chips stay and whether any wording changes.

### Parts B, C, D — only after I say "continue"
- **Part B (agent):**
  - vendor `flameo_tools` (with a sync script) and add `FLAMEO_DB`;
  - `src/adapter.py`;
  - 9 intent tool wrappers (their docstrings generated from `tool_specs()`); `show_dashboard` backed by `show_view`; delete `query_data` and `mock_data.py`;
  - in `categories.py`: coverage from the data (spacesuit: "None" + the oxygen-rich-flames note), the new intros and chips, no background text;
  - the 12 voice phases, the `question.asked` event and the silence nudge in `events.py` / `notify.py`;
  - the `prompts.py` rewrite (the answer order, the phase table, the "open question" templates, the never-say list, at most 10 router examples, short);
  - `/api/charts/o2_vs_pressure`;
  - `logs/questions.jsonl`.
- **Part C (frontend, `coreSolution`):**
  - remove every hard-coded item in brief C1 (the grep list must come back empty);
  - one panel layout for all four categories, with overview and answer states;
  - the dashboard follows the answer's `pillar`;
  - coverage badge and note;
  - the ranking panel from `rank_investigations`;
  - charts by `ref` (the full O2-vs-pressure scatter, with the user's custom point);
  - only the oxygen and pressure sliders;
  - "Ask me" chips that send `question.asked`;
  - the "Open questions: not in the data yet" panel with its footer;
  - `npm run build`.
- **Part D (tests):**
  - adapter unit tests, including "no new numbers" and < 8000 bytes;
  - all goldens through the agent path: the spoken prefix (3 lines, 4 for spacesuit) keeps every mandatory caveat, and the payload returned to the model is small;
  - the number check;
  - the hard-code grep test;
  - the new `VOICE_TEST.md` rows (8 demo steps, 3 backups, 12 free questions, one per phase);
  - Python suite and `npm run build` green.

Commit in small, logical commits on `stage7-real-data` (one per Part at least), with clear messages.

### Part E — STOP 2
Write `chat_decisions/stage7_report.md`:
- files changed per Part and test counts;
- the adapter size table (bytes before → after per view);
- any golden whose spoken prefix lost a caveat;
- chips still `pending_review`;
- anything from the decisions file you could not apply, and why.

Then stop and tell me. Do not push.

## How to report back at each stop
Give me, briefly:
- what you did;
- what passed or failed, with counts;
- the report paths;
- every place where the code forced you away from the decisions file.

No long summaries of code I can read myself.
