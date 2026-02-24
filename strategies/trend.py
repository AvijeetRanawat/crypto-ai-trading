from .base import BaseStrategy, Signal

class TrendAgent(BaseStrategy):
    def __init__(self):
        # Trend agent doesn't have a weight because it's a MULTIPLIER, not an additive score.
        super().__init__(name="Market Health Trend", weight=1.0)

    def analyze(self, symbol: str, current_price: float, history: list, meta: dict) -> Signal:
        """
        The Trend Agent acts as a risk multiplier.
        If the coin is crashing hard over 24h, it returns a low multiplier (e.g., 0.2)
        to suppress BUY signals from other agents. If it's stable/pumping, it returns 1.0.
        """
        if not meta:
            return Signal("HOLD", 1.0, self.weight, "Neutral trend (no data)")

        change = meta.get('change_24h', 0)

        # Extreme crash: Suppress all buys
        if change < -10.0:
            return Signal("HOLD", 0.1, self.weight, "Severe Crash (-10%+) — Suppressing Buys")

        # Heavy dip: Reduce buy confidence by half
        if change < -5.0:
            return Signal("HOLD", 0.5, self.weight, "Heavy Dip (-5%+) — Caution")

        # Healthy market: Green light
        if change > 2.0:
            return Signal("HOLD", 1.2, self.weight, "Strong Uptrend (+2%+) — Boosting Buys")

        return Signal("HOLD", 1.0, self.weight, "Stable trend")
