#!/usr/bin/env bash
# Stitch MCP — create .env from example, verify proxy can start.
# Run from repo root: bash scripts/setup-stitch-mcp.sh

set -euo pipefail
cd "$(dirname "$0")/.."

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "Created .env — paste your STITCH_API_KEY from https://stitch.withgoogle.com/settings"
  echo "  (Rotate any key you pasted in chat; do not commit .env)"
  exit 0
fi

# shellcheck disable=SC1091
set -a
source .env
set +a

if [[ -z "${STITCH_API_KEY:-}" ]]; then
  echo "STITCH_API_KEY is empty in .env — add your key from Stitch settings."
  exit 1
fi

echo "==> Stitch MCP doctor (via @_davideast/stitch-mcp)..."
npx -y @_davideast/stitch-mcp doctor || true

echo ""
echo "Skills: npx skills add google-labs-code/stitch-skills --yes  (already in .agents/skills/)"
echo ""
echo "Done. In Cursor:"
echo "  1. Settings → MCP → enable stitch → restart Cursor"
echo "  2. New Agent chat: \"List my Stitch projects\""
