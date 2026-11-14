# Stage 7: RAG build report (Round 6.1 and Round 7, steps 3 to 7)

Branch `stage7-real-data` in AstroEntropy. Written 2026-11-09, ~04:40. Nothing is pushed. Keys were never printed, logged or committed.
Status in one line: **the corpus is parsed (263 of 267 files, the last 4 giant files are running) and indexed twice (Gemini index half done, Cohere index 239 of 263 files); `ask_sources`, the retrieval log, the prompt/router changes and the goldens are NOT built yet.**

## 1. Where each part stands

| part | what | state |
|---|---|---|
| Round 6.1 | dashboard polish, display audit, chat-bubble fix, scene debounce, question-log fix | done, commit `831491a` (see section 9) |
| A | `src/paper_rag` brought in and fixed, scoped pgvector store, Gemini embedder, key pool, rerank/fusion | done, `4d3c5e1` |
| B | tier-1 chunks (322 cards, 24 profiles, 10 challenge sections, 6 references = 362) embedded and inserted | done, `1d808b1` |
| C | parsing master (FastAPI + SQLite queue) and docling worker, Dockerfiles, READMEs | done and used on 4 real laptops |
| D | manifest, describe, docling chunker, embed + insert watcher | done; descriptions (figures/tables) NOT yet filled |
| P | 5-file pilot | done and reviewed (section 4) |
| E | scope resolver and retrieval eval | scope + eval written; eval run on tier 1 only |
| E | `ask_sources` tool | **not built** |
| F | `logs/retrieval.jsonl`, `tail_retrieval.py` | **not built** |
| steps 8, 9 | prompt/router ladder, goldens | **not done** |

Tests: 173 passing (pytest), plus the frontend suites from earlier rounds.

## 2. Data in the database now (local pgvector)

Two separate indexes, same chunks, different embedding models (their vectors cannot be mixed):

| table | model | dims | text | table | figure | tier 1 | sources done |
|---|---|---|---|---|---|---|---|
| `chunks` (Gemini) | gemini-embedding-001 | 768 | 9,919 | 497 | 219 | 362 | 133 of 262 files |
| `chunks_cohere` | embed-v4.0 | 1024 | 11,955 | 981 | 0 | 362 | 239 of 262 files |

Figure chunks exist only for the pilot and the first files (descriptions ran while Groq/Gemini had quota). Everything else is text and tables only (phase 1).

## 3. What was decided or changed versus the prompt and Round 7 (please review)

1. **Two embedding indexes.** The prompt said Gemini embeddings. Gemini's free embedding limit is ~1,000 texts per key per day; all 13 keys ran out at ~12,700 texts, so ~half the corpus would wait until the next day. When 9 Cohere keys became available I built a second index (`chunks_cohere`) so the corpus can be complete today. Decision needed: keep both and pick by eval, or keep one.
2. **Embedding model choice.** `gemini-embedding-001`, 768 dims. `gemini-embedding-2` was rejected: it returns ONE vector for a whole batch, so it cannot embed chunks in batches. Cohere: `embed-v4.0` at 1024 dims (pgvector HNSW supports up to 2000).
3. **Rerank:** Cohere rerank (`rerank-v3.5`) now that Cohere keys exist; otherwise reciprocal-rank fusion. Not yet wired into a live `ask_sources` (it does not exist yet).
4. **Non-PDF files excluded.** The pilot found that 10 of the 277 files in the document list are Word files (.docx 8, .doc 2). The PDF workers cannot parse them. They are listed in `rag_cache/manifest_missing.json` (about 54 pages, ~1.4% of pages). The manifest is 267 PDFs, 3,727 kept pages.
5. **Figures are pre-filtered before any model call** (requested after you saw logos and hardware photos). Of 2,909 extracted figures: 383 were byte-identical repeats (52 images, one appeared 40 times), 1,078 had no caption, 588 were under 200 px. Rules: skip if under 150 px, aspect ratio over 4, the same image 3+ times in the corpus, or no caption. About 1,800 of 2,909 remain as candidates.
6. **Two-phase indexing.** Phase 1 (done): text and tables, no model descriptions. Phase 2 (pending): add figure and table descriptions when quotas reset; it redoes only the sources inserted without descriptions.
7. **Tier-1 reference chunks got their own ids** (`ref:<id>`), because their `src_id` equalled the document id of the parsed file and `replace_source` deleted them (a bug of mine, fixed; tier 1 is back to 362 in both tables).
8. **Docling tag/version:** docling 2.149.0, torch 2.15 CPU, image `rag-docling-worker` tags `:1` (pilot), `:2` (all workers), `:3` (memory fix, only the last 4 files). The master pins the tag of the first accepted result; I restarted it for `:3`. Package versions are locked in `docker/docling-worker/requirements.lock`.
9. **Native Windows worker:** the other laptops are Windows. I wrote `windows_worker.ps1` (Python 3.12, no Docker/WSL). Untested by me; used by at least one laptop.
10. **Deviation:** the team's `generation.py` and `indexing.py` were removed (the new modules replace them).

