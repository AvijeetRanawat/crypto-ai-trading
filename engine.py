import asyncio
from datetime import datetime, timedelta
from collections import deque
from logger import logger, log_trade
from config import config
from database import save_trade, update_trade_exit, save_portfolio_snapshot, update_intent, save_signal_event

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
)
import sys

# ─────────────────────────────────────────
#  Paper Trading Simulator
# ─────────────────────────────────────────
class PaperTradingSimulator:
    def __init__(self):
        self.balance_usdt = 1_250.0
        self.positions = {}

    def enter_position(self, symbol, price, amount_usdt, reason, side="LONG"):
        if self.balance_usdt < amount_usdt:
            logger.warning(f"Insufficient balance for {symbol}")
            return False

        quantity = amount_usdt / price
        self.balance_usdt -= amount_usdt
        entry_time = datetime.now()
        
        db_id = save_trade(symbol, side, price, quantity, entry_time, reason)

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
        self.client.monitored_channels = config.BLUE_CHIP_WHITELIST
        
        history_size = int((config.MOMENTUM_WINDOW_MINS * 60) / config.POLL_INTERVAL_SECONDS)
        self.price_history = {symbol: deque(maxlen=history_size) for symbol in config.BLUE_CHIP_WHITELIST}
        
        # Algorithmic tools
        self.algo_agents = [MomentumAgent(), SwingAgent()]
        self.trend_filter = TrendAgent()
        self.session_tracker = SessionTracker()
        
        # LLM agents
        self.llm_agent = None
        self.retro_agent = None
        self.meta_optimizer = None
        try:
            self.llm_agent = LLMAgent()
            if self.llm_agent.bedrock:
                self.retro_agent = RetrospectiveAgent(self.llm_agent.bedrock)
                self.meta_optimizer = MetaOptimizer(self.llm_agent.bedrock)
                self.missed_analyzer = MissedOpportunityAnalyzer(self.llm_agent.bedrock, config.BEDROCK_MODEL_ID)
                logger.info("✅ Engine v5: LLM + Retro + Meta-Optimizer + MissedOpportunityAnalyzer + 10 Tools")
            else:
                logger.error("Bedrock failed.")
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
        
        logger.info(f"Engine v5 ready. Watching: {config.BLUE_CHIP_WHITELIST}")
        logger.info(f"  Stop-Loss: -{config.EARLY_STOP_LOSS_PCT*100:.2f}%  |  TP: +{config.TAKE_PROFIT_PCT*100:.2f}%  |  Trailing: +{config.TRAILING_STOP_TRIGGER_PCT*100:.2f}%")
        logger.info(f"  Position: ${config.MAX_POSITION_SIZE_USDT:,.0f}  |  LLM Throttle: {config.LLM_POLL_INTERVAL_SECONDS}s  |  Max Hold: {config.MANDATORY_EXIT_SECONDS}s")

    def _count_pro_signals(self, rsi_result, macd_result, bb_result, sr_result, candle_result) -> tuple:
        """Count how many pro tools are giving a BUY or SELL signal."""
        buy_count = 0
        sell_count = 0
        
        buy_signals  = {"STRONG_BUY", "BUY", "BULLISH_CROSS", "BULLISH_ENGULFING", "HAMMER"}
        sell_signals = {"STRONG_SELL", "SELL", "BEARISH_CROSS", "BEARISH_ENGULFING", "SHOOTING_STAR"}
        
        for sig in [rsi_result.get("signal"), macd_result.get("crossover"), bb_result.get("signal")]:
            if sig in buy_signals: buy_count += 1
            elif sig in sell_signals: sell_count += 1

        if sr_result.get("signal") in ("BUY", "WATCH_BUY"): buy_count += 1
        elif sr_result.get("signal") in ("SELL", "WATCH_SELL"): sell_count += 1

        if candle_result.get("signal") == "BUY": buy_count += 1
        elif candle_result.get("signal") == "SELL": sell_count += 1

        return buy_count, sell_count

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

                if not self.llm_agent or not self.llm_agent.bedrock:
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
                    new_id = run_mini_review(
                        bedrock_client=self.llm_agent.bedrock,
                        since_trade_id=last_reviewed_trade_id,
                        label=f"PERIODIC-{review_count}",
                    )
                    last_reviewed_trade_id = new_id
                except Exception as e:
                    logger.error(f"run_mini_review failed: {e}", exc_info=True)

                last_review_time     = now
                last_closed_snapshot = self.trades_closed

                # Reload config so any auto-tuned values take effect immediately
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
        
        while self.trades_closed < config.MAX_TRADES_RUN:
            try:
                for symbol, price in self.client.latest_prices.items():
                    if price > 0:
                        self.price_history[symbol].append(price)

                min_ticks = 35  # Enough for MACD (26 periods + 9 signal)
                ticks_ready = len(self.price_history[config.BLUE_CHIP_WHITELIST[0]]) if self.price_history else 0
                if ticks_ready < min_ticks:
                    update_intent(f"Warming up... ({ticks_ready}/{min_ticks} ticks)", [])
                    await asyncio.sleep(config.CHECK_INTERVAL_SECONDS)
                    continue

                prices = self.client.latest_prices

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
                    if (pnl_pct >= tp_pct * 0.5 and pyramid_count < 2
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

                    # ── Fix 3: MINIMUM HOLD TIME (45s) ────────────────────
                    # Trades held <30s had 13% WR — pure noise. Force 45s minimum.
                    min_hold_met = hold_secs >= 45

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
                    for symbol in config.BLUE_CHIP_WHITELIST:
                        current_price = prices.get(symbol, 0)
                        history = list(self.price_history[symbol])
                        meta = self.client.ticker_meta.get(symbol, {})
                        
                        if current_price <= 0 or len(history) < min_ticks:
                            continue

                        # ── RUN CORE TOOLS ─────────────────────────────────
                        vol_result  = VolatilityScanner.analyze(history)
                        vol_prof    = VolumeProfile.analyze(meta)

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
                        rsi_result    = RSIAnalyzer.analyze(history)
                        macd_result   = MACDSignal.analyze(history)
                        bb_result     = BollingerBands.analyze(history, current_price)
                        sr_result     = SupportResistance.analyze(history, current_price)
                        candle_result = CandlePatterns.analyze(history)

                        buy_count, sell_count = self._count_pro_signals(
                            rsi_result, macd_result, bb_result, sr_result, candle_result
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
                        regime_result = MarketRegimeDetector.analyze(history)
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

                        # ── v6: ATR-BASED DYNAMIC STOPS ────────────────────
                        atr_result = ATRTracker.analyze(history)
                        dynamic_sl  = atr_result["stop_loss_pct"]
                        dynamic_tp  = atr_result["take_profit_pct"]

                        # ── v6: MULTI-TIMEFRAME CONFIRMATION ───────────────
                        mtf_result = MultiTimeframeConfirmer.analyze(history, proposed_dir)
                        if not mtf_result["confirms"] and mtf_result["htf_trend"] != "UNKNOWN":
                            update_intent(f"📊 HTF REJECT: {mtf_result['verdict']}", [symbol])
                            # Soft reject: add to miss count but don't hard-block
                            self.skipped_cycles += 1
                            continue

                        # ── LLM THROTTLE ───────────────────────────────────
                        now = datetime.now()
                        if self.last_llm_call and (now - self.last_llm_call).total_seconds() < config.LLM_POLL_INTERVAL_SECONDS:
                            wait_left = int(config.LLM_POLL_INTERVAL_SECONDS - (now - self.last_llm_call).total_seconds())
                            if self.skipped_cycles % 2 == 0:
                                update_intent(
                                    f"⚡ SETUP: {proposed_dir} ({buy_count if proposed_dir=='LONG' else sell_count}/5) | {regime} | LLM in {wait_left}s...",
                                    [symbol]
                                )
                            continue

                        # ── DIRECTION BLOCK ─────────────────────────────────
                        block = self.direction_block.get(symbol)
                        if block and block["side"] == proposed_dir and now < block["blocked_until"]:
                            remaining_block = int((block["blocked_until"] - now).total_seconds())
                            update_intent(f"🚫 {proposed_dir} BLOCKED ({remaining_block}s — consecutive losses)", [symbol])
                            continue

                        # ── Fix 5: POST-CLOSE COOLDOWN (60s) ───────────────
                        if self.last_close_time and (now - self.last_close_time).total_seconds() < 60:
                            remaining_cd = 60 - int((now - self.last_close_time).total_seconds())
                            if self.skipped_cycles % 3 == 0:
                                update_intent(f"⏸ Post-close cooldown: {remaining_cd}s remaining", [symbol])
                            continue

                        # ── Fix 1: HARD DUPLICATE BLOCKER ──────────────────
                        # Old: $500 threshold (0.008% of BTC = useless). 140 dupes lost $1,428.
                        # New: 120s lockout + 0.15% relative price threshold
                        last_entry = self.last_entry_prices.get(symbol)
                        if last_entry:
                            last_price, last_side, last_time = last_entry
                            time_since = (now - last_time).total_seconds()
                            price_diff_pct = abs(current_price - last_price) / last_price
                            # Hard time lock: no entry within 120s of last entry (any direction)
                            if time_since < 120:
                                update_intent(f"⏸ Entry blocked: {int(120 - time_since)}s lockout remaining", [symbol])
                                continue
                            # Same-direction price proximity: block if within 0.15%
                            if last_side == proposed_dir and price_diff_pct < 0.0015 and time_since < 600:
                                update_intent(f"⏸ Duplicate blocked: {proposed_dir} only {price_diff_pct*100:.3f}% from last entry", [symbol])
                                continue

                        # ── ALL TOOLS FOR CLAUDE ────────────────────────────
                        vel_result    = PriceVelocity.analyze(history, current_price)
                        ob_result     = OrderBookPressure.analyze(meta, current_price)
                        session_stats = self.session_tracker.get_stats()

                        tool_outputs = [
                            {"name": "Market Regime",
                             "data": f"{regime_result['verdict']} (strength: {regime_result['strength']})"},
                            {"name": "ATR Tracker",
                             "data": atr_result['verdict']},
                            {"name": "Multi-Timeframe",
                             "data": mtf_result['verdict']},
                            {"name": "Session Filter",
                             "data": session_filt['verdict']},
                            {"name": "Volatility Scanner",
                             "data": f"Vol: {vol_result['volatility_pct']:.4f}% — {vol_result['verdict']}"},
                            {"name": "Price Velocity",
                             "data": f"30s: {vel_result['velocity_30s']:+.4f}% | 1m: {vel_result['velocity_1m']:+.4f}% | 5m: {vel_result['velocity_5m']:+.4f}% — {vel_result['acceleration']}"},
                            {"name": "Volume Profile",
                             "data": f"24h Vol: {vol_prof['volume_24h']} | Spread: {vol_prof['spread_pct']:.4f}% — {vol_prof['verdict']}"},
                            {"name": "Order Book Pressure",
                             "data": f"{ob_result['pressure']} (bias: {ob_result['bias']:+.4f}%)"},
                            {"name": "RSI (14)",
                             "data": rsi_result['verdict'], "signal": rsi_result["signal"]},
                            {"name": "MACD Signal",
                             "data": macd_result['verdict'], "signal": macd_result["crossover"]},
                            {"name": "Bollinger Bands",
                             "data": bb_result['verdict'], "signal": bb_result["signal"]},
                            {"name": "Support & Resistance",
                             "data": sr_result['verdict'], "signal": sr_result.get("signal", "NEUTRAL")},
                            {"name": "Candle Patterns",
                             "data": candle_result['verdict'], "signal": candle_result["signal"]},
                        ]
                        for agent in self.algo_agents:
                            sig = agent.analyze(symbol, current_price, history, meta)
                            tool_outputs.append({"name": agent.name,
                                                 "data": f"{sig.action} (conf: {sig.confidence:.2f}) — {sig.reason}"})
                        trend_sig = self.trend_filter.analyze(symbol, current_price, history, meta)
                        tool_outputs.append({"name": "Trend Filter",
                                             "data": f"{trend_sig.action} — {trend_sig.reason}"})
                        tool_outputs.append({"name": "Session Performance",
                                             "data": f"WR: {session_stats['win_rate']} | Streak: {session_stats['streak']} | PnL: ${session_stats['cumulative_pnl']} — {session_stats['recommendation']}"})

                        # ── CLAUDE MAKES THE FINAL CALL ──────────────────
                        self.last_llm_call = now
                        logger.info(f"⚡ SETUP: {proposed_dir} ({buy_count}B/{sell_count}S) | {regime} | {session_filt['session']} | ATR-SL:{dynamic_sl*100:.2f}% TP:{dynamic_tp*100:.2f}% | Sending to Claude...")

                        if self.llm_agent:
                            llm_signal = self.llm_agent.analyze_with_tools(
                                symbol, current_price, history, meta, tool_outputs,
                                buy_count=buy_count, sell_count=sell_count,
                                regime=regime,
                                rsi=rsi_result['rsi'],
                                macd=macd_result['crossover'],
                                bb_pct=bb_result['position_pct'],
                            )
                        else:
                            continue

                        # ── EFFECTIVE CONFIDENCE: session-adjusted ─────────
                        effective_conf = (llm_signal.confidence if llm_signal else 0.0) * conf_multiplier

                        # ── Fix 2: CONFIDENCE FLOOR = 0.70 ────────────────
                        # Below 0.70: 202 trades at 28-36% WR, lost $3,583 total
                        CONFIDENCE_FLOOR = 0.70

                        if not llm_signal or llm_signal.action == "NEUTRAL" or llm_signal.confidence < CONFIDENCE_FLOOR or effective_conf < config.MIN_ENSEMBLE_CONFIDENCE:
                            self.skipped_cycles += 1
                            conf = llm_signal.confidence if llm_signal else 0
                            action = llm_signal.action if llm_signal else "NEUTRAL"
                            reject_reason = ""
                            if llm_signal and llm_signal.confidence < CONFIDENCE_FLOOR and llm_signal.action != "NEUTRAL":
                                reject_reason = f" | 🚫 CONF FLOOR: {conf:.2f} < {CONFIDENCE_FLOOR}"
                            if self.skipped_cycles % 3 == 1:
                                update_intent(f"⏳ Claude passed (raw:{conf:.2f} adj:{effective_conf:.2f}){reject_reason}. Skipped {self.skipped_cycles}x", [symbol])
                            save_signal_event(symbol, current_price, buy_count, sell_count,
                                              rsi_result['rsi'], macd_result['crossover'],
                                              bb_result['position_pct'], 'MISSED',
                                              claude_action=action, claude_conf=conf)
                            self.missed_opportunities_count += 1
                            if self.missed_opportunities_count % 5 == 0 and hasattr(self, 'missed_analyzer') and self.missed_analyzer:
                                try:
                                    logger.info(f"🔍 Running MissedOpportunityAnalyzer ({self.missed_opportunities_count} misses)...")
                                    self.missed_analyzer.analyze(symbol)
                                except Exception as e:
                                    logger.error(f"MissedOpportunityAnalyzer error: {e}")
                            continue

                        # ── v6: CONFIDENCE-SCALED + KELLY POSITION SIZING ──
                        # Base sizing: 10k-28k based on confidence; Kelly fraction reduces after losses
                        base_conf = llm_signal.confidence
                        if base_conf >= 0.80:
                            pos_usdt = 350
                        elif base_conf >= 0.65:
                            pos_usdt = 250
                        elif base_conf >= 0.50:
                            pos_usdt = 160
                        else:
                            pos_usdt = 125

                        # Kelly adjustment: shrink after losing streaks
                        streak_info = session_stats.get('streak', '')
                        if 'LOSS' in str(streak_info) and any(str(n) in str(streak_info) for n in ['2','3','4','5']):
                            pos_usdt = int(pos_usdt * 0.7)   # 30% reduction on losing streak
                            logger.info(f"📉 Kelly: position shrunk to ${pos_usdt:,} (loss streak)")

                        pos_usdt = max(125, min(pos_usdt, int(self.simulator.balance_usdt * 0.30)))  # never > 30% balance

                        # ── EXECUTE ─────────────────────────────────────────
                        side = "LONG" if llm_signal.action == "BUY" else "SHORT"
                        reason = (f"Claude({llm_signal.confidence:.2f} adj:{effective_conf:.2f}) | "
                                  f"{buy_count}B/{sell_count}S | {regime} | {session_filt['session']} | "
                                  f"ATR-SL:{dynamic_sl*100:.2f}%/TP:{dynamic_tp*100:.2f}% | {llm_signal.reason}")

                        self.trades_executed += 1
                        self.skipped_cycles = 0
                        update_intent(f"🎯 Trade #{self.trades_executed}: {side} ${pos_usdt:,} | conf:{llm_signal.confidence:.2f} | {reason}", [symbol])
                        self.simulator.enter_position(symbol, current_price, pos_usdt, reason, side=side)

                        # Store dynamic stops in position for use in management
                        if symbol in self.simulator.positions:
                            self.simulator.positions[symbol]["dynamic_sl"] = dynamic_sl
                            self.simulator.positions[symbol]["dynamic_tp"] = dynamic_tp
                            self.simulator.positions[symbol]["pyramid_count"] = 0
                            self.simulator.positions[symbol]["original_pos_usdt"] = pos_usdt

                        save_signal_event(symbol, current_price, buy_count, sell_count,
                                          rsi_result['rsi'], macd_result['crossover'],
                                          bb_result['position_pct'], 'TRADED',
                                          claude_action=side, claude_conf=llm_signal.confidence)
                        break
                        
            except Exception as e:
                logger.error(f"Engine error: {e}", exc_info=True)

            await asyncio.sleep(config.CHECK_INTERVAL_SECONDS)

        # ── Session Complete ─────────────────────────────────────────────────────
        logger.info(f"🏁 Session Complete! {self.trades_closed} trades.")
        logger.info(f"💰 Net PnL: ${self.total_session_pnl:,.2f}")
        logger.info(f"💼 Final Balance: ${self.simulator.balance_usdt:,.2f}")
        
        # ── 1. Meta-Optimizer (synthesises golden rules from lessons) ──
        if self.meta_optimizer:
            try:
                self.meta_optimizer.optimize()
            except Exception as e:
                logger.error(f"Meta-Optimizer error: {e}")

        # ── 2. Full Session Post-Mortem (deep LLM analysis + auto config tuning) ──
        try:
            logger.info("🔬 Running session post-mortem analysis...")
            update_intent("🔬 Session post-mortem: Claude reviewing all trades and missed opportunities...", [])
            from session_review import run_review
            run_review()
        except Exception as e:
            logger.error(f"Session post-mortem error: {e}")
        
        update_intent(f"Done. {self.trades_closed} trades. PnL: ${self.total_session_pnl:,.2f}. Run 'python3 reset_session.py' to start fresh.", [])
        sys.exit(0)
