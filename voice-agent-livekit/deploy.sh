#!/usr/bin/env bash
# Deploy the agent to LiveKit Cloud:   ./deploy.sh [--check]
#   1. stage a clean build folder (code from ../backend-api, ../data/serving.db, this Dockerfile, livekit.toml)
#   2. lk agent deploy <stage> --secrets-file secrets.env      (LiveKit Cloud builds the image from the Dockerfile)
# Needs: lk (logged in: `lk cloud auth`), secrets.env next to this script. --check stages and builds locally, deploys nothing.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"; ROOT="$(cd "$HERE/.." && pwd)"
STAGE="$(mktemp -d)"; trap 'rm -rf "$STAGE"' EXIT
[ "${1:-}" = "--check" ] || [ -f "$HERE/secrets.env" ] || { echo "secrets.env is missing (cp secrets.env.example secrets.env and fill it in)"; exit 1; }
[ -f "$ROOT/data/serving.db" ] || { echo "data/serving.db is missing"; exit 1; }

cp "$ROOT/backend-api/pyproject.toml" "$ROOT/backend-api/uv.lock" "$ROOT/backend-api/.python-version" "$STAGE/"
rsync -a --exclude '__pycache__' --exclude '.env*' "$ROOT/backend-api/src" "$ROOT/backend-api/vendor" "$STAGE/"
cp "$ROOT/data/serving.db" "$STAGE/serving.db"
cp "$HERE/Dockerfile" "$HERE/.dockerignore" "$HERE/livekit.toml" "$STAGE/"
du -sh "$STAGE" | sed 's/^/build context: /'

if [ "${1:-}" = "--check" ]; then
  docker build -t flame-agent:check "$STAGE"
  echo "image builds; nothing was deployed"; exit 0
fi
cd "$STAGE"
if grep -q '^\[agent\]' "$HERE/livekit.toml" && grep -q '^ *id *=' "$HERE/livekit.toml"; then
  lk agent deploy --yes --secrets-file "$HERE/secrets.env" --ignore-empty-secrets "$STAGE"
else
  # first time (or after `lk agent delete`): create the agent from the staged folder, keep the new livekit.toml
  lk agent create --yes --region "${LK_REGION:-eu-central}" --secrets-file "$HERE/secrets.env" --ignore-empty-secrets "$STAGE"
  cp "$STAGE/livekit.toml" "$HERE/livekit.toml"
  echo "agent created; livekit.toml updated (commit it)"
fi
