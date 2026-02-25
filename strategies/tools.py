"""
Analysis Tools — Lightweight, pure-Python data processors.
These tools run locally (free, instant) and feed structured outputs to Claude.

v2: Added RSIAnalyzer, MACDSignal, BollingerBands, SupportResistance, CandlePatterns
"""
import statistics



# ─── EXISTING TOOLS ───────────────────────────────────────────────────────────

class VolatilityScanner:
    """
    Measures price volatility using standard deviation of recent ticks.
    High volatility = opportunity. Near-zero = dead market, don't trade.
    """
    name = "Volatility Scanner"

    @staticmethod
    def analyze(history: list) -> dict:
        if len(history) < 10:
            return {"volatility_pct": 0.0, "verdict": "Insufficient data", "tradeable": False}
        
        recent = history[-60:]  # Last 5 min of 5s ticks
        mean = statistics.mean(recent)
        if mean == 0:
            return {"volatility_pct": 0.0, "verdict": "Dead market", "tradeable": False}
        
        stdev = statistics.stdev(recent)
        vol_pct = (stdev / mean) * 100
        
        if vol_pct < 0.005:
            verdict = "DEAD — No movement, do NOT trade"
            tradeable = False
        elif vol_pct < 0.02:
            verdict = "LOW — Minimal movement, risky"
            tradeable = False
        elif vol_pct < 0.1:
            verdict = "MODERATE — Tradeable with caution"
            tradeable = True
        else:
            verdict = "HIGH — Strong movement, good opportunity"
            tradeable = True

        return {"volatility_pct": round(vol_pct, 4), "verdict": verdict, "tradeable": tradeable}


class PriceVelocity:
    """
    Measures rate of price change over multiple windows.
    Detects momentum acceleration (speeding up) vs deceleration (slowing down).
    """
    name = "Price Velocity"

    @staticmethod
    def analyze(history: list, current_price: float) -> dict:
        result = {"velocity_30s": 0.0, "velocity_1m": 0.0, "velocity_5m": 0.0, "acceleration": "flat"}
        if len(history) < 12:
            return result
        
        if len(history) >= 6:
            p30 = history[-6]
            result["velocity_30s"] = round(((current_price - p30) / p30) * 100, 4) if p30 else 0
        
        if len(history) >= 12:
            p1m = history[-12]
            result["velocity_1m"] = round(((current_price - p1m) / p1m) * 100, 4) if p1m else 0
        
        if len(history) >= 60:
            p5m = history[-60]
            result["velocity_5m"] = round(((current_price - p5m) / p5m) * 100, 4) if p5m else 0
        
        v30 = abs(result["velocity_30s"])
        v1m = abs(result["velocity_1m"])
        
        if v30 > v1m * 1.5:
            result["acceleration"] = "ACCELERATING — momentum building"
        elif v30 < v1m * 0.5:
            result["acceleration"] = "DECELERATING — momentum fading"
        else:
            result["acceleration"] = "STEADY — stable speed"
        
        return result


class VolumeProfile:
    """
    Analyzes 24h volume and bid/ask spread from ticker metadata.
    Low volume = poor liquidity = slippage risk.
    """
    name = "Volume Profile"

    @staticmethod
    def analyze(meta: dict) -> dict:
        volume = meta.get('volume', 0)
        bid = meta.get('bid', 0)
        ask = meta.get('ask', 0)
        
        spread_pct = 0.0
        if bid > 0 and ask > 0:
            spread_pct = ((ask - bid) / bid) * 100
        
        if volume < 1:
            verdict = "ZERO VOLUME — Market is closed or stale"
            liquid = False
        elif volume < 100:
            verdict = "VERY LOW — Extremely thin, avoid"
            liquid = False
        elif volume < 1000:
            verdict = "LOW — Trade small only"
            liquid = True
        else:
            verdict = "HEALTHY — Good liquidity"
            liquid = True
            
        return {
            "volume_24h": round(volume, 2),
            "bid": bid,
            "ask": ask,
            "spread_pct": round(spread_pct, 4),
            "verdict": verdict,
            "liquid": liquid,
        }


class OrderBookPressure:
    """
    Infers buy/sell pressure from bid vs ask imbalance.
    """
    name = "Order Book Pressure"

    @staticmethod
    def analyze(meta: dict, current_price: float) -> dict:
        bid = meta.get('bid', 0)
        ask = meta.get('ask', 0)
        
        if bid <= 0 or ask <= 0:
            return {"pressure": "UNKNOWN", "bias": 0.0}
        
        midpoint = (bid + ask) / 2
        bias = (current_price - midpoint) / midpoint * 100
        
        if current_price > midpoint:
            pressure = "BULLISH — Price above bid/ask midpoint"
        elif current_price < midpoint:
            pressure = "BEARISH — Price below bid/ask midpoint"
        else:
            pressure = "NEUTRAL — At midpoint"
            
        return {"pressure": pressure, "bias": round(bias, 4), "bid": bid, "ask": ask}


