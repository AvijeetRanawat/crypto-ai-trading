import asyncio
import os
from datetime import datetime, timedelta
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from logger import logger, log_trade
from config import config
from database import (
    save_trade,
    update_trade_exit,
    save_portfolio_snapshot,
    save_portfolio_full_snapshot,
    update_intent,
    save_signal_event,
    save_llm_usage,
    save_rl_event,
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
from rl_agent import RLWeightAgent, MLXWeightAgent, is_mlx_available
from engine_simulator import PaperTradingSimulator
from engine_rl_helpers import (
    rl_infer,
    rl_apply_weight_multipliers,
    attach_rl_metadata,
    rl_reward_skip_opportunity,
    rl_loss_penalty_cap,
)
from rl_tuning import get_value as rl_cfg

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
                bedrock_client = getattr(self.llm_agent, 'bedrock', None)
                if config.ENABLE_RETROSPECTIVE:
                    self.retro_agent = RetrospectiveAgent(bedrock_client)
                if config.ENABLE_META_OPTIMIZER:
                    self.meta_optimizer = MetaOptimizer(bedrock_client)
                if config.ENABLE_MISSED_OPPORTUNITY_ANALYZER:
                    self.missed_analyzer = MissedOpportunityAnalyzer(bedrock_client, config.BEDROCK_MODEL_ID)
                logger.info(f"✅ Engine initialized with LLM provider={self.llm_agent.provider} (profit-first mode)")
            else:
                logger.error("LLM provider initialization failed.")
        except Exception as e:
            logger.error(f"Failed to load LLM: {e}")

        self.trades_executed = 0
        self.trades_closed = 0
        self.total_session_pnl = 0.0
        self.skipped_cycles_by_mode: dict[str, int] = {}
        self.trades_executed_by_mode: dict[str, int] = {"SPOT": 0, "FUTURES": 0, "OPTIONS": 0}
        self.trades_closed_by_mode: dict[str, int] = {"SPOT": 0, "FUTURES": 0, "OPTIONS": 0}
        self.rl_updates_by_mode: dict[str, int] = {"SPOT": 0, "FUTURES": 0, "OPTIONS": 0}
        self.rl_trade_rewards_by_mode: dict[str, int] = {"SPOT": 0, "FUTURES": 0, "OPTIONS": 0}
        self.last_llm_call: dict[str, datetime | None] = {}  # per-mode LLM throttle
        self.missed_opportunities_count = 0
        self.last_entry_prices: dict = {}      # key(symbol:mode) -> (price, side, timestamp)
        self.direction_block: dict = {}         # key(symbol:mode) -> {side, blocked_until}
        self._latest_prices: dict = {}          # symbol -> most-recently-seen price (for portfolio valuation)         # key(symbol:mode) -> {side, blocked_until}
        self.last_close_time_by_mode: dict[str, datetime] = {}
        self.symbol_drift_alerted = set()
        self.consecutive_losses: dict[str, int] = {"SPOT": 0, "FUTURES": 0, "OPTIONS": 0}
        self.trading_halted_reason = None
        self.session_start_balance = self.simulator.balance_usdt
        self.parallel_products = list(config.PARALLEL_PRODUCTS)
        self.enable_parallel_products = bool(config.ENABLE_PARALLEL_PRODUCT_STRATEGIES)
        if bool(config.ENABLE_MLX_RL_AGENT) and is_mlx_available():
            self.rl_agent = MLXWeightAgent(
                state_file=os.path.join(os.path.dirname(__file__), "data", "rl_weights.json"),
                enabled=bool(config.ENABLE_RL_WEIGHT_AGENT),
                epsilon=float(config.RL_EPSILON),
                min_epsilon=float(config.RL_MIN_EPSILON),
                epsilon_decay=float(config.RL_EPSILON_DECAY),
                learning_rate=float(config.RL_MLX_LEARNING_RATE),
                hidden_size=int(config.RL_MLX_HIDDEN_SIZE),
            )
        else:
            self.rl_agent = RLWeightAgent(
                state_file=os.path.join(os.path.dirname(__file__), "data", "rl_weights.json"),
                enabled=bool(config.ENABLE_RL_WEIGHT_AGENT),
                epsilon=float(config.RL_EPSILON),
                min_epsilon=float(config.RL_MIN_EPSILON),
                epsilon_decay=float(config.RL_EPSILON_DECAY),
                learning_rate=float(config.RL_LEARNING_RATE),
            )
        self._pending_rl_by_symbol = {}
        self.policy_executor = ThreadPoolExecutor(
            max_workers=max(1, len(self.parallel_products)),
            thread_name_prefix="policy-worker",
        )

        logger.info(f"Engine ready. Watching: {sorted(self.allowed_symbols)}")
        logger.info(f"  Product: {config.TRADING_PRODUCT}")
        logger.info(
            "  Parallel products: enabled=%s products=%s",
            self.enable_parallel_products,
            self.parallel_products,
        )

    @staticmethod
    def _pos_key(symbol: str, mode: str) -> str:
        return f"{str(symbol).upper()}:{str(mode).upper()}"

    def _positions_for_mode(self, mode: str) -> dict:
        active_mode = str(mode or config.TRADING_PRODUCT).upper()
        return {k: v for k, v in (self.simulator.positions or {}).items() if v.get("mode") == active_mode}

    @staticmethod
    def _mode_decision_source(mode: str, decision_source: str) -> str:
        if not decision_source:
            return decision_source
        active_mode = str(mode or config.TRADING_PRODUCT).upper()
        prefix = f"{active_mode}_"
        if str(decision_source).upper().startswith(prefix):
            return decision_source
        return f"{active_mode}_{decision_source}"

    def _exploration_state(self, mode: str) -> dict:
        active_mode = str(mode or config.TRADING_PRODUCT).upper()
        executed = int(self.trades_executed_by_mode.get(active_mode, 0) or 0)
        closed = int(self.trades_closed_by_mode.get(active_mode, 0) or 0)
        skip_streak = int(self.skipped_cycles_by_mode.get(active_mode, 0) or 0)
        under_sampled = (
            executed < int(rl_cfg("RL_MIN_TRADES_BEFORE_STRICT_GATES"))
            or closed < int(rl_cfg("RL_MIN_CLOSED_TRADES_BEFORE_STRICT_GATES"))
        )
        force_entry = (
            bool(rl_cfg("RL_FORCE_ENTRY_ON_SKIP_STREAK"))
            and under_sampled
            and skip_streak >= int(rl_cfg("RL_FORCE_ENTRY_SKIP_STREAK"))
            and executed < int(rl_cfg("RL_FORCE_ENTRY_MAX_TRADES"))
        )
        return {
            "mode": active_mode,
            "executed": executed,
            "closed": closed,
            "skip_streak": skip_streak,
            "under_sampled": under_sampled,
            "force_entry": force_entry,
        }

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

    def _weighted_vote_counts(self, rsi_result, macd_result, bb_result, sr_result, candle_result,
                              stochrsi_result=None, ema_result=None, volmom_result=None,
                              vote_weights: dict | None = None) -> tuple:
        weights = {
            "rsi": 1.0,
            "macd": 1.0,
            "bb": 1.0,
            "sr": 1.0,
            "candle": 1.0,
            "stochrsi": 1.0,
            "ema": 1.0,
            "volmom": 1.0,
        }
        for key, val in (vote_weights or {}).items():
            if key in weights:
                weights[key] = max(0.2, float(val))

        buy_score = 0.0
        sell_score = 0.0
        raw_buy = 0
        raw_sell = 0

        buy_signals = {"STRONG_BUY", "BUY", "BULLISH_CROSS", "BULLISH_ENGULFING", "HAMMER"}
        sell_signals = {"STRONG_SELL", "SELL", "BEARISH_CROSS", "BEARISH_ENGULFING", "SHOOTING_STAR"}

        def _apply(signal, key):
            nonlocal buy_score, sell_score, raw_buy, raw_sell
            if signal in buy_signals:
                buy_score += weights[key]
                raw_buy += 1
            elif signal in sell_signals:
                sell_score += weights[key]
                raw_sell += 1

        _apply(rsi_result.get("signal"), "rsi")
        _apply(macd_result.get("crossover"), "macd")
        _apply(bb_result.get("signal"), "bb")

        sr_sig = sr_result.get("signal")
        if sr_sig in ("BUY", "WATCH_BUY"):
            buy_score += weights["sr"]
            raw_buy += 1
        elif sr_sig in ("SELL", "WATCH_SELL"):
            sell_score += weights["sr"]
            raw_sell += 1

        candle_sig = candle_result.get("signal")
        if candle_sig == "BUY":
            buy_score += weights["candle"]
            raw_buy += 1
        elif candle_sig == "SELL":
            sell_score += weights["candle"]
            raw_sell += 1

        if stochrsi_result:
            _apply(stochrsi_result.get("signal"), "stochrsi")
        if ema_result:
            _apply(ema_result.get("signal"), "ema")
        if volmom_result:
            _apply(volmom_result.get("signal"), "volmom")

        total_weight = sum(weights.values())
        return buy_score, sell_score, raw_buy, raw_sell, total_weight

    def _safe_tool_call(self, name: str, fn, fallback):
        try:
            out = fn()
            return fallback if out is None else out
        except Exception as e:
            logger.error(f"Tool failure ({name}): {e}")
            return fallback

    @staticmethod
    def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
        return max(low, min(high, float(value)))

    def _rl_infer(
        self,
        mode: str,
        regime: str,
        session_quality: str,
        volatility_pct: float,
        sentiment_score: float,
        vote_imbalance: float,
        expected_edge_pct: float,
    ) -> dict:
        return rl_infer(
            self,
            mode=mode,
            regime=regime,
            session_quality=session_quality,
            volatility_pct=volatility_pct,
            sentiment_score=sentiment_score,
            vote_imbalance=vote_imbalance,
            expected_edge_pct=expected_edge_pct,
        )

    def _rl_apply_weight_multipliers(self, weights: dict, rl_inference: dict) -> dict:
        return rl_apply_weight_multipliers(weights, rl_inference)

    def _attach_rl_metadata(self, mode: str, result: dict, kwargs: dict) -> dict:
        return attach_rl_metadata(self, mode, result, kwargs)

    def _rl_reward_skip_opportunity(
        self,
        mode: str,
        policy_eval: dict,
        expected_edge_pct: float,
        reason: str,
        symbol: str = None,
    ):
        rl_reward_skip_opportunity(self, mode, policy_eval, expected_edge_pct, reason, symbol)

    def _rl_penalize_skip(
        self,
        mode: str,
        reason: str,
        expected_edge_pct: float,
        symbol: str = None,
        regime_result: dict = None,
        session_filt: dict = None,
        vol_result: dict = None,
        sentiment_snapshot: dict = None,
        buy_count: int = 0,
        sell_count: int = 0,
        total_vote_weight: float = 8.0,
    ):
        if not bool(config.ENABLE_RL_WEIGHT_AGENT):
            return
        vote_imbalance = min(1.0, abs(float(buy_count or 0) - float(sell_count or 0)) / max(total_vote_weight, 1.0))
        rl_inf = self._rl_infer(
            mode=str(mode or config.TRADING_PRODUCT).upper(),
            regime=str((regime_result or {}).get("regime", "UNKNOWN")).upper(),
            session_quality=str((session_filt or {}).get("quality", "LOW")).upper(),
            volatility_pct=float((vol_result or {}).get("volatility_pct", 0.0) or 0.0),
            sentiment_score=float((sentiment_snapshot or {}).get("sentiment_score", 0.0) or 0.0),
            vote_imbalance=vote_imbalance,
            expected_edge_pct=float(expected_edge_pct or 0.0),
        )
        policy_eval = {
            "rl_profile_id": rl_inf.get("profile_id", ""),
            "rl_state_key": rl_inf.get("state_key", ""),
        }
        self._rl_reward_skip_opportunity(
            mode=str(mode or config.TRADING_PRODUCT).upper(),
            policy_eval=policy_eval,
            expected_edge_pct=expected_edge_pct,
            reason=reason,
            symbol=symbol,
        )

    @staticmethod
    def _rl_loss_penalty_cap(pnl_reward: float = None) -> float:
        return rl_loss_penalty_cap(pnl_reward)

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

    def _sentiment_gate(
        self,
        symbol: str,
        proposed_dir: str,
        snapshot: dict = None,
        sentiment_gate_mult: float = 1.0,
    ):
        """
        Sentiment-aware entry gate.
        Returns: (allowed: bool, verdict: str)
        """
        if not config.ENABLE_SENTIMENT_GATE:
            return True, "Sentiment gate disabled"

        try:
            if snapshot is None:
                snapshot = build_sentiment_snapshot(
                    alpha_key=config.ALPHAVANTAGE_API_KEY,
                    cryptocompare_key=config.CRYPTOCOMPARE_API_KEY,
                    symbol=symbol,
                )
            score = float(snapshot.get("sentiment_score", 0.0))
            label = str(snapshot.get("sentiment_label", "NEUTRAL"))
            components = snapshot.get("components", {}) or {}
            article_count = int(components.get("articles_count", 0) or 0)
            gate_mult = max(0.60, min(1.40, float(sentiment_gate_mult or 1.0)))
            min_abs_score = float(config.SENTIMENT_MIN_ABS_SCORE) * gate_mult
            directional_floor = float(config.SENTIMENT_DIRECTIONAL_FLOOR) * gate_mult

            # If feed coverage is thin, do not hard-block entries.
            if article_count < config.SENTIMENT_MIN_ARTICLES:
                return True, f"Sentiment thin ({article_count} articles)"

            # Neutral / undecided sentiment should not block trades —
            # only STRONG directional conflict should hard-block.
            if abs(score) < min_abs_score:
                return True, f"Sentiment neutral ({score:+.2f}; gate x{gate_mult:.2f})"

            # Block only when sentiment STRONGLY opposes the direction.
            # (Previous logic required positive sentiment for LONG which
            #  blocked all entries during "Extreme Fear" periods even when
            #  TA signals were strong.)
            if proposed_dir == "LONG" and score < -directional_floor:
                return False, f"Sentiment opposes LONG ({label} {score:+.2f}; gate x{gate_mult:.2f})"

            if proposed_dir == "SHORT" and score > directional_floor:
                return False, f"Sentiment opposes SHORT ({label} {score:+.2f}; gate x{gate_mult:.2f})"

            return True, f"Sentiment supports {proposed_dir} ({label} {score:+.2f}; gate x{gate_mult:.2f})"
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

    def _estimate_expected_edge_pct(self, buy_count: float, sell_count: float, tp_pct: float, sl_pct: float, total_weight: float = 8.0) -> float:
        agreement = max(buy_count, sell_count)
        disagreement = min(buy_count, sell_count)
        quality = max(0.0, (agreement - disagreement) / max(total_weight, 1.0))
        # Win probability scales with signal quality: 50% base + 30% from quality
        win_prob = min(0.85, 0.50 + quality * 0.30)
        tp_pct_val = tp_pct * 100  # convert fraction to percentage
        sl_pct_val = sl_pct * 100
        fee_pct = config.FEE_SLIPPAGE_BUFFER_PCT
        # Expected value = P(win) × TP - P(loss) × SL - fees
        return (win_prob * tp_pct_val) - ((1.0 - win_prob) * sl_pct_val) - fee_pct

    def _deterministic_decision(self, buy_count: float, sell_count: float, total_weight: float = 8.0) -> tuple:
        agreement = max(buy_count, sell_count)
        disagreement = min(buy_count, sell_count)
        margin = agreement - disagreement

        scaled_min = max(2.0, 3.0 * (total_weight / 8.0))
        if agreement < scaled_min:
            return "NEUTRAL", 0.0, "insufficient deterministic agreement"

        if buy_count > sell_count:
            action = "BUY"
        elif sell_count > buy_count:
            action = "SELL"
        else:
            return "NEUTRAL", 0.0, "conflicting deterministic votes"

        # Strong confluence bypasses LLM completely.
        if agreement >= (5.0 * (total_weight / 8.0)) and margin >= (2.0 * (total_weight / 8.0)):
            conf = min(0.92, 0.60 + (agreement / max(total_weight, 1.0)) * 0.40 + (margin / max(total_weight, 1.0)) * 0.20)
            return action, conf, "deterministic strong confluence"

        # Borderline setup: LLM tie-breaker allowed.
        conf = min(0.82, 0.50 + (agreement / max(total_weight, 1.0)) * 0.30 + (margin / max(total_weight, 1.0)) * 0.15)
        return action, conf, "deterministic borderline setup"

    def _futures_policy_decision(
        self,
        symbol: str,
        proposed_dir: str,
        buy_count: int,
        sell_count: int,
        total_vote_weight: float,
        confidence: float,
        expected_edge_pct: float,
        regime_result: dict,
        session_filt: dict,
        vol_result: dict,
        vol_prof: dict,
        sentiment_snapshot: dict,
        vel_result: dict,
        macd_result: dict,
        ema_result: dict,
        ob_result: dict,
        mode: str = None,
        enforce_confidence_gate: bool = True,
    ) -> dict:
        active_mode = str(mode or config.TRADING_PRODUCT).upper()
        if active_mode != "FUTURES":
            return {
                "allow": True,
                "composite_score": 1.0,
                "recommended_leverage": 1,
                "size_multiplier": 1.0,
                "verdict": "Spot/options mode active",
                "component_scores": {},
                "penalties": {},
                "hard_reject_reason": "",
            }

        is_long = proposed_dir == "LONG"
        confidence = self._clamp(confidence)
        regime_strength = float(regime_result.get("strength", 0.0) or 0.0)
        vol_pct = float(vol_result.get("volatility_pct", 0.0) or 0.0)
        spread_pct = float(vol_prof.get("spread_pct", 0.0) or 0.0)
        volume_24h = float(vol_prof.get("volume_24h", 0.0) or 0.0)
        session_quality = str(session_filt.get("quality", "LOW")).upper()

        if regime_strength < config.FUTURES_MIN_REGIME_STRENGTH:
            return {
                "allow": False,
                "composite_score": 0.0,
                "recommended_leverage": 1,
                "size_multiplier": config.FUTURES_SIZE_MIN_MULT,
                "verdict": (
                    f"Futures reject: weak trend strength ({regime_strength:.2f} < "
                    f"{config.FUTURES_MIN_REGIME_STRENGTH:.2f})"
                ),
                "component_scores": {},
                "penalties": {},
                "hard_reject_reason": "weak_regime",
            }

        if vol_pct > config.FUTURES_EXTREME_VOL_PCT:
            return {
                "allow": False,
                "composite_score": 0.0,
                "recommended_leverage": 1,
                "size_multiplier": config.FUTURES_SIZE_MIN_MULT,
                "verdict": (
                    f"Futures reject: extreme volatility {vol_pct:.3f}% > "
                    f"{config.FUTURES_EXTREME_VOL_PCT:.3f}%"
                ),
                "component_scores": {},
                "penalties": {},
                "hard_reject_reason": "extreme_volatility",
            }

        if spread_pct > config.FUTURES_MAX_SPREAD_PCT:
            return {
                "allow": False,
                "composite_score": 0.0,
                "recommended_leverage": 1,
                "size_multiplier": config.FUTURES_SIZE_MIN_MULT,
                "verdict": (
                    f"Futures reject: spread too wide {spread_pct:.3f}% > "
                    f"{config.FUTURES_MAX_SPREAD_PCT:.3f}%"
                ),
                "component_scores": {},
                "penalties": {},
                "hard_reject_reason": "wide_spread",
            }

        if volume_24h < config.FUTURES_MIN_VOLUME_24H:
            return {
                "allow": False,
                "composite_score": 0.0,
                "recommended_leverage": 1,
                "size_multiplier": config.FUTURES_SIZE_MIN_MULT,
                "verdict": (
                    f"Futures reject: low liquidity volume {volume_24h:.2f} < "
                    f"{config.FUTURES_MIN_VOLUME_24H:.2f}"
                ),
                "component_scores": {},
                "penalties": {},
                "hard_reject_reason": "low_liquidity",
            }

        vote_imbalance = self._clamp(abs(buy_count - sell_count) / max(total_vote_weight, 1.0))
        regime_score = self._clamp(regime_strength / max(config.FUTURES_MIN_REGIME_STRENGTH * 2.2, 0.30))

        vel_1m = float(vel_result.get("velocity_1m", 0.0) or 0.0)
        vel_5m = float(vel_result.get("velocity_5m", 0.0) or 0.0)
        directional_vel = ((vel_1m * 0.7) + (vel_5m * 0.3)) * (1 if is_long else -1)
        velocity_score = self._clamp(0.5 + (directional_vel / 0.25))

        macd_signal = str(macd_result.get("crossover", "")).upper()
        if is_long:
            macd_score = 1.0 if "BULLISH_CROSS" in macd_signal else (0.82 if "BULL" in macd_signal else 0.28)
        else:
            macd_score = 1.0 if "BEARISH_CROSS" in macd_signal else (0.82 if "BEAR" in macd_signal else 0.28)

        ema_signal = str(ema_result.get("signal", "")).upper()
        if is_long:
            ema_score = 1.0 if ema_signal == "STRONG_BUY" else (0.82 if ema_signal == "BUY" else 0.25)
        else:
            ema_score = 1.0 if ema_signal == "STRONG_SELL" else (0.82 if ema_signal == "SELL" else 0.25)

        ob_bias = float(ob_result.get("bias", 0.0) or 0.0)
        directional_ob = ob_bias * (1 if is_long else -1)
        ob_score = self._clamp(0.5 + (directional_ob / 0.12))
        momentum_score = round((velocity_score * 0.45) + (macd_score * 0.30) + (ema_score * 0.15) + (ob_score * 0.10), 4)

        low_vol = max(config.FUTURES_TARGET_VOL_PCT_LOW, 0.0001)
        high_vol = max(config.FUTURES_TARGET_VOL_PCT_HIGH, low_vol + 0.01)
        extreme_vol = max(config.FUTURES_EXTREME_VOL_PCT, high_vol + 0.01)
        if vol_pct <= low_vol:
            volatility_score = self._clamp((vol_pct / low_vol) * 0.8)
        elif vol_pct <= high_vol:
            volatility_score = 1.0
        else:
            decay = (vol_pct - high_vol) / max(extreme_vol - high_vol, 0.01)
            volatility_score = self._clamp(1.0 - decay)

        volume_score = self._clamp(volume_24h / max(config.FUTURES_MIN_VOLUME_24H * 2.0, 1.0))
        spread_score = self._clamp((config.FUTURES_MAX_SPREAD_PCT - spread_pct) / max(config.FUTURES_MAX_SPREAD_PCT, 0.001))
        liquidity_score = round((volume_score * 0.55) + (spread_score * 0.45), 4)

        sentiment_score = 0.55
        sentiment_val = 0.0
        article_count = 0
        if sentiment_snapshot:
            sentiment_val = float(sentiment_snapshot.get("sentiment_score", 0.0) or 0.0)
            comp = sentiment_snapshot.get("components", {}) or {}
            article_count = int(comp.get("articles_count", 0) or 0)
            directional_sentiment = sentiment_val if is_long else -sentiment_val
            if article_count >= config.SENTIMENT_MIN_ARTICLES:
                sentiment_score = self._clamp(0.5 + directional_sentiment)
                if (
                    config.FUTURES_BLOCK_ON_OPPOSING_SENTIMENT
                    and directional_sentiment < -config.SENTIMENT_DIRECTIONAL_FLOOR
                ):
                    return {
                        "allow": False,
                        "composite_score": 0.0,
                        "recommended_leverage": 1,
                        "size_multiplier": config.FUTURES_SIZE_MIN_MULT,
                        "verdict": (
                            f"Futures reject: sentiment opposes {proposed_dir} "
                            f"({sentiment_val:+.2f}, articles={article_count})"
                        ),
                        "component_scores": {},
                        "penalties": {},
                        "hard_reject_reason": "sentiment_conflict",
                    }

        session_map = {"PREMIUM": 1.0, "HIGH": 0.88, "MODERATE": 0.75, "LOW": 0.58}
        session_score = session_map.get(session_quality, 0.60)
        rl_inf = self._rl_infer(
            mode="FUTURES",
            regime=str(regime_result.get("regime", "UNKNOWN")).upper(),
            session_quality=session_quality,
            volatility_pct=vol_pct,
            sentiment_score=sentiment_val,
            vote_imbalance=vote_imbalance,
            expected_edge_pct=expected_edge_pct,
        )

        weights = {
            "vote_imbalance": max(0.0, float(config.FUTURES_WEIGHT_VOTE_IMBALANCE)),
            "regime": max(0.0, float(config.FUTURES_WEIGHT_REGIME)),
            "momentum": max(0.0, float(config.FUTURES_WEIGHT_MOMENTUM)),
            "volatility": max(0.0, float(config.FUTURES_WEIGHT_VOLATILITY)),
            "liquidity": max(0.0, float(config.FUTURES_WEIGHT_LIQUIDITY)),
            "sentiment": max(0.0, float(config.FUTURES_WEIGHT_SENTIMENT)),
            "session": max(0.0, float(config.FUTURES_WEIGHT_SESSION)),
        }
        weights = self._rl_apply_weight_multipliers(weights, rl_inf)
        w_sum = sum(weights.values()) or 1.0
        weighted_core = (
            weights["vote_imbalance"] * vote_imbalance
            + weights["regime"] * regime_score
            + weights["momentum"] * momentum_score
            + weights["volatility"] * volatility_score
            + weights["liquidity"] * liquidity_score
            + weights["sentiment"] * sentiment_score
            + weights["session"] * session_score
        ) / w_sum

        edge_score = self._clamp(expected_edge_pct / max(float(rl_cfg("MIN_EXPECTED_EDGE_PCT")) * 2.5, 0.25))
        confidence_score = self._clamp(confidence + float(rl_inf.get("confidence_bias", 0.0)))
        composite_score = self._clamp((weighted_core * 0.82) + (edge_score * 0.10) + (confidence_score * 0.08))

        penalties = {}
        if session_quality == "LOW":
            penalties["off_hours"] = config.FUTURES_OFF_HOURS_PENALTY
            composite_score -= config.FUTURES_OFF_HOURS_PENALTY
        _cons_losses = self.consecutive_losses.get("FUTURES", 0)
        if _cons_losses > 0:
            loss_penalty = min(0.25, _cons_losses * config.FUTURES_LOSS_STREAK_PENALTY)
            penalties["loss_streak"] = loss_penalty
            composite_score -= loss_penalty
        composite_score = self._clamp(composite_score)

        conf_gate = confidence >= config.FUTURES_MIN_CONFIDENCE if enforce_confidence_gate else True
        allow = composite_score >= config.FUTURES_MIN_COMPOSITE_SCORE and conf_gate

        min_lev = config.FUTURES_MIN_LEVERAGE
        max_lev = max(min_lev, config.FUTURES_MAX_LEVERAGE)
        score_span = self._clamp(
            (composite_score - config.FUTURES_MIN_COMPOSITE_SCORE)
            / max(1.0 - config.FUTURES_MIN_COMPOSITE_SCORE, 0.001)
        )
        rec_lev = int(round(min_lev + score_span * (max_lev - min_lev)))
        rec_lev = int(round(rec_lev * float(rl_inf.get("leverage_mult", 1.0) or 1.0)))
        if vol_pct > config.FUTURES_TARGET_VOL_PCT_HIGH:
            rec_lev -= 1
        if spread_pct > config.FUTURES_MAX_SPREAD_PCT * 0.7:
            rec_lev -= 1
        if confidence < config.FUTURES_MIN_CONFIDENCE + 0.07:
            rec_lev = min(rec_lev, 2)
        if _cons_losses > 0:
            rec_lev = min(rec_lev, 2)
        rec_lev = max(min_lev, min(max_lev, rec_lev))

        size_span = max(config.FUTURES_SIZE_MAX_MULT - config.FUTURES_SIZE_MIN_MULT, 0.01)
        size_multiplier = config.FUTURES_SIZE_MIN_MULT + (score_span * size_span)
        size_multiplier *= float(rl_inf.get("size_mult", 1.0) or 1.0)
        if _cons_losses >= 2:
            size_multiplier *= 0.75
        size_multiplier = max(config.FUTURES_SIZE_MIN_MULT, min(config.FUTURES_SIZE_MAX_MULT, size_multiplier))

        verdict = (
            f"Futures score={composite_score:.3f} "
            f"(min={config.FUTURES_MIN_COMPOSITE_SCORE:.2f}) | "
            f"conf={confidence:.2f} | lev={rec_lev}x | edge={expected_edge_pct:+.3f}% | "
            f"RL:{rl_inf.get('profile_id')}/{rl_inf.get('decision_type')}"
        )
        return {
            "allow": allow,
            "composite_score": round(composite_score, 4),
            "recommended_leverage": rec_lev,
            "size_multiplier": round(size_multiplier, 4),
            "rl_profile_id": rl_inf.get("profile_id", ""),
            "rl_state_key": rl_inf.get("state_key", ""),
            "rl_decision_type": rl_inf.get("decision_type", ""),
            "verdict": verdict,
            "component_scores": {
                "vote_imbalance": round(vote_imbalance, 4),
                "regime": round(regime_score, 4),
                "momentum": round(momentum_score, 4),
                "volatility": round(volatility_score, 4),
                "liquidity": round(liquidity_score, 4),
                "sentiment": round(sentiment_score, 4),
                "session": round(session_score, 4),
                "edge": round(edge_score, 4),
                "confidence": round(confidence_score, 4),
                "spread_pct": round(spread_pct, 4),
                "volatility_pct": round(vol_pct, 4),
                "sentiment_raw": round(sentiment_val, 4),
                "articles_count": article_count,
                "rl_q_value": round(float(rl_inf.get("q_value", 0.0) or 0.0), 6),
            },
            "penalties": penalties,
            "hard_reject_reason": "",
        }

    def _options_policy_decision(
        self,
        symbol: str,
        proposed_dir: str,
        buy_count: int,
        sell_count: int,
        total_vote_weight: float,
        confidence: float,
        expected_edge_pct: float,
        regime_result: dict,
        session_filt: dict,
        vol_result: dict,
        vol_prof: dict,
        sentiment_snapshot: dict,
        vel_result: dict,
        macd_result: dict,
        ema_result: dict,
        ob_result: dict,
        mode: str = None,
        enforce_confidence_gate: bool = True,
    ) -> dict:
        active_mode = str(mode or config.TRADING_PRODUCT).upper()
        if active_mode != "OPTIONS":
            return {
                "allow": True,
                "composite_score": 1.0,
                "recommended_leverage": 1,
                "recommended_strategy": "SPOT_FLOW",
                "size_multiplier": 1.0,
                "verdict": "Spot/futures mode active",
                "component_scores": {},
                "penalties": {},
                "hard_reject_reason": "",
            }

        is_long = proposed_dir == "LONG"
        confidence = self._clamp(confidence)
        regime = str(regime_result.get("regime", "UNKNOWN")).upper()
        regime_strength = float(regime_result.get("strength", 0.0) or 0.0)
        vol_pct = float(vol_result.get("volatility_pct", 0.0) or 0.0)
        spread_pct = float(vol_prof.get("spread_pct", 0.0) or 0.0)
        volume_24h = float(vol_prof.get("volume_24h", 0.0) or 0.0)
        session_quality = str(session_filt.get("quality", "LOW")).upper()
        vote_imbalance = self._clamp(abs(buy_count - sell_count) / max(total_vote_weight, 1.0))

        if spread_pct > config.OPTIONS_MAX_SPREAD_PCT:
            return {
                "allow": False,
                "composite_score": 0.0,
                "recommended_leverage": 1,
                "recommended_strategy": "NO_TRADE",
                "size_multiplier": config.OPTIONS_SIZE_MIN_MULT,
                "verdict": (
                    f"Options reject: spread too wide {spread_pct:.3f}% > "
                    f"{config.OPTIONS_MAX_SPREAD_PCT:.3f}%"
                ),
                "component_scores": {},
                "penalties": {},
                "hard_reject_reason": "wide_spread",
            }

        if volume_24h < config.OPTIONS_MIN_VOLUME_24H:
            return {
                "allow": False,
                "composite_score": 0.0,
                "recommended_leverage": 1,
                "recommended_strategy": "NO_TRADE",
                "size_multiplier": config.OPTIONS_SIZE_MIN_MULT,
                "verdict": (
                    f"Options reject: low liquidity volume {volume_24h:.2f} < "
                    f"{config.OPTIONS_MIN_VOLUME_24H:.2f}"
                ),
                "component_scores": {},
                "penalties": {},
                "hard_reject_reason": "low_liquidity",
            }

        if vol_pct > config.OPTIONS_EXTREME_VOL_PCT:
            return {
                "allow": False,
                "composite_score": 0.0,
                "recommended_leverage": 1,
                "recommended_strategy": "NO_TRADE",
                "size_multiplier": config.OPTIONS_SIZE_MIN_MULT,
                "verdict": (
                    f"Options reject: extreme volatility {vol_pct:.3f}% > "
                    f"{config.OPTIONS_EXTREME_VOL_PCT:.3f}%"
                ),
                "component_scores": {},
                "penalties": {},
                "hard_reject_reason": "extreme_volatility",
            }

        if regime in {"CHOPPY", "UNKNOWN"} and regime_strength < config.OPTIONS_MIN_REGIME_STRENGTH:
            return {
                "allow": False,
                "composite_score": 0.0,
                "recommended_leverage": 1,
                "recommended_strategy": "NO_TRADE",
                "size_multiplier": config.OPTIONS_SIZE_MIN_MULT,
                "verdict": (
                    f"Options reject: weak structure ({regime_strength:.2f} < "
                    f"{config.OPTIONS_MIN_REGIME_STRENGTH:.2f})"
                ),
                "component_scores": {},
                "penalties": {},
                "hard_reject_reason": "weak_structure",
            }

        sentiment_score = 0.55
        sentiment_val = 0.0
        article_count = 0
        if sentiment_snapshot:
            sentiment_val = float(sentiment_snapshot.get("sentiment_score", 0.0) or 0.0)
            comp = sentiment_snapshot.get("components", {}) or {}
            article_count = int(comp.get("articles_count", 0) or 0)
            directional_sentiment = sentiment_val if is_long else -sentiment_val
            if article_count >= config.SENTIMENT_MIN_ARTICLES:
                sentiment_score = self._clamp(0.5 + directional_sentiment)
                if (
                    config.OPTIONS_BLOCK_ON_OPPOSING_SENTIMENT
                    and directional_sentiment < -config.SENTIMENT_DIRECTIONAL_FLOOR
                ):
                    return {
                        "allow": False,
                        "composite_score": 0.0,
                        "recommended_leverage": 1,
                        "recommended_strategy": "NO_TRADE",
                        "size_multiplier": config.OPTIONS_SIZE_MIN_MULT,
                        "verdict": (
                            f"Options reject: sentiment opposes {proposed_dir} "
                            f"({sentiment_val:+.2f}, articles={article_count})"
                        ),
                        "component_scores": {},
                        "penalties": {},
                        "hard_reject_reason": "sentiment_conflict",
                    }

        strategy = "WAIT"
        strategy_fit = 0.55
        strategy_note = "Mixed structure"
        low_vol = max(config.OPTIONS_TARGET_VOL_PCT_LOW, 0.0001)
        high_vol = max(config.OPTIONS_TARGET_VOL_PCT_HIGH, low_vol + 0.01)

        if vol_pct >= high_vol and regime in {"CHOPPY", "NEUTRAL"} and vote_imbalance <= 0.35:
            strategy = "IRON_CONDOR"
            strategy_fit = 0.95
            strategy_note = "High vol + range structure -> sell premium with wings"
        elif vol_pct >= high_vol and regime in {"BULL", "BEAR"}:
            strategy = "BULL_PUT_CREDIT_SPREAD" if is_long else "BEAR_CALL_CREDIT_SPREAD"
            strategy_fit = 0.84
            strategy_note = "Elevated vol + directional trend -> credit spread"
        elif vol_pct <= low_vol and vote_imbalance >= 0.35 and regime in {"BULL", "BEAR", "NEUTRAL"}:
            strategy = "CALL_DEBIT_SPREAD" if is_long else "PUT_DEBIT_SPREAD"
            strategy_fit = 0.90
            strategy_note = "Low vol + direction -> buy premium via debit spread"
        elif vol_pct <= low_vol and vote_imbalance < 0.35:
            strategy = "LONG_STRADDLE_PROXY"
            strategy_fit = 0.76
            strategy_note = "Low vol + weak direction -> breakout optionality"
        else:
            strategy = "DIRECTIONAL_DEBIT_SPREAD" if vote_imbalance >= 0.35 else "SKIP"
            strategy_fit = 0.65 if vote_imbalance >= 0.35 else 0.42
            strategy_note = "No strong vol edge"

        if strategy == "SKIP":
            return {
                "allow": False,
                "composite_score": 0.0,
                "recommended_leverage": 1,
                "recommended_strategy": strategy,
                "size_multiplier": config.OPTIONS_SIZE_MIN_MULT,
                "verdict": f"Options reject: {strategy_note}",
                "component_scores": {},
                "penalties": {},
                "hard_reject_reason": "weak_vol_edge",
            }

        momentum_dir = ((float(vel_result.get("velocity_1m", 0.0) or 0.0) * 0.7) + (float(vel_result.get("velocity_5m", 0.0) or 0.0) * 0.3))
        momentum_score = self._clamp(0.5 + ((momentum_dir * (1 if is_long else -1)) / 0.30))
        regime_score = self._clamp(regime_strength / max(config.OPTIONS_MIN_REGIME_STRENGTH * 2.5, 0.25))
        liquidity_score = self._clamp(
            ((volume_24h / max(config.OPTIONS_MIN_VOLUME_24H * 2.0, 1.0)) * 0.55)
            + (((config.OPTIONS_MAX_SPREAD_PCT - spread_pct) / max(config.OPTIONS_MAX_SPREAD_PCT, 0.001)) * 0.45)
        )
        if vol_pct <= low_vol:
            volatility_score = 0.92
        elif vol_pct >= high_vol:
            decay = (vol_pct - high_vol) / max(config.OPTIONS_EXTREME_VOL_PCT - high_vol, 0.01)
            volatility_score = self._clamp(0.92 - (decay * 0.30))
        else:
            volatility_score = 0.45
        session_map = {"PREMIUM": 1.0, "HIGH": 0.90, "MODERATE": 0.74, "LOW": 0.56}
        session_score = session_map.get(session_quality, 0.60)
        edge_score = self._clamp(expected_edge_pct / max(float(rl_cfg("MIN_EXPECTED_EDGE_PCT")) * 2.8, 0.25))
        rl_inf = self._rl_infer(
            mode="OPTIONS",
            regime=regime,
            session_quality=session_quality,
            volatility_pct=vol_pct,
            sentiment_score=sentiment_val,
            vote_imbalance=vote_imbalance,
            expected_edge_pct=expected_edge_pct,
        )

        weights = {
            "vote_imbalance": max(0.0, float(config.OPTIONS_WEIGHT_VOTE_IMBALANCE)),
            "regime": max(0.0, float(config.OPTIONS_WEIGHT_REGIME)),
            "momentum": max(0.0, float(config.OPTIONS_WEIGHT_MOMENTUM)),
            "volatility": max(0.0, float(config.OPTIONS_WEIGHT_VOLATILITY)),
            "liquidity": max(0.0, float(config.OPTIONS_WEIGHT_LIQUIDITY)),
            "sentiment": max(0.0, float(config.OPTIONS_WEIGHT_SENTIMENT)),
            "session": max(0.0, float(config.OPTIONS_WEIGHT_SESSION)),
            "edge": max(0.0, float(config.OPTIONS_WEIGHT_EDGE)),
        }
        weights = self._rl_apply_weight_multipliers(weights, rl_inf)
        w_sum = sum(weights.values()) or 1.0
        weighted_core = (
            weights["vote_imbalance"] * vote_imbalance
            + weights["regime"] * regime_score
            + weights["momentum"] * momentum_score
            + weights["volatility"] * volatility_score
            + weights["liquidity"] * liquidity_score
            + weights["sentiment"] * sentiment_score
            + weights["session"] * session_score
            + weights["edge"] * edge_score
        ) / w_sum

        confidence_score = self._clamp(confidence + float(rl_inf.get("confidence_bias", 0.0)))
        composite_score = self._clamp((weighted_core * 0.78) + (strategy_fit * 0.14) + (confidence_score * 0.08))

        penalties = {}
        if session_quality == "LOW":
            penalties["off_hours"] = config.OPTIONS_OFF_HOURS_PENALTY
            composite_score -= config.OPTIONS_OFF_HOURS_PENALTY
        _cons_losses = self.consecutive_losses.get("OPTIONS", 0)
        if _cons_losses > 0:
            loss_penalty = min(0.30, _cons_losses * config.OPTIONS_LOSS_STREAK_PENALTY)
            penalties["loss_streak"] = loss_penalty
            composite_score -= loss_penalty
        composite_score = self._clamp(composite_score)

        conf_gate = confidence >= config.OPTIONS_MIN_CONFIDENCE if enforce_confidence_gate else True
        allow = composite_score >= config.OPTIONS_MIN_COMPOSITE_SCORE and conf_gate
        score_span = self._clamp(
            (composite_score - config.OPTIONS_MIN_COMPOSITE_SCORE)
            / max(1.0 - config.OPTIONS_MIN_COMPOSITE_SCORE, 0.001)
        )
        size_span = max(config.OPTIONS_SIZE_MAX_MULT - config.OPTIONS_SIZE_MIN_MULT, 0.01)
        size_multiplier = config.OPTIONS_SIZE_MIN_MULT + (score_span * size_span)
        size_multiplier *= float(rl_inf.get("size_mult", 1.0) or 1.0)
        if _cons_losses >= 2:
            size_multiplier *= 0.75
        size_multiplier = max(config.OPTIONS_SIZE_MIN_MULT, min(config.OPTIONS_SIZE_MAX_MULT, size_multiplier))

        verdict = (
            f"Options score={composite_score:.3f} (min={config.OPTIONS_MIN_COMPOSITE_SCORE:.2f}) | "
            f"conf={confidence:.2f} | strat={strategy} | {strategy_note} | "
            f"RL:{rl_inf.get('profile_id')}/{rl_inf.get('decision_type')}"
        )
        return {
            "allow": allow,
            "composite_score": round(composite_score, 4),
            "recommended_leverage": 1,
            "recommended_strategy": strategy,
            "size_multiplier": round(size_multiplier, 4),
            "rl_profile_id": rl_inf.get("profile_id", ""),
            "rl_state_key": rl_inf.get("state_key", ""),
            "rl_decision_type": rl_inf.get("decision_type", ""),
            "verdict": verdict,
            "component_scores": {
                "vote_imbalance": round(vote_imbalance, 4),
                "regime": round(regime_score, 4),
                "momentum": round(momentum_score, 4),
                "volatility": round(volatility_score, 4),
                "liquidity": round(liquidity_score, 4),
                "sentiment": round(sentiment_score, 4),
                "session": round(session_score, 4),
                "edge": round(edge_score, 4),
                "strategy_fit": round(strategy_fit, 4),
                "confidence": round(confidence_score, 4),
                "spread_pct": round(spread_pct, 4),
                "volatility_pct": round(vol_pct, 4),
                "sentiment_raw": round(sentiment_val, 4),
                "articles_count": article_count,
                "rl_q_value": round(float(rl_inf.get("q_value", 0.0) or 0.0), 6),
            },
            "penalties": penalties,
            "hard_reject_reason": "",
        }

    def _spot_policy_decision(
        self,
        symbol: str,
        proposed_dir: str,
        buy_count: int,
        sell_count: int,
        total_vote_weight: float,
        confidence: float,
        expected_edge_pct: float,
        regime_result: dict,
        session_filt: dict,
        vol_result: dict,
        vol_prof: dict,
        sentiment_snapshot: dict,
        vel_result: dict,
        macd_result: dict,
        ema_result: dict,
        ob_result: dict,
        mode: str = None,
        enforce_confidence_gate: bool = True,
    ) -> dict:
        active_mode = str(mode or config.TRADING_PRODUCT).upper()
        if active_mode != "SPOT":
            return {
                "allow": True,
                "composite_score": 1.0,
                "recommended_leverage": 1,
                "recommended_strategy": "NON_SPOT_MODE",
                "size_multiplier": 1.0,
                "verdict": "Non-spot mode active",
                "component_scores": {},
                "penalties": {},
                "hard_reject_reason": "",
            }

        if config.SPOT_LONG_ONLY and proposed_dir != "LONG":
            return {
                "allow": False,
                "composite_score": 0.0,
                "recommended_leverage": 1,
                "recommended_strategy": "SPOT_LONG_ONLY_SKIP",
                "size_multiplier": config.SPOT_SIZE_MIN_MULT,
                "verdict": "Spot reject: long-only mode blocks SHORT entries",
                "component_scores": {},
                "penalties": {},
                "hard_reject_reason": "long_only",
            }

        confidence = self._clamp(confidence)
        regime = str(regime_result.get("regime", "UNKNOWN")).upper()
        regime_strength = float(regime_result.get("strength", 0.0) or 0.0)
        vol_pct = float(vol_result.get("volatility_pct", 0.0) or 0.0)
        spread_pct = float(vol_prof.get("spread_pct", 0.0) or 0.0)
        volume_24h = float(vol_prof.get("volume_24h", 0.0) or 0.0)
        session_quality = str(session_filt.get("quality", "LOW")).upper()
        vote_imbalance = self._clamp(abs(buy_count - sell_count) / max(total_vote_weight, 1.0))

        if spread_pct > config.SPOT_MAX_SPREAD_PCT:
            return {
                "allow": False,
                "composite_score": 0.0,
                "recommended_leverage": 1,
                "recommended_strategy": "SPOT_SKIP",
                "size_multiplier": config.SPOT_SIZE_MIN_MULT,
                "verdict": f"Spot reject: spread too wide {spread_pct:.3f}% > {config.SPOT_MAX_SPREAD_PCT:.3f}%",
                "component_scores": {},
                "penalties": {},
                "hard_reject_reason": "wide_spread",
            }
        if volume_24h < config.SPOT_MIN_VOLUME_24H:
            return {
                "allow": False,
                "composite_score": 0.0,
                "recommended_leverage": 1,
                "recommended_strategy": "SPOT_SKIP",
                "size_multiplier": config.SPOT_SIZE_MIN_MULT,
                "verdict": f"Spot reject: low liquidity volume {volume_24h:.2f} < {config.SPOT_MIN_VOLUME_24H:.2f}",
                "component_scores": {},
                "penalties": {},
                "hard_reject_reason": "low_liquidity",
            }
        if vol_pct > config.SPOT_EXTREME_VOL_PCT:
            return {
                "allow": False,
                "composite_score": 0.0,
                "recommended_leverage": 1,
                "recommended_strategy": "SPOT_SKIP",
                "size_multiplier": config.SPOT_SIZE_MIN_MULT,
                "verdict": f"Spot reject: extreme volatility {vol_pct:.3f}% > {config.SPOT_EXTREME_VOL_PCT:.3f}%",
                "component_scores": {},
                "penalties": {},
                "hard_reject_reason": "extreme_volatility",
            }

        sentiment_val = 0.0
        sentiment_score = 0.55
        article_count = 0
        if sentiment_snapshot:
            sentiment_val = float(sentiment_snapshot.get("sentiment_score", 0.0) or 0.0)
            comp = sentiment_snapshot.get("components", {}) or {}
            article_count = int(comp.get("articles_count", 0) or 0)
            if article_count >= config.SENTIMENT_MIN_ARTICLES:
                directional_sentiment = sentiment_val if proposed_dir == "LONG" else -sentiment_val
                sentiment_score = self._clamp(0.5 + directional_sentiment)
                if (
                    config.SPOT_BLOCK_ON_OPPOSING_SENTIMENT
                    and directional_sentiment < -config.SENTIMENT_DIRECTIONAL_FLOOR
                ):
                    return {
                        "allow": False,
                        "composite_score": 0.0,
                        "recommended_leverage": 1,
                        "recommended_strategy": "SPOT_SKIP",
                        "size_multiplier": config.SPOT_SIZE_MIN_MULT,
                        "verdict": (
                            f"Spot reject: sentiment opposes {proposed_dir} "
                            f"({sentiment_val:+.2f}, articles={article_count})"
                        ),
                        "component_scores": {},
                        "penalties": {},
                        "hard_reject_reason": "sentiment_conflict",
                    }

        regime_alignment = 0.4
        if regime == "BULL":
            regime_alignment = 1.0 if proposed_dir == "LONG" else 0.15
        elif regime == "BEAR":
            regime_alignment = 0.20 if proposed_dir == "LONG" else 1.0
        elif regime == "NEUTRAL":
            regime_alignment = 0.62
        elif regime == "CHOPPY":
            regime_alignment = 0.35
        trend_strength_score = self._clamp(regime_strength / max(config.SPOT_MIN_REGIME_STRENGTH * 3.0, 0.30))
        trend_score = self._clamp((regime_alignment * 0.62) + (trend_strength_score * 0.38))

        vel_1m = float(vel_result.get("velocity_1m", 0.0) or 0.0)
        vel_5m = float(vel_result.get("velocity_5m", 0.0) or 0.0)
        directional_vel = ((vel_1m * 0.7) + (vel_5m * 0.3)) * (1 if proposed_dir == "LONG" else -1)
        vel_score = self._clamp(0.5 + (directional_vel / 0.25))

        macd_signal = str(macd_result.get("crossover", "")).upper()
        if proposed_dir == "LONG":
            macd_score = 1.0 if "BULLISH_CROSS" in macd_signal else (0.82 if "BULL" in macd_signal else 0.28)
        else:
            macd_score = 1.0 if "BEARISH_CROSS" in macd_signal else (0.82 if "BEAR" in macd_signal else 0.28)

        ema_signal = str(ema_result.get("signal", "")).upper()
        if proposed_dir == "LONG":
            ema_score = 1.0 if ema_signal == "STRONG_BUY" else (0.82 if ema_signal == "BUY" else 0.30)
        else:
            ema_score = 1.0 if ema_signal == "STRONG_SELL" else (0.82 if ema_signal == "SELL" else 0.30)

        ob_bias = float(ob_result.get("bias", 0.0) or 0.0)
        directional_ob = ob_bias * (1 if proposed_dir == "LONG" else -1)
        ob_score = self._clamp(0.5 + (directional_ob / 0.12))
        momentum_score = self._clamp((vel_score * 0.40) + (macd_score * 0.30) + (ema_score * 0.20) + (ob_score * 0.10))

        low_vol = max(config.SPOT_TARGET_VOL_PCT_LOW, 0.0001)
        high_vol = max(config.SPOT_TARGET_VOL_PCT_HIGH, low_vol + 0.01)
        if vol_pct < low_vol:
            volatility_score = self._clamp(0.65 + ((vol_pct / low_vol) * 0.25))
        elif vol_pct <= high_vol:
            volatility_score = 1.0
        else:
            decay = (vol_pct - high_vol) / max(config.SPOT_EXTREME_VOL_PCT - high_vol, 0.01)
            volatility_score = self._clamp(1.0 - decay)

        volume_score = self._clamp(volume_24h / max(config.SPOT_MIN_VOLUME_24H * 2.0, 1.0))
        spread_score = self._clamp((config.SPOT_MAX_SPREAD_PCT - spread_pct) / max(config.SPOT_MAX_SPREAD_PCT, 0.001))
        liquidity_score = self._clamp((volume_score * 0.55) + (spread_score * 0.45))

        session_map = {"PREMIUM": 1.0, "HIGH": 0.90, "MODERATE": 0.76, "LOW": 0.58}
        session_score = session_map.get(session_quality, 0.62)

        session_stats = self.session_tracker.get_stats()
        win_rate_score = 0.50
        wr_text = str(session_stats.get("win_rate", "N/A"))
        if wr_text.endswith("%"):
            try:
                win_rate_score = self._clamp(0.5 + ((float(wr_text[:-1]) - 50.0) / 100.0))
            except Exception:
                win_rate_score = 0.50
        _cons_losses = self.consecutive_losses.get("SPOT", 0)
        performance_score = self._clamp(win_rate_score - (_cons_losses * 0.12))
        rl_inf = self._rl_infer(
            mode="SPOT",
            regime=regime,
            session_quality=session_quality,
            volatility_pct=vol_pct,
            sentiment_score=sentiment_val,
            vote_imbalance=vote_imbalance,
            expected_edge_pct=expected_edge_pct,
        )

        strategy = "SPOT_SELECTIVE_BUY"
        strategy_fit = 0.70
        strategy_note = "Selective long setup"
        if regime == "BULL" and vote_imbalance >= 0.35 and momentum_score >= 0.62:
            strategy = "SPOT_TREND_PULLBACK_BUY"
            strategy_fit = 0.92
            strategy_note = "Bull regime continuation"
        elif regime == "NEUTRAL" and vote_imbalance >= 0.45 and momentum_score >= 0.60 and vol_pct <= high_vol:
            strategy = "SPOT_BREAKOUT_BUY"
            strategy_fit = 0.84
            strategy_note = "Neutral-to-breakout impulse"
        elif regime == "BEAR" and sentiment_val > 0.20 and vol_pct <= high_vol * 0.8 and confidence >= config.SPOT_MIN_CONFIDENCE + 0.06:
            strategy = "SPOT_MEAN_REVERSION_SCALP"
            strategy_fit = 0.68
            strategy_note = "Bear regime contrarian scalp (small size)"
        elif regime == "CHOPPY":
            if vote_imbalance >= 0.35 and momentum_score >= 0.55:
                strategy = "SPOT_CHOPPY_BREAKOUT"
                strategy_fit = 0.58
                strategy_note = "Choppy with strong directional conviction"
            else:
                strategy = "SPOT_CHOPPY_CAUTIOUS"
                strategy_fit = 0.40
                strategy_note = "Choppy regime — reduced size"

        weights = {
            "trend": max(0.0, float(config.SPOT_WEIGHT_TREND)),
            "momentum": max(0.0, float(config.SPOT_WEIGHT_MOMENTUM)),
            "volatility": max(0.0, float(config.SPOT_WEIGHT_VOLATILITY)),
            "liquidity": max(0.0, float(config.SPOT_WEIGHT_LIQUIDITY)),
            "sentiment": max(0.0, float(config.SPOT_WEIGHT_SENTIMENT)),
            "session": max(0.0, float(config.SPOT_WEIGHT_SESSION)),
            "performance": max(0.0, float(config.SPOT_WEIGHT_PERFORMANCE)),
        }
        weights = self._rl_apply_weight_multipliers(weights, rl_inf)
        w_sum = sum(weights.values()) or 1.0
        weighted_core = (
            weights["trend"] * trend_score
            + weights["momentum"] * momentum_score
            + weights["volatility"] * volatility_score
            + weights["liquidity"] * liquidity_score
            + weights["sentiment"] * sentiment_score
            + weights["session"] * session_score
            + weights["performance"] * performance_score
        ) / w_sum

        edge_score = self._clamp(expected_edge_pct / max(float(rl_cfg("MIN_EXPECTED_EDGE_PCT")) * 2.5, 0.25))
        confidence_score = self._clamp(confidence + float(rl_inf.get("confidence_bias", 0.0)))
        composite_score = self._clamp((weighted_core * 0.80) + (strategy_fit * 0.10) + (edge_score * 0.05) + (confidence_score * 0.05))

        penalties = {}
        if session_quality == "LOW":
            penalties["off_hours"] = config.SPOT_OFF_HOURS_PENALTY
            composite_score -= config.SPOT_OFF_HOURS_PENALTY
        if _cons_losses > 0:
            loss_penalty = min(0.20, _cons_losses * config.SPOT_LOSS_STREAK_PENALTY)
            penalties["loss_streak"] = loss_penalty
            composite_score -= loss_penalty
        if strategy in ("SPOT_CHOPPY_CAUTIOUS", "SPOT_CHOPPY_BREAKOUT"):
            choppy_penalty = 0.05 if strategy == "SPOT_CHOPPY_CAUTIOUS" else 0.02
            penalties["choppy_regime"] = choppy_penalty
            composite_score -= choppy_penalty
        composite_score = self._clamp(composite_score)

        conf_gate = confidence >= config.SPOT_MIN_CONFIDENCE if enforce_confidence_gate else True
        allow = composite_score >= config.SPOT_MIN_COMPOSITE_SCORE and conf_gate
        score_span = self._clamp(
            (composite_score - config.SPOT_MIN_COMPOSITE_SCORE)
            / max(1.0 - config.SPOT_MIN_COMPOSITE_SCORE, 0.001)
        )
        size_span = max(config.SPOT_SIZE_MAX_MULT - config.SPOT_SIZE_MIN_MULT, 0.01)
        size_multiplier = config.SPOT_SIZE_MIN_MULT + (score_span * size_span)
        size_multiplier *= float(rl_inf.get("size_mult", 1.0) or 1.0)
        if strategy == "SPOT_MEAN_REVERSION_SCALP":
            size_multiplier = min(size_multiplier, 0.80)
        if strategy == "SPOT_CHOPPY_CAUTIOUS":
            size_multiplier = min(size_multiplier, 0.65)
        elif strategy == "SPOT_CHOPPY_BREAKOUT":
            size_multiplier = min(size_multiplier, 0.85)
        if _cons_losses >= 2:
            size_multiplier *= 0.75
        size_multiplier = max(config.SPOT_SIZE_MIN_MULT, min(config.SPOT_SIZE_MAX_MULT, size_multiplier))

        verdict = (
            f"Spot score={composite_score:.3f} (min={config.SPOT_MIN_COMPOSITE_SCORE:.2f}) | "
            f"conf={confidence:.2f} | strat={strategy} | {strategy_note} | "
            f"RL:{rl_inf.get('profile_id')}/{rl_inf.get('decision_type')}"
        )
        return {
            "allow": allow,
            "composite_score": round(composite_score, 4),
            "recommended_leverage": 1,
            "recommended_strategy": strategy,
            "size_multiplier": round(size_multiplier, 4),
            "rl_profile_id": rl_inf.get("profile_id", ""),
            "rl_state_key": rl_inf.get("state_key", ""),
            "rl_decision_type": rl_inf.get("decision_type", ""),
            "verdict": verdict,
            "component_scores": {
                "trend": round(trend_score, 4),
                "vote_imbalance": round(vote_imbalance, 4),
                "regime_strength": round(trend_strength_score, 4),
                "momentum": round(momentum_score, 4),
                "volatility": round(volatility_score, 4),
                "liquidity": round(liquidity_score, 4),
                "sentiment": round(sentiment_score, 4),
                "session": round(session_score, 4),
                "performance": round(performance_score, 4),
                "strategy_fit": round(strategy_fit, 4),
                "edge": round(edge_score, 4),
                "confidence": round(confidence_score, 4),
                "spread_pct": round(spread_pct, 4),
                "volatility_pct": round(vol_pct, 4),
                "sentiment_raw": round(sentiment_val, 4),
                "articles_count": article_count,
                "rl_q_value": round(float(rl_inf.get("q_value", 0.0) or 0.0), 6),
            },
            "penalties": penalties,
            "hard_reject_reason": "",
        }

    def _product_policy_decision(self, mode: str = None, total_vote_weight: float = 8.0, **kwargs) -> dict:
        active_mode = str(mode or config.TRADING_PRODUCT).upper()
        # 'stage' is consumed by the caller for logging, not by policy methods
        kwargs.pop("stage", None)
        if active_mode == "FUTURES":
            return self._futures_policy_decision(mode=active_mode, total_vote_weight=total_vote_weight, **kwargs)
        if active_mode == "OPTIONS":
            return self._options_policy_decision(mode=active_mode, total_vote_weight=total_vote_weight, **kwargs)
        return self._spot_policy_decision(mode=active_mode, total_vote_weight=total_vote_weight, **kwargs)

    def _log_futures_eval(self, symbol: str, stage: str, eval_result: dict, mode: str = None):
        active_mode = str(mode or config.TRADING_PRODUCT).upper()
        if active_mode != "FUTURES":
            return
        comps = eval_result.get("component_scores") or {}
        penalties = eval_result.get("penalties") or {}
        logger.info(
            "FUTURES_EVAL stage=%s symbol=%s allow=%s score=%.3f lev=%sx verdict=%s components=%s penalties=%s",
            stage,
            symbol,
            eval_result.get("allow"),
            float(eval_result.get("composite_score", 0.0) or 0.0),
            int(eval_result.get("recommended_leverage", 1) or 1),
            eval_result.get("verdict", ""),
            comps,
            penalties,
        )

    def _log_options_eval(self, symbol: str, stage: str, eval_result: dict, mode: str = None):
        active_mode = str(mode or config.TRADING_PRODUCT).upper()
        if active_mode != "OPTIONS":
            return
        comps = eval_result.get("component_scores") or {}
        penalties = eval_result.get("penalties") or {}
        logger.info(
            "OPTIONS_EVAL stage=%s symbol=%s allow=%s score=%.3f strategy=%s verdict=%s components=%s penalties=%s",
            stage,
            symbol,
            eval_result.get("allow"),
            float(eval_result.get("composite_score", 0.0) or 0.0),
            eval_result.get("recommended_strategy", "N/A"),
            eval_result.get("verdict", ""),
            comps,
            penalties,
        )

    def _log_spot_eval(self, symbol: str, stage: str, eval_result: dict, mode: str = None):
        active_mode = str(mode or config.TRADING_PRODUCT).upper()
        if active_mode != "SPOT":
            return
        comps = eval_result.get("component_scores") or {}
        penalties = eval_result.get("penalties") or {}
        logger.info(
            "SPOT_EVAL stage=%s symbol=%s allow=%s score=%.3f strategy=%s verdict=%s components=%s penalties=%s",
            stage,
            symbol,
            eval_result.get("allow"),
            float(eval_result.get("composite_score", 0.0) or 0.0),
            eval_result.get("recommended_strategy", "N/A"),
            eval_result.get("verdict", ""),
            comps,
            penalties,
        )

    def _log_product_eval(self, symbol: str, stage: str, eval_result: dict, mode: str = None):
        active_mode = str(mode or config.TRADING_PRODUCT).upper()
        if active_mode == "FUTURES":
            self._log_futures_eval(symbol, stage, eval_result, mode=active_mode)
        elif active_mode == "OPTIONS":
            self._log_options_eval(symbol, stage, eval_result, mode=active_mode)
        elif active_mode == "SPOT":
            self._log_spot_eval(symbol, stage, eval_result, mode=active_mode)

    def _evaluate_product_policies_parallel(self, symbol: str, stage: str, **kwargs) -> dict:
        products = (
            list(self.parallel_products)
            if self.enable_parallel_products
            else [str(config.TRADING_PRODUCT).upper()]
        )
        products = [p for p in products if p in {"SPOT", "FUTURES", "OPTIONS"}]
        if not products:
            products = [str(config.TRADING_PRODUCT).upper()]

        results = {}
        if len(products) == 1:
            mode = products[0]
            result = self._product_policy_decision(mode=mode, **kwargs)
            result = self._attach_rl_metadata(mode, result, kwargs)
            self._log_product_eval(symbol, stage, result, mode=mode)
            results[mode] = result
            return results

        futures_map = {}
        for mode in products:
            fut = self.policy_executor.submit(self._product_policy_decision, mode=mode, **kwargs)
            futures_map[fut] = mode

        for fut in as_completed(futures_map):
            mode = futures_map[fut]
            try:
                result = fut.result()
            except Exception as e:
                logger.error("Policy evaluation failed mode=%s symbol=%s stage=%s err=%s", mode, symbol, stage, e, exc_info=True)
                result = {
                    "allow": False,
                    "composite_score": 0.0,
                    "recommended_leverage": 1,
                    "recommended_strategy": "ERROR",
                    "size_multiplier": 1.0,
                    "verdict": f"{mode} policy failed: {e}",
                    "component_scores": {},
                    "penalties": {},
                    "hard_reject_reason": "policy_error",
                }
            result = self._attach_rl_metadata(mode, result, kwargs)
            self._log_product_eval(symbol, stage, result, mode=mode)
            results[mode] = result
        return results

    def _check_kill_switch(self, latest_prices: dict | None = None) -> tuple:
        equity = self.simulator.total_equity(latest_prices)
        drawdown = max(0.0, self.session_start_balance - equity)
        if drawdown >= config.MAX_DAILY_DRAWDOWN_USD:
            return True, f"Kill-switch: drawdown ${drawdown:.2f} >= ${config.MAX_DAILY_DRAWDOWN_USD:.2f}"

        spend_today = get_llm_cost_today()
        if spend_today >= config.LLM_DAILY_BUDGET_USD:
            return True, f"Kill-switch: LLM budget exceeded (${spend_today:.2f})"

        max_cons = max(self.consecutive_losses.get(m, 0) for m in ("SPOT", "FUTURES", "OPTIONS"))
        if max_cons >= config.MAX_CONSECUTIVE_LOSSES:
            return True, f"Kill-switch: consecutive losses {max_cons}"

        return False, ""

    def _save_portfolio_snapshot(self, trigger: str = "EVENT"):
        """Persist a full portfolio snapshot: cash, equity, per-asset values, PnL, win-rate, missed."""
        try:
            bal = float(self.simulator.balance_usdt or 0.0)
            realized = float(self.total_session_pnl or 0.0)
            wins = int(self.session_tracker.wins or 0)
            losses = int(self.session_tracker.losses or 0)
            missed = int(self.missed_opportunities_count or 0)
            total_trades = int(self.trades_executed or 0)

            positions_data = []
            unrealized_total = 0.0
            now = datetime.now()
            for pos_key, pos in list(self.simulator.positions.items()):
                symbol = pos.get("symbol", "")
                entry_price = float(pos.get("entry_price", 0.0) or 0.0)
                qty = float(pos.get("quantity", 0.0) or 0.0)
                cur_price = float(self._latest_prices.get(symbol, entry_price) or entry_price)
                side = pos.get("side", "LONG")
                mode = pos.get("mode", "SPOT")
                notional = qty * entry_price
                cur_value = qty * cur_price
                unrealized = (cur_price - entry_price) * qty if side == "LONG" else (entry_price - cur_price) * qty
                unrealized_pct = round(unrealized / notional * 100, 3) if notional > 0 else 0.0
                hold_secs = int((now - pos.get("entry_time", now)).total_seconds())
                unrealized_total += unrealized
                rl_ctx = pos.get("rl_context") or {}
                positions_data.append({
                    "key": pos_key,
                    "symbol": symbol,
                    "mode": mode,
                    "side": side,
                    "entry_price": round(entry_price, 6),
                    "current_price": round(cur_price, 6),
                    "quantity": round(qty, 6),
                    "notional_usd": round(notional, 2),
                    "current_usd_value": round(cur_value, 2),
                    "unrealized_pnl": round(unrealized, 4),
                    "unrealized_pnl_pct": unrealized_pct,
                    "hold_secs": hold_secs,
                    "entry_reason": (pos.get("entry_reason") or "")[:120],
                    "rl_profile": rl_ctx.get("profile_id", ""),
                    "rl_decision": rl_ctx.get("decision_type", ""),
                })

            total_equity = bal + sum(p["current_usd_value"] for p in positions_data)

            # Summarize open assets log
            if positions_data:
                asset_lines = "  ".join(
                    f"{p['symbol']} {p['side']} {p['mode']} ${p['current_usd_value']:.2f} "
                    f"(PnL {p['unrealized_pnl_pct']:+.2f}%)"
                    for p in positions_data
                )
                logger.info(
                    "PORTFOLIO [%s]  cash=$%.2f  equity=$%.2f  realized=%+.2f  unrealized=%+.2f  "
                    "W/L=%d/%d (%.0f%%)  trades=%d  missed=%d  open=%d\n"
                    "  assets: %s",
                    trigger, bal, total_equity, realized, unrealized_total,
                    wins, losses, (wins / (wins + losses) * 100 if (wins + losses) > 0 else 0),
                    total_trades, missed, len(positions_data),
                    asset_lines,
                )
            else:
                logger.info(
                    "PORTFOLIO [%s]  cash=$%.2f  equity=$%.2f  realized=%+.2f  unrealized=%+.2f  "
                    "W/L=%d/%d (%.0f%%)  trades=%d  missed=%d  open=0",
                    trigger, bal, total_equity, realized, unrealized_total,
                    wins, losses, (wins / (wins + losses) * 100 if (wins + losses) > 0 else 0),
                    total_trades, missed,
                )

            save_portfolio_full_snapshot(
                balance_usdt=bal,
                total_equity=total_equity,
                realized_pnl=realized,
                unrealized_pnl=unrealized_total,
                win_count=wins,
                loss_count=losses,
                total_trades=total_trades,
                missed_count=missed,
                open_positions_count=len(positions_data),
                positions=positions_data,
                trigger=trigger,
            )
        except Exception as _snap_err:
            logger.warning("Portfolio snapshot failed (%s): %s", trigger, _snap_err)

    async def _close_trade(self, symbol, current_price, reason, mode: str = None):
        """Helper to close a position and run retrospective."""
        active_mode = str(mode or config.TRADING_PRODUCT).upper()
        pos_key = self._pos_key(symbol, active_mode)
        pos_ctx = dict(self.simulator.positions.get(pos_key, {}) or {})
        trade_result = self.simulator.exit_position(symbol, current_price, reason, mode=active_mode)
        if trade_result:
            self.total_session_pnl += trade_result["pnl"]
            self.trades_closed += 1
            self.trades_closed_by_mode[active_mode] = int(self.trades_closed_by_mode.get(active_mode, 0) or 0) + 1
            self.session_tracker.record_trade(trade_result["pnl"])
            self.last_close_time_by_mode[active_mode] = datetime.now()  # Fix 5: record close time for cooldown

            # ── Record for duplicate-entry guard ──
            self.last_entry_prices[pos_key] = (
                trade_result["entry_price"], trade_result["side"], datetime.now()
            )

            # ── Direction block: if this is a loss, track consecutive losses per direction ──
            if trade_result["pnl"] <= 0:
                self.consecutive_losses[active_mode] = self.consecutive_losses.get(active_mode, 0) + 1
                side = trade_result["side"]
                block_key = f"{pos_key}_{side}"
                self._loss_streak = getattr(self, '_loss_streak', {})
                self._loss_streak[block_key] = self._loss_streak.get(block_key, 0) + 1
                if self._loss_streak[block_key] >= 2:
                    block_until = datetime.now() + timedelta(seconds=600)  # 10 min block
                    self.direction_block[pos_key] = {"side": side, "blocked_until": block_until}
                    logger.warning(f"🚫 DIRECTION BLOCK: {side} on {symbol} for 10 min after {self._loss_streak[block_key]} consecutive losses")
                    self._loss_streak[block_key] = 0  # reset after block
            else:
                self.consecutive_losses[active_mode] = 0
                # Win — reset the loss streak for this symbol's direction
                side = trade_result["side"]
                block_key = f"{pos_key}_{side}"
                self._loss_streak = getattr(self, '_loss_streak', {})
                self._loss_streak[block_key] = 0
                # Clear any direction block if we just won
                if self.direction_block.get(pos_key, {}).get("side") == side:
                    self.direction_block.pop(pos_key, None)

            # ── RL reward update (profit/loss + opportunity cost penalty) ──
            rl_ctx = (pos_ctx.get("rl_context") or self._pending_rl_by_symbol.get(pos_key) or {})
            rl_mode = str(rl_ctx.get("mode", "") or "")
            rl_state_key = str(rl_ctx.get("state_key", "") or "")
            rl_profile_id = str(rl_ctx.get("profile_id", "") or "")
            if rl_mode and rl_state_key and rl_profile_id:
                notional = float(
                    rl_ctx.get("entry_notional_usdt")
                    or pos_ctx.get("original_pos_usdt")
                    or ((pos_ctx.get("quantity", 0.0) or 0.0) * (pos_ctx.get("entry_price", 0.0) or 0.0))
                    or 1.0
                )
                notional = max(1.0, notional)
                pnl_usd = float(trade_result.get("pnl", 0.0) or 0.0)
                pnl_reward = pnl_usd / notional
                
                # Apply reward multipliers: heavily favor wins, keep losses 1:1
                if pnl_reward > 0:
                    pnl_reward *= float(rl_cfg("RL_PROFIT_REWARD_MULTIPLIER"))  # 3x boost for profits
                elif pnl_reward < 0:
                    pnl_reward *= float(rl_cfg("RL_LOSS_PENALTY_MULTIPLIER"))  # 1x for losses
                
                hold_secs = float(trade_result.get("hold_secs", 0) or 0)
                raw_opp_cost_penalty = float(rl_cfg("RL_OPEN_TRADE_COST_PENALTY")) * max(1.5, hold_secs / 180.0)
                opp_cap = self._rl_loss_penalty_cap(pnl_reward / max(1.0, float(rl_cfg("RL_PROFIT_REWARD_MULTIPLIER")) if pnl_reward > 0 else 1.0))
                opp_cost_penalty = min(raw_opp_cost_penalty, opp_cap)
                reward = pnl_reward - opp_cost_penalty
                self.rl_agent.update(rl_mode, rl_state_key, rl_profile_id, reward)
                self.rl_updates_by_mode[rl_mode] = int(self.rl_updates_by_mode.get(rl_mode, 0) or 0) + 1
                self.rl_trade_rewards_by_mode[rl_mode] = int(self.rl_trade_rewards_by_mode.get(rl_mode, 0) or 0) + 1
                save_rl_event(
                    mode=rl_mode,
                    profile_id=rl_profile_id,
                    state_key=rl_state_key,
                    event_type="TRADE_CLOSE_REWARD",
                    reason=trade_result.get("entry_reason"),
                    symbol=symbol,
                    reward=reward,
                    penalty=opp_cost_penalty,
                    raw_penalty=raw_opp_cost_penalty,
                    pnl_reward=pnl_reward,
                    hold_secs=hold_secs,
                )
                logger.info(
                    "RL_TRADE_REWARD mode=%s profile=%s pnl=%.4f notional=%.2f hold_secs=%s pnl_reward=%.6f raw_opp=%.6f cap=%.6f reward=%.6f",
                    rl_mode,
                    rl_profile_id,
                    pnl_usd,
                    notional,
                    int(hold_secs),
                    pnl_reward,
                    raw_opp_cost_penalty,
                    opp_cap,
                    reward,
                )
            self._pending_rl_by_symbol.pop(pos_key, None)

            # ── Persist full portfolio accounting after every close ──
            self._save_portfolio_snapshot(trigger="EXIT")

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

    async def run_loop(self, mode: str = None):
        active_mode = str(mode or config.TRADING_PRODUCT).upper()
        if active_mode not in {"SPOT", "FUTURES", "OPTIONS"}:
            active_mode = "SPOT"
        self.skipped_cycles_by_mode.setdefault(active_mode, 0)
        def intent(message, targets):
            update_intent(message, targets, mode=active_mode)
        logger.info(f"Starting Session ({config.MAX_TRADES_RUN} trades max) mode={active_mode}...")
        primary_symbol = sorted(self.allowed_symbols)[0]

        # ── Warmup: fetch historical klines to reduce startup wait ──
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

                min_ticks = max(5, int(config.WARMUP_MIN_TICKS))
                ticks_ready = len(self.price_history.get(primary_symbol, [])) if self.price_history else 0
                if ticks_ready < min_ticks:
                    intent(f"Warming up... ({ticks_ready}/{min_ticks} ticks)", [])
                    await asyncio.sleep(config.CHECK_INTERVAL_SECONDS)
                    continue

                prices = self.client.latest_prices
                self._latest_prices.update(prices)  # keep rolling snapshot for portfolio valuation

                kill, reason = self._check_kill_switch(prices)
                if kill and not self.trading_halted_reason:
                    self.trading_halted_reason = reason
                    logger.error(reason)
                    intent(f"🛑 {reason}", [])

                # ── 1. Manage open positions ──────────────────────────────────
                for pos_key, pos in list(self.simulator.positions.items()):
                    if str(pos.get("mode", "")).upper() != active_mode:
                        continue
                    symbol = pos.get("symbol")
                    if not symbol or symbol not in prices:
                        continue

                    current_price = prices[symbol]
                    hold_secs = int((datetime.now() - pos["entry_time"]).total_seconds())
                    entry = pos["entry_price"]

                    if pos["side"] == "LONG":
                        pnl_pct = (current_price - entry) / entry
                    else:
                        pnl_pct = (entry - current_price) / entry

                    if self.trading_halted_reason:
                        await self._close_trade(symbol, current_price, f"🛑 Kill-switch exit: {self.trading_halted_reason}", mode=active_mode)
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
                                    added = self.simulator.add_to_position(
                                        symbol,
                                        current_price,
                                        add_usdt,
                                        f"🔺 Pyramid #{pyramid_count + 1}",
                                        mode=active_mode,
                                    )
                                    if added:
                                        pos["pyramid_count"] = pyramid_count + 1
                                        pos["original_pos_usdt"] = int(pos.get("original_pos_usdt", 125) + add_usdt)
                                        logger.info(f"🔺 PYRAMID #{pyramid_count+1}: Added ${add_usdt:,} to {pos['side']} {symbol} at {pnl_pct*100:+.2f}%")

                    # ── Fix 3: MINIMUM HOLD TIME (300s) ────────────────────
                    # Allow 1m candles enough time to breathe. Force 5m minimum.
                    min_hold_met = hold_secs >= 120

                    # ── TAKE PROFIT ──
                    if min_hold_met and pnl_pct >= tp_pct:
                        await self._close_trade(symbol, current_price, f"✅ Take-Profit ({pnl_pct*100:+.3f}%)", mode=active_mode)
                        continue

                    # ── TRAILING STOP ──
                    if min_hold_met and pos["trailing_active"]:
                        trail_stop = pos["peak_pnl_pct"] - config.TRAILING_STOP_OFFSET_PCT
                        if pnl_pct < trail_stop:
                            await self._close_trade(
                                symbol,
                                current_price,
                                f"📉 Trailing Stop (peak: {pos['peak_pnl_pct']*100:+.3f}% → now: {pnl_pct*100:+.3f}%)",
                                mode=active_mode,
                            )
                            continue

                    # ── EARLY STOP-LOSS ──
                    if min_hold_met and pnl_pct < -sl_pct:
                        await self._close_trade(symbol, current_price, f"⛔ Stop-Loss ({pnl_pct*100:.3f}%)", mode=active_mode)
                        continue

                    # ── TIME EXIT (always applies, ignores min hold) ──
                    if hold_secs >= config.MANDATORY_EXIT_SECONDS:
                        await self._close_trade(symbol, current_price, f"⏰ Time Exit ({config.MANDATORY_EXIT_SECONDS}s)", mode=active_mode)
                        continue

                    remaining = config.MANDATORY_EXIT_SECONDS - hold_secs
                    trailing_label = " | 🔔 TRAILING" if pos["trailing_active"] else ""
                    pos_mode = str(pos.get("selected_product", active_mode)).upper()
                    leverage_label = ""
                    if pos_mode == "FUTURES":
                        leverage_label = f" | Lev:{int(pos.get('recommended_leverage', 1))}x"
                    elif pos_mode == "OPTIONS":
                        leverage_label = f" | Strat:{pos.get('options_strategy', 'N/A')}"
                    elif pos_mode == "SPOT":
                        leverage_label = f" | Strat:{pos.get('spot_strategy', 'SPOT_FLOW')}"
                    intent(
                        f"Holding {pos['side']} {symbol} | PnL: {pnl_pct*100:+.3f}% (SL:{sl_pct*100:.2f}%/TP:{tp_pct*100:.2f}%) | {remaining}s{trailing_label}{leverage_label}",
                        [symbol]
                    )

                # ── 2. Enter new positions ────────────────────────────────────
                open_positions = self._positions_for_mode(active_mode)
                if len(open_positions) < config.MAX_POSITIONS and self.trades_closed < config.MAX_TRADES_RUN:
                    if self.trading_halted_reason:
                        intent(f"🛑 Trading halted: {self.trading_halted_reason}", [])
                        break

                    # Symbols that already have an open position in this mode
                    symbols_with_positions = {v["symbol"] for v in open_positions.values()}

                    for symbol in sorted(self.allowed_symbols):
                        # Stop scanning if we've filled all slots this cycle
                        if len(self._positions_for_mode(active_mode)) >= config.MAX_POSITIONS:
                            break

                        # Skip symbols that already have an open position in this mode
                        if symbol in symbols_with_positions:
                            continue

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
                            self.skipped_cycles_by_mode[active_mode] += 1
                            if self.skipped_cycles_by_mode[active_mode] % 12 == 1:
                                intent(f"⏳ Market dead (vol: {vol_result['volatility_pct']:.4f}%). Skipped {self.skipped_cycles_by_mode[active_mode]}x", [symbol])
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

                        raw_buy_count, raw_sell_count = self._count_pro_signals(
                            rsi_result, macd_result, bb_result, sr_result, candle_result,
                            stochrsi_result, ema_result, volmom_result
                        )

                        regime_result = self._safe_tool_call(
                            "MarketRegimeDetector",
                            lambda: MarketRegimeDetector.analyze(history),
                            {"regime": "UNKNOWN", "trade_direction": "ANY", "strength": 0.0, "verdict": "Tool error"},
                        )
                        regime = regime_result["regime"]
                        allowed_dir = regime_result["trade_direction"]

                        vote_imbalance_raw = abs(raw_buy_count - raw_sell_count) / 8.0
                        rl_vote_inf = self._rl_infer(
                            mode=active_mode,
                            regime=str(regime_result.get("regime", "UNKNOWN")).upper(),
                            session_quality=str(session_filt.get("quality", "LOW")).upper(),
                            volatility_pct=float(vol_result.get("volatility_pct", 0.0) or 0.0),
                            sentiment_score=0.0,
                            vote_imbalance=vote_imbalance_raw,
                            expected_edge_pct=0.0,
                        )
                        buy_count, sell_count, raw_buy_count, raw_sell_count, total_vote_weight = self._weighted_vote_counts(
                            rsi_result, macd_result, bb_result, sr_result, candle_result,
                            stochrsi_result, ema_result, volmom_result,
                            vote_weights=rl_vote_inf.get("voter_weight_mult", {}),
                        )
                        explore = self._exploration_state(active_mode)
                        under_sampled = bool(explore["under_sampled"])
                        force_entry = bool(explore["force_entry"])
                        min_pro_needed_weighted = min_pro_needed * (total_vote_weight / 8.0)
                        skip_streak = int(explore["skip_streak"])
                        skip_pressure = max(
                            0.0,
                            min(
                                float(rl_cfg("RL_SKIP_PRESSURE_MAX")),
                                float(skip_streak - int(rl_cfg("RL_SKIP_PRESSURE_START"))) * float(rl_cfg("RL_SKIP_PRESSURE_STEP")),
                            ),
                        )
                        if under_sampled:
                            min_pro_needed_weighted = max(
                                0.8,
                                min_pro_needed_weighted * float(rl_cfg("RL_UNDERSAMPLED_MIN_PRO_MULT")),
                            )
                        if skip_pressure > 0:
                            min_pro_needed_weighted = max(1.0, min_pro_needed_weighted * (1.0 - skip_pressure))

                        # ── OPPORTUNITY PRE-FILTER (session-adjusted signal bar) ─
                        if buy_count < min_pro_needed_weighted and sell_count < min_pro_needed_weighted:
                            if force_entry:
                                intent(
                                    f"⚡ Exploration override [{active_mode}]: forcing setup evaluation after {skip_streak} skips.",
                                    [symbol],
                                )
                            else:
                                self.skipped_cycles_by_mode[active_mode] += 1
                                best = max(buy_count, sell_count)
                                if self.skipped_cycles_by_mode[active_mode] % 6 == 1:
                                    intent(
                                        f"⏳ Waiting for setup ({best:.1f}/{min_pro_needed_weighted:.1f} pro signals) [{session_filt['session']}]. RSI:{rsi_result['rsi']:.1f} | {macd_result['crossover']} | BB:{bb_result['position_pct']:.0f}%",
                                        [symbol]
                                    )
                                if self.skipped_cycles_by_mode[active_mode] % 3 == 0:
                                    save_signal_event(
                                        symbol,
                                        current_price,
                                        raw_buy_count,
                                        raw_sell_count,
                                        buy_count,
                                        sell_count,
                                        total_vote_weight,
                                        rsi_result["rsi"],
                                        macd_result["crossover"],
                                        bb_result["position_pct"],
                                        "SKIPPED",
                                        decision_source=self._mode_decision_source(active_mode, "SETUP_WAIT"),
                                    )
                                continue

                        # ── Direction: 2+ signals for LONG, 2+ for SHORT ───
                        # Quality enforced by confidence floor (0.70) + duplicate blocker (120s)
                        dir_threshold = 2.0 * (total_vote_weight / 8.0)
                        if under_sampled:
                            dir_threshold = max(
                                0.8,
                                dir_threshold * float(rl_cfg("RL_UNDERSAMPLED_DIR_THRESHOLD_MULT")),
                            )
                        if skip_pressure > 0:
                            dir_threshold = max(1.0, dir_threshold * (1.0 - (skip_pressure * 0.85)))
                        if sell_count >= dir_threshold and sell_count > buy_count:
                            proposed_dir = "SHORT"
                        elif buy_count >= dir_threshold and buy_count >= sell_count:
                            proposed_dir = "LONG"
                        else:
                            if force_entry:
                                proposed_dir = "LONG" if buy_count >= sell_count else "SHORT"
                                intent(
                                    f"⚡ Exploration override [{active_mode}]: forcing {proposed_dir} despite low directional edge.",
                                    [symbol],
                                )
                            else:
                                self.skipped_cycles_by_mode[active_mode] += 1
                                directional_action = "LONG" if buy_count > sell_count else ("SHORT" if sell_count > buy_count else "NEUTRAL")
                                directional_conf = max(buy_count, sell_count) / max(total_vote_weight, 1.0)
                                save_signal_event(
                                    symbol,
                                    current_price,
                                    raw_buy_count,
                                    raw_sell_count,
                                    buy_count,
                                    sell_count,
                                    total_vote_weight,
                                    rsi_result["rsi"],
                                    macd_result["crossover"],
                                    bb_result["position_pct"],
                                    "SKIPPED",
                                    decision_source=self._mode_decision_source(active_mode, "DIRECTIONAL_EDGE_REJECT"),
                                    deterministic_action=directional_action if directional_action != "NEUTRAL" else None,
                                    deterministic_conf=directional_conf,
                                )
                                continue  # Not enough signals for either direction

                        det_action, det_conf, det_reason = self._deterministic_decision(buy_count, sell_count, total_vote_weight)
                        deterministic_dir = "LONG" if det_action == "BUY" else ("SHORT" if det_action == "SELL" else "NEUTRAL")
                        if det_action == "NEUTRAL":
                            if force_entry:
                                det_action = "BUY" if proposed_dir == "LONG" else "SELL"
                                det_conf = max(float(det_conf or 0.0), 0.51)
                                det_reason = f"{det_reason} | exploration_override"
                                deterministic_dir = proposed_dir
                            else:
                                self.skipped_cycles_by_mode[active_mode] += 1
                                save_signal_event(
                                    symbol,
                                    current_price,
                                    raw_buy_count,
                                    raw_sell_count,
                                    buy_count,
                                    sell_count,
                                    total_vote_weight,
                                    rsi_result["rsi"],
                                    macd_result["crossover"],
                                    bb_result["position_pct"],
                                    "SKIPPED",
                                    decision_source=self._mode_decision_source(active_mode, "DETERMINISTIC_NEUTRAL"),
                                    deterministic_action=deterministic_dir,
                                    deterministic_conf=det_conf,
                                )
                                continue

                        # ── v6: MARKET REGIME FILTER ───────────────────────
                        # Use dynamic ATR-based TP/SL when available for a more
                        # realistic edge estimate; fall back to config defaults.
                        # IMPORTANT: Use max(config, ATR) — ATR on 1-min tick
                        # data yields tiny values that get floor-clamped; when
                        # those floor values are smaller than config targets the
                        # fee term dominates and edges go permanently negative.
                        _bl_tp = config.TAKE_PROFIT_PCT
                        _bl_sl = config.EARLY_STOP_LOSS_PCT
                        _bl_atr = self._safe_tool_call(
                            "ATRTracker_baseline",
                            lambda: ATRTracker.analyze(history),
                            None,
                        )
                        if _bl_atr and _bl_atr.get("take_profit_pct"):
                            _bl_tp = max(_bl_tp, _bl_atr["take_profit_pct"])
                            _bl_sl = max(_bl_sl, _bl_atr["stop_loss_pct"])
                        baseline_edge_pct = self._estimate_expected_edge_pct(
                            buy_count,
                            sell_count,
                            _bl_tp,
                            _bl_sl,
                            total_vote_weight,
                        )

                        if regime == "CHOPPY":
                            vote_imbalance = abs(buy_count - sell_count) / max(total_vote_weight, 1.0)
                            if (
                                not config.ALLOW_CHOPPY_HIGH_CONVICTION
                                or vote_imbalance < config.CHOPPY_MIN_VOTE_IMBALANCE
                                or max(det_conf, 0.0) < config.CHOPPY_MIN_CONFIDENCE
                            ):
                                self.skipped_cycles_by_mode[active_mode] += 1
                                intent(
                                    f"🌊 CHOPPY regime — skip weak setup. "
                                    f"Need vote_imbalance>={config.CHOPPY_MIN_VOTE_IMBALANCE:.2f}, "
                                    f"conf>={config.CHOPPY_MIN_CONFIDENCE:.2f}. {regime_result['verdict']}",
                                    [symbol],
                                )
                                save_signal_event(
                                    symbol,
                                    current_price,
                                    raw_buy_count,
                                    raw_sell_count,
                                    buy_count,
                                    sell_count,
                                    total_vote_weight,
                                    rsi_result["rsi"],
                                    macd_result["crossover"],
                                    bb_result["position_pct"],
                                    "SKIPPED",
                                    decision_source=self._mode_decision_source(active_mode, "REGIME_CHOPPY_SKIP"),
                                    deterministic_action=deterministic_dir,
                                    deterministic_conf=det_conf,
                                )
                                self._rl_penalize_skip(
                                    mode=active_mode,
                                    reason="regime_choppy_skip",
                                    expected_edge_pct=baseline_edge_pct,
                                    symbol=symbol,
                                    regime_result=regime_result,
                                    session_filt=session_filt,
                                    vol_result=vol_result,
                                    sentiment_snapshot=None,
                                    buy_count=buy_count,
                                    sell_count=sell_count,
                                    total_vote_weight=total_vote_weight,
                                )
                                continue
                            intent(
                                f"⚡ CHOPPY override — high-conviction setup allowed "
                                f"({vote_imbalance:.2f} imbalance, conf {det_conf:.2f}).",
                                [symbol],
                            )

                        if allowed_dir not in ("ANY", proposed_dir):
                            if (
                                skip_pressure > 0
                                and baseline_edge_pct >= float(rl_cfg("RL_SKIP_PRESSURE_EDGE_MIN"))
                                and max(buy_count, sell_count) >= dir_threshold
                            ):
                                intent(
                                    f"⚡ Skip-pressure override: bypassing regime mismatch "
                                    f"({skip_pressure:.2f}, {regime}) for learning.",
                                    [symbol],
                                )
                            elif force_entry and baseline_edge_pct >= float(rl_cfg("RL_FORCE_ENTRY_MIN_EDGE_PCT")):
                                intent(
                                    f"⚡ Exploration override [{active_mode}]: bypassing regime mismatch ({regime}).",
                                    [symbol],
                                )
                            else:
                                self.skipped_cycles_by_mode[active_mode] += 1
                                intent(
                                    f"🚫 Regime MISMATCH: {proposed_dir} rejected in {regime} market. {regime_result['verdict']}",
                                    [symbol]
                                )
                                save_signal_event(
                                    symbol,
                                    current_price,
                                    raw_buy_count,
                                    raw_sell_count,
                                    buy_count,
                                    sell_count,
                                    total_vote_weight,
                                    rsi_result["rsi"],
                                    macd_result["crossover"],
                                    bb_result["position_pct"],
                                    "SKIPPED",
                                    decision_source=self._mode_decision_source(active_mode, "REGIME_MISMATCH"),
                                    deterministic_action=deterministic_dir,
                                    deterministic_conf=det_conf,
                                )
                                self._rl_penalize_skip(
                                    mode=active_mode,
                                    reason="regime_mismatch",
                                    expected_edge_pct=baseline_edge_pct,
                                    symbol=symbol,
                                    regime_result=regime_result,
                                    session_filt=session_filt,
                                    vol_result=vol_result,
                                    sentiment_snapshot=None,
                                    buy_count=buy_count,
                                    sell_count=sell_count,
                                    total_vote_weight=total_vote_weight,
                                )
                                continue

                        # ── Sentiment Gate ─────────────────────────────────
                        sentiment_snapshot = None
                        if config.ENABLE_SENTIMENT_GATE or active_mode in {"FUTURES", "OPTIONS", "SPOT"}:
                            sentiment_snapshot = self._safe_tool_call(
                                "MarketSentiment",
                                lambda: build_sentiment_snapshot(
                                    alpha_key=config.ALPHAVANTAGE_API_KEY,
                                    cryptocompare_key=config.CRYPTOCOMPARE_API_KEY,
                                    symbol=symbol,
                                ),
                                None,
                            )

                        sentiment_ok, sentiment_verdict = self._sentiment_gate(
                            symbol,
                            proposed_dir,
                            snapshot=sentiment_snapshot,
                            sentiment_gate_mult=rl_vote_inf.get("sentiment_gate_mult", 1.0),
                        )
                        if not sentiment_ok:
                            if (
                                skip_pressure > 0
                                and baseline_edge_pct >= float(rl_cfg("RL_SKIP_PRESSURE_EDGE_MIN"))
                                and max(buy_count, sell_count) >= dir_threshold
                            ):
                                intent(
                                    f"⚡ Skip-pressure override: bypassing sentiment gate ({skip_pressure:.2f}) for learning.",
                                    [symbol],
                                )
                                sentiment_ok = True
                                sentiment_verdict = f"{sentiment_verdict} | override:{skip_pressure:.2f}"
                            elif force_entry and baseline_edge_pct >= float(rl_cfg("RL_FORCE_ENTRY_MIN_EDGE_PCT")):
                                intent(
                                    f"⚡ Exploration override [{active_mode}]: bypassing sentiment gate for early learning.",
                                    [symbol],
                                )
                                sentiment_ok = True
                                sentiment_verdict = f"{sentiment_verdict} | override:exploration"
                            else:
                                self.skipped_cycles_by_mode[active_mode] += 1
                                intent(f"📰 Sentiment reject: {sentiment_verdict}", [symbol])
                                save_signal_event(
                                    symbol,
                                    current_price,
                                    raw_buy_count,
                                    raw_sell_count,
                                    buy_count,
                                    sell_count,
                                    total_vote_weight,
                                    rsi_result["rsi"],
                                    macd_result["crossover"],
                                    bb_result["position_pct"],
                                    "SKIPPED",
                                    decision_source=self._mode_decision_source(active_mode, "SENTIMENT_REJECT"),
                                    deterministic_action=deterministic_dir,
                                    deterministic_conf=det_conf,
                                )
                                self._rl_penalize_skip(
                                    mode=active_mode,
                                    reason="sentiment_reject",
                                    expected_edge_pct=baseline_edge_pct,
                                    symbol=symbol,
                                    regime_result=regime_result,
                                    session_filt=session_filt,
                                    vol_result=vol_result,
                                    sentiment_snapshot=sentiment_snapshot,
                                    buy_count=buy_count,
                                    sell_count=sell_count,
                                    total_vote_weight=total_vote_weight,
                                )
                                continue

                        # ── v6: ATR-BASED DYNAMIC STOPS ────────────────────
                        atr_result = self._safe_tool_call(
                            "ATRTracker",
                            lambda: ATRTracker.analyze(history),
                            {"stop_loss_pct": config.EARLY_STOP_LOSS_PCT, "take_profit_pct": config.TAKE_PROFIT_PCT, "verdict": "Tool error"},
                        )
                        # Use max(config, ATR) — ATR on 1-min tick data
                        # often floor-clamps to tiny values that make fees
                        # dominate the edge formula.  Config values represent
                        # the actual trading-horizon targets.
                        dynamic_sl  = max(config.EARLY_STOP_LOSS_PCT, atr_result["stop_loss_pct"])
                        dynamic_tp  = max(config.TAKE_PROFIT_PCT, atr_result["take_profit_pct"])

                        # ── v6: MULTI-TIMEFRAME CONFIRMATION ───────────────
                        mtf_result = self._safe_tool_call(
                            "MultiTimeframeConfirmer",
                            lambda: MultiTimeframeConfirmer.analyze(history, proposed_dir),
                            {"confirms": True, "htf_trend": "UNKNOWN", "verdict": "Tool error"},
                        )
                        if not mtf_result["confirms"] and mtf_result["htf_trend"] != "UNKNOWN":
                            if force_entry and baseline_edge_pct >= float(rl_cfg("RL_FORCE_ENTRY_MIN_EDGE_PCT")):
                                intent(
                                    f"⚡ Exploration override [{active_mode}]: bypassing HTF reject for sample collection.",
                                    [symbol],
                                )
                            else:
                                intent(f"📊 HTF REJECT: {mtf_result['verdict']}", [symbol])
                                # Soft reject: add to miss count but don't hard-block
                                self.skipped_cycles_by_mode[active_mode] += 1
                                save_signal_event(
                                    symbol,
                                    current_price,
                                    raw_buy_count,
                                    raw_sell_count,
                                    buy_count,
                                    sell_count,
                                    total_vote_weight,
                                    rsi_result["rsi"],
                                    macd_result["crossover"],
                                    bb_result["position_pct"],
                                    "SKIPPED",
                                    decision_source=self._mode_decision_source(active_mode, "HTF_REJECT"),
                                    deterministic_action=deterministic_dir,
                                    deterministic_conf=det_conf,
                                )
                                self._rl_penalize_skip(
                                    mode=active_mode,
                                    reason="htf_reject",
                                    expected_edge_pct=baseline_edge_pct,
                                    symbol=symbol,
                                    regime_result=regime_result,
                                    session_filt=session_filt,
                                    vol_result=vol_result,
                                    sentiment_snapshot=sentiment_snapshot,
                                    buy_count=buy_count,
                                    sell_count=sell_count,
                                    total_vote_weight=total_vote_weight,
                                )
                                continue

                        now = datetime.now()

                        # ── DIRECTION BLOCK ─────────────────────────────────
                        pos_key = self._pos_key(symbol, active_mode)
                        block = self.direction_block.get(pos_key)
                        if block and block["side"] == proposed_dir and now < block["blocked_until"]:
                            remaining_block = int((block["blocked_until"] - now).total_seconds())
                            self.skipped_cycles_by_mode[active_mode] += 1
                            intent(f"🚫 {proposed_dir} BLOCKED ({remaining_block}s — consecutive losses)", [symbol])
                            save_signal_event(
                                symbol,
                                current_price,
                                raw_buy_count,
                                raw_sell_count,
                                buy_count,
                                sell_count,
                                total_vote_weight,
                                rsi_result["rsi"],
                                macd_result["crossover"],
                                bb_result["position_pct"],
                                "SKIPPED",
                                decision_source=self._mode_decision_source(active_mode, "DIRECTION_BLOCK"),
                                deterministic_action=deterministic_dir,
                                deterministic_conf=det_conf,
                            )
                            self._rl_penalize_skip(
                                mode=active_mode,
                                reason="direction_block",
                                expected_edge_pct=baseline_edge_pct,
                                symbol=symbol,
                                regime_result=regime_result,
                                session_filt=session_filt,
                                vol_result=vol_result,
                                sentiment_snapshot=sentiment_snapshot,
                                buy_count=buy_count,
                                sell_count=sell_count,
                                total_vote_weight=total_vote_weight,
                            )
                            continue

                        # ── POST-CLOSE COOLDOWN (300s) ─────────────────────
                        last_close_time = self.last_close_time_by_mode.get(active_mode)
                        if last_close_time and (now - last_close_time).total_seconds() < 300:
                            remaining_cd = 300 - int((now - last_close_time).total_seconds())
                            self.skipped_cycles_by_mode[active_mode] += 1
                            if self.skipped_cycles_by_mode[active_mode] % 3 == 0:
                                intent(f"⏸ Post-close cooldown: {remaining_cd}s remaining", [symbol])
                            save_signal_event(
                                symbol,
                                current_price,
                                raw_buy_count,
                                raw_sell_count,
                                buy_count,
                                sell_count,
                                total_vote_weight,
                                rsi_result["rsi"],
                                macd_result["crossover"],
                                bb_result["position_pct"],
                                "SKIPPED",
                                decision_source=self._mode_decision_source(active_mode, "POST_CLOSE_COOLDOWN"),
                                deterministic_action=deterministic_dir,
                                deterministic_conf=det_conf,
                            )
                            self._rl_penalize_skip(
                                mode=active_mode,
                                reason="post_close_cooldown",
                                expected_edge_pct=baseline_edge_pct,
                                symbol=symbol,
                                regime_result=regime_result,
                                session_filt=session_filt,
                                vol_result=vol_result,
                                sentiment_snapshot=sentiment_snapshot,
                                buy_count=buy_count,
                                sell_count=sell_count,
                                total_vote_weight=total_vote_weight,
                            )
                            continue

                        # ── HARD DUPLICATE BLOCKER ──────────────────────────
                        last_entry = self.last_entry_prices.get(pos_key)
                        if last_entry:
                            last_price, last_side, last_time = last_entry
                            time_since = (now - last_time).total_seconds()
                            price_diff_pct = abs(current_price - last_price) / last_price
                            if time_since < 600:
                                self.skipped_cycles_by_mode[active_mode] += 1
                                intent(f"⏸ Entry blocked: {int(600 - time_since)}s lockout remaining", [symbol])
                                save_signal_event(
                                    symbol,
                                    current_price,
                                    raw_buy_count,
                                    raw_sell_count,
                                    buy_count,
                                    sell_count,
                                    total_vote_weight,
                                    rsi_result["rsi"],
                                    macd_result["crossover"],
                                    bb_result["position_pct"],
                                    "SKIPPED",
                                    decision_source=self._mode_decision_source(active_mode, "ENTRY_LOCKOUT"),
                                    deterministic_action=deterministic_dir,
                                    deterministic_conf=det_conf,
                                )
                                self._rl_penalize_skip(
                                    mode=active_mode,
                                    reason="entry_lockout",
                                    expected_edge_pct=baseline_edge_pct,
                                    symbol=symbol,
                                    regime_result=regime_result,
                                    session_filt=session_filt,
                                    vol_result=vol_result,
                                    sentiment_snapshot=sentiment_snapshot,
                                    buy_count=buy_count,
                                    sell_count=sell_count,
                                    total_vote_weight=total_vote_weight,
                                )
                                continue
                            if last_side == proposed_dir and price_diff_pct < 0.0015 and time_since < 1200:
                                self.skipped_cycles_by_mode[active_mode] += 1
                                intent(f"⏸ Duplicate blocked: {proposed_dir} only {price_diff_pct*100:.3f}% from last entry", [symbol])
                                save_signal_event(
                                    symbol,
                                    current_price,
                                    raw_buy_count,
                                    raw_sell_count,
                                    buy_count,
                                    sell_count,
                                    total_vote_weight,
                                    rsi_result["rsi"],
                                    macd_result["crossover"],
                                    bb_result["position_pct"],
                                    "SKIPPED",
                                    decision_source=self._mode_decision_source(active_mode, "DUPLICATE_BLOCK"),
                                    deterministic_action=deterministic_dir,
                                    deterministic_conf=det_conf,
                                )
                                self._rl_penalize_skip(
                                    mode=active_mode,
                                    reason="duplicate_block",
                                    expected_edge_pct=baseline_edge_pct,
                                    symbol=symbol,
                                    regime_result=regime_result,
                                    session_filt=session_filt,
                                    vol_result=vol_result,
                                    sentiment_snapshot=sentiment_snapshot,
                                    buy_count=buy_count,
                                    sell_count=sell_count,
                                    total_vote_weight=total_vote_weight,
                                )
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

                        expected_edge_pct = self._estimate_expected_edge_pct(
                            buy_count,
                            sell_count,
                            dynamic_tp,
                            dynamic_sl,
                            total_vote_weight,
                        )
                        min_edge_required = float(rl_cfg("MIN_EXPECTED_EDGE_PCT"))
                        if under_sampled:
                            min_edge_required *= float(rl_cfg("RL_UNDERSAMPLED_EDGE_THRESHOLD_MULT"))
                        if expected_edge_pct < min_edge_required:
                            if force_entry and expected_edge_pct >= float(rl_cfg("RL_FORCE_ENTRY_MIN_EDGE_PCT")):
                                intent(
                                    f"⚡ Exploration override [{active_mode}]: low edge {expected_edge_pct:.4f}% accepted for learning.",
                                    [symbol],
                                )
                            else:
                                self.skipped_cycles_by_mode[active_mode] += 1
                                save_signal_event(
                                    symbol,
                                    current_price,
                                    raw_buy_count,
                                    raw_sell_count,
                                    buy_count,
                                    sell_count,
                                    total_vote_weight,
                                    rsi_result["rsi"],
                                    macd_result["crossover"],
                                    bb_result["position_pct"],
                                    "SKIPPED",
                                    decision_source=self._mode_decision_source(active_mode, "EDGE_REJECT"),
                                    deterministic_action=deterministic_dir,
                                    deterministic_conf=det_conf,
                                )
                                self._rl_penalize_skip(
                                    mode=active_mode,
                                    reason="edge_reject",
                                    expected_edge_pct=expected_edge_pct,
                                    symbol=symbol,
                                    regime_result=regime_result,
                                    session_filt=session_filt,
                                    vol_result=vol_result,
                                    sentiment_snapshot=sentiment_snapshot,
                                    buy_count=buy_count,
                                    sell_count=sell_count,
                                    total_vote_weight=total_vote_weight,
                                )
                                continue

                        pre_policy = self._product_policy_decision(
                            mode=active_mode,
                            total_vote_weight=total_vote_weight,
                            symbol=symbol,
                            stage="pre-llm",
                            proposed_dir=proposed_dir,
                            buy_count=buy_count,
                            sell_count=sell_count,
                            confidence=det_conf,
                            expected_edge_pct=expected_edge_pct,
                            regime_result=regime_result,
                            session_filt=session_filt,
                            vol_result=vol_result,
                            vol_prof=vol_prof,
                            sentiment_snapshot=sentiment_snapshot,
                            vel_result=vel_result,
                            macd_result=macd_result,
                            ema_result=ema_result,
                            ob_result=ob_result,
                            enforce_confidence_gate=False,
                        )
                        self._log_product_eval(symbol, "pre-llm", pre_policy, mode=active_mode)
                        if not bool((pre_policy or {}).get("allow")):
                            if force_entry:
                                intent(
                                    f"⚡ Exploration override [{active_mode}]: bypassing pre-policy reject (score={pre_policy.get('composite_score', 0):.3f}) for sample collection.",
                                    [symbol],
                                )
                            else:
                                self.skipped_cycles_by_mode[active_mode] += 1
                                self._rl_reward_skip_opportunity(
                                    active_mode,
                                    pre_policy,
                                    expected_edge_pct=expected_edge_pct,
                                    reason="pre_policy_reject",
                                    symbol=symbol,
                                )
                                intent(f"🚫 [{active_mode}] {pre_policy.get('verdict', 'Rejected')}", [symbol])
                                reject_source = f"{active_mode}_REJECT"
                                save_signal_event(
                                    symbol,
                                    current_price,
                                    raw_buy_count,
                                    raw_sell_count,
                                    buy_count,
                                    sell_count,
                                    total_vote_weight,
                                    rsi_result["rsi"],
                                    macd_result["crossover"],
                                    bb_result["position_pct"],
                                    "SKIPPED",
                                    decision_source=self._mode_decision_source(active_mode, reject_source),
                                    deterministic_action=deterministic_dir,
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

                        borderline_setup = det_conf < 0.75 or max(buy_count, sell_count) <= (4.0 * (total_vote_weight / 8.0))
                        if force_entry:
                            # Exploration overrides skip LLM — use deterministic
                            # signal directly to avoid LLM throttle/budget/reject
                            # blocking forced sample collection.
                            borderline_setup = False
                        if borderline_setup:
                            llm_ok, llm_reason = self._llm_budget_ok()
                            if not llm_ok:
                                self.skipped_cycles_by_mode[active_mode] += 1
                                intent(f"⏳ LLM blocked: {llm_reason}", [symbol])
                                save_signal_event(
                                    symbol,
                                    current_price,
                                    raw_buy_count,
                                    raw_sell_count,
                                    buy_count,
                                    sell_count,
                                    total_vote_weight,
                                    rsi_result["rsi"],
                                    macd_result["crossover"],
                                    bb_result["position_pct"],
                                    "SKIPPED",
                                    decision_source=self._mode_decision_source(active_mode, "LLM_BUDGET_BLOCK"),
                                    deterministic_action=deterministic_dir,
                                    deterministic_conf=det_conf,
                                )
                                continue

                            last_llm = self.last_llm_call.get(active_mode)
                            if last_llm and (now - last_llm).total_seconds() < config.LLM_POLL_INTERVAL_SECONDS:
                                self.skipped_cycles_by_mode[active_mode] += 1
                                wait_left = int(config.LLM_POLL_INTERVAL_SECONDS - (now - last_llm).total_seconds())
                                if self.skipped_cycles_by_mode[active_mode] % 2 == 0:
                                    intent(
                                        f"⚡ Borderline setup {proposed_dir} ({buy_count:.1f}B/{sell_count:.1f}S) | LLM in {wait_left}s...",
                                        [symbol],
                                    )
                                save_signal_event(
                                    symbol,
                                    current_price,
                                    raw_buy_count,
                                    raw_sell_count,
                                    buy_count,
                                    sell_count,
                                    total_vote_weight,
                                    rsi_result["rsi"],
                                    macd_result["crossover"],
                                    bb_result["position_pct"],
                                    "SKIPPED",
                                    decision_source=self._mode_decision_source(active_mode, "LLM_THROTTLED"),
                                    deterministic_action=deterministic_dir,
                                    deterministic_conf=det_conf,
                                )
                                continue

                            if not self.llm_agent:
                                self.skipped_cycles_by_mode[active_mode] += 1
                                save_signal_event(
                                    symbol,
                                    current_price,
                                    raw_buy_count,
                                    raw_sell_count,
                                    buy_count,
                                    sell_count,
                                    total_vote_weight,
                                    rsi_result["rsi"],
                                    macd_result["crossover"],
                                    bb_result["position_pct"],
                                    "SKIPPED",
                                    decision_source=self._mode_decision_source(active_mode, "LLM_AGENT_UNAVAILABLE"),
                                    deterministic_action=deterministic_dir,
                                    deterministic_conf=det_conf,
                                )
                                continue

                            self.last_llm_call[active_mode] = now
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
                            confidence_floor = config.LLM_CONFIDENCE_FLOOR
                            if (
                                not llm_signal
                                or llm_signal.action == "NEUTRAL"
                                or llm_signal.confidence < confidence_floor
                                or effective_conf < config.MIN_ENSEMBLE_CONFIDENCE
                            ):
                                self.skipped_cycles_by_mode[active_mode] += 1
                                conf = llm_signal.confidence if llm_signal else 0.0
                                action = llm_signal.action if llm_signal else "NEUTRAL"
                                save_signal_event(
                                    symbol,
                                    current_price,
                                    raw_buy_count,
                                    raw_sell_count,
                                    buy_count,
                                    sell_count,
                                    total_vote_weight,
                                    rsi_result["rsi"],
                                    macd_result["crossover"],
                                    bb_result["position_pct"],
                                    "MISSED",
                                    claude_action=action,
                                    claude_conf=conf,
                                    decision_source=self._mode_decision_source(active_mode, "LLM_REJECT"),
                                    deterministic_action=deterministic_dir,
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

                        final_dir = "LONG" if final_action == "BUY" else "SHORT"
                        post_policy = self._product_policy_decision(
                            mode=active_mode,
                            total_vote_weight=total_vote_weight,
                            symbol=symbol,
                            stage="post-llm",
                            proposed_dir=final_dir,
                            buy_count=buy_count,
                            sell_count=sell_count,
                            confidence=final_conf,
                            expected_edge_pct=expected_edge_pct,
                            regime_result=regime_result,
                            session_filt=session_filt,
                            vol_result=vol_result,
                            vol_prof=vol_prof,
                            sentiment_snapshot=sentiment_snapshot,
                            vel_result=vel_result,
                            macd_result=macd_result,
                            ema_result=ema_result,
                            ob_result=ob_result,
                        )
                        self._log_product_eval(symbol, "post-llm", post_policy, mode=active_mode)
                        if not bool((post_policy or {}).get("allow")):
                            if force_entry:
                                intent(
                                    f"⚡ Exploration override [{active_mode}]: bypassing post-policy reject (score={post_policy.get('composite_score', 0):.3f}) for sample collection.",
                                    [symbol],
                                )
                            else:
                                self.skipped_cycles_by_mode[active_mode] += 1
                                self._rl_reward_skip_opportunity(
                                    active_mode,
                                    post_policy,
                                    expected_edge_pct=expected_edge_pct,
                                    reason="post_policy_reject",
                                    symbol=symbol,
                                )
                                intent(f"🚫 [{active_mode}] {post_policy.get('verdict', 'Rejected')}", [symbol])
                                reject_source = f"{active_mode}_REJECT"
                                save_signal_event(
                                    symbol,
                                    current_price,
                                    raw_buy_count,
                                    raw_sell_count,
                                    buy_count,
                                    sell_count,
                                    total_vote_weight,
                                    rsi_result["rsi"],
                                    macd_result["crossover"],
                                    bb_result["position_pct"],
                                    "SKIPPED",
                                    decision_source=self._mode_decision_source(active_mode, reject_source),
                                    deterministic_action=final_dir,
                                    deterministic_conf=det_conf,
                                    llm_cost_usd=llm_cost,
                                    llm_tokens=llm_tokens,
                                )
                                continue
                        selected_mode, policy_eval = active_mode, post_policy

                        # ── LLM decision review (support vs oppose) ─────────
                        if (
                            config.ENABLE_LLM_DECISION_REVIEW
                            and self.llm_agent
                            and self.llm_agent.ready
                            and final_conf >= float(config.LLM_REVIEW_MIN_CONFIDENCE)
                        ):
                            review, review_usage = self.llm_agent.review_decision(
                                symbol=symbol,
                                current_price=current_price,
                                action=final_action,
                                confidence=final_conf,
                                reason=final_reason,
                                regime=regime,
                                buy_count=buy_count,
                                sell_count=sell_count,
                                raw_buy=raw_buy_count,
                                raw_sell=raw_sell_count,
                                total_vote_weight=total_vote_weight,
                                tool_outputs=tool_outputs,
                                policy_verdict=str(post_policy.get("verdict", "")),
                            )
                            if review_usage:
                                self._register_llm_usage(symbol, review_usage, context=f"review|{final_action}|{regime}")
                            if review:
                                verdict = str(review.get("verdict", "NEUTRAL")).upper()
                                suggested = str(review.get("suggested_action", "SKIP")).upper()
                                review_conf = float(review.get("confidence", 0.0) or 0.0)
                                if verdict == "OPPOSE" and review_conf >= 0.50:
                                    self.skipped_cycles_by_mode[active_mode] += 1
                                    intent(
                                        f"🧠 LLM REVIEW OPPOSED: {review.get('reason', '')}",
                                        [symbol],
                                    )
                                    save_signal_event(
                                        symbol,
                                        current_price,
                                        raw_buy_count,
                                        raw_sell_count,
                                        buy_count,
                                        sell_count,
                                        total_vote_weight,
                                        rsi_result["rsi"],
                                        macd_result["crossover"],
                                        bb_result["position_pct"],
                                        "SKIPPED",
                                        decision_source=self._mode_decision_source(active_mode, "LLM_REVIEW_OPPOSE"),
                                        deterministic_action=deterministic_dir,
                                        deterministic_conf=det_conf,
                                        llm_cost_usd=llm_cost,
                                        llm_tokens=llm_tokens,
                                    )
                                    continue
                                if verdict == "OPPOSE" and suggested in {"BUY", "SELL"}:
                                    final_action = suggested
                                    final_dir = "LONG" if final_action == "BUY" else "SHORT"
                                    final_reason = f"LLM review override: {review.get('reason', '')}"

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

                        recommended_leverage = 1
                        product_score = None
                        product_strategy = "SPOT_FLOW"
                        if selected_mode in {"FUTURES", "OPTIONS", "SPOT"}:
                            recommended_leverage = int(policy_eval.get("recommended_leverage", 1) or 1)
                            product_score = float(policy_eval.get("composite_score", 0.0) or 0.0)
                            product_strategy = str(policy_eval.get("recommended_strategy", "N/A"))
                            pos_usdt = int(pos_usdt * float(policy_eval.get("size_multiplier", 1.0) or 1.0))

                        # Exploration trades use smaller size to gather more data with less risk
                        if force_entry:
                            pos_usdt = int(pos_usdt * 0.6)
                            logger.info(f"🔬 Exploration size: ${pos_usdt:,} (60%% of normal)")

                        if self.consecutive_losses.get(active_mode, 0) >= 2:
                            pos_usdt = int(pos_usdt * 0.7)
                            logger.info(f"📉 Risk cut: position shrunk to ${pos_usdt:,} (loss streak)")

                        max_by_risk = int(self.simulator.balance_usdt * config.MAX_RISK_PER_TRADE_PCT_BALANCE)
                        min_pos = int(config.MIN_POSITION_SIZE_USDT)
                        if max_by_risk < min_pos:
                            self.skipped_cycles_by_mode[active_mode] += 1
                            save_signal_event(
                                symbol,
                                current_price,
                                raw_buy_count,
                                raw_sell_count,
                                buy_count,
                                sell_count,
                                total_vote_weight,
                                rsi_result["rsi"],
                                macd_result["crossover"],
                                bb_result["position_pct"],
                                "SKIPPED",
                                decision_source=self._mode_decision_source(active_mode, "RISK_CAP_BLOCK"),
                                deterministic_action=deterministic_dir,
                                deterministic_conf=det_conf,
                                llm_cost_usd=llm_cost,
                                llm_tokens=llm_tokens,
                            )
                            continue
                        pos_usdt = max(min_pos, min(pos_usdt, max_by_risk, int(self.simulator.balance_usdt)))
                        pos_usdt = min(pos_usdt, int(config.MAX_POSITION_SIZE_USDT))
                        if pos_usdt < min_pos:
                            self.skipped_cycles_by_mode[active_mode] += 1
                            save_signal_event(
                                symbol,
                                current_price,
                                raw_buy_count,
                                raw_sell_count,
                                buy_count,
                                sell_count,
                                total_vote_weight,
                                rsi_result["rsi"],
                                macd_result["crossover"],
                                bb_result["position_pct"],
                                "SKIPPED",
                                decision_source=self._mode_decision_source(active_mode, "POSITION_SIZE_TOO_SMALL"),
                                deterministic_action=deterministic_dir,
                                deterministic_conf=det_conf,
                                llm_cost_usd=llm_cost,
                                llm_tokens=llm_tokens,
                            )
                            continue

                        side = "LONG" if final_action == "BUY" else "SHORT"
                        decision_source_tag = decision_source
                        if selected_mode == "FUTURES":
                            decision_source_tag = f"FUTURES_{decision_source}"
                        elif selected_mode == "OPTIONS":
                            decision_source_tag = f"OPTIONS_{decision_source}"
                        elif selected_mode == "SPOT":
                            decision_source_tag = f"SPOT_{decision_source}"
                        product_context = ""
                        if selected_mode == "FUTURES":
                            product_context = f" | FutScore:{product_score:.3f} | Lev:{recommended_leverage}x"
                        elif selected_mode == "OPTIONS":
                            product_context = f" | OptScore:{product_score:.3f} | Strat:{product_strategy}"
                        elif selected_mode == "SPOT":
                            product_context = f" | SpotScore:{product_score:.3f} | Strat:{product_strategy}"
                        reason = (
                            f"{decision_source}({final_conf:.2f}) | {buy_count}B/{sell_count}S | "
                            f"{regime} | {session_filt['session']} | {sentiment_verdict} | Edge:{expected_edge_pct:+.3f}% | "
                            f"ATR-SL:{dynamic_sl*100:.2f}%/TP:{dynamic_tp*100:.2f}%{product_context} | {final_reason}"
                        )
                        rl_context = {
                            "mode": selected_mode,
                            "state_key": str(policy_eval.get("rl_state_key", "") or ""),
                            "profile_id": str(policy_eval.get("rl_profile_id", "") or ""),
                            "expected_edge_pct": float(expected_edge_pct or 0.0),
                            "entry_notional_usdt": float(pos_usdt),
                        }
                        pos_key = self._pos_key(symbol, selected_mode)
                        self._pending_rl_by_symbol[pos_key] = rl_context

                        self.trades_executed += 1
                        self.trades_executed_by_mode[selected_mode] = int(self.trades_executed_by_mode.get(selected_mode, 0) or 0) + 1
                        self.skipped_cycles_by_mode[active_mode] = 0
                        lev_label = ""
                        if selected_mode == "FUTURES":
                            lev_label = f" | lev:{recommended_leverage}x"
                        elif selected_mode == "OPTIONS":
                            lev_label = f" | strat:{product_strategy}"
                        elif selected_mode == "SPOT":
                            lev_label = f" | strat:{product_strategy}"
                        intent(
                            f"🎯 Trade #{self.trades_executed}: {side} ${pos_usdt:,} | conf:{final_conf:.2f} | {decision_source_tag}{lev_label} | pool:shared",
                            [symbol],
                        )
                        entered = self.simulator.enter_position(
                            symbol,
                            current_price,
                            pos_usdt,
                            reason,
                            side=side,
                            decision_source=decision_source_tag,
                            deterministic_conf=det_conf,
                            llm_conf=final_conf if decision_source == "LLM_TIEBREAKER" else None,
                            llm_cost_usd=llm_cost if decision_source == "LLM_TIEBREAKER" else 0.0,
                            mode=selected_mode,
                            rl_context=rl_context,
                        )

                        if not entered:
                            logger.warning("Entry failed for %s (%s) — skipping signal event save", symbol, selected_mode)
                            continue

                        if pos_key in self.simulator.positions:
                            self.simulator.positions[pos_key]["dynamic_sl"] = dynamic_sl
                            self.simulator.positions[pos_key]["dynamic_tp"] = dynamic_tp
                            self.simulator.positions[pos_key]["pyramid_count"] = 0
                            self.simulator.positions[pos_key]["original_pos_usdt"] = pos_usdt
                            self.simulator.positions[pos_key]["recommended_leverage"] = recommended_leverage
                            self.simulator.positions[pos_key]["futures_score"] = product_score
                            self.simulator.positions[pos_key]["spot_score"] = product_score
                            self.simulator.positions[pos_key]["spot_strategy"] = product_strategy
                            self.simulator.positions[pos_key]["options_strategy"] = product_strategy
                            self.simulator.positions[pos_key]["selected_product"] = selected_mode

                        save_signal_event(
                            symbol,
                            current_price,
                            raw_buy_count,
                            raw_sell_count,
                            buy_count,
                            sell_count,
                            total_vote_weight,
                            rsi_result["rsi"],
                            macd_result["crossover"],
                            bb_result["position_pct"],
                            "TRADED",
                            claude_action=side if decision_source == "LLM_TIEBREAKER" else None,
                            claude_conf=final_conf if decision_source == "LLM_TIEBREAKER" else None,
                            decision_source=decision_source_tag,
                            deterministic_action=deterministic_dir,
                            deterministic_conf=det_conf,
                            llm_cost_usd=llm_cost,
                            llm_tokens=llm_tokens,
                        )
                        symbols_with_positions.add(symbol)
                        # ── Persist full portfolio accounting after entry ──
                        self._save_portfolio_snapshot(trigger="ENTRY")
                        continue  # keep scanning other symbols for entries

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
        logger.info("Engine run complete for mode=%s. Returning control to supervisor.", active_mode)
