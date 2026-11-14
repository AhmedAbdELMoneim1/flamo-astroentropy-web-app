# Deploy: Firebase (site) + LiveKit Cloud (agent) + your server (Postgres and the backend API)

```
browser ──https──> Firebase Hosting (frontend/dist)
   │                  │ VITE_API_URL
   │                  ▼
   │            backend API  ──> Postgres (pgvector, the RAG index)      your server, docker compose
   │                  ▲  RAG_API_URL + RAG_INTERNAL_KEY
   └──wss──> LiveKit Cloud ──> the agent (voice-agent-livekit)           lk agent deploy
```
Why the agent asks the API for the RAG instead of connecting to Postgres: LiveKit Cloud has no fixed IP, so Postgres would have to be open to the whole internet. Now only the API is public, and the RAG endpoint needs a shared secret.

## 0. Once
* Docker Hub: create a **private** repository for each image (`flame-backend-api`, `flame-postgres`), `docker login`.
* Server: Docker + the compose plugin, a domain for the API (A record -> the server), ports 80 and 443 open.
* LiveKit Cloud project with an API key and secret (the project in `voice-agent-livekit/livekit.toml`).
* Firebase project; `npm i -g firebase-tools` (or `npx firebase-tools`), `firebase login`.

## 1. Build and push the two images (on this machine)
```bash
cp .env.example .env            # DOCKERHUB_USER, POSTGRES_PASSWORD, LIVEKIT_*, CORS_ORIGINS, RAG_INTERNAL_KEY (openssl rand -hex 32), API_DOMAIN
docker compose build            # flame-postgres (includes data/postgres/paper_rag.dump) and flame-backend-api (includes data/serving.db)
docker compose push
```
The images hold the data (serving.db 35 MB, the 118 MB RAG dump), so keep the repositories private. The NASA PDFs (2.2 GB) are not in any image: copy `data/docs/` to the server (`rsync -az ../Nasa-PSIs-Data/docs/ server:~/flame/data/docs/`).

## 2. Run on the server
Only `docker-compose.yml`, `deploy/Caddyfile` and `.env` are needed there (copy them with scp).
```bash
docker login && docker compose pull
docker compose --profile https up -d        # postgres, api, caddy (https on API_DOMAIN)
curl https://API_DOMAIN/health              # {"ok":true,"rag":true}
```
The first start of an empty Postgres volume restores the dump (about a minute; `docker compose logs postgres` ends with `restored chunks_cohere: 17424`). Later starts reuse the volume. The key pools (`GEMINI_API_KEY_n`, `GROQ_API_KEY_n`, `cohere_api_key_n`) go into the server's `.env` (`sed 's/^export //' ~/.stage4_keys.sh >> .env`).

## 3. Deploy the agent to LiveKit Cloud
```bash
cd voice-agent-livekit
cp secrets.env.example secrets.env     # GOOGLE_API_KEY, RAG_API_URL=https://API_DOMAIN, RAG_INTERNAL_KEY (same as the server), the Gemini/Groq pools
lk cloud auth                          # once
./deploy.sh --check                    # stages the build folder and builds the image locally, deploys nothing
./deploy.sh                            # lk agent deploy: LiveKit Cloud builds it and rolls it out
lk agent status; lk agent logs
```
`deploy.sh` stages `backend-api/src`, `vendor`, the lock file and `data/serving.db` with the Dockerfile in a temp folder (the Cloud build only sees the folder you give it). The agent name is `nasa-agent` and must match `AGENT_NAME` on the API. Secrets are never in the image; changing them restarts the agent. Rollback: `lk agent rollback`.

## 4. Deploy the site to Firebase
```bash
cd frontend
cp .env.production.example .env.production      # VITE_API_URL=https://API_DOMAIN
cp .firebaserc.example .firebaserc              # your project id
npm ci && npm run build
npx firebase-tools deploy --only hosting
```
Then put the site address (`https://<project>.web.app`, plus your own domain if any) into `CORS_ORIGINS` on the server and `docker compose up -d api`. Check: open the site, the categories load (no CORS error in the browser console), press the microphone, the agent greets.

## Self-hosting the agent instead of LiveKit Cloud
`docker compose --profile self-hosted-agent up -d` runs the same backend image with `python -m src.agent start` next to Postgres (no `RAG_API_URL` needed), with `LIVEKIT_*` of any LiveKit server and `GOOGLE_API_KEY` in `.env`.

## Backups
`backend-api/scripts/db_export.sh` dumps the running database into `data/postgres/paper_rag.dump` (+ sha256); rebuild `flame-postgres` to ship it. Or `docker compose exec -T postgres pg_dump -U paper -d paper_rag -Fc > backup.dump`.