class SessionTracker:
    """
    Tracks the running win rate, streak, and cumulative PnL of the current session.
    Claude can use this to adjust its aggression level dynamically.
    """
    name = "Session Performance"

    def __init__(self):
        self.trades = []
        self.wins = 0
        self.losses = 0
    
    def record_trade(self, pnl: float):
        self.trades.append(pnl)
        if pnl >= 0:
            self.wins += 1
        else:
            self.losses += 1
    
    def get_stats(self) -> dict:
        total = len(self.trades)
        if total == 0:
            return {
                "total_trades": 0, "win_rate": "N/A",
                "streak": "No trades yet", "cumulative_pnl": 0,
                "avg_win": 0, "avg_loss": 0,
                "recommendation": "First trade — use moderate confidence"
            }
        
        win_rate = (self.wins / total) * 100
        cum_pnl = sum(self.trades)
        
        streak = 0
        streak_type = "neutral"
        for pnl in reversed(self.trades):
            if pnl >= 0 and (streak_type == "neutral" or streak_type == "win"):
                streak += 1
                streak_type = "win"
            elif pnl < 0 and (streak_type == "neutral" or streak_type == "loss"):
                streak += 1
                streak_type = "loss"
            else:
                break
        
        streak_str = f"{streak} {'WINS' if streak_type == 'win' else 'LOSSES'} in a row"
        
        wins_list = [p for p in self.trades if p >= 0]
        losses_list = [p for p in self.trades if p < 0]
        avg_win = statistics.mean(wins_list) if wins_list else 0
        avg_loss = statistics.mean(losses_list) if losses_list else 0
        
        if streak_type == "loss" and streak >= 2:
            rec = "LOSING STREAK — Raise confidence threshold, be more selective"
        elif streak_type == "win" and streak >= 2:
            rec = "WINNING STREAK — Maintain current approach, stay disciplined"
        elif win_rate < 40:
            rec = "LOW WIN RATE — Be much more conservative, skip marginal trades"
        elif win_rate > 70:
            rec = "HIGH WIN RATE — Strategy is working, maintain discipline"
        else:
            rec = "MIXED RESULTS — Stick to high-confidence setups only"
        
        return {
            "total_trades": total,
            "win_rate": f"{win_rate:.0f}%",
            "streak": streak_str,
            "cumulative_pnl": round(cum_pnl, 2),
            "avg_win": round(avg_win, 2),
            "avg_loss": round(avg_loss, 2),
            "recommendation": rec,
        }


# ─── NEW PRO-GRADE TECHNICAL ANALYSIS TOOLS ───────────────────────────────────

class RSIAnalyzer:
    """
    Relative Strength Index (RSI-14).
    < 30 = oversold (BUY signal), > 70 = overbought (SELL signal).
    RSI < 5 or > 95 on 1m data is flagged as SUSPECT (momentum spike artifact).
    """
    name = "RSI (14)"
    PERIOD = 14
    MIN_HISTORY = 28  # Need 2x the period for stable Wilder smoothing

    @staticmethod
    def analyze(history: list) -> dict:
        if len(history) < RSIAnalyzer.MIN_HISTORY:
            return {"rsi": 50.0, "signal": "NEUTRAL", "verdict": f"Warming up ({len(history)}/{RSIAnalyzer.MIN_HISTORY} ticks)"}

        # Use last PERIOD+1 prices for the core calc, but seed with smoothed avg from longer window
        prices = list(history)[-RSIAnalyzer.PERIOD - 1:]
        gains, losses = [], []
        for i in range(1, len(prices)):
            delta = prices[i] - prices[i - 1]
            if delta > 0:
                gains.append(delta)
                losses.append(0)
            else:
                gains.append(0)
                losses.append(abs(delta))

        avg_gain = statistics.mean(gains) if gains else 0
        avg_loss = statistics.mean(losses) if losses else 0

        if avg_loss == 0 and avg_gain == 0:
            rsi = 50.0  # No movement at all
        elif avg_loss == 0:
            rsi = 99.0  # All gains, but cap at 99 (not 100) to flag momentum spike
        elif avg_gain == 0:
            rsi = 1.0   # All losses, but cap at 1 (not 0)
        else:
            rs = avg_gain / avg_loss
            rsi = 100 - (100 / (1 + rs))

        rsi = round(rsi, 2)

        # ── Treat RSI extremes as strong signals, not artifacts ──
        # On 5s ticks BTC can legitimately hit RSI extremes during sharp moves
        if rsi < 5:
            return {"rsi": rsi, "signal": "STRONG_BUY",
                    "verdict": f"RSI {rsi} — DEEPLY OVERSOLD, extreme buying opportunity",
                    "suspect": False}
        if rsi > 95:
            return {"rsi": rsi, "signal": "STRONG_SELL",
                    "verdict": f"RSI {rsi} — DEEPLY OVERBOUGHT, extreme selling opportunity",
                    "suspect": False}

        if rsi < 20:
            signal = "STRONG_BUY"
            verdict = f"RSI {rsi} — EXTREMELY OVERSOLD, high-probability bounce"
        elif rsi < 30:
            signal = "BUY"
            verdict = f"RSI {rsi} — OVERSOLD, bullish reversal likely"
        elif rsi < 40:
            signal = "WEAK_BUY"
            verdict = f"RSI {rsi} — Approaching oversold, watch for bounce"
        elif rsi > 80:
            signal = "STRONG_SELL"
            verdict = f"RSI {rsi} — EXTREMELY OVERBOUGHT, high-probability drop"
        elif rsi > 70:
            signal = "SELL"
            verdict = f"RSI {rsi} — OVERBOUGHT, bearish reversal likely"
        elif rsi > 60:
            signal = "WEAK_SELL"
            verdict = f"RSI {rsi} — Approaching overbought, watch for rejection"
        else:
            signal = "NEUTRAL"
            verdict = f"RSI {rsi} — Neutral zone, no edge"

        return {"rsi": rsi, "signal": signal, "verdict": verdict, "suspect": False}


