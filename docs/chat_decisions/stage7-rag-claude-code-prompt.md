# Claude Code prompt: Stage 7 RAG build (Round 7, steps 3–7) — v3: master + 4 workers, Gemini embeddings

Work in `/home/ahmed/Desktop/nasa-multi-agents-stages/AstroEntropy`, branch `stage7-real-data`. Read `chat_decisions/stage7-decisions.md` Round 6 §6.3–6.4 and Round 7 first, and follow them. Where this prompt and Round 7 differ, this prompt wins.

**What changed in v2 / v3 (team decisions, 2026-11-08 23:12 and 23:17):**
- PDF chunks come only from the team's `chunk_data.py`; the `serving.db` page-text index is dropped.
- The docling parsing runs in Docker as 1 master (the main laptop, 8 threads) + 4 workers (4 laptops). Workers pull tasks and download the PDFs from the master over the LAN, and send the results back. The threads are set by hand in each container's env.
- The descriptions, the embeddings and the database insert run on the main machine, with the Gemini keys in parallel.
- Embeddings use a Gemini embedding model, not Cohere.

## Ground rules
- You may call the Gemini and Groq APIs for this pipeline (descriptions, embeddings, the composer), and Cohere only if a Cohere key is in `src/paper_rag/.env`. No LiveKit session from you.
- **Keys exist only on the main machine.**
  - Load them with `source /home/ahmed/.stage4_keys.sh` in the shell that runs the script (`GEMINI_API_KEY_1..13`, `GROQ_API_KEY_1..6`).
  - Never print, log, commit or copy a key value, and never put one in a Docker image, a manifest or a file sent to another laptop.
  - Logs show only the key's index (`gemini#4`).
  - **The worker laptops need no keys:** docling parsing calls no API. The only secret on them is the LAN `WORKER_TOKEN` (C1).
- Postgres runs from `docker/docker-compose.yml` (already up). Use the values in `docker/env/.env.postgres`; don't hard-code them.
- `serving.db`, `pipeline.db`, `logs/`, `rag_cache/`, worker outputs and `.env*` are never committed. Do not push.
- Never build a URL by guessing: links come from `pipeline.db` (`paper.doi`, `doc.download_url`) only.
- No model id is guessed: list the models each API offers and choose from that list; write the choice in the report.

## Key pool (`src/paper_rag/keypool.py`)
- Round-robin over the numbered keys of one provider.
- On 429 or quota errors, put that key on cooldown (respect `retry-after`, else 60 s) and move on.
- Per-key limits (RPM, TPM, RPD) are configurable in `.env`, defaulting to each free tier's limits; never send faster.
- Free-tier limits count per Google Cloud project, not per key. Measure in the first minute of the run whether the 13 keys behave as separate quotas; if two keys share a project, report it.
- Log per run: requests and tokens per key index, 429 count, cooldown time.

