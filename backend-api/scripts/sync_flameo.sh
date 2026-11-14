#!/usr/bin/env bash
# Re-copy flameo_tools (stdlib only, plus glossary.json) from the data repo into vendor/. serving.db is NOT copied (set FLAMEO_DB).
set -euo pipefail
SRC="${1:-$HOME/Desktop/nasa-multi-agents-stages/s1/s0-results/psi_stage1/flameo_tools}"
DST="$(cd "$(dirname "$0")/.." && pwd)/vendor/flameo_tools"
[ -f "$SRC/registry.py" ] || { echo "flameo_tools not found at $SRC (pass the path as the first argument)"; exit 1; }
rm -rf "$DST"
mkdir -p "$DST"
cp "$SRC"/*.py "$SRC"/README.md "$SRC"/router_examples.yaml "$SRC"/glossary.json "$DST"/      # glossary.json too: the glossary ladder reads it (Round 16: it was lost on every sync)
( cd "$SRC/.." && echo "psi_stage1 commit $(git rev-parse --short HEAD 2>/dev/null || echo unknown)$(git diff --quiet 2>/dev/null || echo ' (uncommitted changes)')" ) > "$DST/FROM_COMMIT.txt"
[ -f "$DST/glossary.json" ] || { echo "glossary.json missing after the sync (it must exist in $SRC)"; exit 1; }
echo "synced $(ls "$DST" | wc -l) files from $SRC"