## 4. The 5-file pilot (master + 1 worker on the main laptop, 6 threads)

- Image 3.52 GB; models inside: layout (heron, plus ONNX), table structure (docling-models 342 MB), CodeFormulaV2 611 MB, figure classifier 33 MB, RapidOCR 62 MB. Build ~13 minutes.
- 78 pages in 5 files; parse 2.1 to 2.5 s/page on normal files, 10 s/page on a table-heavy test plan (11 tables). Figure export under 1 s per file.
- OCR: one page without a text layer made the worker OCR the whole 28-page run (81 s). Fixed to OCR only the pages that need it (3.4 s).
- CPU ~365% of 600% average, peak 473%; RAM peak 4.2 GB for one process.
- Upload 0.1 to 5.1 MB per file; master disk 1 to 6 MB per file; ~0.2 MB per page overall (~0.8 GB for everything).
- 373 chunks from 78 pages (4.8 per page, ~350 tokens each: 278 text, 45 table, 50 figure). Dropped: 52 too short, 28 junk, 2 logos.
- Embeddings: 10 requests, ~1,700 tokens per page.
- Descriptions: 72 items, 70 Groq calls, 45 Groq 429s, 2 failed (Gemini fallback did not work then: `gemini-2.5-flash` returns 404 for this account although the API lists it; switched to `gemini-3.5-flash-lite`).
- Sample chunks (text, table, figure) were reviewed from the database. Known issue: docling's table numbering can disagree with the caption (e.g. "[Table 11 (part 4/5)] Table 12 ...").

## 5. The full parse run (4 laptops, Windows, one native worker, one Docker)

