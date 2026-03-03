#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${1:-http://127.0.0.1:8000}"

echo "[smoke] Checking $BASE_URL/api/portfolio/summary"
curl -fsS "$BASE_URL/api/portfolio/summary" >/dev/null

echo "[smoke] Checking $BASE_URL/api/intent?mode=SPOT"
curl -fsS "$BASE_URL/api/intent?mode=SPOT" >/dev/null

echo "[smoke] OK"
