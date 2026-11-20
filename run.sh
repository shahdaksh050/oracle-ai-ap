#!/usr/bin/env bash
set -euo pipefail

PORT="${1:-8765}"
URL="http://127.0.0.1:${PORT}"
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export AP_CONFIG="${DIR}/.runtime/app.json"

echo "=== AI-Native Enterprise Oracle AP Workspace ==="

# Check requirements
command -v uv >/dev/null 2>&1 || { echo >&2 "Error: 'uv' is required. Install via https://astral.sh/uv"; exit 1; }
command -v node >/dev/null 2>&1 || { echo >&2 "Error: 'node' (v20+) is required."; exit 1; }

# Install locked dependencies
uv sync --frozen --group dev

# Initialize local database and seed accounts
uv run python -m ap.admin init

# Generate sample invoice if not present
if [ ! -f "${DIR}/.runtime/supplier-invoice.pdf" ]; then
    uv run python -m ap.admin sample --number DEMO-1001
fi

echo "Access keys located at: ${DIR}/.runtime/demo-keys.json"

# Build web frontend
npm --prefix web ci --no-audit --no-fund
npm --prefix web run build

echo "Starting server on ${URL}..."
exec uv run uvicorn ap.api:app --host 127.0.0.1 --port "${PORT}" --no-access-log
