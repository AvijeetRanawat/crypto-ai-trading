import asyncio
from datetime import datetime, timedelta
from collections import deque
from logger import logger, log_trade
from config import config
from database import save_trade, update_trade_exit, save_portfolio_snapshot, save_lesson, update_intent, save_signal_event

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
)
import sys

# ─────────────────────────────────────────
#  Paper Trading Simulator
# ─────────────────────────────────────────
class PaperTradingSimulator:
    def __init__(self):
        self.balance_inr = 100_000.0
        self.positions = {}

    def enter_position(self, symbol, price, amount_inr, reason, side="LONG"):
        if self.balance_inr < amount_inr:
            logger.warning(f"Insufficient balance for {symbol}")
            return False

        quantity = amount_inr / price
        self.balance_inr -= amount_inr
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
        save_portfolio_snapshot(self.balance_inr, len(self.positions))
        
        emoji = "📈" if side == "LONG" else "📉"
        logger.info(f"{emoji} {side}: {symbol} at ₹{price:,.2f} | Size: ₹{amount_inr:,.0f} | Bal: ₹{self.balance_inr:,.0f}")
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
            
        self.balance_inr += revenue
        exit_time = datetime.now()
        hold_secs = (exit_time - pos["entry_time"]).seconds

        update_trade_exit(pos["db_id"], exit_time, profit)
        pnl_str = f"+₹{profit:.2f}" if profit >= 0 else f"-₹{abs(profit):.2f}"
        
        log_trade("CLOSE", symbol, current_price, pos["quantity"],
                  f"{reason} | PnL: {pnl_str} | Held: {hold_secs}s", trade_id=pos["db_id"])

        save_portfolio_snapshot(self.balance_inr, len(self.positions))
        
        emoji = "✅" if profit >= 0 else "❌"
        logger.info(f"{emoji} CLOSED {side} {symbol} at ₹{current_price:,.2f} | PnL: {pnl_str} | Held: {hold_secs}s | {reason}")
        
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
        
        logger.info(f"Engine v5 ready. Watching: {config.BLUE_CHIP_WHITELIST}")
        logger.info(f"  Stop-Loss: -{config.EARLY_STOP_LOSS_PCT*100:.2f}%  |  TP: +{config.TAKE_PROFIT_PCT*100:.2f}%  |  Trailing: +{config.TRAILING_STOP_TRIGGER_PCT*100:.2f}%")
        logger.info(f"  Position: ₹{config.MAX_POSITION_SIZE_INR:,.0f}  |  LLM Throttle: {config.LLM_POLL_INTERVAL_SECONDS}s  |  Max Hold: {config.MANDATORY_EXIT_SECONDS}s")

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
        Background loop: runs continuously while the bot trades.
        Every PERIODIC_REVIEW_TRADES closed trades (or PERIODIC_REVIEW_INTERVAL_SECONDS),
        calls run_mini_review() to:
          1. Analyze recent performance with Claude
          2. Save new lessons
          3. Auto-tune config (confidence threshold, stop-loss, take-profit)
          4. Commit changes to GitHub
        """
        from session_review import run_mini_review
        
        REVIEW_EVERY_N_TRADES   = getattr(config, 'PERIODIC_REVIEW_TRADES', 5)
        REVIEW_EVERY_N_SECONDS  = getattr(config, 'PERIODIC_REVIEW_SECONDS', 900)  # 15 min
        MIN_TRADES_FOR_TIME_REVIEW = 3  # at least 3 new trades before time-based review

        last_reviewed_trade_id  = 0
        last_review_time        = datetime.now()
        review_count            = 0

        logger.info(f"🔁 Periodic Self-Improvement Loop started (every {REVIEW_EVERY_N_TRADES} trades or {REVIEW_EVERY_N_SECONDS//60} min)")

        await asyncio.sleep(60)  # Give the engine 60s to warm up before first check

        while True:
            try:
                await asyncio.sleep(60)  # Check every minute

                if not self.llm_agent or not self.llm_agent.bedrock:
                    continue

                new_trades = self.trades_closed - (last_reviewed_trade_id // 1 if last_reviewed_trade_id else 0)
                trades_since_last = self.trades_closed  # total closed so far (proxy for "new")
                time_since_last   = (datetime.now() - last_review_time).total_seconds()

                # Trigger condition: enough new trades OR enough time has passed
                enough_by_trades = (self.trades_closed - (review_count * REVIEW_EVERY_N_TRADES)) >= REVIEW_EVERY_N_TRADES
                enough_by_time   = (time_since_last >= REVIEW_EVERY_N_SECONDS and self.trades_closed >= last_reviewed_trade_id + MIN_TRADES_FOR_TIME_REVIEW)

                if not (enough_by_trades or enough_by_time):
                    continue

                # Don't run during an open position (wait for calm)
                if len(self.simulator.positions) > 0:
                    logger.info("🔁 Periodic review ready but position open — waiting...")
                    continue

                review_count += 1
                label    = f"PERIODIC-{review_count}"
                logger.info(f"\n{'='*55}")
                logger.info(f"🔁 PERIODIC SELF-IMPROVEMENT #{review_count}")
                logger.info(f"   Trades since last: {self.trades_closed - (review_count-1)*REVIEW_EVERY_N_TRADES}")
                logger.info(f"   Time since last:   {int(time_since_last//60)} min")
                logger.info(f"{'='*55}")

                update_intent(f"🔁 Running periodic self-improvement #{review_count}...", [])

                new_id = run_mini_review(
                    bedrock_client=self.llm_agent.bedrock,
                    since_trade_id=last_reviewed_trade_id,
                    label=label
                )
                last_reviewed_trade_id = new_id
                last_review_time       = datetime.now()

                # Reload config so new values take effect immediately (without restart)
                import importlib, config as cfg_module
                importlib.reload(cfg_module)
                from config import config as new_cfg
                logger.info(f"🔄 Config reloaded: confidence={new_cfg.MIN_ENSEMBLE_CONFIDENCE}, SL={new_cfg.EARLY_STOP_LOSS_PCT}, TP={new_cfg.TAKE_PROFIT_PCT}")

            except asyncio.CancelledError:
                logger.info("🔁 Periodic self-improvement loop cancelled.")
                break
            except Exception as e:
                logger.error(f"Periodic review error: {e}", exc_info=True)
                await asyncio.sleep(120)  # Back off on error

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

                    # Update peak PnL for trailing stop
                    if pnl_pct > pos["peak_pnl_pct"]:
                        pos["peak_pnl_pct"] = pnl_pct
                        if pnl_pct >= config.TRAILING_STOP_TRIGGER_PCT and not pos["trailing_active"]:
                            pos["trailing_active"] = True
                            logger.info(f"🔔 Trailing stop ACTIVATED for {symbol} (peak: {pnl_pct*100:+.3f}%)")

                    # ── TAKE PROFIT ──
                    if pnl_pct >= config.TAKE_PROFIT_PCT:
                        await self._close_trade(symbol, current_price, f"✅ Take-Profit ({pnl_pct*100:+.3f}%)")
                        continue

                    # ── TRAILING STOP ──
                    if pos["trailing_active"]:
                        trail_stop = pos["peak_pnl_pct"] - config.TRAILING_STOP_OFFSET_PCT
                        if pnl_pct < trail_stop:
                            await self._close_trade(symbol, current_price, f"📉 Trailing Stop (peak: {pos['peak_pnl_pct']*100:+.3f}% → now: {pnl_pct*100:+.3f}%)")
                            continue

                    # ── EARLY STOP-LOSS ──
                    if pnl_pct < -config.EARLY_STOP_LOSS_PCT:
                        await self._close_trade(symbol, current_price, f"⛔ Stop-Loss ({pnl_pct*100:.3f}%)")
                        continue
                    
                    # ── TIME EXIT ──
                    if hold_secs >= config.MANDATORY_EXIT_SECONDS:
                        await self._close_trade(symbol, current_price, f"⏰ Time Exit ({config.MANDATORY_EXIT_SECONDS}s)")
                        continue
                    
                    remaining = config.MANDATORY_EXIT_SECONDS - hold_secs
                    trailing_label = " | 🔔 TRAILING" if pos["trailing_active"] else ""
                    update_intent(
                        f"Holding {pos['side']} {symbol} | PnL: {pnl_pct*100:+.3f}% | {remaining}s left{trailing_label}",
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

                        # ── RUN PRO TA TOOLS ───────────────────────────────
                        rsi_result    = RSIAnalyzer.analyze(history)
                        macd_result   = MACDSignal.analyze(history)
                        bb_result     = BollingerBands.analyze(history, current_price)
                        sr_result     = SupportResistance.analyze(history, current_price)
                        candle_result = CandlePatterns.analyze(history)

                        buy_count, sell_count = self._count_pro_signals(
                            rsi_result, macd_result, bb_result, sr_result, candle_result
                        )

                        # ── OPPORTUNITY PRE-FILTER (require 2+ pro signals) ─
                        if buy_count < 2 and sell_count < 2:
                            self.skipped_cycles += 1
                            best = max(buy_count, sell_count)
                            if self.skipped_cycles % 6 == 1:
                                update_intent(
                                    f"⏳ Waiting for setup ({best}/2 pro signals). RSI:{rsi_result['rsi']:.1f} | {macd_result['crossover']} | BB:{bb_result['position_pct']:.0f}%",
                                    [symbol]
                                )
                            # Save as SKIPPED (low-signal, not worth recording every cycle - sample every 3rd)
                            if self.skipped_cycles % 3 == 0:
                                save_signal_event(symbol, current_price, buy_count, sell_count,
                                                  rsi_result['rsi'], macd_result['crossover'],
                                                  bb_result['position_pct'], 'SKIPPED')
                            continue

                        # ── LLM THROTTLE ───────────────────────────────────
                        now = datetime.now()
                        if self.last_llm_call and (now - self.last_llm_call).total_seconds() < config.LLM_POLL_INTERVAL_SECONDS:
                            wait_left = int(config.LLM_POLL_INTERVAL_SECONDS - (now - self.last_llm_call).total_seconds())
                            if self.skipped_cycles % 2 == 0:
                                direction = "BUY" if buy_count >= sell_count else "SELL"
                                update_intent(
                                    f"⚡ SETUP FOUND: {direction} ({buy_count if direction=='BUY' else sell_count}/5 signals). LLM in {wait_left}s...",
                                    [symbol]
                                )
                            continue

                        # ── DIRECTION BLOCK (Claude Rule 1: no same-direction trades after 2 consecutive losses) ─
                        block = self.direction_block.get(symbol)
                        proposed_dir = "LONG" if buy_count >= sell_count else "SHORT"
                        if block and block["side"] == proposed_dir and now < block["blocked_until"]:
                            remaining_block = int((block["blocked_until"] - now).total_seconds())
                            update_intent(f"🚫 {proposed_dir} BLOCKED ({remaining_block}s remaining after consecutive losses)", [symbol])
                            continue

                        # ── DUPLICATE ENTRY GUARD (Claude Rule 3: don't re-enter within ₹500 of a recent failed price) ─
                        last_entry = self.last_entry_prices.get(symbol)
                        if last_entry:
                            last_price, last_side, last_time = last_entry
                            time_since = (now - last_time).total_seconds()
                            if time_since < 300 and last_side == proposed_dir and abs(current_price - last_price) < 500:
                                update_intent(f"⏸ Duplicate entry blocked: {proposed_dir} @ ₹{current_price:,.0f} too close to last entry @ ₹{last_price:,.0f} ({int(time_since)}s ago)", [symbol])
                                continue

                        # ── ALL TOOLS FOR CLAUDE ────────────────────────────
                        vel_result    = PriceVelocity.analyze(history, current_price)
                        ob_result     = OrderBookPressure.analyze(meta, current_price)
                        session_stats = self.session_tracker.get_stats()

                        tool_outputs = [
                            {"name": "Volatility Scanner",
                             "data": f"Vol: {vol_result['volatility_pct']:.4f}% — {vol_result['verdict']}"},
                            {"name": "Price Velocity",
                             "data": f"30s: {vel_result['velocity_30s']:+.4f}% | 1m: {vel_result['velocity_1m']:+.4f}% | 5m: {vel_result['velocity_5m']:+.4f}% — {vel_result['acceleration']}"},
                            {"name": "Volume Profile",
                             "data": f"24h Vol: {vol_prof['volume_24h']} | Spread: {vol_prof['spread_pct']:.4f}% — {vol_prof['verdict']}"},
                            {"name": "Order Book Pressure",
                             "data": f"{ob_result['pressure']} (bias: {ob_result['bias']:+.4f}%)"},
                            # ── PRO TOOLS ──
                            {"name": "RSI (14)",
                             "data": f"{rsi_result['verdict']}", "signal": rsi_result["signal"]},
                            {"name": "MACD (12,26,9)",
                             "data": f"{macd_result['verdict']}", "signal": macd_result["crossover"]},
                            {"name": "Bollinger Bands (20,2)",
                             "data": f"{bb_result['verdict']}", "signal": bb_result["signal"]},
                            {"name": "Support & Resistance",
                             "data": f"{sr_result['verdict']}", "signal": sr_result.get("signal", "NEUTRAL")},
                            {"name": "Candle Patterns",
                             "data": f"{candle_result['verdict']}", "signal": candle_result["signal"]},
                            # ── ALGO & SESSION ──
                        ]
                        for agent in self.algo_agents:
                            sig = agent.analyze(symbol, current_price, history, meta)
                            tool_outputs.append({
                                "name": agent.name,
                                "data": f"{sig.action} (conf: {sig.confidence:.2f}) — {sig.reason}",
                            })
                        trend_sig = self.trend_filter.analyze(symbol, current_price, history, meta)
                        tool_outputs.append({
                            "name": "Trend Filter",
                            "data": f"{trend_sig.action} (multiplier: {trend_sig.confidence:.1f}) — {trend_sig.reason}",
                        })
                        tool_outputs.append({
                            "name": "Session Performance",
                            "data": f"Trades: {session_stats['total_trades']} | WR: {session_stats['win_rate']} | Streak: {session_stats['streak']} | PnL: ₹{session_stats['cumulative_pnl']} — {session_stats['recommendation']}",
                        })

                        # ── CLAUDE MAKES THE FINAL CALL ──────────────────
                        self.last_llm_call = now
                        direction = "BUY" if buy_count >= sell_count else "SELL"
                        logger.info(f"⚡ SETUP: {direction} ({buy_count}B/{sell_count}S) | RSI:{rsi_result['rsi']:.1f} | {macd_result['crossover']} | BB:{bb_result['position_pct']:.0f}% | Sending to Claude...")
                        
                        if self.llm_agent:
                            llm_signal = self.llm_agent.analyze_with_tools(
                                symbol, current_price, history, meta, tool_outputs
                            )
                        else:
                            continue

                        if not llm_signal or llm_signal.action == "NEUTRAL" or llm_signal.confidence < config.MIN_ENSEMBLE_CONFIDENCE:
                            self.skipped_cycles += 1
                            conf = llm_signal.confidence if llm_signal else 0
                            action = llm_signal.action if llm_signal else "NEUTRAL"
                            if self.skipped_cycles % 3 == 1:
                                update_intent(f"⏳ Claude passed (conf: {conf:.2f}). Skipped {self.skipped_cycles}x", [symbol])
                            # MISSED: strong signals present but Claude declined
                            save_signal_event(symbol, current_price, buy_count, sell_count,
                                              rsi_result['rsi'], macd_result['crossover'],
                                              bb_result['position_pct'], 'MISSED',
                                              claude_action=action, claude_conf=conf)
                            self.missed_opportunities_count += 1
                            # Every 5 misses, run self-critique analyzer
                            if self.missed_opportunities_count % 5 == 0 and hasattr(self, 'missed_analyzer') and self.missed_analyzer:
                                try:
                                    logger.info(f"🔍 Running MissedOpportunityAnalyzer ({self.missed_opportunities_count} misses)...")
                                    self.missed_analyzer.analyze(symbol)
                                except Exception as e:
                                    logger.error(f"MissedOpportunityAnalyzer error: {e}")
                            continue
                        
                        # ── EXECUTE ─────────────────────────────────────
                        side = "LONG" if llm_signal.action == "BUY" else "SHORT"
                        reason = f"Claude({llm_signal.confidence:.2f}) | {buy_count}B/{sell_count}S | {llm_signal.reason}"

                        self.trades_executed += 1
                        self.skipped_cycles = 0
                        update_intent(f"🎯 Trade #{self.trades_executed}: {side} | {reason}", [symbol])
                        self.simulator.enter_position(symbol, current_price, config.MAX_POSITION_SIZE_INR, reason, side=side)
                        # Save TRADED signal event
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
        logger.info(f"💰 Net PnL: ₹{self.total_session_pnl:,.2f}")
        logger.info(f"💼 Final Balance: ₹{self.simulator.balance_inr:,.2f}")
        
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
        
        update_intent(f"Done. {self.trades_closed} trades. PnL: ₹{self.total_session_pnl:,.2f}. Run 'python3 reset_session.py' to start fresh.", [])
        sys.exit(0)