class MACDSignal:
    """
    MACD (12, 26, 9) — Moving Average Convergence Divergence.
    Bullish crossover (MACD crosses above signal) = BUY.
    Bearish crossover (MACD crosses below signal) = SELL.
    Histogram direction shows momentum strength.
    """
    name = "MACD (12,26,9)"

    @staticmethod
    def _ema(prices: list, period: int) -> list:
        if len(prices) < period:
            return []
        k = 2 / (period + 1)
        emas = [statistics.mean(prices[:period])]
        for p in prices[period:]:
            emas.append(p * k + emas[-1] * (1 - k))
        return emas

    @staticmethod
    def analyze(history: list) -> dict:
        if len(history) < 35:
            return {"macd": 0, "signal_line": 0, "histogram": 0,
                    "crossover": "NONE", "verdict": "Insufficient data"}

        prices = list(history)
        ema12 = MACDSignal._ema(prices, 12)
        ema26 = MACDSignal._ema(prices, 26)

        # Align lengths
        offset = len(ema12) - len(ema26)
        macd_line = [ema12[i + offset] - ema26[i] for i in range(len(ema26))]

        if len(macd_line) < 9:
            return {"macd": 0, "signal_line": 0, "histogram": 0,
                    "crossover": "NONE", "verdict": "Insufficient data"}

        signal_line = MACDSignal._ema(macd_line, 9)

        # Current and previous values
        macd_now  = macd_line[-1]
        macd_prev = macd_line[-2] if len(macd_line) > 1 else macd_now
        sig_now   = signal_line[-1]
        sig_prev  = signal_line[-2] if len(signal_line) > 1 else sig_now
        histogram = round(macd_now - sig_now, 2)

        # Crossover detection
        bullish_cross = macd_prev < sig_prev and macd_now > sig_now
        bearish_cross = macd_prev > sig_prev and macd_now < sig_now

        if bullish_cross:
            crossover = "BULLISH_CROSS"
            verdict = f"MACD bullish crossover — strong BUY signal (hist: {histogram:+.2f})"
        elif bearish_cross:
            crossover = "BEARISH_CROSS"
            verdict = f"MACD bearish crossover — strong SELL signal (hist: {histogram:+.2f})"
        elif macd_now > sig_now:
            crossover = "BULLISH"
            verdict = f"MACD above signal — bullish momentum (hist: {histogram:+.2f})"
        else:
            crossover = "BEARISH"
            verdict = f"MACD below signal — bearish momentum (hist: {histogram:+.2f})"

        return {
            "macd": round(macd_now, 2),
            "signal_line": round(sig_now, 2),
            "histogram": histogram,
            "crossover": crossover,
            "verdict": verdict,
        }


class BollingerBands:
    """
    Bollinger Bands (20-period, 2 std devs).
    Price near lower band = oversold bounce setup (BUY).
    Price near upper band = overbought rejection setup (SELL).
    Price breaking OUT of bands = strong breakout momentum.
    """
    name = "Bollinger Bands (20,2)"
    PERIOD = 20

    @staticmethod
    def analyze(history: list, current_price: float) -> dict:
        if len(history) < BollingerBands.PERIOD:
            return {
                "upper": 0, "middle": 0, "lower": 0,
                "position_pct": 50.0, "signal": "NEUTRAL",
                "verdict": "Insufficient data"
            }

        recent = list(history)[-BollingerBands.PERIOD:]
        middle = statistics.mean(recent)
        std = statistics.stdev(recent)
        upper = middle + 2 * std
        lower = middle - 2 * std
        band_width = upper - lower

        # Where is price within the bands? (0% = at lower, 100% = at upper)
        if band_width > 0:
            position_pct = ((current_price - lower) / band_width) * 100
        else:
            position_pct = 50.0

        position_pct = round(position_pct, 1)

        if current_price <= lower:
            signal = "STRONG_BUY"
            verdict = f"Price AT/BELOW lower band ({position_pct:.0f}%) — oversold breakout or bounce"
        elif position_pct < 15:
            signal = "BUY"
            verdict = f"Price near lower band ({position_pct:.0f}%) — likely bounce zone"
        elif current_price >= upper:
            signal = "STRONG_SELL"
            verdict = f"Price AT/ABOVE upper band ({position_pct:.0f}%) — overbought, expect pullback"
        elif position_pct > 85:
            signal = "SELL"
            verdict = f"Price near upper band ({position_pct:.0f}%) — overbought territory"
        else:
            signal = "NEUTRAL"
            verdict = f"Price in mid-band ({position_pct:.0f}%) — no edge"

        return {
            "upper": round(upper, 2),
            "middle": round(middle, 2),
            "lower": round(lower, 2),
            "position_pct": position_pct,
            "signal": signal,
            "verdict": verdict,
        }


