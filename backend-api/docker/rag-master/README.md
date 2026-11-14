# RAG parsing: 1 master + 4 workers (docling, CPU, no API keys)

The **master** (this laptop) holds the PDFs, hands out tasks, and receives the results. Each **worker** laptop leases one file at a time,
downloads that PDF from the master over the LAN, parses it with docling, uploads the result and leases the next. Nothing here calls an
external API and **no API key goes into an image, a manifest or onto a worker laptop**; the only secret on a worker is the LAN `WORKER_TOKEN`.
Descriptions, embeddings and the database insert run on the master laptop afterwards (`scripts/rag/run_pipeline.py`).

## 1. Master (this laptop)
```bash
cd AstroEntropy
export FLAMEO_DB=$PWD/../s1/s0-results/psi_stage1/local_data/serving.db
.venv/bin/python scripts/rag/make_manifest.py          # -> rag_cache/manifest.jsonl (277 files, 3,781 kept pages)
cp docker/rag-master/.env.example docker/rag-master/.env   # then fill WORKER_TOKEN and BIND_HOST
cd docker/rag-master && docker compose up -d --build
```
* Address and port: `http://<BIND_HOST>:<MASTER_PORT>` (default 8765). Find the LAN address with `hostname -I`.
* Open that port to the LAN only, e.g. `sudo ufw allow from 192.168.1.0/24 to any port 8765 proto tcp` (use your subnet).
* Watch: `curl -H "Authorization: Bearer $WORKER_TOKEN" http://<BIND_HOST>:8765/status` or open `http://<BIND_HOST>:8765/` in a browser and paste the token.

## 2. Workers (4 laptops)
Build the image **once**, then copy it (every worker then reports the same image tag):
```bash
# on one laptop (or the master): build, save
cd docker/docling-worker && docker build -t rag-docling-worker:3 --build-arg IMAGE_TAG=rag-docling-worker:3 .
docker save rag-docling-worker:3 | gzip > rag-docling-worker-1.tar.gz
# on each worker laptop: load
gunzip -c rag-docling-worker-1.tar.gz | docker load
```
Per worker laptop, in `docker/docling-worker/`:
```bash
cp .env.example .env        # fill MASTER_URL, WORKER_TOKEN, WORKER_ID (unique), PROCS, THREADS_PER_PROC
docker compose up -d
docker compose logs -f
```
**Threads:** leave 2 threads free on each laptop; `PROCS x THREADS_PER_PROC` = the threads left. With 12 threads free: `PROCS=3`, `THREADS_PER_PROC=4`.
Each process needs about 2-3 GB of RAM while it parses a large file, so do not raise `PROCS` past what the RAM allows.

## 3. Stop and restart a worker
`docker compose stop` (it sends SIGTERM; the worker releases its leased file, which returns to the queue at once). `docker compose up -d` starts it again.
If a laptop dies without stopping, its file returns to the queue after `LEASE_MINUTES` without a heartbeat. A file is tried at most `MAX_ATTEMPTS` times, then marked `failed`
(listed in `/status`). A result from a worker with another docling version or image tag is rejected.

## 4. The master laptop parsing too (off by default)
`LOCAL_WORKER_PROCS` / `LOCAL_THREADS_PER_PROC` in `.env`, then `docker compose --profile local up -d`. Off by default: the main laptop's disk is nearly full and the docling models need several GB.

## 5. What a result contains
`rag_cache/docling/<src_id>/`: `docling_<a>-<b>.json`, `blocks.jsonl` (text per page, tables as markdown with caption and 500-character context, figure records), `figures/*.png` (>= 120 px), `done.json`.
