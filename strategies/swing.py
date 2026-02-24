from .base import BaseStrategy, Signal
from config import config

class SwingAgent(BaseStrategy):
    def __init__(self):
        super().__init__(name="Swing Reversion", weight=config.WEIGHT_SWING)

    def analyze(self, symbol: str, current_price: float, history: list, meta: dict) -> Signal:
        if not meta:
            return Signal("HOLD", 0.0, self.weight, "No meta data")

        low = meta.get('low', 0)
        high = meta.get('high', 0)
        change = meta.get('change_24h', 0)
        
        if low <= 0 or high <= 0:
            return Signal("HOLD", 0.0, self.weight, "Invalid 24h H/L")

        dip_pct = (current_price - low) / low

        # Sell signal if it's hitting the 24h ceiling
        peak_pct = (high - current_price) / current_price
        if peak_pct <= config.ENTRY_NEAR_LOW_PCT:
            return Signal("SELL", 0.8, self.weight, f"Near 24h High (1-{peak_pct*100:.1f}%)")

        # Buy signal if it's dipping and near 24h floor
        if change <= config.MIN_24H_DIP_PCT and dip_pct <= config.ENTRY_NEAR_LOW_PCT:
            # Confidence scales with how perfectly touching the bottom it is
            # If dip_pct == 0.0 (exact bottom), conf is 0.95
            # If dip_pct == 0.02 (2% off bottom), conf is 0.60
            closeness = 1.0 - (dip_pct / config.ENTRY_NEAR_LOW_PCT)
            confidence = min(0.95, 0.6 + (closeness * 0.35))
            return Signal("BUY", confidence, self.weight, f"Floor bounce ({dip_pct*100:.1f}% from low)")

        return Signal("HOLD", 0.0, self.weight, "Mid-range")
