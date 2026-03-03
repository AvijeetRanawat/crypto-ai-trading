from datetime import datetime

from config import config
from database import (
    save_trade,
    save_portfolio_snapshot,
    update_trade_exit,
    get_open_positions,
    get_latest_balance,
)
from logger import logger, log_trade


class PaperTradingSimulator:
    def __init__(self):
        self.balance_usdt = float(config.STARTING_BALANCE_USDT)
        self.positions = {}
        self._restore_open_positions()

    def _restore_open_positions(self):
        """On startup, reload any OPEN trades from DB so the engine can manage them."""
        open_trades = get_open_positions()
        if not open_trades:
            return
        restored_balance = get_latest_balance()
        if restored_balance is not None:
            self.balance_usdt = restored_balance
        for row in open_trades:
            pos_key = self._pos_key(row["symbol"], row["mode"])
            self.positions[pos_key] = {
                "symbol": row["symbol"],
                "mode": row["mode"],
                "side": row["side"],
                "entry_price": row["entry_price"],
                "quantity": row["quantity"],
                "entry_time": row["entry_time"],
                "db_id": row["db_id"],
                "entry_reason": row["entry_reason"],
                "rl_context": row["rl_context"],
                "peak_pnl_pct": 0.0,
                "trailing_active": False,
            }
        logger.info(
            "RESTORED %d open position(s) from DB (balance=%.2f)",
            len(open_trades), self.balance_usdt,
        )

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
        rl_context=None,
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
        balance_before = self.balance_usdt
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
            rl_context=rl_context,
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
            "rl_context": rl_context,
            "peak_pnl_pct": 0.0,
            "trailing_active": False,
        }
        log_trade(side, symbol, price, quantity, reason, trade_id=db_id)
        save_portfolio_snapshot(self.balance_usdt, len(self.positions))

        rl_profile = (rl_context or {}).get("profile_id", "-")
        rl_decision = (rl_context or {}).get("decision_type", "-")
        rl_q = float((rl_context or {}).get("q_value", 0.0) or 0.0)
        rl_state = (rl_context or {}).get("state_key", "-")
        ep_fmt = f"${price:,.6f}" if price < 1.0 else f"${price:,.2f}"
        src_tag = decision_source or "-"
        det_str = f"{deterministic_conf:.3f}" if deterministic_conf is not None else "-"
        llm_str = f"{llm_conf:.3f}" if llm_conf is not None else "-"
        logger.info(
            "\u250c\u2500 TRADE ENTRY \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\n"
            "\u2502  Symbol  : %-10s | Mode: %-8s | Side: %s\n"
            "\u2502  Price   : %-14s | Qty: %.6f | Notional: $%.2f\n"
            "\u2502  Balance : $%.2f \u2192 $%.2f | DB id: %s\n"
            "\u2502  Source  : %-22s | Det.conf: %s | LLM.conf: %s\n"
            "\u2502  RL      : profile=%-15s | decision=%-12s | q=%+.5f\n"
            "\u2502  State   : %s\n"
            "\u2514\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500",
            symbol, mode, side,
            ep_fmt, quantity, amount_usdt,
            balance_before, self.balance_usdt, db_id,
            src_tag, det_str, llm_str,
            rl_profile, rl_decision, rl_q,
            rl_state,
        )
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
        balance_before = self.balance_usdt
        self.balance_usdt += revenue
        exit_time = datetime.now()
        hold_secs = int((exit_time - pos["entry_time"]).total_seconds())

        update_trade_exit(pos["db_id"], exit_time, profit)
        pnl_str = f"+${profit:.2f}" if profit >= 0 else f"-${abs(profit):.2f}"

        log_trade("CLOSE", symbol, current_price, pos["quantity"],
                  f"{reason} | PnL: {pnl_str} | Held: {hold_secs}s", trade_id=pos["db_id"])

        save_portfolio_snapshot(self.balance_usdt, len(self.positions))

        ep_fmt = f"${pos['entry_price']:,.6f}" if pos['entry_price'] < 1.0 else f"${pos['entry_price']:,.2f}"
        cp_fmt = f"${current_price:,.6f}" if current_price < 1.0 else f"${current_price:,.2f}"
        pnl_pct = (profit / notional * 100) if notional > 0 else 0.0
        pnl_emoji = "\u2705" if profit >= 0 else "\u274c"
        logger.info(
            "%s TRADE EXIT \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\n"
            "\u2502  Symbol  : %-10s | Mode: %-8s | Side: %s\n"
            "\u2502  Entry   : %-14s \u2192 Exit: %s\n"
            "\u2502  Qty     : %.6f | Notional: $%.2f\n"
            "\u2502  Raw PnL : %+.4f | Fee: -%.4f | Net PnL: %+.4f (%+.3f%%)\n"
            "\u2502  Held    : %ds  | Reason  : %s\n"
            "\u2502  Balance : $%.2f \u2192 $%.2f\n"
            "\u2514\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500",
            pnl_emoji,
            symbol, mode, side,
            ep_fmt, cp_fmt,
            pos["quantity"], notional,
            raw_profit, fee_cost, profit, pnl_pct,
            hold_secs, reason,
            balance_before, self.balance_usdt,
        )

        return {
            "symbol": symbol, "side": side,
            "entry_price": pos["entry_price"], "exit_price": current_price,
            "hold_secs": hold_secs, "entry_reason": pos["entry_reason"],
            "pnl": profit,
            "mode": mode,
        }
