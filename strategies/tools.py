"""
Analysis Tools — Lightweight, pure-Python data processors.
These tools run locally (free, instant) and feed structured outputs to Claude.

v2: Added RSIAnalyzer, MACDSignal, BollingerBands, SupportResistance, CandlePatterns
"""
import statistics
from logger import logger


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
    <30 = oversold (BUY signal), >70 = overbought (SELL signal).
    One of the highest-reliability indicators for crypto scalping.
    """
    name = "RSI (14)"
    PERIOD = 14

    @staticmethod
    def analyze(history: list) -> dict:
        if len(history) < RSIAnalyzer.PERIOD + 1:
            return {"rsi": 50.0, "signal": "NEUTRAL", "verdict": "Insufficient data"}

        prices = list(history)[-(RSIAnalyzer.PERIOD + 1):]
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

        if avg_loss == 0:
            rsi = 100.0
        else:
            rs = avg_gain / avg_loss
            rsi = 100 - (100 / (1 + rs))

        rsi = round(rsi, 2)

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

        return {"rsi": rsi, "signal": signal, "verdict": verdict}


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