class SupportResistance:
    """
    Identifies nearest support and resistance levels from recent price history.
    Finds swing highs and swing lows — where price reversed before.
    Provides context: is price near a bounce zone or a rejection zone?
    """
    name = "Support & Resistance"

    @staticmethod
    def analyze(history: list, current_price: float) -> dict:
        if len(history) < 30:
            return {
                "nearest_support": 0, "nearest_resistance": 0,
                "distance_to_support_pct": 0, "distance_to_resistance_pct": 0,
                "verdict": "Insufficient data"
            }

        prices = list(history)
        window = 5  # Swing point detection window

        swing_highs = []
        swing_lows = []

        for i in range(window, len(prices) - window):
            local_slice = prices[i - window: i + window + 1]
            if prices[i] == max(local_slice):
                swing_highs.append(prices[i])
            if prices[i] == min(local_slice):
                swing_lows.append(prices[i])

        # Find nearest support (below current price) and resistance (above)
        supports = sorted([p for p in swing_lows if p < current_price], reverse=True)
        resistances = sorted([p for p in swing_highs if p > current_price])

        nearest_support = supports[0] if supports else min(prices)
        nearest_resistance = resistances[0] if resistances else max(prices)

        dist_support_pct = ((current_price - nearest_support) / current_price) * 100
        dist_resist_pct = ((nearest_resistance - current_price) / current_price) * 100

        # Verdict: how close is the price to key levels?
        if dist_support_pct < 0.05:
            verdict = f"AT SUPPORT ₹{nearest_support:,.0f} — high-probability BUY zone"
            signal = "BUY"
        elif dist_resist_pct < 0.05:
            verdict = f"AT RESISTANCE ₹{nearest_resistance:,.0f} — high-probability SELL/SHORT zone"
            signal = "SELL"
        elif dist_support_pct < 0.15:
            verdict = f"Near support ₹{nearest_support:,.0f} ({dist_support_pct:.3f}% away) — watch for bounce"
            signal = "WATCH_BUY"
        elif dist_resist_pct < 0.15:
            verdict = f"Near resistance ₹{nearest_resistance:,.0f} ({dist_resist_pct:.3f}% away) — watch for rejection"
            signal = "WATCH_SELL"
        else:
            verdict = f"Mid-range. Support: ₹{nearest_support:,.0f} ({dist_support_pct:.2f}% away). Resistance: ₹{nearest_resistance:,.0f} ({dist_resist_pct:.2f}% away)"
            signal = "NEUTRAL"

        return {
            "nearest_support": round(nearest_support, 2),
            "nearest_resistance": round(nearest_resistance, 2),
            "distance_to_support_pct": round(dist_support_pct, 4),
            "distance_to_resistance_pct": round(dist_resist_pct, 4),
            "signal": signal,
            "verdict": verdict,
        }


