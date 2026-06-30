#!/usr/bin/env bash
# Install Aceternity MCP + verify shadcn MCP for Cursor.
# Run from repo root: bash scripts/setup-ui-mcp.sh

set -euo pipefail
cd "$(dirname "$0")/.."

echo "==> Installing Aceternity MCP (Python backend)..."
if command -v pipx >/dev/null 2>&1; then
  pipx install aceternity-mcp || pipx upgrade aceternity-mcp
  pipx ensurepath
elif command -v uv >/dev/null 2>&1; then
  uv tool install aceternity-mcp || uv tool upgrade aceternity-mcp
else
  python3 -m pip install --user aceternity-mcp
fi

echo "==> Verifying aceternity-mcp-server..."
command -v aceternity-mcp-server
aceternity-mcp status || aceternity-mcp diagnose || true

echo "==> Ensuring shadcn CLI (for shadcn MCP)..."
if [[ ! -f node_modules/shadcn/dist/index.js ]]; then
  npm install
fi

echo "==> Quick MCP smoke tests..."
printf '%s\n' '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' \
  | node node_modules/shadcn/dist/index.js mcp | head -c 200
echo ""
printf '%s\n' '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' \
  | aceternity-mcp-server | head -c 200
echo ""

echo ""
echo "Done. In Cursor: Settings → MCP → toggle shadcn + aceternity-ui off/on → restart Cursor → new chat."
