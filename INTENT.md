# INTENT

## Mission

This application is a **simulation-first crypto trading system** designed to:

1. Find tradeable setups across a focused whitelist of liquid crypto pairs.
2. Combine deterministic technical logic with optional LLM tie-breaking.
3. Allocate capital across **SPOT**, **FUTURES**, and **OPTIONS** policy tracks.
4. Run those three modes **concurrently**, sharing the same balance but maintaining separate policy/intent state.
5. Continuously adapt policy weighting with an online RL layer.
6. Maximize long-run risk-adjusted profitability while preserving configurable safety rails.

The system is intentionally opinionated toward rapid iteration: clear logs, session-scoped analytics, persistent learning artifacts, and explicit decision reasons.

---

## High-Level Functionalities

## 1) Data Ingestion

- Exchange support:
  - `COINDCX`
  - `BINANCE` (`https://api.binance.us`)
- Polling-based market feed via `poll_prices()`:
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
- Starting balance is configurable via `STARTING_BALANCE_USDT` (default 1250).
- Manages open trades with:
  - dynamic ATR stop/take-profit
  - trailing stop activation (preserved across pyramid adds)
  - time exits
  - optional pyramiding (preserves trailing stop and peak PnL state)
- Trade PnL accounting:
  - FUTURES PnL applies position leverage multiplier
  - Fee/slippage buffer deducted from gross PnL (`FEE_SLIPPAGE_BUFFER_PCT`)
- Per-mode state tracking:
  - `consecutive_losses` tracked independently per mode (not global)
  - `last_llm_call` throttled independently per mode
- Engine loop exits gracefully (returns control to supervisor) rather than hard-exiting the process.
- Position entry return value is checked — failure to enter is handled without crashing.

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
- Optional LLM decision review can SUPPORT/OPPOSE a final action and suggest overrides.
- Provider support:
  - **Bedrock** (Claude via AWS)
  - **OpenAI** (configurable base URL and model)
- All LLM-consuming modules support both providers uniformly:
  - `strategies/llm.py` (tie-breaker)
  - `strategies/meta_optimizer.py` (golden rules distillation)
  - `strategies/retrospective.py` (session lessons)
  - `strategies/missed_opportunity_analyzer.py` (skip analysis)
  - `session_review.py` (post-session review)
  - `news_sentiment.py` (headline summarization)
- LLM response cache:
  - TTL-based eviction (`_CACHE_TTL_SECONDS`)
  - Size-capped at `_CACHE_MAX_SIZE` entries with LRU-style pruning
- LLM usage and cost are persisted (`llm_usage`) and visualized in dashboard.

## 5) Technical Indicators

The deterministic voter system uses 8+ tool classes, each casting BUY/SELL votes:

- **RSI**: Uses Wilder's exponential smoothing (SMA seed, then iterative decay)
- **StochRSI**: Same Wilder-smoothed RSI series as input
- **MACD**: Standard EMA difference with signal line
- **Bollinger Band**: %B position for mean-reversion signals
- **EMA Cross**: SMA-seeded exponential moving averages for crossover detection
- **Price Range Momentum** (formerly VolumeMomentum): Tick-data price range analysis
- **Order Book Pressure**: Bid/ask imbalance scoring
- **Market Regime Detector**: SMA-seeded EMA for regime classification (TRENDING_UP/DOWN/RANGING)
- **ATR Scanner**: Tick-data approximation of Average True Range for volatility-aware sizing

Signal confidence can be unclamped (no ceiling) for trend-strategy multipliers via `allow_unclamped=True`.

## 6) Dashboard + API

- FastAPI backend serves:
  - runtime stats
  - trade/signal history
  - regime/sentiment snapshots
  - logs
  - model token/cost breakdown
  - strategy diagnostics by mode
- Security:
  - `eval()` replaced with `ast.literal_eval()` for safe deserialization
  - SQL LIKE queries use proper `ESCAPE` clause for underscore-containing mode prefixes
- React frontend visualizes these sections and mode-specific diagnostics.

---

## Decision Architecture (Core Flow)

For each eligible symbol:

1. Collect tool outputs:
   - volatility, liquidity, RSI, MACD, BB, EMA cross, StochRSI, price range momentum, order book pressure, etc.
2. Build deterministic vote counts (buy vs sell), plus weighted vote totals.
3. Apply market regime + session filters.
4. Apply sentiment gate.
5. Estimate expected edge.
6. Evaluate SPOT/FUTURES/OPTIONS policies in parallel (pre-LLM).
7. If borderline and permitted, call LLM tie-breaker.
8. Re-evaluate policies (post-LLM) with final direction/confidence.
9. Optionally run an LLM decision review (support vs oppose) and override/skip if needed.
10. Choose best allowed mode by composite score **within the active mode**.
11. Size position (risk-capped by balance + config limits).
12. Execute paper trade and persist full decision metadata.

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
  - voter weight multipliers (applied to the 8 deterministic vote parameters)
  - sentiment gate multiplier (`sentiment_gate_mult`) that scales sentiment gate strictness
