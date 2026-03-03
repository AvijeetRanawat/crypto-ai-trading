#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LOG_DIR="$ROOT_DIR/.devlogs"
mkdir -p "$LOG_DIR"

API_LOG="$LOG_DIR/api.log"
FRONT_LOG="$LOG_DIR/frontend.log"
ENGINE_LOG="$LOG_DIR/engine.log"

cleanup() {
  set +e
  # Send SIGTERM first so the engine can flush DB writes gracefully.
  if [[ -n "${ENGINE_PID:-}" ]]; then kill -TERM "$ENGINE_PID" 2>/dev/null || true; fi
  if [[ -n "${API_PID:-}" ]];    then kill -TERM "$API_PID"    2>/dev/null || true; fi
  if [[ -n "${FRONT_PID:-}" ]];  then kill -TERM "$FRONT_PID"  2>/dev/null || true; fi

  # Wait up to 12 seconds for graceful exit before escalating to SIGKILL.
  GRACE=12
  while [[ $GRACE -gt 0 ]]; do
    ALL_DONE=true
    for _PID in "${ENGINE_PID:-}" "${API_PID:-}" "${FRONT_PID:-}"; do
      [[ -z "$_PID" ]] && continue
      kill -0 "$_PID" 2>/dev/null && ALL_DONE=false
    done
    $ALL_DONE && break
    sleep 1
    (( GRACE-- ))
  done

  # Force-kill anything still alive after the grace period.
  if [[ -n "${ENGINE_PID:-}" ]]; then kill -KILL "$ENGINE_PID" 2>/dev/null || true; fi
  if [[ -n "${API_PID:-}" ]];    then kill -KILL "$API_PID"    2>/dev/null || true; fi
  if [[ -n "${FRONT_PID:-}" ]];  then kill -KILL "$FRONT_PID"  2>/dev/null || true; fi
  wait "${ENGINE_PID:-}" "${API_PID:-}" "${FRONT_PID:-}" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

if [[ ! -x "$ROOT_DIR/.venv/bin/python" ]]; then
  echo "Missing virtualenv python at $ROOT_DIR/.venv/bin/python"
  echo "Create it first: python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt"
  exit 1
fi

if ! command -v npm >/dev/null 2>&1; then
  echo "npm not found in PATH; install Node.js/npm first."
  exit 1
fi

echo "[dev] Starting API on :8000 (reload)..."
(
  cd "$ROOT_DIR"
  exec .venv/bin/python -m uvicorn dashboard_api:app --reload --host 0.0.0.0 --port 8000
) >"$API_LOG" 2>&1 &
API_PID=$!

echo "[dev] Starting frontend on :5173..."
(
  cd "$ROOT_DIR/frontend"
  exec npm run dev -- --host 0.0.0.0 --port 5173
) >"$FRONT_LOG" 2>&1 &
FRONT_PID=$!

echo "[dev] Starting engine..."
(
  cd "$ROOT_DIR"
  exec .venv/bin/python main.py
) >"$ENGINE_LOG" 2>&1 &
ENGINE_PID=$!

echo "[dev] API PID=$API_PID log=$API_LOG"
echo "[dev] Frontend PID=$FRONT_PID log=$FRONT_LOG"
echo "[dev] Engine PID=$ENGINE_PID log=$ENGINE_LOG"
echo "[dev] Dashboard: http://localhost:5173"
echo "[dev] API:       http://localhost:8000"
echo "[dev] Ctrl+C stops all three."

wait -n "$API_PID" "$FRONT_PID" "$ENGINE_PID"
STATUS=$?
echo "[dev] One process exited with status $STATUS. Stopping others..."
exit "$STATUS"