class CandlePatterns:
    """
    Detects high-probability short-term reversal candlestick patterns
    using recent price ticks as pseudo-candles.
    
    Detects: Hammer, Shooting Star, Bullish/Bearish Engulfing, Doji.
    Each pattern has a known directional bias used by professional traders.
    """
    name = "Candle Patterns"

    @staticmethod
    def analyze(history: list) -> dict:
        """
        Uses groups of 5 ticks as synthetic candles (25s candles at 5s interval).
        Looks at last 3 synthetic candles for patterns.
        """
        if len(history) < 25:
            return {"pattern": "NONE", "signal": "NEUTRAL", "verdict": "Insufficient data"}

        def make_candle(ticks):
            o = ticks[0]
            c = ticks[-1]
            h = max(ticks)
            l = min(ticks)
            return {"open": o, "close": c, "high": h, "low": l}

        # Build 3 recent synthetic candles (each = 5 ticks = 25s)
        c1 = make_candle(list(history)[-25:-20])
        c2 = make_candle(list(history)[-20:-15])
        c3 = make_candle(list(history)[-15:-10])
        c4 = make_candle(list(history)[-10:-5])
        c_now = make_candle(list(history)[-5:])

        patterns_found = []

        body_now   = abs(c_now["close"] - c_now["open"])
        range_now  = c_now["high"] - c_now["low"] if c_now["high"] != c_now["low"] else 0.0001
        lower_wick = min(c_now["open"], c_now["close"]) - c_now["low"]
        upper_wick = c_now["high"] - max(c_now["open"], c_now["close"])

        # Hammer: small body, long lower wick, appears in downtrend → bullish
        if lower_wick > 2 * body_now and upper_wick < body_now and c4["close"] < c3["close"]:
            patterns_found.append(("HAMMER", "BUY", "Hammer candle in downtrend — bullish reversal signal"))

        # Shooting Star: small body, long upper wick, appears in uptrend → bearish
        if upper_wick > 2 * body_now and lower_wick < body_now and c4["close"] > c3["close"]:
            patterns_found.append(("SHOOTING_STAR", "SELL", "Shooting Star in uptrend — bearish reversal signal"))

        # Bullish Engulfing: current bullish candle larger than previous bearish
        if (c_now["close"] > c_now["open"] and c4["close"] < c4["open"] and
                c_now["open"] <= c4["close"] and c_now["close"] >= c4["open"]):
            patterns_found.append(("BULLISH_ENGULFING", "BUY", "Bullish Engulfing — strong buying pressure absorbed sellers"))

        # Bearish Engulfing: current bearish candle larger than previous bullish
        if (c_now["close"] < c_now["open"] and c4["close"] > c4["open"] and
                c_now["open"] >= c4["close"] and c_now["close"] <= c4["open"]):
            patterns_found.append(("BEARISH_ENGULFING", "SELL", "Bearish Engulfing — strong selling pressure absorbed buyers"))

        # Doji: open ≈ close (indecision)
        if body_now < range_now * 0.1:
            patterns_found.append(("DOJI", "NEUTRAL", "Doji — market indecision, wait for breakout direction"))

        if not patterns_found:
            return {"pattern": "NONE", "signal": "NEUTRAL", "verdict": "No recognizable pattern"}

        # Return the most actionable pattern
        for p in patterns_found:
            if p[1] in ("BUY", "SELL"):
                return {"pattern": p[0], "signal": p[1], "verdict": p[2]}

        p = patterns_found[0]
        return {"pattern": p[0], "signal": p[1], "verdict": p[2]}


# ─── v7 ADDITIONAL INDICATORS ─────────────────────────────────────────────────


class StochasticRSI:
    """
    Stochastic of RSI — more sensitive than raw RSI for catching turning points.
    Oscillates 0-100. < 20 = oversold BUY, > 80 = overbought SELL.
    Uses 14-period RSI over a 14-period lookback window.
    """
    name = "Stochastic RSI"
    RSI_PERIOD = 14
    STOCH_PERIOD = 14
    MIN_HISTORY = 60  # Need enough data for stable RSI series

    @staticmethod
    def _rsi_series(prices: list, period: int = 14) -> list:
        """Compute RSI value for each point in prices list."""
        rsi_vals = []
        for i in range(period, len(prices)):
            window = prices[i - period:i + 1]
            gains = [max(window[j] - window[j-1], 0) for j in range(1, len(window))]
            losses = [max(window[j-1] - window[j], 0) for j in range(1, len(window))]
            ag = sum(gains) / period
            al = sum(losses) / period
            if al == 0:
                rsi_vals.append(99.0 if ag > 0 else 50.0)
            else:
                rs = ag / al
                rsi_vals.append(100 - (100 / (1 + rs)))
        return rsi_vals

    @staticmethod
    def analyze(history: list) -> dict:
        if len(history) < StochasticRSI.MIN_HISTORY:
            return {"stochrsi": 50.0, "signal": "NEUTRAL",
                    "verdict": f"StochRSI warming up ({len(history)}/{StochasticRSI.MIN_HISTORY})"}

        prices = list(history)[-StochasticRSI.MIN_HISTORY:]
        rsi_series = StochasticRSI._rsi_series(prices, StochasticRSI.RSI_PERIOD)

        if len(rsi_series) < StochasticRSI.STOCH_PERIOD:
            return {"stochrsi": 50.0, "signal": "NEUTRAL", "verdict": "StochRSI: insufficient RSI series"}

        window = rsi_series[-StochasticRSI.STOCH_PERIOD:]
        lo, hi = min(window), max(window)
        current_rsi = rsi_series[-1]

        if hi == lo:
            stochrsi = 50.0
        else:
            stochrsi = round((current_rsi - lo) / (hi - lo) * 100, 1)

        if stochrsi < 10:
            signal, verdict = "STRONG_BUY", f"StochRSI {stochrsi:.1f} — DEEPLY OVERSOLD, strong reversal expected"
        elif stochrsi < 20:
            signal, verdict = "BUY", f"StochRSI {stochrsi:.1f} — Oversold, buying opportunity"
        elif stochrsi > 90:
            signal, verdict = "STRONG_SELL", f"StochRSI {stochrsi:.1f} — DEEPLY OVERBOUGHT, strong reversal expected"
        elif stochrsi > 80:
            signal, verdict = "SELL", f"StochRSI {stochrsi:.1f} — Overbought, selling opportunity"
        else:
            signal, verdict = "NEUTRAL", f"StochRSI {stochrsi:.1f} — Mid-range, no strong edge"

        return {"stochrsi": stochrsi, "signal": signal, "verdict": verdict}