- Real speed was far better than projected: 3,285 pages done in about 2.5 hours of wall clock, ~19 pages/min across all laptops (projection was 1 to 2 hours for the whole job on 40 threads).
- Throughput by laptop varied 1 to 20 pages/min per process.
- 263 of 267 files done, 0 failed in the final state. The last 4 are the biggest: 144, 109, 109 and 80 pages. They were OOM-killed repeatedly (the main laptop's worker `OOMKilled=true`; `laptop-b` restarted them 5 to 6 times). Fix: cut long documents into runs of at most 12 pages per docling call. These 4 now run on the main laptop with a 7 GB memory cap (the 144-page file used 2.4 GB so far).

## 6. Problems found and fixed (including my own mistakes)

1. **Master crash under load:** the master's SQLite connection was shared by request threads without a lock, so 8 worker processes caused "bad parameter or other API misuse" (a 500) and false 404s. Fixed with a re-entrant lock around every read, with a 16-thread regression test.
2. **Permission errors after I made the master run as the host user:** the `uploads` and `docling` folders had been created by root earlier, so uploads failed with 500. I moved the root-owned folders aside and reset the attempt counts of the files that failed from this.
3. **Stray line in the master `.env`** (left from rewriting the token) broke `docker compose`; removed. The token did not change.
4. **Two full image rebuilds (about 25 minutes)**: I changed the tag default in the Dockerfile, which invalidated the cache. My mistake; the reason the pilot took about an hour.
5. **Race when two sources created the pgvector table at the same time** (found by a test): now created once under a lock.
6. **Reference chunks deleted** by `replace_source` (see decision 7).
7. **Pipeline stalls from quotas** (section 7); the description step now switches from Groq to Gemini when every Groq key would make it wait more than 20 s, and Gemini descriptions have their own stricter key pool.

## 7. Quotas and limits discovered (important for planning)

- **Gemini embedding (free):** ~1,000 texts per key per day, 100/min per key; all 13 keys exhausted; cooldown reported ~23,000 s (until ~10:00 tonight). Keys 1 to 7 verified as separate quotas (the other 6 only with single-text probes).
- **Gemini generation (free):** with 13 keys, bursts of figure descriptions returned 429 "Resource has been exhausted" even from different keys; unusable for the volume today. Models in the API list are not all usable (`gemini-2.5-flash` 404).
- **Groq (`qwen/qwen3.8-27b`, text and vision):** worked in the pilot; 45 429s in 70 calls; daily token limit reached later (cooldowns up to 780 s).
- **Cohere (trial, 9 keys):** counters are per key; 40 calls/min per key on embed and rerank (the header said 100 earlier, then 40); 1,000 calls/month per key per endpoint. A full embedding of ~24,000 chunks is only ~250 calls.
- **Description volume:** ~3,335 tables+figures, now ~1,800 candidate figures plus ~460 tables after the filter. Because both generation providers are throttled, phase 2 may take a day or more.

## 8. Retrieval eval (tier 1 only, 362 chunks)

31 questions (4 logged oxygen questions, goldens, Q-set), expected chunk ids written by hand, hit@5: **scoped 90% vs unscoped 90%** (28 to 30 questions have a scope). On a corpus this small the unscoped search is already good, so no scoped gain can be shown yet. Misses: two "when is oxygen dangerous" questions (both modes: the 17% and 26% chunks do not reach the top 5), and a spacesuit question whose scope is empty (no tests near the suit atmosphere; that case belongs on the clarify path). The scope resolver: PSI/oxygen ±3 points/pressure ±10%/material/fuel/pillar/scenario, with the challenge text always in scope. Eval file: `rag_cache/eval_tier1.md`. **The eval has not been run on the full corpus or on the Cohere index yet** (Round 7 step 6 target: hit@5 at least 80% in scope and a clear gain over no scope).

## 9. Round 6.1 (dashboard) in one paragraph

All "[ ]" wrappers removed; a display audit test over the 20 overviews and 43 golden answers (no None/null/NaN, ligatures, en-dash ranges, µm/O₂/CO₂, "1 test", exact digits); KPI tile, ranking-row and answer-card polish within the existing theme; chat bubbles keyed by role, segment id and reuse count and frozen when final (reproduced in a unit test, not live); scene audio debounced to 1.5 s; question-log transcript fixed with late-arriving transcripts filled in. Open: not checked in a live voice session.

## 10. Still to do (in order)

1. Finish parsing the last 4 files (running now, ~30 minutes), then finish the Cohere index (24 files left) and the Gemini index after its quota resets.
2. Run the retrieval eval on the full Cohere index and on the Gemini index; pick one (decision above).
3. Build `ask_sources` (scope, filtered hybrid search, Cohere rerank, composer, checker, clarify, 4-second budget, serving.db FTS fallback) and the retrieval log (`logs/retrieval.jsonl`, `tail_retrieval.py`).
4. Composer checker rule: a number is accepted only from the `raw_text` of a chunk with `generated: false` (the chunker already marks figure chunks generated and keeps table descriptions out of `raw_text`); add tests.
5. Prompt and router: ladder step 3 becomes `ask_sources`; "not covered" only if it also finds nothing; router examples; goldens and the number/forbidden-word checks.
6. Phase 2: figure and table descriptions when quotas allow.
7. Live voice test #2 (a person).

## 11. Questions for the planner chat

1. Keep both indexes (Gemini 768 and Cohere 1024) and choose by eval, or standardise on Cohere (complete today) and drop the Gemini index?
2. For the Word files (10 of 277, ~1.4% of pages): ignore, or add a separate docx path?
3. Figure descriptions: wait for quotas (a day or more) or index figures by caption only (captioned, unique figures, about 1,800) with no model summary?
4. The 3 giant documents and one large report are now parsed on the main laptop; confirm they are wanted (all are tier 2 reports/theses).
5. Cohere trial keys are limited to 1,000 calls per month per endpoint: is that acceptable for the demo day (each `ask_sources` uses 1 embed + 1 rerank call)?
