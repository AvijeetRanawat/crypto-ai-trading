import asyncio
from datetime import datetime, timedelta
from collections import deque
from logger import logger, log_trade
from config import config
from database import (
    save_trade,
    update_trade_exit,
    save_portfolio_snapshot,
    update_intent,
    save_signal_event,
    save_llm_usage,
    get_llm_cost_today,
    get_llm_call_count_last_hour,
    get_runtime_context,
)

from strategies.momentum import MomentumAgent
from strategies.swing import SwingAgent
from strategies.trend import TrendAgent
from strategies.llm import LLMAgent
from strategies.retrospective import RetrospectiveAgent
from strategies.meta_optimizer import MetaOptimizer
from strategies.missed_opportunity_analyzer import MissedOpportunityAnalyzer
from strategies.tools import (
    VolatilityScanner, PriceVelocity, VolumeProfile, OrderBookPressure, SessionTracker,
    RSIAnalyzer, MACDSignal, BollingerBands, SupportResistance, CandlePatterns,
    MarketRegimeDetector, ATRTracker, MultiTimeframeConfirmer, SessionTimeFilter,
    StochasticRSI, EMACross, VolumeMomentum,
)
import sys
from news_sentiment import build_sentiment_snapshot

# ─────────────────────────────────────────
#  Paper Trading Simulator
# ─────────────────────────────────────────
class PaperTradingSimulator:
    def __init__(self):
        self.balance_usdt = 1_250.0
        self.positions = {}

    def enter_position(
        self,
        symbol,
        price,
        amount_usdt,
        reason,
        side="LONG",
        decision_source=None,
        deterministic_conf=None,
        llm_conf=None,
        llm_cost_usd=None,
    ):
        if not config.is_symbol_allowed(symbol):
            logger.error(f"Blocked non-allowlisted trade symbol: {symbol}")
            return False

        if self.balance_usdt < amount_usdt:
            logger.warning(f"Insufficient balance for {symbol}")
            return False

        quantity = amount_usdt / price
        self.balance_usdt -= amount_usdt
        entry_time = datetime.now()
        
        db_id = save_trade(
            symbol,
            side,
            price,
            quantity,
            entry_time,
            reason,
            decision_source=decision_source,
            deterministic_conf=deterministic_conf,
            llm_conf=llm_conf,
            llm_cost_usd=llm_cost_usd,
        )

        self.positions[symbol] = {
            "side": side,
            "entry_price": price,
            "quantity": quantity,
            "entry_time": entry_time,
            "db_id": db_id,
            "entry_reason": reason,
            "peak_pnl_pct": 0.0,       # Track peak for trailing stop
            "trailing_active": False,   # Trailing stop activated?
        }
        log_trade(side, symbol, price, quantity, reason, trade_id=db_id)
        save_portfolio_snapshot(self.balance_usdt, len(self.positions))
        
        emoji = "📈" if side == "LONG" else "📉"
        logger.info(f"{emoji} {side}: {symbol} at ${price:,.2f} | Size: ${amount_usdt:,.0f} | Bal: ${self.balance_usdt:,.0f}")
        return True

    def exit_position(self, symbol, current_price, reason):
        if symbol not in self.positions:
            return None

        pos = self.positions.pop(symbol)
        side = pos["side"]
        
        if side == "LONG":
            revenue = pos["quantity"] * current_price
            profit = revenue - (pos["quantity"] * pos["entry_price"])
        else:
            profit = (pos["entry_price"] - current_price) * pos["quantity"]
            revenue = (pos["quantity"] * pos["entry_price"]) + profit
            
        self.balance_usdt += revenue
        exit_time = datetime.now()
        hold_secs = (exit_time - pos["entry_time"]).seconds

        update_trade_exit(pos["db_id"], exit_time, profit)
        pnl_str = f"+${profit:.2f}" if profit >= 0 else f"-${abs(profit):.2f}"
        
        log_trade("CLOSE", symbol, current_price, pos["quantity"],
                  f"{reason} | PnL: {pnl_str} | Held: {hold_secs}s", trade_id=pos["db_id"])

        save_portfolio_snapshot(self.balance_usdt, len(self.positions))
        
        emoji = "✅" if profit >= 0 else "❌"
        logger.info(f"{emoji} CLOSED {side} {symbol} at ${current_price:,.2f} | PnL: {pnl_str} | Held: {hold_secs}s | {reason}")
        
        return {
            "symbol": symbol, "side": side,
            "entry_price": pos["entry_price"], "exit_price": current_price,
            "hold_secs": hold_secs, "entry_reason": pos["entry_reason"],
            "pnl": profit,
        }