class EMACross:
    """
    EMA(9) vs EMA(21) crossover — a non-correlated trend-following signal.
    Golden cross (EMA9 > EMA21 and trending up) = BUY.
    Death cross (EMA9 < EMA21 and trending down) = SELL.
    """
    name = "EMA Cross (9/21)"
    MIN_HISTORY = 30

    @staticmethod
    def _ema(prices: list, period: int) -> list:
        k = 2 / (period + 1)
        ema = [prices[0]]
        for p in prices[1:]:
            ema.append(p * k + ema[-1] * (1 - k))
        return ema

    @staticmethod
    def analyze(history: list) -> dict:
        if len(history) < EMACross.MIN_HISTORY:
            return {"signal": "NEUTRAL", "verdict": f"EMA Cross warming up ({len(history)}/{EMACross.MIN_HISTORY})"}

        prices = list(history)[-EMACross.MIN_HISTORY:]
        ema9  = EMACross._ema(prices, 9)
        ema21 = EMACross._ema(prices, 21)

        # Current and previous values
        e9_now, e9_prev   = ema9[-1],  ema9[-2]
        e21_now, e21_prev = ema21[-1], ema21[-2]

        gap_pct = (e9_now - e21_now) / e21_now * 100

        if e9_now > e21_now and e9_prev <= e21_prev:
            signal  = "STRONG_BUY"
            verdict = f"EMA Cross: GOLDEN CROSS just fired (9-EMA crossed above 21-EMA) | gap: {gap_pct:+.3f}%"
        elif e9_now > e21_now:
            signal  = "BUY"
            verdict = f"EMA(9) above EMA(21) — bullish trend intact | gap: {gap_pct:+.3f}%"
        elif e9_now < e21_now and e9_prev >= e21_prev:
            signal  = "STRONG_SELL"
            verdict = f"EMA Cross: DEATH CROSS just fired (9-EMA crossed below 21-EMA) | gap: {gap_pct:+.3f}%"
        elif e9_now < e21_now:
            signal  = "SELL"
            verdict = f"EMA(9) below EMA(21) — bearish trend intact | gap: {gap_pct:+.3f}%"
        else:
            signal  = "NEUTRAL"
            verdict = f"EMA(9) ≈ EMA(21) — no trend bias | gap: {gap_pct:+.3f}%"

        return {"ema9": round(e9_now, 2), "ema21": round(e21_now, 2),
                "gap_pct": round(gap_pct, 4), "signal": signal, "verdict": verdict}


class VolumeMomentum:
    """
    Detects volume spikes combined with price direction to confirm conviction.
    Uses bid/ask spread change as proxy for volume since CoinDCX ticker provides bid/ask.
    A tightening spread + upward price = buying pressure.
    Widening spread + downward price = selling panic.
    Uses price acceleration as the momentum proxy when volume is unavailable.
    """
    name = "Volume Momentum"
    MIN_HISTORY = 20

    @staticmethod
    def analyze(history: list) -> dict:
        if len(history) < VolumeMomentum.MIN_HISTORY:
            return {"signal": "NEUTRAL", "verdict": f"VolMom warming up ({len(history)}/{VolumeMomentum.MIN_HISTORY})"}

        prices = list(history)
        # Recent window vs baseline
        recent  = prices[-6:]    # last 30s
        baseline = prices[-20:-6]  # prior 70s

        recent_vol  = max(max(recent)  - min(recent),  0.0001)
        base_vol    = max(max(baseline) - min(baseline), 0.0001)
        vol_ratio   = recent_vol / base_vol

        price_dir = recent[-1] - recent[0]  # positive = rising, negative = falling

        if vol_ratio > 1.8 and price_dir > 0:
            signal  = "STRONG_BUY"
            verdict = f"Volume spike ({vol_ratio:.1f}x) with price rising — strong buying conviction"
        elif vol_ratio > 1.4 and price_dir > 0:
            signal  = "BUY"
            verdict = f"Elevated volume ({vol_ratio:.1f}x) with upward price — buying momentum"
        elif vol_ratio > 1.8 and price_dir < 0:
            signal  = "STRONG_SELL"
            verdict = f"Volume spike ({vol_ratio:.1f}x) with price falling — strong selling conviction"
        elif vol_ratio > 1.4 and price_dir < 0:
            signal  = "SELL"
            verdict = f"Elevated volume ({vol_ratio:.1f}x) with downward price — selling momentum"
        elif vol_ratio < 0.5:
            signal  = "NEUTRAL"
            verdict = f"Low activity ({vol_ratio:.1f}x normal) — dull market, avoid entry"
        else:
            signal  = "NEUTRAL"
            verdict = f"Normal activity ({vol_ratio:.1f}x) — no volume-based conviction"

        return {"vol_ratio": round(vol_ratio, 2), "price_dir": round(price_dir, 2),
                "signal": signal, "verdict": verdict}


