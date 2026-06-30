#!/usr/bin/env bash
# ponytail: loads STITCH_API_KEY from repo .env — Cursor mcp.json envFile is unreliable
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
if [[ ! -f .env ]]; then
  echo "stitch-mcp: missing .env — set STITCH_API_KEY (see .env.example)" >&2
  exit 1
fi
set -a
# shellcheck disable=SC1091
source .env
set +a
if [[ -z "${STITCH_API_KEY:-}" ]]; then
  echo "stitch-mcp: STITCH_API_KEY empty in .env" >&2
  exit 1
fi
exec /usr/local/bin/npx -y @_davideast/stitch-mcp proxy
