from datetime import datetime

from config import config
from database import (
    save_trade,
    save_portfolio_snapshot,
    update_trade_exit,
)
from logger import logger, log_trade


class PaperTradingSimulator:
    def __init__(self):
        self.balance_usdt = float(config.STARTING_BALANCE_USDT)
        self.positions = {}

    def total_equity(self, latest_prices: dict | None = None) -> float:
        """Return cash + unrealized value of all open positions.

        If *latest_prices* is ``None``, positions are valued at their entry
        price (i.e. equity == session_start_balance when no PnL has occurred).
        """
        equity = self.balance_usdt
        for pos in self.positions.values():
            symbol = pos.get("symbol", "")
            qty = pos.get("quantity", 0.0)
            entry = pos.get("entry_price", 0.0)
            cur = (latest_prices or {}).get(symbol, entry)
            if pos.get("side") == "LONG":
                equity += qty * cur
            else:  # SHORT
                equity += qty * (2 * entry - cur)
        return equity

    @staticmethod
    def _pos_key(symbol: str, mode: str) -> str:
        return f"{str(symbol).upper()}:{str(mode).upper()}"

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
        mode=None,
    ):
        if not config.is_symbol_allowed(symbol):
            logger.error(f"Blocked non-allowlisted trade symbol: {symbol}")
            return False
        mode = str(mode or config.TRADING_PRODUCT).upper()
        pos_key = self._pos_key(symbol, mode)
        if pos_key in self.positions:
            logger.warning(f"Position already open for {symbol} ({mode}); skipping new entry.")
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
            mode=mode,
        )

        self.positions[pos_key] = {
            "symbol": str(symbol).upper(),
            "mode": mode,
            "side": side,
            "entry_price": price,
            "quantity": quantity,
            "entry_time": entry_time,
            "db_id": db_id,
            "entry_reason": reason,
            "peak_pnl_pct": 0.0,
            "trailing_active": False,
        }
        log_trade(side, symbol, price, quantity, reason, trade_id=db_id)
        save_portfolio_snapshot(self.balance_usdt, len(self.positions))

        emoji = "📈" if side == "LONG" else "📉"
        price_fmt = f"${price:,.2f}" if price >= 1.0 else f"${price:.6f}"
        logger.info(f"{emoji} {side}: {symbol} at {price_fmt} | Size: ${amount_usdt:,.0f} | Bal: ${self.balance_usdt:,.0f}")
        return True

    def add_to_position(self, symbol, price, amount_usdt, reason, mode=None):
        mode = str(mode or config.TRADING_PRODUCT).upper()
        pos_key = self._pos_key(symbol, mode)
        if pos_key not in self.positions:
            logger.warning(f"Cannot pyramid {symbol} ({mode}): no active position")
            return False
        if amount_usdt <= 0:
            return False
        if self.balance_usdt < amount_usdt:
            logger.warning(f"Insufficient balance to pyramid {symbol}")
            return False

        pos = self.positions[pos_key]
        old_qty = float(pos.get("quantity", 0.0) or 0.0)
        old_entry = float(pos.get("entry_price", price) or price)
        add_qty = float(amount_usdt) / float(price)
        new_qty = old_qty + add_qty
        if new_qty <= 0:
            return False

        old_notional = old_qty * old_entry
        add_notional = add_qty * float(price)
        new_entry = (old_notional + add_notional) / new_qty

        self.balance_usdt -= amount_usdt
        pos["quantity"] = new_qty
        pos["entry_price"] = new_entry
        # Preserve trailing stop state on pyramid — resetting would remove protective stops
        pos["entry_reason"] = f"{pos.get('entry_reason', '')} | {reason}".strip(" |")

        save_portfolio_snapshot(self.balance_usdt, len(self.positions))
        logger.info(
            "🔺 PYRAMID_ADD %s (%s) at $%.2f | add=$%.2f | new_qty=%.6f | new_entry=%.2f | bal=%.2f",
            symbol,
            mode,
            float(price),
            float(amount_usdt),
            float(new_qty),
            float(new_entry),
            float(self.balance_usdt),
        )
        return True

    def exit_position(self, symbol, current_price, reason, mode=None):
        mode = str(mode or config.TRADING_PRODUCT).upper()
        pos_key = self._pos_key(symbol, mode)
        if pos_key not in self.positions:
            return None

        pos = self.positions.pop(pos_key)
        side = pos["side"]

        if side == "LONG":
            raw_profit = (current_price - pos["entry_price"]) * pos["quantity"]
        else:
            raw_profit = (pos["entry_price"] - current_price) * pos["quantity"]

        # Apply leverage multiplier for FUTURES mode
        leverage = float(pos.get("recommended_leverage", 1) or 1)
        if mode == "FUTURES" and leverage > 1:
            raw_profit *= leverage

        # Deduct fee/slippage buffer from PnL
        notional = pos["quantity"] * pos["entry_price"]
        fee_cost = notional * (config.FEE_SLIPPAGE_BUFFER_PCT / 100.0)
        profit = raw_profit - fee_cost

        revenue = (pos["quantity"] * pos["entry_price"]) + profit
        self.balance_usdt += revenue
        exit_time = datetime.now()
        hold_secs = int((exit_time - pos["entry_time"]).total_seconds())

        update_trade_exit(pos["db_id"], exit_time, profit)
        pnl_str = f"+${profit:.2f}" if profit >= 0 else f"-${abs(profit):.2f}"

        log_trade("CLOSE", symbol, current_price, pos["quantity"],
                  f"{reason} | PnL: {pnl_str} | Held: {hold_secs}s", trade_id=pos["db_id"])

        save_portfolio_snapshot(self.balance_usdt, len(self.positions))

        emoji = "✅" if profit >= 0 else "❌"
        cp_fmt = f"${current_price:,.2f}" if current_price >= 1.0 else f"${current_price:.6f}"
        logger.info(
            f"{emoji} CLOSED {side} {symbol} ({mode}) at {cp_fmt} | PnL: {pnl_str} | Held: {hold_secs}s | {reason}"
        )

        return {
            "symbol": symbol, "side": side,
            "entry_price": pos["entry_price"], "exit_price": current_price,
            "hold_secs": hold_secs, "entry_reason": pos["entry_reason"],
            "pnl": profit,
            "mode": mode,
        }