## Part A — bring in the team's RAG and fix it (Round 7 §7.4)
1. Bring `src/paper_rag/`, `docker/` and their dependencies from `experiment/ui_communication` (@ `6289b60`) into `stage7-real-data` (checkout of paths, not a merge). Add the deps to `pyproject.toml`.
2. **Table** (dimension = the chosen Gemini embedding model's output size; if the model supports a smaller output size, use 768):
   - `chunk_id TEXT PRIMARY KEY`;
   - `text` (what is embedded: header + text) and `raw_text` (what the screen shows and the checker reads);
   - `embedding`, a tsvector on `raw_text`, and `metadata JSONB`;
   - an HNSW index (cosine) and a GIN index on `metadata`.
3. **Embeddings provider:** a Gemini embedding provider next to the Cohere one, with the document task type for chunks and the query task type for questions. Batch as many texts per request as the API allows.
4. **Scoped search:** `search_by_vector` / `search_by_keyword` take an optional scope (`src_ids[]`, `psis[]`) and return metadata. Keyword search uses `websearch_to_tsquery`, not an OR of every word.
5. **Rerank:** Cohere rerank if a Cohere key exists; otherwise reciprocal-rank fusion of the vector and keyword lists. A Gemini reranker is optional, behind a flag, only if it fits the 4-second budget.
6. **Config:** build the `.env` path from `__file__` (the Windows path fails on Linux).
7. **`replace_source(src_id, chunks)`:** delete that source's rows, then insert (idempotent; resumable).
8. **Tests** against the local Postgres: scoped vs unscoped SQL, `replace_source`, resumable insert.

## Part B — small tier-1 chunks from `serving.db` (index these first)
`scripts/rag/build_chunks_tier1.py` → `rag_cache/tier1/chunks.jsonl`:
- the 322 cards (one chunk each);
- the 24 investigation profiles;
- the challenge text by section;
- the 6 references.

Use the Round 7 §7.3 metadata, with `text_origin: "serving"`. Embed and insert right away, so retrieval and the logs (Part F) can be tested while the laptops parse.

## Part C — distributed parsing: 1 master + 4 workers (team decision, 2026-11-08 23:17)
Two Docker images, on the team's own LAN:
- **master**: on the main laptop (8 threads); it holds the PDFs, hands out the tasks, receives the results;
- **worker**: on 4 other laptops; each pulls a task, downloads that PDF from the master, parses it with docling, uploads the result, and pulls the next.

Threads are set by hand in each container's env. Nothing in this part calls an external API, and no API key goes into either image or onto any worker laptop.

### C1. The master (`docker/rag-master/`: Dockerfile, `compose.yml`, `.env.example`, `README.md`)
A small FastAPI service with a SQLite task queue, `rag_cache/queue.db`:
- `task(src_id, kind, path, sha256, pages, kept_pages, status pending|leased|done|failed, worker_id, lease_until, attempts, secs)`.
- Filled from the manifest (D1).
- Order: largest files first, so the long jobs don't finish last.

Endpoints:
- `POST /lease {worker_id}` → the next pending task (`src_id`, sha256, kept pages), or 204 when none are left.
- `GET /pdf/{src_id}` → streams the PDF with its sha256 in a header (only files in the manifest; no path from the request is ever used to open a file).
- `POST /heartbeat {worker_id, src_id}` → extends the lease.
- `POST /result/{src_id}` → a `.tar.gz` of the outputs (C2). The master checks the sha256, the docling version / image tag and the `.done` page count, unpacks into `rag_cache/docling/<src_id>/`, and marks the task done.
- `POST /fail/{src_id} {error}`.
- `GET /status` → counts per status, pages done, ETA, per-worker rate, failed files (also a tiny HTML page for the team to watch).

Rules:
- A lease expires after `LEASE_MINUTES` (env, default 30) without a heartbeat and goes back to pending.
- At most `MAX_ATTEMPTS` (default 2); then `failed`.
- A result from a worker with a different docling version / image tag is rejected.

Env (`.env.example`):
- `MASTER_PORT`, `BIND_HOST` (the LAN address);
- `WORKER_TOKEN`: a random shared secret the team generates locally. Every request needs it as a bearer header. It's a LAN token, not an API key; never commit it or paste it in a chat.
- `LEASE_MINUTES`, `MAX_ATTEMPTS`;
- `LOCAL_WORKER_PROCS` / `LOCAL_THREADS_PER_PROC`: the master laptop can also run its own worker processes. Default 0, because the main laptop's disk is nearly full and the docling models need several GB; turn it on only if the pilot shows enough free space.

Mounts: the PDF folders read-only, and `rag_cache/` read-write.

### C2. The worker (`docker/docling-worker/`: Dockerfile, `compose.yml`, `.env.example`, `README.md`)
- **Image:** the docling part of `chunk_data.py` (no Groq); exact versions locked; the docling models downloaded at build time (runs offline apart from the master); CPU only; no keys.
- **Env:**
  - `MASTER_URL`, `WORKER_TOKEN`, `WORKER_ID`;
  - `PROCS` (parallel files) and `THREADS_PER_PROC`, which set `OMP_NUM_THREADS`, the torch threads and docling's thread option;
  - `OCR_LANG` (default English);
  - `MAX_TASKS` (0 = until the queue is empty).
- **Loop, per process:**
  1. lease → download → check sha256 → parse (heartbeat every minute);
  2. pack the outputs → upload → delete the local copy → lease again.
  3. On an error: `/fail` with the message, then the next task.
- **Parse, per file:**
  - check for a text layer; OCR only on pages without one;
  - keep only the `kept_pages` the master sent (papers: abstract / results / discussion / conclusion pages; documents: all pages);
  - export the DoclingDocument JSON, `blocks.jsonl` (text per page; tables as markdown with caption and the 500-character context; figure records with caption and context), `figures/*.png` (≥ 120 px on a side), and `done.json` (pages, seconds per stage, docling version, image tag, `WORKER_ID`).
- **Same image everywhere:** build it once, then `docker save` → copy the tar → `docker load` on each laptop (the README shows the commands), so every worker reports the same image tag.

### C3. Team README (in `docker/rag-master/README.md`)
- the master's LAN address and port, and opening that port on the master laptop's firewall for the LAN only;
- the command to start the master;
- per worker: fill `.env` (`MASTER_URL`, `WORKER_TOKEN`, `WORKER_ID`, `PROCS`, `THREADS_PER_PROC`), then `docker compose up -d`;
- a suggested split: leave 2 threads free on each laptop; `PROCS × THREADS_PER_PROC` = the threads left (e.g. 12 threads free → 3 × 4);
- how to watch `/status`, stop a worker (its leased task returns to the queue) and restart.

## Part D — manifest, results, describe, chunk, embed (master laptop, outside Docker or in the master container)
**D1. Manifest** (`scripts/rag/make_manifest.py`). From `pipeline.db`:
- the tier-2 papers (`paper.pdf_path`) and the tier-2 documents (`doc.local_path`, categories Reports and Science Documents; skip Raw Data);
- one row per file: `src_id`, kind, path, sha256, page count, the kept pages, title, `psis[]`, `doi` / `download_url`;
- duplicates (same sha256) are listed once, with all their PSIs.

Load it into the master's queue.

**D2. Results as they arrive.** D3–D5 run on each finished file as soon as the master marks it done (a watcher process), so describing and embedding overlap with parsing. A final check confirms every manifest row is done or listed as failed.

**D3. Describe** (Groq / Gemini key pools, the team's prompts unchanged):
- table descriptions and figure descriptions;
- per-item cache (`<src_id>.desc.jsonl`), resumable;
- figures only on kept pages;
- logo / decorative figures dropped as in the script.

**D4. Chunk** (the team's splitter settings from `chunk_data.py`: 600 / 100, the same separators, tables split by rows with the header repeated) plus everything in Round 7 §7.3:
- never across a page;
- the drop rules and dedupe;
- metadata `chunk_id`, `src_id`, `psis[]`, `pillars[]`, tags, `doi` / `download_url`, `type` (text / table / figure), `table_id`, `text_origin: "docling"`.

**Generated text is marked:**
- figure chunks: `generated: true`, `raw_text` = caption + summary;
- table chunks: `raw_text` = the caption + the extracted markdown table only. The model's table description goes in `text` (for search) and `metadata.table_desc`, never in `raw_text`;
- the composer's checker accepts a number only from the `raw_text` of a chunk with `generated: false`. A figure chunk can be cited for what a figure shows, never as the source of a number. Add tests.

**D5. Embed + insert:**
- the Gemini key pool in parallel (one async worker per key, each within its key's limits);
- `replace_source` per file;
- resumable;
- the row count must equal the chunk count.

## Part P — pilot first, then STOP
With the master and **one** worker, run C + D on 5 files (2 papers, 2 reports, 1 science document), with figures. Report:
- the Docker image size and build time, and the models included;
- seconds per page per stage (parse, OCR, figure export) and CPU use per worker;
- Groq / Gemini calls per page for the descriptions, and 429s;
- chunks per page and tokens per chunk; embedding tokens and requests per page;
- 10 sample chunks (text, table, figure);
- the upload size per file and the master's disk use per file;
- a projection for all files over the 4 workers (and the master's own procs, if enabled): parse hours, description calls and days at the measured limits, embedding minutes with 13 keys.

Do not start the other workers before the chat reviews the pilot.

## Part E — retrieval check (Round 7 step 6), then `ask_sources` (step 7)
- `scripts/rag/eval_retrieval.py`:
  - ~30 questions (goldens, the 4 logged oxygen questions from `logs/questions.jsonl`, Q1–Q12, use cases) with the expected PSI / source;
  - hit@5 scoped vs unscoped;
  - print a table.
  - Run it on tier 1 now, and again when the queue is done.
- `ask_sources` as in Round 6 §6.4:
  - scope → filtered hybrid search → rerank (Part A.5) → composer (Gemini key pool, JSON with chunk numbers) → checker → `speak[]` + `sources[]`;
  - clarify on an empty or weak scope;
  - 4-second budget;
  - `serving.db` FTS fallback.

## Part F — retrieval logs while the server runs
Every `ask_sources` call writes one JSON line to `logs/retrieval.jsonl` and a short summary to the console (`RAG_LOG=off|summary|full`, default `summary`):
- `ts`, `request_id`, the question, the parameters Gemini passed;
- the scope: PSIs, number of sources, and which parameter selected them;
- vector top-k and keyword top-k: `chunk_id`, type, page, score;
- the reranked or fused top-n: `chunk_id`, score, the first 200 characters of `raw_text`;
- the composer: each sentence and its cited chunks, kept or dropped with the reason (no citation / number not in chunk / forbidden word);
- the outcome (answer / clarify / fallback), latency per stage, and the key index used.

No key values and no audio. `full` adds the whole `raw_text` of the top-n. A small `scripts/rag/tail_retrieval.py` pretty-prints the log live.

## Report back
- At the pilot STOP: the Part P report.
- At the end:
  - the final queue status (done / failed);
  - chunk counts per type;
  - the eval hit@5 table (tier 1 only, then everything);
  - 3 sample `logs/retrieval.jsonl` entries;
  - test results.
