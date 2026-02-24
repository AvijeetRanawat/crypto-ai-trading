class Signal:
    def __init__(self, action: str, confidence: float, weight: float, reason: str):
        """
        :param action: 'BUY', 'SELL', or 'HOLD'
        :param confidence: 0.0 to 1.0 probability of success
        :param weight: Multiplier for this strategy's importance
        :param reason: Human-readable explanation
        """
        self.action = action.upper()
        self.confidence = max(0.0, min(1.0, confidence))
        self.weight = weight
        self.reason = reason

    def __repr__(self):
        return f"<Signal {self.action} Conf:{self.confidence:.2f} W:{self.weight} Reason:'{self.reason}'>"

class BaseStrategy:
    def __init__(self, name: str, weight: float):
        self.name = name
        self.weight = weight

    def analyze(self, symbol: str, current_price: float, history: list, meta: dict) -> Signal:
        """
        Analyze the market and return a Signal.
        :param symbol: e.g. 'BTCINR'
        :param current_price: Latest tick price
        :param history: Rolling deque of historical prices (tick level)
        :param meta: Dict with 24h high/low/volume/change
        """
        raise NotImplementedError("Subclasses must implement analyze()")