# ─── ENGINE v6 TOOLS ──────────────────────────────────────────────────────────


class MarketRegimeDetector:
    """
    Classifies the current market into BULL / BEAR / CHOPPY.

    Algorithm:
      - EMA-20 and EMA-50 crossover  → trend direction
      - Price vs EMA-20              → short-term momentum
      - ADX-style normalised range   → trend STRENGTH filter
        (choppy = high frequency oscillation with small net move)

    Usage in engine:
      - BULL  → only accept LONG signals  (reject SHORT)
      - BEAR  → only accept SHORT signals (reject LONG)
      - CHOPPY → skip (no edge in mean-reverting noise)
    """
    name = "Market Regime"

    @staticmethod
    def _ema(prices: list, period: int) -> float:
        """Exponential moving average (simplified Wilder method)."""
        if len(prices) < period:
            return prices[-1] if prices else 0.0
        k = 2 / (period + 1)
        ema = prices[0]
        for p in prices[1:]:
            ema = p * k + ema * (1 - k)
        return ema

    @staticmethod
    def analyze(history: list) -> dict:
        if len(history) < 60:
            return {"regime": "UNKNOWN", "strength": 0.0,
                    "verdict": "Warming up — not enough data for regime", "trade_direction": "ANY"}

        prices = list(history)
        ema20  = MarketRegimeDetector._ema(prices[-60:],  20)
        ema50  = MarketRegimeDetector._ema(prices[-120:] if len(prices) >= 120 else prices, 50)
        price  = prices[-1]

        # ADX-style strength: compare net move vs total range over 30 ticks
        window = prices[-30:]
        net_move   = abs(window[-1] - window[0])
        total_range = sum(abs(window[i] - window[i-1]) for i in range(1, len(window))) or 1
        efficiency = net_move / total_range  # 0 = choppy, 1 = perfectly trending

        # Determine regime
        bull_signals = sum([
            price > ema20,       # price above short-term MA
            ema20 > ema50,       # short MA above long MA (golden cross)
            prices[-1] > prices[-10],  # last 50s price is up
        ])

        bear_signals = sum([
            price < ema20,
            ema20 < ema50,
            prices[-1] < prices[-10],
        ])

        if efficiency < 0.15:
            regime = "CHOPPY"
            verdict = f"CHOPPY — Market oscillating ({efficiency:.2%} efficiency). Skip all trades."
            direction = "NONE"
        elif bull_signals >= 2:
            regime = "BULL"
            verdict = f"BULL — EMA20({ema20:,.0f}) > EMA50({ema50:,.0f}). Take LONG only. Strength: {efficiency:.2%}"
            direction = "LONG"
        elif bear_signals >= 2:
            regime = "BEAR"
            verdict = f"BEAR — EMA20({ema20:,.0f}) < EMA50({ema50:,.0f}). Take SHORT only. Strength: {efficiency:.2%}"
            direction = "SHORT"
        else:
            regime = "NEUTRAL"
            verdict = f"NEUTRAL — Mixed signals. Require higher confidence."
            direction = "ANY"

        return {
            "regime": regime,
            "strength": round(efficiency, 3),
            "ema20": round(ema20, 0),
            "ema50": round(ema50, 0),
            "trade_direction": direction,
            "verdict": verdict,
        }


class ATRTracker:
    """
    Average True Range (ATR-14) — measures how much price moves per tick.

    Uses ATR to dynamically size stop-loss and take-profit:
      - Stop-Loss  = entry ± (ATR × SL_MULT)
      - Take-Profit = entry ± (ATR × TP_MULT)

    In high-volatility markets: wider stops (won't get shaken out)
    In low-volatility markets:  tighter stops (quick losses cut fast)
    """
    name = "ATR Tracker"
    SL_MULT = 1.5   # Stop-loss at 1.5× ATR
    TP_MULT = 3.0   # Take-profit at 3.0× ATR (always 2:1 R:R minimum)

    @staticmethod
    def analyze(history: list) -> dict:
        prices = list(history)
        if len(prices) < 16:
            return {"atr": 0, "atr_pct": 0.0, "stop_loss_pct": 0.003,
                    "take_profit_pct": 0.006, "verdict": "Warming up"}

        # True Range = max(high-low, |high-prev_close|, |low-prev_close|)
        # On tick data we approximate: TR_i = |price[i] - price[i-1]|
        trs = [abs(prices[i] - prices[i-1]) for i in range(-14, 0)]
        atr = statistics.mean(trs)
        price = prices[-1]
        atr_pct = atr / price if price else 0

        sl_pct = round(atr_pct * ATRTracker.SL_MULT, 5)
        tp_pct = round(atr_pct * ATRTracker.TP_MULT, 5)

        # Safety guards: never tighter than 0.1%, never wider than 1.5%
        sl_pct = max(0.001, min(0.015, sl_pct))
        tp_pct = max(0.002, min(0.030, tp_pct))

        return {
            "atr": round(atr, 2),
            "atr_pct": round(atr_pct * 100, 4),
            "stop_loss_pct": sl_pct,
            "take_profit_pct": tp_pct,
            "verdict": f"ATR={atr:.1f} ({atr_pct*100:.3f}%) → SL:{sl_pct*100:.2f}% / TP:{tp_pct*100:.2f}%"
        }


