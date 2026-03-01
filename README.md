# Crypto AI Trading

Algorithmic + LLM-assisted crypto trading engine with:
- Exchange data ingestion
- Rule-based signal generation
- Optional LLM tie-breaker decisions
- Session-scoped dashboard and analytics

The app runs two processes together:
- Trading engine loop
- FastAPI dashboard backend with static frontend

Default dashboard URL: `http://localhost:8000`

## What This Project Does

- Pulls market data for allowlisted symbols (for example `BTCUSDT`)
- Computes deterministic strategy votes (momentum/swing + technical tools)
- Optionally calls an LLM on borderline setups
- Simulates trades in paper mode (default)
- Persists prices, trades, signals, lessons, and LLM usage to SQLite
- Serves a live dashboard for session metrics and logs

## Supported Exchanges

- `COINDCX`
- `BINANCE` (configured for `https://api.binance.us`)

Exchange selection is controlled by `EXCHANGE` in `.env`.

## Supported LLM Providers

- `BEDROCK` (Anthropic models through AWS Bedrock)
- `OPENAI` (Chat Completions API)

Provider selection is controlled by `LLM_PROVIDER` in `.env`.

## Quick Start

See the full setup guide in [SETUP.md](./SETUP.md).

Minimal run flow:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
cp .env.template .env
python run.py
```

Open:
- `http://localhost:8000`

## Runtime Behavior

`run.py` does the following when starting:

1. Sets a shared runtime session id (`TRADING_SESSION_ID`)
2. Enforces a single-instance PID lock via `run.pid`
3. Clears `trading.log`
4. Initializes DB schema/migrations
5. Resets session data (trades/portfolio/signals/prices)
6. Starts dashboard and trading engine concurrently

Important: each `python run.py` starts a fresh session and clears transient session data while preserving lessons/rules.

## Configuration

Primary configuration is in:
- `.env` (runtime values)
- [`config.py`](./config.py) (parsing/defaults)
- [`.env.template`](./.env.template) (example values)

Common keys:

- Exchange:
  - `EXCHANGE=BINANCE` or `COINDCX`
  - `BINANCE_REST_BASE_URL=https://api.binance.us`
  - `BLUE_CHIP_WHITELIST=BTCUSDT,ETHUSDT`
- Trading mode:
  - `TRADING_MODE=SIMULATION` (recommended)
- LLM:
  - `LLM_PROVIDER=OPENAI` or `BEDROCK`
  - `OPENAI_API_KEY=...`
  - `OPENAI_MODEL_ID=gpt-4o` (or another supported model)
- Safety controls:
  - `LLM_DAILY_BUDGET_USD`
  - `LLM_MAX_CALLS_PER_HOUR`
  - `MAX_DAILY_DRAWDOWN_USD`

## Dashboard/API Endpoints

Dashboard backend lives in [`dashboard_api.py`](./dashboard_api.py).

Core endpoints:
- `GET /api/session_start`
- `GET /api/warmup`
- `GET /api/trades/recent`
- `GET /api/portfolio/history`
- `GET /api/portfolio/summary`
- `GET /api/market/history?symbol=BTCUSDT`
- `GET /api/signals/history?symbol=BTCUSDT&limit=200`
- `GET /api/llm/summary`
- `GET /api/regime`
- `GET /api/intent`
- `GET /api/logs?lines=60`

Static frontend is mounted at `/` from the `static/` directory.

## Data and Storage

SQLite DB: `trading_data.db`

Main tables:
- `prices`
- `trades`
- `portfolio`
- `signal_events`
- `llm_usage`
- `lessons`
- `strategy_rules`
- `intent`

## Development and Tests

Install dev deps from `requirements.txt`, then run:

```bash
pytest -q
```

Additional utility scripts:
- [`reset_session.py`](./reset_session.py)
- [`validation_gates.py`](./validation_gates.py)
- [`session_review.py`](./session_review.py)
- [`distill_lessons.py`](./distill_lessons.py)

## Troubleshooting

- `ModuleNotFoundError: uvicorn`:
  - Activate `.venv`
  - Reinstall dependencies with `pip install -r requirements.txt`
- Binance HTTP `451`:
  - Ensure `BINANCE_REST_BASE_URL=https://api.binance.us`
- Existing lock error from `run.pid`:
  - Stop old process or remove stale `run.pid` if process no longer exists

## Security Notes

- Never commit `.env` or API keys.
- Rotate keys immediately if they are exposed in logs/chat/history.
- Start in `TRADING_MODE=SIMULATION` before enabling any live-trading behavior.
