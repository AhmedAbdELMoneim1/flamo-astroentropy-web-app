# Stage 7 report (STOP 2)

Branch `stage7-real-data` in `AstroEntropy` (from `main` @ `c8093ae`), 3 commits: Part B, Part C, Part D. Nothing pushed. Data repo `psi_stage1` is not a git repo: backups in `s0-results/stage7_backup/` (before Part A) and `stage7_backup2/` (before Round 4).
No LLM, Gemini or LiveKit call was made; no `.env` value was read or printed.

## Files changed per Part
**Part A + Round 4 (`psi_stage1`, see `reports/stage7/partA_report.md`)**
- `flameo_tools/tools.py` (`rank_investigations` with scenario groups and divider; `rank_agents` first line; `show_view` gap noise, doubled words, all-zero sentence, `debug[]`; `search_text` junk filter, de-duplication, sentence start), `registry.py`, `router_examples.yaml`, `README.md`; `config/serving.yaml` (LUCI / FM2 line); `serving.db` rebuilt with `--verify` (hash `ca779009...`); `tests/golden/golden_questions.yaml` (g01-g43), `tests/test_tools.py`, `tests/test_golden_checks.py`; `tools/stage7_review_prints*.py`; `reports/stage7/{partA_report,review_prints,review_prints_v2}.md`.

**Part B (agent)**
- New: `vendor/flameo_tools/`, `scripts/{sync_flameo.sh,gen_tool_docs.py}`, `src/{adapter,content,flameo,qlog,charts}.py`, `.env.example`.
- Rewritten: `src/{tools,categories,prompts,events,notify,state,agent,api,bridge}.py`, `run.sh`, `run-local.sh`, `.gitignore` (`*.db`, `logs/`).
- Deleted: `src/mock_data.py`, `src/data.py`, `scripts/check_mock_data.py`, `scripts/test_mock_tools.py`; `query_data` is gone.

**Part C (frontend `coreSolution`)**
- `adapters.js`, `FlameDashboard.jsx` (+ `.css`), `FlameApp.jsx`, `DashboardContext.jsx`, `protocol.js`, `adapters.test.js`; `adapters.check.mjs` removed. Kept from `c8093ae`: scenes and preloading, `envParam.js` (`?env=`), the ISS / habitat / suit buttons.

**Part D**
- `tests/` (8 files), `VOICE_TEST.md` (8 demo steps, 3 backups, 12 free questions, 15 phase rows), `CONTRACT.md`, `HANDOFF.md`.

## Test counts (all green)
| suite | result |
|---|---|
| `psi_stage1` full suite (`pytest tests`) | **475 passed** (goldens g01-g43, shared negative checks incl. Round 4) |
| `AstroEntropy` `pytest tests` | **108 passed, 1 skipped** (the FastAPI route test needs `fastapi`, not installed here) |
| `AstroEntropy/frontend` `vitest` | **17 passed** |
| `npm run build` | passes |
The hard-code grep (C1 list, `mock: true`, `Math.random` in `coreSolution`) is a test (`tests/test_static.py`) and comes back empty.

## Adapter size table (bytes before -> after)
"flameo bytes" = the `show_view` JSON; "adapter bytes" = the Dashboard sent in `view.open`; the last column is the whole `view.open` packet (dashboard + ranking + chips). Limit 8000.

| view | scenario | flameo bytes | adapter bytes (dashboard) | view.open bytes (dashboard + ranking + chips) | rows | cols |
|---|---|---|---|---|---|---|
| ignition | iss | 2785 | 2002 | 4527 | 2 -> 2 | 8 -> 6 |
| ignition | moon_base | 2644 | 1368 | 4079 | 0 -> 0 | 8 -> 0 |
| ignition | spacesuit | 27325 | 2971 | 6168 | 0 -> 0 | 8 -> 0 |
| ignition | none (custom) | 4502 | 3458 | 5919 | 11 -> 11 | 8 -> 6 |
| materials | iss | 5655 | 3613 | 5944 | 20 -> 12 | 7 -> 6 |
| materials | moon_base | 1652 | 624 | 3004 | 0 -> 0 | 7 -> 0 |
| materials | spacesuit | 27231 | 2933 | 6115 | 0 -> 0 | 7 -> 0 |
| materials | none (custom) | 5471 | 3593 | 5889 | 20 -> 12 | 7 -> 6 |
| flame_spread | iss | 5435 | 3836 | 6561 | 19 -> 12 | 6 -> 6 |
| flame_spread | moon_base | 1796 | 674 | 3361 | 0 -> 0 | 6 -> 0 |
| flame_spread | spacesuit | 27210 | 2956 | 6465 | 0 -> 0 | 6 -> 0 |
| flame_spread | none (custom) | 5600 | 3907 | 6551 | 20 -> 12 | 6 -> 6 |
| smoke | iss | 1913 | 912 | 5215 | 0 -> 0 | 6 -> 0 |
| smoke | moon_base | 1871 | 814 | 5236 | 0 -> 0 | 6 -> 0 |
| smoke | spacesuit | 27176 | 2954 | 5442 | 0 -> 0 | 6 -> 0 |
| smoke | none (custom) | 3478 | 3190 | 5228 | 10 -> 10 | 6 -> 6 |
| suppression | iss | 7519 | 3839 | 5680 | 20 -> 12 | 8 -> 6 |
| suppression | moon_base | 2269 | 971 | 2730 | 0 -> 0 | 8 -> 0 |
| suppression | spacesuit | 27571 | 2997 | 5462 | 0 -> 0 | 8 -> 0 |
| suppression | none (custom) | 9600 | 4140 | 6058 | 20 -> 12 | 8 -> 6 |