class MultiTimeframeConfirmer:
    """
    Builds synthetic 5-minute candles from 1-minute tick data and checks
    whether the higher timeframe trend agrees with the proposed trade direction.

    Why: 1-minute signals are noisy and frequently contradict the 5-minute trend.
    Requiring HTF agreement cuts false signals dramatically (~40% reduction).
    """
    name = "Multi-Timeframe"
    TICKS_PER_5MIN = 60  # 5 min × 12 ticks/min (5s interval)

    @staticmethod
    def analyze(history: list, proposed_direction: str) -> dict:
        """
        proposed_direction: 'LONG' or 'SHORT'
        Returns whether the 5-min structure CONFIRMS or REJECTS the signal.
        """
        prices = list(history)

        if len(prices) < MultiTimeframeConfirmer.TICKS_PER_5MIN * 2:
            return {"confirms": True, "htf_trend": "UNKNOWN",
                    "verdict": "Insufficient history — defaulting to ALLOW"}

        # Build 2 × 5-minute synthetic candles
        def candle(seg):
            return {"open": seg[0], "high": max(seg), "low": min(seg), "close": seg[-1]}

        c1 = candle(prices[-MultiTimeframeConfirmer.TICKS_PER_5MIN * 2:
                          -MultiTimeframeConfirmer.TICKS_PER_5MIN])
        c2 = candle(prices[-MultiTimeframeConfirmer.TICKS_PER_5MIN:])

        # 5-min trend: is c2 bullish or bearish vs c1?
        if c2["close"] > c1["close"] * 1.0002:   # at least 0.02% higher
            htf_trend = "BULL"
        elif c2["close"] < c1["close"] * 0.9998:
            htf_trend = "BEAR"
        else:
            htf_trend = "FLAT"

        # Also check: is current price above/below 5-min mid-range?
        mid = (c2["high"] + c2["low"]) / 2
        price_vs_mid = "ABOVE" if prices[-1] > mid else "BELOW"

        confirms = (
            (proposed_direction == "LONG"  and htf_trend in ("BULL", "FLAT") and price_vs_mid == "ABOVE") or
            (proposed_direction == "SHORT" and htf_trend in ("BEAR", "FLAT") and price_vs_mid == "BELOW") or
            htf_trend == "FLAT"  # Flat = no contradiction
        )

        verdict = (
            f"5m trend: {htf_trend}, price {price_vs_mid} mid → "
            f"{'✅ CONFIRMS' if confirms else '❌ REJECTS'} {proposed_direction}"
        )

        return {
            "confirms": confirms,
            "htf_trend": htf_trend,
            "price_vs_mid": price_vs_mid,
            "verdict": verdict,
        }


class SessionTimeFilter:
    """
    Crypto markets have predictable volume windows. This filter detects them.

    HIGH-QUALITY windows (IST):
      - Asian:  06:00 – 10:30 (moderate)
      - London: 13:30 – 18:00 (high)
      - US:     18:30 – 23:30 (highest)
      - Overlap: 18:30 – 20:30 (best of all)

    Off-hours:  00:00 – 06:00 IST — thin, erratic, skip unless 4+ signals
    """
    name = "Session Filter"

    @staticmethod
    def analyze() -> dict:
        from datetime import timezone, timedelta
        import datetime as dt

        IST = timezone(timedelta(hours=5, minutes=30))
        now_ist = dt.datetime.now(IST)
        h = now_ist.hour + now_ist.minute / 60.0

        if 18.5 <= h <= 20.5:
            session = "US_LONDON_OVERLAP"
            quality = "PREMIUM"
            confidence_multiplier = 1.15   # Lower the confidence bar slightly in premium hours
            min_pro_signals = 2
        elif 18.5 <= h <= 23.5:
            session = "US_OPEN"
            quality = "HIGH"
            confidence_multiplier = 1.10
            min_pro_signals = 2
        elif 13.5 <= h <= 18.0:
            session = "LONDON"
            quality = "HIGH"
            confidence_multiplier = 1.05
            min_pro_signals = 2
        elif 6.0 <= h <= 10.5:
            session = "ASIA"
            quality = "MODERATE"
            confidence_multiplier = 1.00
            min_pro_signals = 2
        else:
            session = "OFF_HOURS"
            quality = "LOW"
            confidence_multiplier = 0.90   # Raise effective bar during off-hours
            min_pro_signals = 2  # Quality controlled by confidence floor, not signal count

        return {
            "session": session,
            "quality": quality,
            "confidence_multiplier": confidence_multiplier,
            "min_pro_signals": min_pro_signals,
            "hour_ist": round(h, 2),
            "verdict": f"[{session}] Quality: {quality} | Bar: {min_pro_signals}+ signals needed",
        }