- Reward:
  - realized trade PnL normalized by notional (profit positive, loss negative)
  - minus open-trade opportunity cost penalty
  - plus skip penalties for rejected high-edge opportunities (with configurable floor/cap)

## Persistent Weight Learning

Strategy weight multipliers (`weight_mult` and `voter_weight_mult`) are **not**
returned as static profile defaults.  They are **persistently learned** per
(mode, state) and evolve over time via a profile-conditioned gradient rule:

- **Storage**: `state["w"][mode][state_key]` contains the accumulated learned
  weights (`wm`, `vm`) and a reward baseline EMA (`reward_ema`).
- **Initialization**: first access seeds from the selected profile's defaults,
  with all weight keys from every profile in that mode included (missing keys
  default to 1.0).
- **Update rule** (runs every `update()` call after n ≥ 3):
  1. Compute normalized advantage: `(reward − baseline) / max(|baseline|, 0.002)`, clamped to [−1, 1].
  2. Positive advantage → compute `diff = profile_target − current` (reinforce profile's bets).
  3. Negative advantage → compute `diff = 1.0 − current` (dampen toward neutral).
  4. Apply `learned += RL_WEIGHT_ADAPT_LR × |advantage| × diff`.
  5. Clamp to [0.5, 2.0].
- **Exploration noise**: 30% chance per update, adds Gaussian noise with σ that
  decays with evidence count. This lets weights explore directions not covered
  by any profile's proposals.
- **Effect size**: ~0.5–1% per update (vs ~0.01% in old Q-value-only adaptation),
  compounding over thousands of RL cycles.
- **Tunable**: `RL_WEIGHT_ADAPT_LR` (default 0.15, range 0.01–0.5) is live-tunable
  via the RL tuning API.

## Skip-Pressure Adaptation

To avoid getting stuck in long skip streaks, the engine now adds a mode-local
**skip pressure** term:

- starts after `RL_SKIP_PRESSURE_START` consecutive skips
- grows by `RL_SKIP_PRESSURE_STEP` per additional skip
- capped by `RL_SKIP_PRESSURE_MAX`

Skip pressure gradually relaxes:

- setup threshold (`min_pro_needed_weighted`)
- directional threshold (`dir_threshold`)

And can conditionally override sentiment rejection when:

- skip pressure is active
- baseline edge is above `RL_SKIP_PRESSURE_EDGE_MIN`
- weighted directional support still clears threshold

This keeps the system aggressive enough to keep learning while preserving edge-quality constraints.

## Forced Entry (Exploration Override) Pipeline

When `force_entry=True` (skip streak ≥ `RL_FORCE_ENTRY_SKIP_STREAK` and trade
count below cap), the exploration override extends through the **entire** decision
pipeline — not just the pre-filter gates:

- ✅ Setup threshold bypass (insufficient pro-signals)
- ✅ Directional edge bypass (low buy/sell counts)
- ✅ Regime mismatch bypass
- ✅ Sentiment gate bypass
- ✅ HTF reject bypass
- ✅ Edge reject bypass (low expected edge)
- ✅ Pre-policy composite score bypass (score logged but not blocking)
- ✅ LLM borderline gate bypass (uses deterministic signal directly)
- ✅ Post-policy composite score bypass (score logged but not blocking)

This guarantees that forced exploration entries actually reach the trade entry,
producing real PnL samples for RL weight learning.  Without these downstream
bypasses, the exploration override could log "bypassing HTF reject" but never
trade because pre-policy or LLM gates still blocked.

## RL-Driven Sentiment Gate

Sentiment gating is no longer static. The active RL profile now provides a
`sentiment_gate_mult` value that scales:

- `SENTIMENT_MIN_ABS_SCORE`
- `SENTIMENT_DIRECTIONAL_FLOOR`

Lower multiplier values make the gate less strict (more entries), while higher
values make it stricter. This parameter is learned through the same reward loop
as other RL profile parameters.

## Exploration vs Exploitation

- Epsilon-greedy:
  - explores with probability `RL_EPSILON`
  - decays toward `RL_MIN_EPSILON` by `RL_EPSILON_DECAY`
- Learning rate controlled by `RL_LEARNING_RATE`
- For cold/unseen states with flat Q-values, exploitation can use mode-level
  profile averages (transfer from previously learned states) before defaulting
  to random exploration.

## Persistence

- RL state is persisted at:
  - `data/rl_weights.json`
- Saves are **batched** (every 10 updates) to reduce disk I/O, with a `flush()` method for force-saves.
- MLX neural agent also persists epsilon state under `mlx_meta` key.
- Survives restart and keeps learning continuity.
- Runtime RL tuning overrides are persisted at:
  - `data/rl_tuning_overrides.json`
- Overrides are shared across processes (dashboard API + engine), so live tuning
  from UI does not require restart.

## Runtime RL Tuning (Live From Frontend)

The RL system now supports live parameter tuning from the dashboard modal.

- API:
  - `GET /api/config/rl-tuning` returns tunable keys, current values, defaults, types, min/max bounds.
  - `PUT /api/config/rl-tuning` updates override values (or clears to default with `null`).
- Frontend:
  - RL Agent modal includes a `Runtime RL Tuning` section.
  - Users can edit numeric/boolean settings and save/reset defaults live.

Tunable categories include:

- exploration gating:
  - `RL_MIN_TRADES_BEFORE_STRICT_GATES`
  - `RL_MIN_CLOSED_TRADES_BEFORE_STRICT_GATES`
- forced exploration:
  - `RL_FORCE_ENTRY_ON_SKIP_STREAK`
  - `RL_FORCE_ENTRY_SKIP_STREAK`
  - `RL_FORCE_ENTRY_MAX_TRADES`
  - `RL_FORCE_ENTRY_MIN_EDGE_PCT`
- under-sampled gate softening:
  - `RL_UNDERSAMPLED_MIN_PRO_MULT`
  - `RL_UNDERSAMPLED_DIR_THRESHOLD_MULT`
  - `RL_UNDERSAMPLED_EDGE_THRESHOLD_MULT`
- skip-penalty scaling:
  - `RL_OPPORTUNITY_COST_PENALTY`
  - `RL_SKIP_PENALTY_CAP`
  - `RL_SKIP_PENALTY_FLOOR`
  - `RL_SKIP_PENALTY_WARMUP_UPDATES`
  - `RL_SKIP_PENALTY_WARMUP_SCALE`
  - `RL_SKIP_PENALTY_LOW_TRADE_SCALE`
- skip-pressure dynamics:
  - `RL_SKIP_PRESSURE_START`
  - `RL_SKIP_PRESSURE_STEP`
  - `RL_SKIP_PRESSURE_MAX`
  - `RL_SKIP_PRESSURE_EDGE_MIN`
- entry/trade reward context:
  - `RL_OPEN_TRADE_COST_PENALTY`
  - `MIN_EXPECTED_EDGE_PCT`

---

## Risk Model and Capital Controls

Risk is intentionally elevated compared to conservative defaults, but still bounded:

- Max risk per trade via balance fraction
- Min/max position size clamps
- Futures leverage caps
- Fee/slippage buffer deducted from every trade PnL (`FEE_SLIPPAGE_BUFFER_PCT`)
- Daily drawdown kill-switch (uses **peak-to-trough** max drawdown, not simple range)
- LLM budget caps and call-rate throttles (per-mode)
- Consecutive-loss based risk cuts and direction blocks (**per-mode**, not global)

This is not risk-free; it is controlled aggression.

---

## Database Layer

- SQLite-backed persistence for trades, signals, portfolio snapshots, lessons, and LLM usage.
- Connection management uses `_SafeConnection` wrapper with:
  - Context manager support (`with _conn() as conn:`)
  - `__del__` safety net to auto-close leaked connections
  - Transparent delegation to underlying `sqlite3.Connection`

---

## Startup and Session Management

- `run.py` supervisor manages engine lifecycle with PID tracking.
- Session reset (`reset_session.py`) is **conditional** on `RESET_ON_RESTART` env var (default: off).
- Reset clears trades, signals, portfolio, and logs; balance display uses `config.STARTING_BALANCE_USDT` dynamically.
- Starting balance is configurable via environment variable, not hardcoded.

---

## Observability and Diagnostics

The app logs high-volume event traces by design:

- API request/response logs with timing and payload context
- LLM/Bedrock request-response logs
- policy evaluation diagnostics by mode
- entry/exit reasons with confidence and score traces
- signal events capture raw votes plus weighted buy/sell/total
- RL updates (`RL_UPDATE`, reward, Q-value drift, epsilon)
- sentiment gate verdicts include active gate multiplier (`gate x...`)

Dashboard sections expose:

- market regime
- intent
- vote and TA status
- weighted vote confidence (BUY/SELL %)
- strategy diagnostics (mode-specific)
- sentiment/news summary
- LLM token/cost usage (aggregate + model breakdown)
- lessons learned
- system logs (with smart auto-scroll and pause indicator when user scrolls up)
- RL Agent card with expand modal and mode tabs (`SPOT`, `FUTURES`, `OPTIONS`)
  - per-profile controls: `size_mult`, `leverage_mult`, `confidence_bias`, `sentiment_gate_mult`
  - full multiplier maps: `voter_weight_mult` (8 vote parameters) and `weight_mult` (strategy factors)
  - learned RL tables per state: profile `q` and `n` counts
  - draft protection: local edits are not overwritten by server polling until saved or reset

Frontend architecture:

- Balance display uses `STARTING_BALANCE` constant (synced with backend config)
- API client logs warnings on non-OK responses and fetch failures (visible in dev tools)
- Theme-aware scrollbar colors via CSS custom properties
- RL modal syncs active mode with parent component and tracks dirty state

RL observability APIs:

- `/api/rl/cost` for reward/penalty aggregates and recent RL events
- `/api/rl/weights` for mode-specific profile multipliers and learned state tables
- `/api/config/rl-tuning` for live runtime RL config inspection/update

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
