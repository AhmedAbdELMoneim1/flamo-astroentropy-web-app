#!/usr/bin/env bash
set -e

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
echo "Current working directory: $ROOT"


ENV_FILE="$ROOT/.env.local"
API_PID=""; AGENT_PID=""; FRONT_PID=""; LK_PID=""

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

# Load .env.local
if [ -f "$ENV_FILE" ]; then
  set -a
  source "$ENV_FILE"
  set +a
  echo "✓ Loaded .env.local"
  echo "  LIVEKIT_URL = $LIVEKIT_URL"
else
  echo "❌ .env.local not found in $ROOT"
  exit 1
fi

# Safety checks
if [ -z "$LIVEKIT_URL" ]; then
  echo "❌ LIVEKIT_URL is empty – check your .env.local"
  exit 1
fi
if [ -z "$FLAMEO_DB" ] || [ ! -f "$FLAMEO_DB" ]; then
  echo "❌ FLAMEO_DB is unset or the file is missing – set it in .env.local (path to serving.db)"
  exit 1
fi
if [ -z "$GOOGLE_API_KEY" ] || [[ "$GOOGLE_API_KEY" == YOUR_* ]]; then
  echo "❌ GOOGLE_API_KEY is not set in .env.local"
  exit 1
fi

# Cleanup (runs only once on Ctrl+C)
CLEANED=0
cleanup() {
  if [ "$CLEANED" -eq 1 ]; then
    return
  fi
  CLEANED=1

  echo ""
  echo "🛑 Stopping all services..."

  kill $LK_PID $API_PID $AGENT_PID $FRONT_PID 2>/dev/null || true
  wait $LK_PID $API_PID $AGENT_PID $FRONT_PID 2>/dev/null || true

  echo "✓ All stopped"
  exit 0
}
trap cleanup INT TERM

echo ""
echo "🚀 Starting Flame project from: $ROOT"
echo ""

# 0. Local LiveKit server (only when LIVEKIT_URL points to this computer)
if [[ "$LIVEKIT_URL" == ws://localhost* || "$LIVEKIT_URL" == ws://127.0.0.1* ]]; then
  if command -v livekit-server >/dev/null 2>&1; then
    echo "→ Local LiveKit server on :7880"
    livekit-server --dev &
    LK_PID=$!
    sleep 2
  else
    echo "❌ LIVEKIT_URL is local but 'livekit-server' is not installed"
    echo "   macOS: brew install livekit   |   Linux: curl -sSL https://get.livekit.io | bash"
    exit 1
  fi
else
  echo "→ Using remote LiveKit: $LIVEKIT_URL"
fi

# 1. FastAPI
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
FRONT_DIR="/home/ahmed/Desktop/nasa-multi-agents-stages/AstroEntropy/frontend"
(cd "$FRONT_DIR" && npm run dev) &
FRONT_PID=$!

echo ""
echo "✓ All running"
echo "  LiveKit    → $LIVEKIT_URL"
echo "  API        → http://localhost:8000"
echo "  Frontend   → http://localhost:5173 (or next free port)"
echo "  Agent      → waiting for jobs"
echo ""
echo "Press Ctrl+C to stop everything."
echo ""

wait