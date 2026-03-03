#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

LOG_FILE="${LOG_FILE:-$ROOT_DIR/trading.log}"
DB_FILE="${DB_FILE:-$ROOT_DIR/trading_data.db}"
REPORT_FILE="${REPORT_FILE:-$ROOT_DIR/data/anomaly_context.md}"
LAST_MSG_FILE="${LAST_MSG_FILE:-$ROOT_DIR/data/anomaly_agent_last_message.txt}"

# If codex not on PATH, fall back to macOS app bundle path.
CODEX_BIN="${CODEX_BIN:-codex}"
if ! command -v "$CODEX_BIN" >/dev/null 2>&1; then
  if [[ -x "/Applications/Codex.app/Contents/Resources/codex" ]]; then
    CODEX_BIN="/Applications/Codex.app/Contents/Resources/codex"
  else
    echo "codex binary not found. Set CODEX_BIN or install Codex CLI."
    exit 1
  fi
fi

mkdir -p "$ROOT_DIR/data"

# Stability defaults for unattended cron runs:
# - force MLX off (avoids known Python/Metal aborts in headless cron contexts)
export ENABLE_MLX_RL_AGENT="${ENABLE_MLX_RL_AGENT:-false}"
export DISABLE_MLX="${DISABLE_MLX:-1}"
export MLX_USE_GPU="${MLX_USE_GPU:-0}"

echo "[agent] Building anomaly context report..."
.venv/bin/python scripts/agents/build_anomaly_context.py \
  --log "$LOG_FILE" \
  --db "$DB_FILE" \
  --max-lines 2500 \
  --max-anomalies 180 \
  --output "$REPORT_FILE"

echo "[agent] Running Codex anomaly-fix pass..."

PROMPT_FILE="$(mktemp)"
cat >"$PROMPT_FILE" <<'EOF'
You are operating inside /Users/tanmaydas/dev/crypto-ai-trading.

Task:
1) Read RUN.md and follow its development workflow.
2) Read data/anomaly_context.md, trading.log, and query trading_data.db as needed.
3) Identify concrete anomalies (if any) and infer root causes.
4) Implement fixes directly in code (bugs and critical reliability enhancements only).
5) Run validation checks:
   - make check-backend
   - make check-frontend
   - make smoke (only if API is up; otherwise explain why skipped)
6) Provide a concise summary of:
   - anomalies found
   - root causes
   - files changed
   - verification results

Constraints:
- Do not modify secrets or .env values.
- Do not use destructive git commands.
- Keep fixes minimal, production-safe, and test-backed when feasible.
EOF

cat "$REPORT_FILE" >>"$PROMPT_FILE"

# Default mode is non-interactive auto execution in workspace.
CODEX_AGENT_FLAGS="${CODEX_AGENT_FLAGS:---full-auto --sandbox workspace-write}"

"$CODEX_BIN" exec \
  -C "$ROOT_DIR" \
  $CODEX_AGENT_FLAGS \
  -o "$LAST_MSG_FILE" \
  - <"$PROMPT_FILE"

rm -f "$PROMPT_FILE"

echo "[agent] Done."
echo "[agent] Context: $REPORT_FILE"
echo "[agent] Last message: $LAST_MSG_FILE"
