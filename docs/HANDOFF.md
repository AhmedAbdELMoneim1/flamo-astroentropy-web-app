# HANDOFF: flamo on real data (Stage 7)

The agent and the dashboard read `serving.db` through `flameo_tools` (vendored in `vendor/flameo_tools`, re-copied by `scripts/sync_flameo.sh`).
Decisions: `chat_decisions/stage7-decisions.md` (Rounds 0 to 4). Report: `chat_decisions/stage7_report.md`. Voice checklist: `VOICE_TEST.md`.

## Run
- Set `FLAMEO_DB=/path/to/serving.db` (see `.env.example`). The agent, the API and `run*.sh` refuse to start without it. `serving.db` and `logs/` are never committed.
- Tests: `python -m pytest tests` (needs the psi_stage1 `serving.db` and goldens; `FLAMEO_DB` / `FLAMEO_GOLDEN` override the paths; no network, no model) and `cd frontend && npm test && npm run build`.

## Where things are
| file | job |
|---|---|
| `src/adapter.py` | pure functions: flameo JSON to Dashboard / Answer / ranking / model payload. Selects and trims only (<= 8000 bytes, 6 columns, 12 rows, 3 gaps, 3 cards, 2 charts, 3 series x 12 points, 80-character cells, 8 ranking rows). Never computes a number. |
| `src/content.py` | overview (`show_view` + `rank_investigations`), scene arrival, `Runner.intent` (run a tool, push `answer.show`, log, return the small model payload). |
| `src/tools.py` | `show_dashboard`, `set_conditions`, the 9 intent tools (generated block, `python scripts/gen_tool_docs.py`), state, mission, emergency. 16 tools in all. |
| `src/categories.py` | pillars, views, intros and "Ask me" chips (fixed texts), coverage read from the data, fixed UI texts, the two conditions. |
| `src/events.py`, `src/notify.py` | phases (scene arrival, category entry, custom conditions once settled), `question.asked`, silence nudge, reconnect line. |
| `src/prompts.py` | the answer order (steps 0 to 7), the phase table, open-question templates, the never-say list, 10 router examples. |
| `src/qlog.py` | `logs/questions.jsonl` (`{ts, transcript, tool, args, matched}`). |
| `src/api.py`, `src/charts.py` | token, catalog, mission, `GET /api/charts/o2_vs_pressure`. |
| `frontend/src/coreSolution/` | `adapters.js` (view-models; no sort, no data), `FlameDashboard.jsx` (one layout: overview and answer states), `DashboardContext.jsx`, `protocol.js`, `FlameApp.jsx` (scenes, `?env=`, follows the answer's category). |

## Known limits
- `search_text` can return loosely related passages for out-of-scope questions; the prompt decides off-topic / unsafe questions before any tool call.
- The chip "What did SAME measure?" is `pending_review` (hidden) until the team reviews `get_investigation("SAME")`.
- flameo's sqlite connection is shared: `src/flameo.py` serializes calls with a lock.
- Not verified: any live voice session (see `VOICE_TEST.md`).
