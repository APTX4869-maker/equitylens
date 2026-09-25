#!/usr/bin/env bash
# Start the EquityLens stack locally: FastAPI (:8000) + Next.js dev (:3000)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [ ! -f data/equitylens.duckdb ]; then
  echo "[equitylens] first run: syncing AAPL + MSFT from SEC (needs network)..."
  uv run equitylens sync AAPL MSFT || echo "sync failed; run 'uv run equitylens sync AAPL MSFT' manually"
fi

(uv run uvicorn equitylens.api.main:app --host 127.0.0.1 --port 8000 &)
echo "[api] http://127.0.0.1:8000  (FastAPI)"
cd apps/web
(pnpm dev &)
echo "[web] http://localhost:3000  (Next.js)"
wait
