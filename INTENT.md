# INTENT

## Mission

This application is a **simulation-first crypto trading system** designed to:

1. Find tradeable setups across a focused whitelist of liquid crypto pairs.
2. Combine deterministic technical logic with optional LLM tie-breaking.
3. Allocate capital across **SPOT**, **FUTURES**, and **OPTIONS** policy tracks.
4. Run those three modes **concurrently**, sharing the same balance but maintaining separate policy/intent state.
4. Continuously adapt policy weighting with an online RL layer.
5. Maximize long-run risk-adjusted profitability while preserving configurable safety rails.

The system is intentionally opinionated toward rapid iteration: clear logs, session-scoped analytics, persistent learning artifacts, and explicit decision reasons.

---

## High-Level Functionalities

## 1) Data Ingestion

- Exchange support:
  - `COINDCX`
  - `BINANCE` (`https://api.binance.us`)
- Polling-based market feed updates:
  - Configurable by `POLL_INTERVAL_SECONDS`
- Maintains:
  - `latest_prices` in-memory
  - ticker metadata (`volume`, `spread`, `high`, `low`, etc.)
  - persistent price ticks in SQLite (`prices` table)

## 2) Trading Engine

- Runs deterministic+policy logic loop in `engine.py`.
- Uses a minimum warmup history (`WARMUP_MIN_TICKS`) before decisions.
- Runs **three concurrent loops** (SPOT/FUTURES/OPTIONS) against a shared simulator.
- Evaluates one-symbol-at-a-time opportunities **per mode** when that mode has no open position.
- Manages open trades with:
  - dynamic ATR stop/take-profit
  - trailing stop activation
  - time exits
  - optional pyramiding

## 3) Three Product Policies (Parallel)

The engine runs three modes in parallel:

- `SPOT`
- `FUTURES`
- `OPTIONS`

Each policy returns:

- `allow` / reject
- `composite_score`
- sizing or leverage guidance
- strategy label
- component-wise diagnostic scores

Each mode makes its own trade decisions concurrently while sharing the same balance pool.
Mode-specific decisions are tagged with `SPOT_`, `FUTURES_`, or `OPTIONS_` prefixes.

## 4) LLM Layer

- LLM is used mostly for borderline setups (tie-breaker role).
- Provider support:
  - Bedrock
  - OpenAI
- LLM usage and cost are persisted (`llm_usage`) and visualized in dashboard.
- News sentiment summarization also goes through LLM provider layer.

## 5) Dashboard + API

- FastAPI backend serves:
  - runtime stats
  - trade/signal history
  - regime/sentiment snapshots
  - logs
  - model token/cost breakdown
  - strategy diagnostics by mode
- React frontend visualizes these sections and mode-specific diagnostics.

---

## Decision Architecture (Core Flow)

For each eligible symbol:

1. Collect tool outputs:
   - volatility, liquidity, RSI, MACD, BB, EMA cross, StochRSI, volume momentum, order book pressure, etc.
2. Build deterministic vote counts (buy vs sell).
3. Apply market regime + session filters.
4. Apply sentiment gate.
5. Estimate expected edge.
6. Evaluate SPOT/FUTURES/OPTIONS policies in parallel (pre-LLM).
7. If borderline and permitted, call LLM tie-breaker.
8. Re-evaluate policies (post-LLM) with final direction/confidence.
9. Choose best allowed mode by composite score **within the active mode**.
10. Size position (risk-capped by balance + config limits).
11. Execute paper trade and persist full decision metadata.

If rejected, decision is persisted as `SKIPPED`/`MISSED` with reason context.

---

## Strategy Details by Product

## SPOT Strategy

Intent:

- Directional spot participation with long-biased behavior (if `SPOT_LONG_ONLY=true`).
- Emphasis on trend quality + momentum confirmation.

Inputs weighted:

- Trend structure
- Momentum alignment
- Volatility quality
- Liquidity quality
- Sentiment
- Session quality
- Performance feedback

Typical behavior:

- Prefers continuation and breakout conditions.
- Penalizes choppy/no-edge contexts unless high conviction.
- Produces strategy tags like:
  - `SPOT_TREND_PULLBACK_BUY`
  - `SPOT_BREAKOUT_BUY`
  - `SPOT_MEAN_REVERSION_SCALP`
  - `SPOT_SKIP_*`

