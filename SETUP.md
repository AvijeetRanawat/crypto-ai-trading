# Setup Guide

This guide walks through a clean local setup for the project.

## 1. Prerequisites

- macOS/Linux shell
- Python 3.10+ (project currently runs with modern Python 3)
- Network access for `pip install` (PyPI)
- Node.js 18+ and npm (for Vite frontend build)

## 2. Create Virtual Environment

From project root:

```bash
cd /Users/tanmaydas/dev/crypto-ai-trading
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

## 3. Configure Environment Variables

Create `.env` from template:

```bash
cp .env.template .env
```

Edit `.env` and set values for your exchange and LLM provider.

### Recommended Binance + OpenAI setup

```dotenv
EXCHANGE=BINANCE
BINANCE_REST_BASE_URL=https://api.binance.us
BINANCE_API_KEY=your_binance_key
BINANCE_API_SECRET=your_binance_secret

TRADING_MODE=SIMULATION
BLUE_CHIP_WHITELIST=BTCUSDT,ETHUSDT,SOLUSDT,ETHBTC,SOLBTC,SOLETH

LLM_PROVIDER=OPENAI
OPENAI_API_KEY=your_openai_api_key
OPENAI_MODEL_ID=gpt-4o
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_NEWS_SUMMARY_MODEL_ID=gpt-4.1-mini

# Optional news/sentiment API keys
ALPHAVANTAGE_API_KEY=your_alphavantage_api_key
CRYPTOCOMPARE_API_KEY=your_cryptocompare_api_key
ENABLE_SENTIMENT_GATE=true
SENTIMENT_MIN_ABS_SCORE=0.08
SENTIMENT_DIRECTIONAL_FLOOR=0.05
SENTIMENT_MIN_ARTICLES=3
```

### Optional Bedrock setup

```dotenv
LLM_PROVIDER=BEDROCK
BEDROCK_MODEL_ID=us.anthropic.claude-sonnet-4-6
HAIKU_MODEL_ID=us.anthropic.claude-haiku-4-5-20251001-v1:0
```

### Optional Free Local LLM (Apple Silicon)

```bash
pip install llama-cpp-python
```

1. Download a quantized Llama-style binary (for example `phi-3-mini-ggml-q4_0.bin` or `gemma-2b-gguf-q4_0`) to `~/models/`.
2. Update `.env`:
   ```dotenv
   LOCAL_LLM_ENABLED=true
   LOCAL_LLM_MODEL_PATH=/Users/you/models/phi-3-mini-ggml-q4_0.bin
   LOCAL_LLM_MODEL_NAME=phi-3-mini-q4
   LOCAL_LLM_TEMPERATURE=0.1
   LOCAL_LLM_MAX_TOKENS=200
   ```
3. The backend will now call the local quantized model (via `llama_cpp`) for sentiment summaries instead of paid APIs.

This keeps inference entirely free and works well on M1/M2 MacBooks because the weights are <1.5 GB and the `llama-cpp` backend uses native Metal acceleration.

### Optional MLX Deep RL (Apple Silicon)

```bash
pip install mlx
```

```dotenv
ENABLE_MLX_RL_AGENT=true
RL_MLX_LEARNING_RATE=0.05
RL_MLX_HIDDEN_SIZE=16
```

This swaps the RL weight selector to a tiny MLX MLP contextual bandit running locally.

## 4. Start the App

Build the frontend first:

```bash
cd /Users/tanmaydas/dev/crypto-ai-trading/frontend
npm install
npm run build
```

Then start backend+engine:

```bash
cd /Users/tanmaydas/dev/crypto-ai-trading
python run.py
```

`run.py` starts:
- Dashboard API + frontend on port `8000`
- Trading engine loop
- Auto-restart watcher for backend file changes (`AUTO_RESTART_ON_BACKEND_CHANGES=true`)

Open in browser:
- `http://localhost:8000`

Frontend note:
- React + TypeScript source is under `frontend/src`.
- FastAPI serves compiled assets from `static/dist`.

## 5. Verify It Is Working

Check terminal logs for:
- dashboard startup line
- trading engine startup line
- periodic price feed updates

You can also hit APIs directly:

```bash
curl http://localhost:8000/api/session_start
curl http://localhost:8000/api/portfolio/summary
curl http://localhost:8000/api/logs?lines=20
curl http://localhost:8000/api/llm/summary
curl http://localhost:8000/api/news/sentiment
```

## 6. Stop the App

Press `Ctrl+C` in the terminal running `python run.py`.

If an old lock exists:
- Check `run.pid`
- Ensure that PID is not alive
- Remove stale `run.pid` and restart

## 7. Common Issues

### `ModuleNotFoundError` (for example `uvicorn`)

- Ensure virtualenv is active: `. .venv/bin/activate`
- Reinstall deps: `pip install -r requirements.txt`

### `ERROR: Could not find a version...` during pip install

- Usually DNS/network problem
- Verify internet access and DNS resolution
- Retry install

### Binance HTTP `451`

- Use US endpoint:
  - `BINANCE_REST_BASE_URL=https://api.binance.us`

### Dashboard does not load

- Confirm `python run.py` is still running
- Verify no port conflict on `8000`
- Try `http://127.0.0.1:8000`
- Ensure frontend has been built: `cd frontend && npm run build`
- Open browser devtools console for React/runtime errors

### Frontend local dev mode

You can run Vite dev server separately:

```bash
cd /Users/tanmaydas/dev/crypto-ai-trading/frontend
npm install
npm run dev
```

- Vite runs on `http://localhost:5173`
- `/api` is proxied to `http://localhost:8000` (configured in `vite.config.ts`)

## 8. Running Tests

```bash
pytest -q
```

Targeted scripts:

```bash
python test_api.py
python test_ws.py
python test_profit_rebuild.py
```

## 9. Safety Checklist Before Live Trading

- Keep `TRADING_MODE=SIMULATION` until behavior is validated
- Confirm whitelist symbols and risk thresholds
- Set LLM budget limits:
  - `LLM_DAILY_BUDGET_USD`
  - `LLM_MAX_CALLS_PER_HOUR`
- Rotate and protect API keys
- Never commit `.env`