Largest packet: 6565 bytes. Answers: 1.9 to 5.5 KB (scene answer with ranking, spacesuit: 5.5 KB). The 6 outputs that exceeded 8000 in Part A are now: spacesuit views 27 KB -> 3.0 KB (the chart travels by `ref`), `suppression` custom 9.6 KB -> 4.1 KB.

## Goldens whose spoken prefix lost a caveat
Three would have lost one with the plain `speak[:3]` rule; none loses it now, because `adapter.to_model` pulls a mandatory caveat that lies beyond the prefix forward (only lines already in `speak[]`):
- **g06** `rank_materials`: "No flight finding on this is in the data ..." (line 8).
- **g13, g14** `rank_agents`: "The amount of an extinguishing agent is not in the data ..." (last line).
Mandatory = a line starting "No ", or containing "nothing is ranked", "not supported by the PSI data", "is not in the data", "does not rate", "not the spacesuit atmosphere". `tests/test_agent_path.py` asserts every golden keeps all of them in what the voice receives, and that every spoken number is in the answer's `speak` / facts.

## Chips still `pending_review`
- Detection chip 3 **"What did SAME measure?"** (hidden). `get_investigation("SAME")` (`review_prints_v2.md`): "SAME (PSI-102) is a flight investigation", registry: Detection, 8 table tests, flow speed 5 to 10 cm/s, materials Teflon, Kapton, silicone rubber, lampwick; gap: no pressure values. Thin: no oxygen, no outcome fields. Your call.

## Where the code or the environment forced a change from the decisions
1. **16 tools, not 15.** Round 1 item 5 counted 8 intent tools; with `rank_investigations` Gemini gets 9 + 7 = 16. `VOICE_TEST.md` says to check for 1007 / timeouts and gives the `compare` merge as the fallback.
2. **flameo sqlite connection is shared and not safe for concurrent calls** (two `asyncio.to_thread` calls crashed with "API misuse"). Fixed in the agent with a lock in `src/flameo.py`; `flameo_tools` itself unchanged. Its README says "safe from several threads": that is not true for simultaneous calls.
3. **Default category on page load is silent.** The frontend opens its default category by itself (`view.selected` with `source: "auto"`); the agent pushes the view but stays silent and does not count it as a visit, so it cannot collide with the greeting. Side effect: the first-visit intro of that default category (Flammability) can only be heard by asking, because tapping the already-open tab sends nothing.
4. **Scene answer + ranking are one `answer.show`** (coverage answer with the overall ranking attached), not two packets, so the answer panel shows both.
5. **Q6 golden (g43) "water mist extinguish"** returns 3 distinct lines, not one: the Researchers Guide p26 first, then two other real passages. Round 4 asked for "one line, the Guide p26"; the golden checks that the Guide line is first and that there are no duplicates, DOI or author blocks.
6. **Reconnect line (phase 12)** is wired to the room's `reconnected` event, and the silence nudge to the session events `user_input_transcribed` and `agent_state_changed`. `livekit-agents` is not installed here, so these three event names are **not verified** against the installed plugin version (`VOICE_TEST.md` P11, P12).
7. **Pillar ranking with a scenario** (for example Suppression + spacesuit) stays tier-first as decided (4.1), so rows read "no burner-stream tests ..." for investigations that have none. Only the no-pillar scenario ranking has the divider.
8. `ignition` is reachable by a question or the Materials / Ignition switch only; the Prevention overview is `materials` (decisions 3.2). The `ignition` view is weak (2 rows near the ISS, none for the Moon).
9. Not applied: nothing from the decisions file was left out. The two items that cannot be checked without a live session are the voice behaviours (phases, nudge, URL single-utterance start): written, unit-tested with fakes, not heard.

## What nobody has run yet
- Any live voice session (Gemini, LiveKit): `VOICE_TEST.md` is for a person.
- The page in a browser connected to the real agent. The dashboard engine was rendered in a browser pane with real packets built by the adapter (overview, answer state, spacesuit scatter with the "your conditions" point, ranking with divider); no console errors.
- `fastapi` / `livekit-agents` imports of `src/api.py` and `src/agent.py` (compile only; their logic is in tested modules).

## Round 5 (applied)
- 5.1 `search_text`: with 2+ card lines only the cards go to the voice (Q5: 2 cards, the figure caption stays on screen); test with the Q5 output. 5.2: the greeting ends with "You're on <category>; for example, ask me: <chip 1>. Or pick another topic."; the default category stays not visited. 5.3: "1 finding" fix in `flameo_tools` + shared negative check. 5.4: README thread-safety sentence corrected. 5.5: SAME chip stays hidden.
- 5.6 (`uv sync`, livekit-agents 1.8.10): `user_input_transcribed`, `agent_state_changed` (fields `transcript`, `is_final`, `new_state`) and the room `reconnected` event all exist under exactly those names; `generate_reply(user_input=...)` and `interrupt()` exist. No name needed fixing. `src/agent.py` and `src/api.py` import for real; the FastAPI route test runs (no longer skipped). `tests/test_wiring.py` pins these names.
- Suites: psi_stage1 475 passed; AstroEntropy 116 passed; vitest 17 passed; `npm run build` passes.
