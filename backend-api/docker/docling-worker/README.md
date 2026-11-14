# docling worker

CPU-only, no API key, models baked in at build time. See `../rag-master/README.md` for the whole procedure
(build once, `docker save` / `docker load` on each laptop, fill `.env`, `docker compose up -d`).

Env: `MASTER_URL`, `WORKER_TOKEN` (LAN token), `WORKER_ID`, `PROCS`, `THREADS_PER_PROC`, `OCR_LANG` (default `en`), `MAX_TASKS` (0 = until the queue is empty).
Per file: lease, download, sha256 check, parse (pages without a text layer are OCR'd; only the kept pages), heartbeat every minute, pack, upload, delete the local copy.