# ─────────────────────────────────────────
#  Self-Improving Engine v5 — Advanced Agent Suite
# ─────────────────────────────────────────
class TradingEngine:
    def __init__(self, client):
        self.client = client
        self.simulator = PaperTradingSimulator()
        self.runtime_ctx = get_runtime_context()
        self.allowed_symbols = set(config.BLUE_CHIP_WHITELIST)
        self.client.monitored_channels = list(self.allowed_symbols)
        
        history_size = int((config.MOMENTUM_WINDOW_MINS * 60) / config.POLL_INTERVAL_SECONDS)
        self.price_history = {symbol: deque(maxlen=history_size) for symbol in self.allowed_symbols}
        
        # Algorithmic tools
        self.algo_agents = [MomentumAgent(), SwingAgent()]
        self.trend_filter = TrendAgent()
        self.session_tracker = SessionTracker()
        
        # LLM agents
        self.llm_agent = None
        self.retro_agent = None
        self.meta_optimizer = None
        self.missed_analyzer = None
        try:
            self.llm_agent = LLMAgent()
            if self.llm_agent and self.llm_agent.ready:
                if self.llm_agent.provider == "BEDROCK" and self.llm_agent.bedrock:
                    if config.ENABLE_RETROSPECTIVE:
                        self.retro_agent = RetrospectiveAgent(self.llm_agent.bedrock)
                    if config.ENABLE_META_OPTIMIZER:
                        self.meta_optimizer = MetaOptimizer(self.llm_agent.bedrock)
                    if config.ENABLE_MISSED_OPPORTUNITY_ANALYZER:
                        self.missed_analyzer = MissedOpportunityAnalyzer(self.llm_agent.bedrock, config.BEDROCK_MODEL_ID)
                elif (
                    config.ENABLE_RETROSPECTIVE
                    or config.ENABLE_META_OPTIMIZER
                    or config.ENABLE_MISSED_OPPORTUNITY_ANALYZER
                ):
                    logger.warning(
                        "Retrospective/meta/missed-opportunity analyzers are Bedrock-only and were skipped "
                        f"for provider={self.llm_agent.provider}."
                    )
                logger.info(f"✅ Engine initialized with LLM provider={self.llm_agent.provider} (profit-first mode)")
            else:
                logger.error("LLM provider initialization failed.")
        except Exception as e:
            logger.error(f"Failed to load LLM: {e}")

        self.trades_executed = 0
        self.trades_closed = 0
        self.total_session_pnl = 0.0
        self.skipped_cycles = 0
        self.last_llm_call = None
        self.missed_opportunities_count = 0
        self.last_entry_prices: dict = {}      # symbol -> (price, side, timestamp)
        self.direction_block: dict = {}         # symbol -> {side, blocked_until}
        self.last_close_time = None             # Fix 5: post-close cooldown
        self.symbol_drift_alerted = set()
        self.consecutive_losses = 0
        self.trading_halted_reason = None
        self.session_start_balance = self.simulator.balance_usdt
        
        logger.info(f"Engine ready. Watching: {sorted(self.allowed_symbols)}")
        logger.info(f"  Stop-Loss: -{config.EARLY_STOP_LOSS_PCT*100:.2f}%  |  TP: +{config.TAKE_PROFIT_PCT*100:.2f}%  |  Trailing: +{config.TRAILING_STOP_TRIGGER_PCT*100:.2f}%")
        logger.info(f"  Position: ${config.MAX_POSITION_SIZE_USDT:,.0f}  |  LLM Throttle: {config.LLM_POLL_INTERVAL_SECONDS}s  |  Max Hold: {config.MANDATORY_EXIT_SECONDS}s")
        logger.info(
            f"  LLM budget/day: ${config.LLM_DAILY_BUDGET_USD:.2f} | "
            f"LLM max calls/hour: {config.LLM_MAX_CALLS_PER_HOUR} | "
            f"Max drawdown: ${config.MAX_DAILY_DRAWDOWN_USD:.2f}"
        )

    def _count_pro_signals(self, rsi_result, macd_result, bb_result, sr_result, candle_result,
                            stochrsi_result=None, ema_result=None, volmom_result=None) -> tuple:
        """Count how many pro tools give a BUY or SELL signal (up to 8 voters)."""
        buy_count = 0
        sell_count = 0

        buy_signals  = {"STRONG_BUY", "BUY", "BULLISH_CROSS", "BULLISH_ENGULFING", "HAMMER"}
        sell_signals = {"STRONG_SELL", "SELL", "BEARISH_CROSS", "BEARISH_ENGULFING", "SHOOTING_STAR"}

        # Original 5 voters
        for sig in [rsi_result.get("signal"), macd_result.get("crossover"), bb_result.get("signal")]:
            if sig in buy_signals: buy_count += 1
            elif sig in sell_signals: sell_count += 1

        if sr_result.get("signal") in ("BUY", "WATCH_BUY"): buy_count += 1
        elif sr_result.get("signal") in ("SELL", "WATCH_SELL"): sell_count += 1

        if candle_result.get("signal") == "BUY": buy_count += 1
        elif candle_result.get("signal") == "SELL": sell_count += 1

        # 3 new voters (v7)
        if stochrsi_result:
            sig = stochrsi_result.get("signal")
            if sig in buy_signals: buy_count += 1
            elif sig in sell_signals: sell_count += 1

        if ema_result:
            sig = ema_result.get("signal")
            if sig in buy_signals: buy_count += 1
            elif sig in sell_signals: sell_count += 1

        if volmom_result:
            sig = volmom_result.get("signal")
            if sig in buy_signals: buy_count += 1
            elif sig in sell_signals: sell_count += 1

        return buy_count, sell_count

    def _safe_tool_call(self, name: str, fn, fallback):
        try:
            out = fn()
            return fallback if out is None else out
        except Exception as e:
            logger.error(f"Tool failure ({name}): {e}")
            return fallback

    def _register_llm_usage(self, symbol: str, usage_events: list, context: str):
        for ev in usage_events or []:
            try:
                save_llm_usage(
                    stage=ev.get("stage", "unknown"),
                    model_id=ev.get("model_id", ""),
                    input_tokens=ev.get("input_tokens", 0),
                    output_tokens=ev.get("output_tokens", 0),
                    total_tokens=ev.get("total_tokens", 0),
                    latency_ms=ev.get("latency_ms", 0),
                    estimated_cost_usd=ev.get("estimated_cost_usd", 0.0),
                    symbol=symbol,
                    decision_context=context,
                )
            except Exception as e:
                logger.error(f"Failed to save llm_usage: {e}")

    def _sentiment_gate(self, symbol: str, proposed_dir: str):
        """
        Sentiment-aware entry gate.
        Returns: (allowed: bool, verdict: str)
        """
        if not config.ENABLE_SENTIMENT_GATE:
            return True, "Sentiment gate disabled"

        try:
            snapshot = build_sentiment_snapshot(
                alpha_key=config.ALPHAVANTAGE_API_KEY,
                cryptocompare_key=config.CRYPTOCOMPARE_API_KEY,
                symbol=symbol,
            )
            score = float(snapshot.get("sentiment_score", 0.0))
            label = str(snapshot.get("sentiment_label", "NEUTRAL"))
            components = snapshot.get("components", {}) or {}
            article_count = int(components.get("articles_count", 0) or 0)

            # If feed coverage is thin, do not hard-block entries.
            if article_count < config.SENTIMENT_MIN_ARTICLES:
                return True, f"Sentiment thin ({article_count} articles)"

            if abs(score) < config.SENTIMENT_MIN_ABS_SCORE:
                return False, f"Sentiment weak ({score:+.2f})"

            if proposed_dir == "LONG" and score < config.SENTIMENT_DIRECTIONAL_FLOOR:
                return False, f"Sentiment opposes LONG ({label} {score:+.2f})"

            if proposed_dir == "SHORT" and score > -config.SENTIMENT_DIRECTIONAL_FLOOR:
                return False, f"Sentiment opposes SHORT ({label} {score:+.2f})"

            return True, f"Sentiment supports {proposed_dir} ({label} {score:+.2f})"
        except Exception as e:
            logger.warning(f"Sentiment gate fallback: {e}")
            return True, "Sentiment unavailable (TA-only fallback)"

    def _llm_budget_ok(self) -> tuple:
        calls_last_hour = get_llm_call_count_last_hour()
        if calls_last_hour >= config.LLM_MAX_CALLS_PER_HOUR:
            return False, f"LLM hourly cap reached ({calls_last_hour}/{config.LLM_MAX_CALLS_PER_HOUR})"

        spend_today = get_llm_cost_today()
        if spend_today >= config.LLM_DAILY_BUDGET_USD:
            return False, f"LLM daily budget reached (${spend_today:.2f}/${config.LLM_DAILY_BUDGET_USD:.2f})"

        return True, ""

    def _estimate_expected_edge_pct(self, buy_count: int, sell_count: int, tp_pct: float, sl_pct: float) -> float:
        agreement = max(buy_count, sell_count)
        disagreement = min(buy_count, sell_count)
        quality = max(0.0, (agreement - disagreement) / 8.0)
        expected_move_pct = (tp_pct * 100) * max(0.5, quality + 0.3)
        risk_drag_pct = (sl_pct * 100) * (1.0 - quality)
        return expected_move_pct - risk_drag_pct - config.FEE_SLIPPAGE_BUFFER_PCT

    def _deterministic_decision(self, buy_count: int, sell_count: int) -> tuple:
        agreement = max(buy_count, sell_count)
        disagreement = min(buy_count, sell_count)
        margin = agreement - disagreement

        if agreement < 3:
            return "NEUTRAL", 0.0, "insufficient deterministic agreement"

        if buy_count > sell_count:
            action = "BUY"
        elif sell_count > buy_count:
            action = "SELL"
        else:
            return "NEUTRAL", 0.0, "conflicting deterministic votes"

        # Strong confluence bypasses LLM completely.
        if agreement >= 5 and margin >= 2:
            conf = min(0.92, 0.60 + (agreement * 0.05) + (margin * 0.03))
            return action, conf, "deterministic strong confluence"

        # Borderline setup: LLM tie-breaker allowed.
        conf = min(0.82, 0.50 + (agreement * 0.04) + (margin * 0.02))
        return action, conf, "deterministic borderline setup"

    def _check_kill_switch(self) -> tuple:
        drawdown = max(0.0, self.session_start_balance - self.simulator.balance_usdt)
        if drawdown >= config.MAX_DAILY_DRAWDOWN_USD:
            return True, f"Kill-switch: drawdown ${drawdown:.2f} >= ${config.MAX_DAILY_DRAWDOWN_USD:.2f}"

        spend_today = get_llm_cost_today()
        if spend_today >= config.LLM_DAILY_BUDGET_USD:
            return True, f"Kill-switch: LLM budget exceeded (${spend_today:.2f})"

        if self.consecutive_losses >= config.MAX_CONSECUTIVE_LOSSES:
            return True, f"Kill-switch: consecutive losses {self.consecutive_losses}"

        return False, ""

    async def _close_trade(self, symbol, current_price, reason):
        """Helper to close a position and run retrospective."""
        trade_result = self.simulator.exit_position(symbol, current_price, reason)
        if trade_result:
            self.total_session_pnl += trade_result["pnl"]
            self.trades_closed += 1
            self.session_tracker.record_trade(trade_result["pnl"])
            self.last_close_time = datetime.now()  # Fix 5: record close time for cooldown

            # ── Record for duplicate-entry guard ──
            self.last_entry_prices[symbol] = (
                trade_result["entry_price"], trade_result["side"], datetime.now()
            )

            # ── Direction block: if this is a loss, track consecutive losses per direction ──
            if trade_result["pnl"] <= 0:
                self.consecutive_losses += 1
                side = trade_result["side"]
                block_key = f"{symbol}_{side}"
                self._loss_streak = getattr(self, '_loss_streak', {})
                self._loss_streak[block_key] = self._loss_streak.get(block_key, 0) + 1
                if self._loss_streak[block_key] >= 2:
                    block_until = datetime.now() + timedelta(seconds=600)  # 10 min block
                    self.direction_block[symbol] = {"side": side, "blocked_until": block_until}
                    logger.warning(f"🚫 DIRECTION BLOCK: {side} on {symbol} for 10 min after {self._loss_streak[block_key]} consecutive losses")
                    self._loss_streak[block_key] = 0  # reset after block
            else:
                self.consecutive_losses = 0
                # Win — reset the loss streak for this symbol's direction
                side = trade_result["side"]
                block_key = f"{symbol}_{side}"
                self._loss_streak = getattr(self, '_loss_streak', {})
                self._loss_streak[block_key] = 0
                # Clear any direction block if we just won
                if self.direction_block.get(symbol, {}).get("side") == side:
                    self.direction_block.pop(symbol, None)

            if self.retro_agent:
                try:
                    update_intent(f"🔬 Analyzing trade #{self.trades_closed}...", [symbol])
                    self.retro_agent.analyze_trade(**trade_result)
                except Exception as e:
                    logger.error(f"Retro error: {e}")

    async def _periodic_self_improvement_loop(self):
        """
        Background loop: fires every PERIODIC_REVIEW_SECONDS or every
        PERIODIC_REVIEW_TRADES closed trades — whichever comes first.
        Calls run_mini_review() which: analyzes recent trades with Claude,
        saves new lessons, auto-tunes config, commits to GitHub.
        """
        if not config.ENABLE_PERIODIC_REVIEW:
            logger.info("⏸ Periodic self-improvement loop disabled (ENABLE_PERIODIC_REVIEW=false).")
            return

        from session_review import run_mini_review

        REVIEW_SECS   = getattr(config, 'PERIODIC_REVIEW_SECONDS', 600)   # 10 min
        REVIEW_TRADES = getattr(config, 'PERIODIC_REVIEW_TRADES', 5)

        last_reviewed_trade_id = 0
        last_review_time       = datetime.now()
        review_count           = 0
        last_closed_snapshot   = 0   # tracks trades_closed at last review

        logger.info(
            f"🔁 Periodic Self-Improvement Loop started "
            f"(every {REVIEW_SECS//60} min OR every {REVIEW_TRADES} trades)"
        )

        await asyncio.sleep(90)  # 90s warm-up before first check

        while True:
            try:
                await asyncio.sleep(60)   # Tick every 60 seconds

                if (
                    not self.llm_agent
                    or not self.llm_agent.ready
                    or self.llm_agent.provider != "BEDROCK"
                    or not self.llm_agent.bedrock
                ):
                    continue

                now             = datetime.now()
                secs_since      = (now - last_review_time).total_seconds()
                new_trades      = self.trades_closed - last_closed_snapshot

                # Progress log so the user can see it's alive
                logger.info(
                    f"🔁 Review check: {new_trades} new trades | "
                    f"{int(secs_since//60)}m{int(secs_since%60)}s elapsed "
                    f"(next at {REVIEW_TRADES} trades or {REVIEW_SECS//60}min)"
                )

                time_trigger   = secs_since >= REVIEW_SECS
                trades_trigger = new_trades >= REVIEW_TRADES

                if not (time_trigger or trades_trigger):
                    continue

                # Skip if a position is open — wait for clean state
                if self.simulator.positions:
                    logger.info("🔁 Review ready but position open — waiting for it to close...")
                    continue

                # ── Run the review ──────────────────────────────────────────
                review_count += 1
                trigger_reason = "time" if time_trigger and not trades_trigger else "trades"
                logger.info(f"\n{'='*60}")
                logger.info(f"🔁 PERIODIC SELF-IMPROVEMENT #{review_count} (triggered by {trigger_reason})")
                logger.info(f"   New trades since last review: {new_trades}")
                logger.info(f"   Time since last review:       {int(secs_since//60)} min {int(secs_since%60)}s")
                logger.info(f"{'='*60}")

                update_intent(
                    f"🔁 Running self-improvement #{review_count} "
                    f"({new_trades} new trades, {int(secs_since//60)}m elapsed)...",
                    []
                )

                try:
                    prev_reviewed_trade_id = last_reviewed_trade_id
                    new_id = run_mini_review(
                        bedrock_client=self.llm_agent.bedrock,
                        since_trade_id=last_reviewed_trade_id,
                        label=f"PERIODIC-{review_count}",
                        min_closed_trades=config.MIN_NEW_CLOSED_TRADES_FOR_REVIEW,
                    )
                    last_reviewed_trade_id = new_id
                    
                    # Re-distill only when explicitly enabled and enough new closed trades.
                    if config.ENABLE_DISTILLATION:
                        from distill_lessons import distill_all
                        distill_all(
                            since_trade_id=prev_reviewed_trade_id,
                            min_new_closed_trades=config.MIN_NEW_CLOSED_TRADES_FOR_DISTILLATION,
                        )
                    
                except Exception as e:
                    logger.error(f"Post-review improvement failed: {e}", exc_info=True)

                last_review_time     = now
                last_closed_snapshot = self.trades_closed

                if config.ENABLE_RUNTIME_CONFIG_AUTOTUNE:
                    # Reload config so any auto-tuned values take effect immediately.
                    try:
                        import importlib, config as cfg_module
                        importlib.reload(cfg_module)
                        from config import config as new_cfg
                        logger.info(
                            f"🔄 Config reloaded: conf={new_cfg.MIN_ENSEMBLE_CONFIDENCE} "
                            f"SL={new_cfg.EARLY_STOP_LOSS_PCT} TP={new_cfg.TAKE_PROFIT_PCT}"
                        )
                    except Exception as e:
                        logger.warning(f"Config reload failed: {e}")

            except asyncio.CancelledError:
                logger.info("🔁 Periodic self-improvement loop cancelled.")
                break
            except Exception as e:
                logger.error(f"Periodic review loop error: {e}", exc_info=True)
                await asyncio.sleep(30)   # short backoff, then retry

    async def run_loop(self):
        logger.info(f"Starting Session ({config.MAX_TRADES_RUN} trades max)...")
        primary_symbol = sorted(self.allowed_symbols)[0]
        
        # ── v7 Warmup: Fetch 1m historical klines to skip 35min wait ──
        for symbol in sorted(self.allowed_symbols):
            klines = self.client.get_historical_klines(symbol, interval='1m', limit=60)
            if klines:
                self.price_history[symbol].extend(klines)
                logger.info(f"📈 Pre-loaded {len(klines)} historical 1m ticks for {symbol}.")

        while self.trades_closed < config.MAX_TRADES_RUN:
            try:
                for symbol, price in self.client.latest_prices.items():
                    if symbol not in self.allowed_symbols:
                        if symbol not in self.symbol_drift_alerted:
                            self.symbol_drift_alerted.add(symbol)
                            logger.error(f"🚨 Symbol drift reached engine: {symbol} not in allowlist {sorted(self.allowed_symbols)}")
                        continue
                    if price > 0:
                        if symbol not in self.price_history:
                            self.price_history[symbol] = deque(
                                maxlen=int((config.MOMENTUM_WINDOW_MINS * 60) / config.POLL_INTERVAL_SECONDS)
                            )
                        self.price_history[symbol].append(price)

                min_ticks = 35  # Enough for MACD (26 periods + 9 signal)
                ticks_ready = len(self.price_history.get(primary_symbol, [])) if self.price_history else 0
                if ticks_ready < min_ticks:
                    update_intent(f"Warming up... ({ticks_ready}/{min_ticks} ticks)", [])
                    await asyncio.sleep(config.CHECK_INTERVAL_SECONDS)
                    continue

                prices = self.client.latest_prices

                kill, reason = self._check_kill_switch()
                if kill and not self.trading_halted_reason:
                    self.trading_halted_reason = reason
                    logger.error(reason)
                    update_intent(f"🛑 {reason}", [])

                # ── 1. Manage open positions ──────────────────────────────────
                for symbol in list(self.simulator.positions.keys()):
                    if symbol not in prices: continue

                    pos = self.simulator.positions[symbol]
                    current_price = prices[symbol]
                    hold_secs = (datetime.now() - pos["entry_time"]).seconds
                    entry = pos["entry_price"]

                    if pos["side"] == "LONG":
                        pnl_pct = (current_price - entry) / entry
                    else:
                        pnl_pct = (entry - current_price) / entry

                    if self.trading_halted_reason:
                        await self._close_trade(symbol, current_price, f"🛑 Kill-switch exit: {self.trading_halted_reason}")
                        continue

                    # Per-position dynamic SL/TP (set at entry from ATR, fallback to config)
                    sl_pct = pos.get("dynamic_sl", config.EARLY_STOP_LOSS_PCT)
                    tp_pct = pos.get("dynamic_tp", config.TAKE_PROFIT_PCT)

                    # Update peak PnL for trailing stop
                    if pnl_pct > pos["peak_pnl_pct"]:
                        pos["peak_pnl_pct"] = pnl_pct
                        if pnl_pct >= config.TRAILING_STOP_TRIGGER_PCT and not pos["trailing_active"]:
                            pos["trailing_active"] = True
                            logger.info(f"🔔 Trailing stop ACTIVATED for {symbol} (peak: {pnl_pct*100:+.3f}%)")

                    # ── v6: PYRAMID INTO WINNERS ──────────────────────────────
                    # At 50% of TP reached and signals still strong → add to position
                    pyramid_count = pos.get("pyramid_count", 0)
                    if (config.ENABLE_PYRAMIDING and pnl_pct >= tp_pct * 0.5 and pyramid_count < 2
                            and self.simulator.balance_usdt > 125):
                        # Quick signal check (no LLM needed here)
                        hist = list(self.price_history.get(symbol, []))
                        if len(hist) >= 30:
                            rsi_q = RSIAnalyzer.analyze(hist)
                            macd_q = MACDSignal.analyze(hist)
                            bb_q   = BollingerBands.analyze(hist, current_price)
                            sr_q   = SupportResistance.analyze(hist, current_price)
                            cp_q   = CandlePatterns.analyze(hist)
                            b_cnt, s_cnt = self._count_pro_signals(rsi_q, macd_q, bb_q, sr_q, cp_q)
                            signal_agrees = (pos["side"] == "LONG" and b_cnt >= 3) or \
                                            (pos["side"] == "SHORT" and s_cnt >= 3)
                            if signal_agrees:
                                add_usdt = int(pos.get("original_pos_usdt", 125) * 0.5)
                                add_usdt = min(add_usdt, int(self.simulator.balance_usdt * 0.15))
                                if add_usdt >= 60:
                                    self.simulator.enter_position(symbol, current_price, add_usdt,
                                                                   f"🔺 Pyramid #{pyramid_count+1}", side=pos["side"])
                                    pos["pyramid_count"] = pyramid_count + 1
                                    logger.info(f"🔺 PYRAMID #{pyramid_count+1}: Added ${add_usdt:,} to {pos['side']} {symbol} at {pnl_pct*100:+.2f}%")

                    # ── Fix 3: MINIMUM HOLD TIME (300s) ────────────────────
                    # Allow 1m candles enough time to breathe. Force 5m minimum.
                    min_hold_met = hold_secs >= 300

                    # ── TAKE PROFIT ──
                    if min_hold_met and pnl_pct >= tp_pct:
                        await self._close_trade(symbol, current_price, f"✅ Take-Profit ({pnl_pct*100:+.3f}%)")
                        continue

                    # ── TRAILING STOP ──
                    if min_hold_met and pos["trailing_active"]:
                        trail_stop = pos["peak_pnl_pct"] - config.TRAILING_STOP_OFFSET_PCT
                        if pnl_pct < trail_stop:
                            await self._close_trade(symbol, current_price, f"📉 Trailing Stop (peak: {pos['peak_pnl_pct']*100:+.3f}% → now: {pnl_pct*100:+.3f}%)")
                            continue

                    # ── EARLY STOP-LOSS ──
                    if min_hold_met and pnl_pct < -sl_pct:
                        await self._close_trade(symbol, current_price, f"⛔ Stop-Loss ({pnl_pct*100:.3f}%)")
                        continue

                    # ── TIME EXIT (always applies, ignores min hold) ──
                    if hold_secs >= config.MANDATORY_EXIT_SECONDS:
                        await self._close_trade(symbol, current_price, f"⏰ Time Exit ({config.MANDATORY_EXIT_SECONDS}s)")
                        continue

                    remaining = config.MANDATORY_EXIT_SECONDS - hold_secs
                    trailing_label = " | 🔔 TRAILING" if pos["trailing_active"] else ""
                    update_intent(
                        f"Holding {pos['side']} {symbol} | PnL: {pnl_pct*100:+.3f}% (SL:{sl_pct*100:.2f}%/TP:{tp_pct*100:.2f}%) | {remaining}s{trailing_label}",
                        [symbol]
                    )

                # ── 2. Enter new positions ────────────────────────────────────
                if len(self.simulator.positions) == 0 and self.trades_closed < config.MAX_TRADES_RUN:
                    if self.trading_halted_reason:
                        update_intent(f"🛑 Trading halted: {self.trading_halted_reason}", [])
                        break

                    for symbol in sorted(self.allowed_symbols):
                        current_price = prices.get(symbol, 0)
                        history = list(self.price_history[symbol])
                        meta = self.client.ticker_meta.get(symbol, {})
                        
                        if current_price <= 0 or len(history) < min_ticks:
                            continue

                        # ── RUN CORE TOOLS ─────────────────────────────────
                        vol_result = self._safe_tool_call(
                            "VolatilityScanner",
                            lambda: VolatilityScanner.analyze(history),
                            {"volatility_pct": 0.0, "verdict": "Tool error", "tradeable": False},
                        )
                        vol_prof = self._safe_tool_call(
                            "VolumeProfile",
                            lambda: VolumeProfile.analyze(meta),
                            {"volume_24h": 0.0, "spread_pct": 0.0, "verdict": "Tool error", "liquid": False},
                        )

                        # Dead market filter
                        if not vol_result["tradeable"] and not vol_prof.get("liquid", False):
                            self.skipped_cycles += 1
                            if self.skipped_cycles % 12 == 1:
                                update_intent(f"⏳ Market dead (vol: {vol_result['volatility_pct']:.4f}%). Skipped {self.skipped_cycles}x", [symbol])
                            continue

                        # ── v6: SESSION TIME FILTER ────────────────────────
                        session_filt = SessionTimeFilter.analyze()
                        min_pro_needed = session_filt["min_pro_signals"]
                        conf_multiplier = session_filt["confidence_multiplier"]

                        # ── RUN PRO TA TOOLS ───────────────────────────────
                        rsi_result = self._safe_tool_call(
                            "RSIAnalyzer",
                            lambda: RSIAnalyzer.analyze(history),
                            {"rsi": 50.0, "signal": "NEUTRAL", "verdict": "Tool error"},
                        )
                        macd_result = self._safe_tool_call(
                            "MACDSignal",
                            lambda: MACDSignal.analyze(history),
                            {"crossover": "NONE", "verdict": "Tool error"},
                        )
                        bb_result = self._safe_tool_call(
                            "BollingerBands",
                            lambda: BollingerBands.analyze(history, current_price),
                            {"position_pct": 50.0, "signal": "NEUTRAL", "verdict": "Tool error"},
                        )
                        sr_result = self._safe_tool_call(
                            "SupportResistance",
                            lambda: SupportResistance.analyze(history, current_price),
                            {"signal": "NEUTRAL", "verdict": "Tool error"},
                        )
                        candle_result = self._safe_tool_call(
                            "CandlePatterns",
                            lambda: CandlePatterns.analyze(history),
                            {"signal": "NEUTRAL", "verdict": "Tool error"},
                        )
                        # v7 new voters
                        stochrsi_result = self._safe_tool_call(
                            "StochasticRSI",
                            lambda: StochasticRSI.analyze(history),
                            {"signal": "NEUTRAL", "verdict": "Tool error"},
                        )
                        ema_result = self._safe_tool_call(
                            "EMACross",
                            lambda: EMACross.analyze(history),
                            {"signal": "NEUTRAL", "verdict": "Tool error"},
                        )
                        volmom_result = self._safe_tool_call(
                            "VolumeMomentum",
                            lambda: VolumeMomentum.analyze(history),
                            {"signal": "NEUTRAL", "verdict": "Tool error"},
                        )

                        buy_count, sell_count = self._count_pro_signals(
                            rsi_result, macd_result, bb_result, sr_result, candle_result,
                            stochrsi_result, ema_result, volmom_result
                        )

                        # ── OPPORTUNITY PRE-FILTER (session-adjusted signal bar) ─
                        if buy_count < min_pro_needed and sell_count < min_pro_needed:
                            self.skipped_cycles += 1
                            best = max(buy_count, sell_count)
                            if self.skipped_cycles % 6 == 1:
                                update_intent(
                                    f"⏳ Waiting for setup ({best}/{min_pro_needed} pro signals) [{session_filt['session']}]. RSI:{rsi_result['rsi']:.1f} | {macd_result['crossover']} | BB:{bb_result['position_pct']:.0f}%",
                                    [symbol]
                                )
                            if self.skipped_cycles % 3 == 0:
                                save_signal_event(symbol, current_price, buy_count, sell_count,
                                                  rsi_result['rsi'], macd_result['crossover'],
                                                  bb_result['position_pct'], 'SKIPPED')
                            continue

                        # ── Direction: 2+ signals for LONG, 2+ for SHORT ───
                        # Quality enforced by confidence floor (0.70) + duplicate blocker (120s)
                        if sell_count >= 2 and sell_count > buy_count:
                            proposed_dir = "SHORT"
                        elif buy_count >= 2 and buy_count >= sell_count:
                            proposed_dir = "LONG"
                        else:
                            self.skipped_cycles += 1
                            continue  # Not enough signals for either direction

                        # ── v6: MARKET REGIME FILTER ───────────────────────
                        regime_result = self._safe_tool_call(
                            "MarketRegimeDetector",
                            lambda: MarketRegimeDetector.analyze(history),
                            {"regime": "UNKNOWN", "trade_direction": "ANY", "strength": 0.0, "verdict": "Tool error"},
                        )
                        regime = regime_result["regime"]
                        allowed_dir   = regime_result["trade_direction"]

                        if regime == "CHOPPY":
                            update_intent(f"🌊 CHOPPY regime — skipping signal. {regime_result['verdict']}", [symbol])
                            continue

                        if allowed_dir not in ("ANY", proposed_dir):
                            update_intent(
                                f"🚫 Regime MISMATCH: {proposed_dir} rejected in {regime} market. {regime_result['verdict']}",
                                [symbol]
                            )
                            continue

                        # ── Sentiment Gate ─────────────────────────────────
                        sentiment_ok, sentiment_verdict = self._sentiment_gate(symbol, proposed_dir)
                        if not sentiment_ok:
                            self.skipped_cycles += 1
                            update_intent(f"📰 Sentiment reject: {sentiment_verdict}", [symbol])
                            save_signal_event(
                                symbol,
                                current_price,
                                buy_count,
                                sell_count,
                                rsi_result["rsi"],
                                macd_result["crossover"],
                                bb_result["position_pct"],
                                "SKIPPED",
                                decision_source="SENTIMENT_REJECT",
                                deterministic_action=proposed_dir,
                                deterministic_conf=max(buy_count, sell_count) / 8.0,
                            )
                            continue

                        # ── v6: ATR-BASED DYNAMIC STOPS ────────────────────
                        atr_result = self._safe_tool_call(
                            "ATRTracker",
                            lambda: ATRTracker.analyze(history),
                            {"stop_loss_pct": config.EARLY_STOP_LOSS_PCT, "take_profit_pct": config.TAKE_PROFIT_PCT, "verdict": "Tool error"},
                        )
                        dynamic_sl  = atr_result["stop_loss_pct"]
                        dynamic_tp  = atr_result["take_profit_pct"]

                        # ── v6: MULTI-TIMEFRAME CONFIRMATION ───────────────
                        mtf_result = self._safe_tool_call(
                            "MultiTimeframeConfirmer",
                            lambda: MultiTimeframeConfirmer.analyze(history, proposed_dir),
                            {"confirms": True, "htf_trend": "UNKNOWN", "verdict": "Tool error"},
                        )
                        if not mtf_result["confirms"] and mtf_result["htf_trend"] != "UNKNOWN":
                            update_intent(f"📊 HTF REJECT: {mtf_result['verdict']}", [symbol])
                            # Soft reject: add to miss count but don't hard-block
                            self.skipped_cycles += 1
                            continue

                        now = datetime.now()

                        # ── DIRECTION BLOCK ─────────────────────────────────
                        block = self.direction_block.get(symbol)
                        if block and block["side"] == proposed_dir and now < block["blocked_until"]:
                            remaining_block = int((block["blocked_until"] - now).total_seconds())
                            update_intent(f"🚫 {proposed_dir} BLOCKED ({remaining_block}s — consecutive losses)", [symbol])
                            continue

                        # ── POST-CLOSE COOLDOWN (300s) ─────────────────────
                        if self.last_close_time and (now - self.last_close_time).total_seconds() < 300:
                            remaining_cd = 300 - int((now - self.last_close_time).total_seconds())
                            if self.skipped_cycles % 3 == 0:
                                update_intent(f"⏸ Post-close cooldown: {remaining_cd}s remaining", [symbol])
                            continue

                        # ── HARD DUPLICATE BLOCKER ──────────────────────────
                        last_entry = self.last_entry_prices.get(symbol)
                        if last_entry:
                            last_price, last_side, last_time = last_entry
                            time_since = (now - last_time).total_seconds()
                            price_diff_pct = abs(current_price - last_price) / last_price
                            if time_since < 600:
                                update_intent(f"⏸ Entry blocked: {int(600 - time_since)}s lockout remaining", [symbol])
                                continue
                            if last_side == proposed_dir and price_diff_pct < 0.0015 and time_since < 1200:
                                update_intent(f"⏸ Duplicate blocked: {proposed_dir} only {price_diff_pct*100:.3f}% from last entry", [symbol])
                                continue

                        vel_result = self._safe_tool_call(
                            "PriceVelocity",
                            lambda: PriceVelocity.analyze(history, current_price),
                            {"velocity_30s": 0.0, "velocity_1m": 0.0, "velocity_5m": 0.0, "acceleration": "UNAVAILABLE"},
                        )
                        ob_result = self._safe_tool_call(
                            "OrderBookPressure",
                            lambda: OrderBookPressure.analyze(meta, current_price),
                            {"pressure": "UNKNOWN", "bias": 0.0},
                        )
                        session_stats = self.session_tracker.get_stats()

                        tool_outputs = [
                            {"name": "Market Regime", "data": f"{regime_result['verdict']} (strength: {regime_result['strength']})"},
                            {"name": "Market Sentiment", "data": sentiment_verdict},
                            {"name": "ATR Tracker", "data": atr_result["verdict"]},
                            {"name": "Multi-Timeframe", "data": mtf_result["verdict"]},
                            {"name": "Session Filter", "data": session_filt["verdict"]},
                            {"name": "Volatility Scanner", "data": f"Vol: {vol_result['volatility_pct']:.4f}% — {vol_result['verdict']}"},
                            {
                                "name": "Price Velocity",
                                "data": (
                                    f"30s: {vel_result.get('velocity_30s', 0.0):+.4f}% | "
                                    f"1m: {vel_result.get('velocity_1m', 0.0):+.4f}% | "
                                    f"5m: {vel_result.get('velocity_5m', 0.0):+.4f}% — "
                                    f"{vel_result.get('acceleration', 'UNAVAILABLE')}"
                                ),
                            },
                            {"name": "Volume Profile", "data": f"24h Vol: {vol_prof['volume_24h']} | Spread: {vol_prof['spread_pct']:.4f}% — {vol_prof['verdict']}"},
                            {"name": "Order Book Pressure", "data": f"{ob_result['pressure']} (bias: {ob_result['bias']:+.4f}%)"},
                            {"name": "RSI (14)", "data": rsi_result["verdict"], "signal": rsi_result["signal"]},
                            {"name": "MACD Signal", "data": macd_result["verdict"], "signal": macd_result["crossover"]},
                            {"name": "Bollinger Bands", "data": bb_result["verdict"], "signal": bb_result["signal"]},
                            {"name": "Support & Resistance", "data": sr_result["verdict"], "signal": sr_result.get("signal", "NEUTRAL")},
                            {"name": "Candle Patterns", "data": candle_result["verdict"], "signal": candle_result["signal"]},
                            {"name": "Stochastic RSI", "data": stochrsi_result["verdict"], "signal": stochrsi_result["signal"]},
                            {"name": "EMA Cross (9/21)", "data": ema_result["verdict"], "signal": ema_result["signal"]},
                            {"name": "Volume Momentum", "data": volmom_result["verdict"], "signal": volmom_result["signal"]},
                        ]
                        for agent in self.algo_agents:
                            sig = self._safe_tool_call(
                                agent.name,
                                lambda a=agent: a.analyze(symbol, current_price, history, meta),
                                None,
                            )
                            if sig:
                                tool_outputs.append(
                                    {
                                        "name": agent.name,
                                        "data": f"{sig.action} (conf: {sig.confidence:.2f}) — {sig.reason}",
                                    }
                                )
                        trend_sig = self.trend_filter.analyze(symbol, current_price, history, meta)
                        tool_outputs.append({"name": "Trend Filter", "data": f"{trend_sig.action} — {trend_sig.reason}"})
                        tool_outputs.append(
                            {
                                "name": "Session Performance",
                                "data": (
                                    f"WR: {session_stats['win_rate']} | Streak: {session_stats['streak']} | "
                                    f"PnL: ${session_stats['cumulative_pnl']} — {session_stats['recommendation']}"
                                ),
                            }
                        )

                        det_action, det_conf, det_reason = self._deterministic_decision(buy_count, sell_count)
                        if det_action == "NEUTRAL":
                            self.skipped_cycles += 1
                            continue

                        expected_edge_pct = self._estimate_expected_edge_pct(buy_count, sell_count, dynamic_tp, dynamic_sl)
                        if expected_edge_pct < config.MIN_EXPECTED_EDGE_PCT:
                            self.skipped_cycles += 1
                            save_signal_event(
                                symbol,
                                current_price,
                                buy_count,
                                sell_count,
                                rsi_result["rsi"],
                                macd_result["crossover"],
                                bb_result["position_pct"],
                                "SKIPPED",
                                decision_source="EDGE_REJECT",
                                deterministic_action="LONG" if det_action == "BUY" else "SHORT",
                                deterministic_conf=det_conf,
                            )
                            continue

                        llm_signal = None
                        llm_cost = 0.0
                        llm_tokens = 0
                        decision_source = "DETERMINISTIC"
                        final_action = det_action
                        final_conf = det_conf
                        final_reason = f"Deterministic: {det_reason}"

                        borderline_setup = det_conf < 0.75 or max(buy_count, sell_count) <= 4
                        if borderline_setup:
                            llm_ok, llm_reason = self._llm_budget_ok()
                            if not llm_ok:
                                self.skipped_cycles += 1
                                update_intent(f"⏳ LLM blocked: {llm_reason}", [symbol])
                                continue

                            if self.last_llm_call and (now - self.last_llm_call).total_seconds() < config.LLM_POLL_INTERVAL_SECONDS:
                                wait_left = int(config.LLM_POLL_INTERVAL_SECONDS - (now - self.last_llm_call).total_seconds())
                                if self.skipped_cycles % 2 == 0:
                                    update_intent(
                                        f"⚡ Borderline setup {proposed_dir} ({buy_count}B/{sell_count}S) | LLM in {wait_left}s...",
                                        [symbol],
                                    )
                                continue

                            if not self.llm_agent:
                                self.skipped_cycles += 1
                                continue

                            self.last_llm_call = now
                            llm_signal = self.llm_agent.analyze_with_tools(
                                symbol,
                                current_price,
                                history,
                                meta,
                                tool_outputs,
                                buy_count=buy_count,
                                sell_count=sell_count,
                                regime=regime,
                                rsi=rsi_result["rsi"],
                                macd=macd_result["crossover"],
                                bb_pct=bb_result["position_pct"],
                            )
                            usage_events = (llm_signal.meta or {}).get("llm_usage", [])
                            self._register_llm_usage(symbol, usage_events, context=f"{buy_count}B/{sell_count}S|{regime}")
                            llm_cost = sum(ev.get("estimated_cost_usd", 0.0) for ev in usage_events)
                            llm_tokens = int(sum(ev.get("total_tokens", 0) for ev in usage_events))

                            effective_conf = (llm_signal.confidence if llm_signal else 0.0) * conf_multiplier
                            confidence_floor = 0.70
                            if (
                                not llm_signal
                                or llm_signal.action == "NEUTRAL"
                                or llm_signal.confidence < confidence_floor
                                or effective_conf < config.MIN_ENSEMBLE_CONFIDENCE
                            ):
                                self.skipped_cycles += 1
                                conf = llm_signal.confidence if llm_signal else 0.0
                                action = llm_signal.action if llm_signal else "NEUTRAL"
                                save_signal_event(
                                    symbol,
                                    current_price,
                                    buy_count,
                                    sell_count,
                                    rsi_result["rsi"],
                                    macd_result["crossover"],
                                    bb_result["position_pct"],
                                    "MISSED",
                                    claude_action=action,
                                    claude_conf=conf,
                                    decision_source="LLM_REJECT",
                                    deterministic_action="LONG" if det_action == "BUY" else "SHORT",
                                    deterministic_conf=det_conf,
                                    llm_cost_usd=llm_cost,
                                    llm_tokens=llm_tokens,
                                )
                                self.missed_opportunities_count += 1
                                if (
                                    config.ENABLE_MISSED_OPPORTUNITY_ANALYZER
                                    and self.missed_opportunities_count % 5 == 0
                                    and hasattr(self, "missed_analyzer")
                                    and self.missed_analyzer
                                ):
                                    try:
                                        logger.info(f"🔍 Running MissedOpportunityAnalyzer ({self.missed_opportunities_count} misses)...")
                                        self.missed_analyzer.analyze(symbol)
                                    except Exception as e:
                                        logger.error(f"MissedOpportunityAnalyzer error: {e}")
                                continue

                            decision_source = "LLM_TIEBREAKER"
                            final_action = llm_signal.action
                            final_conf = llm_signal.confidence
                            final_reason = llm_signal.reason

                        # ── Position sizing (risk-capped) ──────────────────
                        base_conf = final_conf
                        if base_conf >= 0.80:
                            pos_usdt = 250
                        elif base_conf >= 0.70:
                            pos_usdt = 200
                        elif base_conf >= 0.60:
                            pos_usdt = 160
                        else:
                            pos_usdt = 125

                        if self.consecutive_losses >= 2:
                            pos_usdt = int(pos_usdt * 0.7)
                            logger.info(f"📉 Risk cut: position shrunk to ${pos_usdt:,} (loss streak)")

                        max_by_risk = int(self.simulator.balance_usdt * config.MAX_RISK_PER_TRADE_PCT_BALANCE)
                        min_pos = int(config.MIN_POSITION_SIZE_USDT)
                        if max_by_risk < min_pos:
                            self.skipped_cycles += 1
                            continue
                        pos_usdt = max(min_pos, min(pos_usdt, max_by_risk, int(self.simulator.balance_usdt)))
                        pos_usdt = min(pos_usdt, int(config.MAX_POSITION_SIZE_USDT))
                        if pos_usdt < min_pos:
                            self.skipped_cycles += 1
                            continue

                        side = "LONG" if final_action == "BUY" else "SHORT"
                        reason = (
                            f"{decision_source}({final_conf:.2f}) | {buy_count}B/{sell_count}S | "
                            f"{regime} | {session_filt['session']} | {sentiment_verdict} | Edge:{expected_edge_pct:+.3f}% | "
                            f"ATR-SL:{dynamic_sl*100:.2f}%/TP:{dynamic_tp*100:.2f}% | {final_reason}"
                        )

                        self.trades_executed += 1
                        self.skipped_cycles = 0
                        update_intent(
                            f"🎯 Trade #{self.trades_executed}: {side} ${pos_usdt:,} | conf:{final_conf:.2f} | {decision_source}",
                            [symbol],
                        )
                        self.simulator.enter_position(
                            symbol,
                            current_price,
                            pos_usdt,
                            reason,
                            side=side,
                            decision_source=decision_source,
                            deterministic_conf=det_conf,
                            llm_conf=final_conf if decision_source == "LLM_TIEBREAKER" else None,
                            llm_cost_usd=llm_cost if decision_source == "LLM_TIEBREAKER" else 0.0,
                        )

                        if symbol in self.simulator.positions:
                            self.simulator.positions[symbol]["dynamic_sl"] = dynamic_sl
                            self.simulator.positions[symbol]["dynamic_tp"] = dynamic_tp
                            self.simulator.positions[symbol]["pyramid_count"] = 0
                            self.simulator.positions[symbol]["original_pos_usdt"] = pos_usdt

                        save_signal_event(
                            symbol,
                            current_price,
                            buy_count,
                            sell_count,
                            rsi_result["rsi"],
                            macd_result["crossover"],
                            bb_result["position_pct"],
                            "TRADED",
                            claude_action=side if decision_source == "LLM_TIEBREAKER" else None,
                            claude_conf=final_conf if decision_source == "LLM_TIEBREAKER" else None,
                            decision_source=decision_source,
                            deterministic_action="LONG" if det_action == "BUY" else "SHORT",
                            deterministic_conf=det_conf,
                            llm_cost_usd=llm_cost,
                            llm_tokens=llm_tokens,
                        )
                        break
                        
            except Exception as e:
                logger.error(f"Engine error: {e}", exc_info=True)

            await asyncio.sleep(config.CHECK_INTERVAL_SECONDS)

        # ── Session Complete ─────────────────────────────────────────────────────
        logger.info(f"🏁 Session Complete! {self.trades_closed} trades.")
        logger.info(f"💰 Net PnL: ${self.total_session_pnl:,.2f}")
        logger.info(f"💼 Final Balance: ${self.simulator.balance_usdt:,.2f}")
        
        # ── 1. Meta-Optimizer (synthesises golden rules from lessons) ──
        if self.meta_optimizer and config.ENABLE_META_OPTIMIZER:
            try:
                self.meta_optimizer.optimize()
            except Exception as e:
                logger.error(f"Meta-Optimizer error: {e}")

        # ── 2. Full Session Post-Mortem (deep LLM analysis + auto config tuning) ──
        if config.ENABLE_END_OF_SESSION_REVIEW:
            try:
                logger.info("🔬 Running session post-mortem analysis...")
                update_intent("🔬 Session post-mortem: Claude reviewing all trades and missed opportunities...", [])
                from session_review import run_review
                run_review()
            except Exception as e:
                logger.error(f"Session post-mortem error: {e}")
        
        update_intent(f"Done. {self.trades_closed} trades. PnL: ${self.total_session_pnl:,.2f}. Run 'python3 reset_session.py' to start fresh.", [])
        sys.exit(0)
