# Claude Code kickoff: Stage 7, Round 15 (the final plan)

You are starting fresh on an existing project. Read before you change anything.

## The project in 5 lines
- **Flamo:** a voice fire-safety copilot for astronauts and learners (NASA Space Apps 2026, "Flame in Freefall").
- **Stack:** LiveKit agents + Gemini Live (voice), a React dashboard, the `flameo_tools` data tools over `serving.db` (SQLite: tests, findings, sources), and a RAG over the papers and NASA documents (pgvector in Docker, Cohere embed / rerank, a Gemini Flash-Lite composer with a citation-and-number checker).
- **The agent repo:** `/home/ahmed/Desktop/nasa-multi-agents-stages/AstroEntropy`, branch `stage7-real-data`.
- **The data repo:** `/home/ahmed/Desktop/nasa-multi-agents-stages/s1/s0-results/psi_stage1` (a local git repo since Round 12). Its `flameo_tools` are vendored into AstroEntropy (`vendor/flameo_tools`).
- **The router (Round 14)** lives in `src/router/` (`understand.py`, `answer.py`, `session.py`). Gemini calls `answer(question)`, and the server picks the data tools and the RAG.

## Read first, in this order
1. `chat_decisions/stage7-round15-final-plan.md`: **the plan you will implement** (§15.0–15.11).
2. `chat_decisions/round15_session_transcript.txt`: the session it is based on (a regression test).
3. `chat_decisions/stage7-decisions.md`: all earlier rounds. Read at least Round 1 (the adapter rules), Round 6 §6.4 (scoped RAG), Round 10–14 (the latest UI, conditions, router), and §13.3 (the three "not covered" cases).
4. The code: `src/agent.py`, `src/prompts.py`, `src/router/*`, `src/tools.py`, `src/rag.py`, `src/paper_rag/{ask,search,scope,composer}.py`, `frontend/src/coreSolution/*`.
5. `logs/questions.jsonl` and `logs/retrieval.jsonl` (the real router traces).

## Decisions already taken for Round 15
- **D15-1 = yes:** one sentence of labelled "general background, not from the PSI data" for "what is / what does X mean", only when the glossary and the RAG have nothing; no numbers.
- **D15-2 = (a):** Crew / Learn mode chosen automatically, plus a toggle on screen.
- **D15-3 = yes:** cached answers for the 72 scenario cards as a demo fallback, refreshed by each passing eval run.
- **D15-4 = yes:** a small model (Gemini Flash-Lite, then Groq) for the understanding step, with the current rules as the fallback.

## Rules that never change
- **Data:**
  - every number shown or spoken comes from a flameo result or a cited chunk; the adapter and frontend compute nothing;
  - never say "safest"; give no Mars numbers; never call the spacesuit atmosphere "coverage";
  - keep "the authors report"; psi first.
- **Keys:**
  - load them with `source /home/ahmed/.stage4_keys.sh` (Gemini 1–13, Groq 1–6, Cohere 1–9) and `src/paper_rag/.env`;
  - never print, log, commit or copy a key value; logs show only the key index.
- **Never commit** `serving.db`, `pipeline.db`, `logs/`, `rag_cache/` or `.env*`.
- **Git:** do not push. Commit on `stage7-real-data` per phase. Changes to `flameo_tools` go into psi_stage1 first (with goldens), then they are vendored.
- **Postgres** runs from `docker/docker-compose.yml`; the RAG index is `chunks_cohere`.
- **Live sessions:** you may call the Gemini / Groq / Cohere APIs for the pipeline and the eval; keep eval runs ≤ 300 Cohere calls. Do not start a LiveKit voice session yourself.
- **Before changing psi_stage1 data or `serving.db`:** a backup or a git commit.

## What to do now
**Implement phase P1 only** (§15.11):
- §15.1 items 1–8: model understanding, the 12 question types, the 5 new tools `explain`, `interpret_conditions`, `get_test`, `compare_tests`, `list_papers`, the answer shape, smart clarify, follow-up lists, the server runs `answer()` on every question turn, "not covered" only after everything, speed, **adaptive retrieval depth**;
- §15.2: the glossary draft (`glossary.json`, about 40 terms, each with a source, marked "draft, to review").

**Before coding,** reply with a short plan:
- the files you will touch;
- the new flameo functions and their goldens;
- how the understanding model is called and how it falls back;
- the test plan.

Then implement.

## STOP after P1 with
- **The replay table** for the Round 15 transcript + the Round 13 / 14 replay sets: question → type → tools → `answered_by` → first spoken line.
- **The "not covered" count before and after,** with each remaining one listed.
- **Latency p50 / p95** of `answer()`.
- **Adaptive depth:** how often the second pass ran, and hit@5 / answer rate with it on vs off.
- **The test results** (AstroEntropy + psi_stage1).
- **The glossary draft** for review.

Do not start P2 before the chat reviews P1.