## FUTURES Strategy

Intent:

- Higher-return directional exposure using leverage with strict liquidity/volatility gating.

Inputs weighted:

- Vote imbalance
- Regime strength
- Momentum
- Volatility fit
- Liquidity quality
- Sentiment support
- Session quality

Typical behavior:

- Produces leverage recommendation (`recommended_leverage`).
- Uses aggressive sizing when score and confidence are strong.
- Rejects extreme volatility/low liquidity/strong sentiment conflict.

## OPTIONS Strategy

Intent:

- Volatility-structure-aware strategy selection rather than pure direction only.

Inputs weighted:

- Vote imbalance
- Regime + momentum
- Volatility regime (most important here)
- Liquidity
- Sentiment
- Session quality
- Edge score

Typical behavior:

- Selects templates such as:
  - `IRON_CONDOR`
  - `BULL_PUT_CREDIT_SPREAD`
  - `BEAR_CALL_CREDIT_SPREAD`
  - `CALL_DEBIT_SPREAD` / `PUT_DEBIT_SPREAD`
  - `LONG_STRADDLE_PROXY`
- Rejects when structure does not provide sufficient edge.

---

## Choppy-Market Handling

Previous behavior was strict skip on choppy states.  
Current behavior allows **high-conviction choppy overrides**:

- requires minimum vote imbalance and confidence thresholds
- otherwise skips weak chop setups

This increases risk appetite while preserving a minimal quality floor.

---

## RL Agent: Adaptive Weight Inference

## Purpose

The RL layer makes the system less static by learning which weight profile works best for each market context.

## Current RL Formulation

- Type: lightweight online contextual bandit/Q update
- State: bucketized market context
  - regime
  - session quality
  - volatility bucket
  - sentiment bucket
  - vote imbalance bucket
  - expected edge bucket
- Action: select profile (per mode), each profile defines:
  - component weight multipliers
  - confidence bias
  - size multiplier
  - leverage multiplier (futures)
- Reward:
  - realized trade PnL normalized by notional (profit positive, loss negative)
  - minus open-trade opportunity cost penalty
  - plus small penalties for rejected high-edge opportunities

## Exploration vs Exploitation

- Epsilon-greedy:
  - explores with probability `RL_EPSILON`
  - decays toward `RL_MIN_EPSILON` by `RL_EPSILON_DECAY`
- Learning rate controlled by `RL_LEARNING_RATE`

## Persistence

- RL state is persisted at:
  - `data/rl_weights.json`
- Survives restart and keeps learning continuity.

---

## Risk Model and Capital Controls

Risk is intentionally elevated compared to conservative defaults, but still bounded:

- Max risk per trade via balance fraction
- Min/max position size clamps
- Futures leverage caps
- Daily drawdown kill-switch
- LLM budget caps and call-rate throttles
- Consecutive-loss based risk cuts and direction blocks

This is not risk-free; it is controlled aggression.

---

## Observability and Diagnostics

The app logs high-volume event traces by design:

- API request/response logs with timing and payload context
- LLM/Bedrock request-response logs
- policy evaluation diagnostics by mode
- entry/exit reasons with confidence and score traces
- RL updates (`RL_UPDATE`, reward, Q-value drift, epsilon)

Dashboard sections expose:

- market regime
- intent
- vote and TA status
- strategy diagnostics (mode-specific)
- sentiment/news summary
- LLM token/cost usage (aggregate + model breakdown)
- lessons learned
- system logs

---

## What the App Is Trying to Achieve

In plain terms:

1. Trade only when there is measurable edge.
2. Route each opportunity to the best product strategy (spot/futures/options).
3. Scale aggressiveness when confidence and context support it.
4. Learn from outcomes continuously (including missed-opportunity penalties).
5. Maintain transparency so every trade/skip is explainable in logs and UI.

This is a **self-adjusting, profit-seeking, explainable trading simulator** with explicit controls for risk appetite and adaptive behavior.

---

## Important Caveat

This system is a decision engine for simulation and experimentation.  
It is not guaranteed to be profitable and should not be treated as financial advice.

Use `TRADING_MODE=SIMULATION` until behavior is validated thoroughly against your risk tolerance.
