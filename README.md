# Crypto AI Trading

Algorithmic + LLM-assisted crypto trading engine with:
- Exchange data ingestion
- Rule-based signal generation
- Optional LLM tie-breaker decisions
- Session-scoped dashboard and analytics

The app runs two processes together:
- Trading engine (runs three modes concurrently: SPOT/FUTURES/OPTIONS)
- FastAPI dashboard backend with React frontend (served from `static/`)

Default dashboard URL: `http://localhost:8000`

## What This Project Does

- Pulls market data for allowlisted symbols (for example `BTCUSDT`)
  - Default allowlist: `BTCUSDT,ETHUSDT,SOLUSDT,ETHBTC,SOLBTC,SOLETH`
- Computes deterministic strategy votes (momentum/swing + technical tools)
- Optionally calls an LLM on borderline setups
- Simulates trades in paper mode (default)
- Runs **SPOT, FUTURES, OPTIONS** in parallel while sharing a common balance pool
- Persists prices, trades, signals, lessons, and LLM usage to SQLite
- Serves a live dashboard for session metrics and logs

## Supported Exchanges

- `COINDCX`
- `BINANCE` (configured for `https://api.binance.us`)

Exchange selection is controlled by `EXCHANGE` in `.env`.

## Supported LLM Providers

- `BEDROCK` (Anthropic models through AWS Bedrock)
- `OPENAI` (Chat Completions API)

## Free Local LLM (Mac M1 / Apple Silicon)

- Use a quantized model such as `phi-3-mini`, `gemma-2b`, or `tinyllama` together with `llama-cpp-python`. These models are open-source, small (≤4 B parameters), and can run on M1 CPU/GPU without external API costs.
- Set `LOCAL_LLM_ENABLED=true` and point `LOCAL_LLM_MODEL_PATH` to the downloaded `.ggml` or `gguf` binary. The summarizer now runs locally via `llama_cpp` and still feeds the dashboard’s LLM usage counters.
- Recommended quantized weights: `phi-3-mini-ggml-q4_0.bin` or similar from Hugging Face / phi-3 Mini community builds. Keep the file under `~/models/` and update `.env` accordingly.

Provider selection is controlled by `LLM_PROVIDER` in `.env`.

## MLX Deep RL (Mac M1 / Apple Silicon)

- Enable MLX-based deep RL for weight selection: `ENABLE_MLX_RL_AGENT=true`.
- This uses Apple’s `mlx` package for a tiny MLP contextual bandit and runs locally with no paid APIs.

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
6. Starts dashboard and trading engine concurrently (engine runs three mode loops)

Important: each `python run.py` starts a fresh session and clears transient session data while preserving lessons/rules.

`run.py` also supports automatic backend restarts on code changes:
- `AUTO_RESTART_ON_BACKEND_CHANGES=true` (default)
- Set `AUTO_RESTART_ON_BACKEND_CHANGES=false` to disable.

## Frontend Architecture

The dashboard UI is React + TypeScript built with Vite:

- Source app: [`frontend/src/App.tsx`](./frontend/src/App.tsx)
- Entry point: [`frontend/src/main.tsx`](./frontend/src/main.tsx)
- Vite config: [`frontend/vite.config.ts`](./frontend/vite.config.ts)
- Styles: [`frontend/src/style.css`](./frontend/src/style.css)

Runtime model:
- Build with Vite into `static/dist`
- UI calls backend API routes under `/api/*`
- FastAPI serves compiled assets from `static/dist` (fallback to `static/` if dist is missing)

Charts:
- Lightweight Charts for price/signal charts
- Chart.js for trade performance bars

## Frontend Commands

From `frontend/`:

```bash
npm install
npm run dev
```

Build production assets for FastAPI:

```bash
npm run build
```

This writes compiled files to `static/dist`.

## Configuration

Primary configuration is in:
- `.env` (runtime values)
- [`config.py`](./config.py) (parsing/defaults)
- [`.env.template`](./.env.template) (example values)

Common keys:

- Exchange:
  - `EXCHANGE=BINANCE` or `COINDCX`
  - `BINANCE_REST_BASE_URL=https://api.binance.us`
  - `BLUE_CHIP_WHITELIST=BTCUSDT,ETHUSDT,SOLUSDT,ETHBTC,SOLBTC,SOLETH`
- Trading mode:
  - `TRADING_MODE=SIMULATION` (recommended)
- LLM:
  - `LLM_PROVIDER=OPENAI` or `BEDROCK`
  - `OPENAI_API_KEY=...`
  - `OPENAI_MODEL_ID=gpt-4o` (or another supported model)
  - `OPENAI_NEWS_SUMMARY_MODEL_ID=gpt-4.1-mini` (dashboard sentiment summarizer)
- News/Sentiment:
  - `ALPHAVANTAGE_API_KEY=...` (optional, used for `NEWS_SENTIMENT`)
  - `CRYPTOCOMPARE_API_KEY=...` (optional)
  - Free no-key feeds are also used: GDELT, Cointelegraph RSS, Fear & Greed
- Safety controls:
  - `LLM_DAILY_BUDGET_USD`
  - `LLM_MAX_CALLS_PER_HOUR`
  - `MAX_DAILY_DRAWDOWN_USD`
  - `ENABLE_SENTIMENT_GATE=true`
  - `SENTIMENT_MIN_ABS_SCORE=0.08`
  - `SENTIMENT_DIRECTIONAL_FLOOR=0.05`
  - `SENTIMENT_MIN_ARTICLES=3`

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
- `GET /api/news/sentiment`
- `GET /api/news/headlines?limit=8`
- `GET /api/intent?mode=SPOT` (mode-specific intent)
- `GET /api/logs?lines=60`

Static frontend is mounted at `/` from the `static/` directory.

`/api/llm/summary` includes persistent token/call usage fields:
- `llm_tokens_session`
- `llm_tokens_today`
- `llm_tokens_all_time`
- `llm_calls_all_time`

News sentiment summaries generated with `gpt-5-nano` are stored in `llm_usage`
with stage `news_sentiment_summary`, and are included in token/cost totals.

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
- Frontend appears blank or stale:
  - Hard refresh the browser
  - Ensure `npm run build` has been run at least once for `static/dist`
  - Check browser console for runtime errors

## Security Notes

- Never commit `.env` or API keys.
- Rotate keys immediately if they are exposed in logs/chat/history.
- Start in `TRADING_MODE=SIMULATION` before enabling any live-trading behavior.
