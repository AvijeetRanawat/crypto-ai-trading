from .base import BaseStrategy, Signal
from config import config

class MomentumAgent(BaseStrategy):
    def __init__(self):
        super().__init__(name="Momentum Scalper", weight=config.WEIGHT_MOMENTUM)

    def analyze(self, symbol: str, current_price: float, history: list, meta: dict) -> Signal:
        if not history or len(history) < 12:  # Need at least 1 min of 5s ticks
            return Signal("HOLD", 0.0, self.weight, "Warming up")

        # Compare to 1-minute ago (12 ticks back)
        idx_1m = -min(12, len(history))
        price_1m = history[idx_1m]
        mom_1m = (current_price - price_1m) / price_1m if price_1m > 0 else 0

        # Compare to 5-minutes ago (up to maxlen)
        price_5m = history[0]
        mom_5m = (current_price - price_5m) / price_5m if price_5m > 0 else 0

        # Both timeframes must be positive, and 1m must surge past a threshold
        if mom_1m > config.MIN_MOMENTUM_PCT and mom_5m > 0:
            # Confidence scales with how big the 1m surge is relative to the minimum threshold
            # e.g., if surge = 0.1% and min = 0.05%, ratio = 2.0 -> high confidence
            surge_ratio = mom_1m / config.MIN_MOMENTUM_PCT
            confidence = min(0.95, 0.5 + (surge_ratio * 0.1))
            return Signal("BUY", confidence, self.weight, f"1m Surge +{mom_1m*100:.2f}%")

        if mom_1m < -config.MIN_MOMENTUM_PCT:
            return Signal("SELL", 0.8, self.weight, f"1m Drop {mom_1m*100:.2f}%")

        return Signal("HOLD", 0.0, self.weight, "No momentum")
    
