# RUN

## Smooth Development Workflow

Use this workflow every time to avoid full-server interruptions while editing.

## When To Run What

## First start of the day

Run all 3 services in separate terminals:

- Terminal 1: `make dev-api`
- Terminal 2: `make dev-frontend`
- Terminal 3: `make dev-engine`

Or use one command:

- `make dev`

## Every time you change backend Python code

1. Save file
2. Run syntax check:
   - `python -m py_compile path/to/file.py`
3. Confirm API terminal has no traceback
4. Run quick endpoint check:
   - `make smoke`

## Every time you change frontend code

1. Save file (Vite HMR should update automatically)
2. Run type check:
   - `cd frontend && npm run -s typecheck`
3. If UI changed significantly, run:
   - `cd frontend && npm run -s lint`

## After completing one small chunk

- Run:
  - `make smoke`
- Manually verify:
  - Dashboard opens
  - No new backend traceback

## Before commit/push

Run full quick gate:

- `make check`

Then commit.

## If one process breaks

- API broke: rerun `make dev-api`
- Frontend broke: rerun `make dev-frontend`
- Engine broke: rerun `make dev-engine`

Restart only the failed process, not all three.

## If you need run.py behavior during debugging

- Use:
  - `make run-safe`

This disables backend file-change auto-restart.

## 1) Run 3 Processes Separately

Terminal 1 (API with reload):
```bash
make dev-api
```

Terminal 2 (Frontend with HMR):
```bash
make dev-frontend
```

Terminal 3 (Engine only):
```bash
make dev-engine
```

Alternative single-command runner:
```bash
make dev
```

## 2) Edit in Small Chunks

For each change:

1. Change one thing
2. Save
3. Wait 2–3 seconds for reload/HMR
4. Check UI + terminal logs
5. Then proceed to next change

## 3) Pre-check After Each Change

Backend file changed:
```bash
python -m py_compile your_file.py
```

Frontend file changed:
```bash
cd frontend && npm run -s typecheck
```

## 4) Fast Health Checks After Each Chunk

Open dashboard once and run:
```bash
make smoke
```

(`make smoke` checks `/api/portfolio/summary` and `/api/intent?mode=SPOT`.)

## 5) Keep Guardrails On

- Do not use `run.py` during active development.
- If you do use it, disable file-watch restarts:
```bash
make run-safe
```
- Commit only when a small chunk is stable.

## 6) If Something Breaks

- Restart only the failed process (API, frontend, or engine).
- Do not restart all three unless necessary.

## 7) Useful One-shot Validation

```bash
make check
```

This runs backend checks, frontend checks, and smoke API checks.

## 8) Autonomous Anomaly Agent (Log + DB Driven)

When you want automatic triage and patching from recent runtime issues:

```bash
make agent-anomaly
```

What it does:

1. Reads `trading.log` and extracts anomaly lines (`ERROR/WARNING/API_ERR/Traceback/etc.`).
2. Queries `trading_data.db` for relevant operational context (trades, signals, RL events, usage).
3. Writes context to:
   - `data/anomaly_context.md`
4. Runs Codex non-interactively to:
   - identify root causes
   - apply code fixes/enhancements
   - run checks per this RUN workflow
5. Saves Codex summary output to:
   - `data/anomaly_agent_last_message.txt`

Optional environment overrides:

- `LOG_FILE=/path/to/log`
- `DB_FILE=/path/to/db`
- `CODEX_BIN=/path/to/codex`
- `CODEX_AGENT_FLAGS="..."`
