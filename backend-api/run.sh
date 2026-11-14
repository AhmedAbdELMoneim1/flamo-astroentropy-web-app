#!/usr/bin/env bash
set -e

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

# Activate venv 
if [ -f "$ROOT/.venv/bin/activate" ]; then
  source "$ROOT/.venv/bin/activate"
  echo "✓ Activated .venv"
elif [ -f "$ROOT/venv/bin/activate" ]; then
  source "$ROOT/venv/bin/activate"
  echo "✓ Activated venv"
else
  echo "⚠  No virtualenv found – using system Python"
fi

# Load .env 
if [ -f "$ROOT/.env" ]; then
  set -a
  source "$ROOT/.env"
  set +a
  echo "✓ Loaded .env"
  echo "  LIVEKIT_URL = $LIVEKIT_URL"
else
  echo "❌ .env not found in $ROOT"
  exit 1
fi

# Safety check
if [ -z "$LIVEKIT_URL" ]; then
  echo "❌ LIVEKIT_URL is empty – check your .env"
  exit 1
fi

# serving.db is required (flameo_tools reads it; see .env.example)
if [ -z "$FLAMEO_DB" ] || [ ! -f "$FLAMEO_DB" ]; then
  echo "❌ FLAMEO_DB is unset or the file is missing – set it in .env (path to serving.db)"
  exit 1
fi

#  Cleanup (runs only once on Ctrl+C) 
CLEANED=0
cleanup() {
  if [ "$CLEANED" -eq 1 ]; then
    return
  fi
  CLEANED=1

  echo ""
  echo "🛑 Stopping all services..."

  kill $API_PID $AGENT_PID $FRONT_PID 2>/dev/null || true
  wait $API_PID $AGENT_PID $FRONT_PID 2>/dev/null || true

  echo "✓ All stopped"
  exit 0
}
trap cleanup INT TERM

echo ""
echo "🚀 Starting Flame project from: $ROOT"
echo ""

#  1. FastAPI 
echo "→ API server on :8000"
uvicorn src.api:app --reload --host 0.0.0.0 --port 8000 &
API_PID=$!

sleep 1

# 2. Agent 
echo "→ LiveKit agent"
python -m src.agent dev &
AGENT_PID=$!

# 3. Frontend 
echo "→ Frontend (Vite)"
(cd frontend && npm run dev) &
FRONT_PID=$!

echo ""
echo "✓ All running"
echo "  API        → http://localhost:8000"
echo "  Frontend   → http://localhost:5173 (or next free port)"
echo "  Agent      → waiting for jobs"
echo ""
echo "Press Ctrl+C to stop everything."
echo ""

wait