from datetime import datetime

import pytest

import engine_simulator
from config import config


class DummyTradeLogger:
    called = []

    @staticmethod
    def log_trade(*args, **kwargs):
        DummyTradeLogger.called.append((args, kwargs))


@pytest.fixture(autouse=True)
def ensure_symbol_allowed(monkeypatch):
    monkeypatch.setattr(config, "is_symbol_allowed", lambda symbol: True)
    # Prevent __init__ from hitting the live DB to restore positions
    monkeypatch.setattr(engine_simulator, "get_open_positions", lambda: [])
    monkeypatch.setattr(engine_simulator, "get_latest_balance", lambda: None)
    yield


def test_enter_position_logs_and_updates_balance(monkeypatch):
    saved = {}

    def fake_save_trade(symbol, side, price, quantity, entry_time, reason, **kwargs):
        saved["symbol"] = symbol
        saved["entry_price"] = price
        return 42

    monkeypatch.setattr(engine_simulator, "save_trade", fake_save_trade)
    monkeypatch.setattr(engine_simulator, "save_portfolio_snapshot", lambda balance, count: None)
    monkeypatch.setattr(engine_simulator, "log_trade", DummyTradeLogger.log_trade)

    sim = engine_simulator.PaperTradingSimulator()
    result = sim.enter_position("BTCUSDT", price=1000, amount_usdt=100, reason="test")

    assert result is True
    assert sim.balance_usdt == 1150.0
    assert "BTCUSDT:SPOT" in sim.positions
    assert saved["symbol"] == "BTCUSDT"


def test_add_to_position_recalculates_entry(monkeypatch):
    monkeypatch.setattr(engine_simulator, "save_portfolio_snapshot", lambda balance, count: None)
    sim = engine_simulator.PaperTradingSimulator()
    sim.positions["BTCUSDT:SPOT"] = {
        "symbol": "BTCUSDT",
        "mode": "SPOT",
        "quantity": 1.0,
        "entry_price": 100,
        "entry_time": datetime.now(),
        "db_id": 1,
        "side": "LONG",
        "entry_reason": "initial",
        "peak_pnl_pct": 0.0,
        "trailing_active": False,
    }
    sim.balance_usdt = 500

    ok = sim.add_to_position("BTCUSDT", price=110, amount_usdt=100, reason="pyramid")
    assert ok
    assert sim.positions["BTCUSDT:SPOT"]["quantity"] > 1.0
    assert "pyramid" in sim.positions["BTCUSDT:SPOT"]["entry_reason"]


def test_exit_position_closes_and_logs(monkeypatch):
    exit_updates = {}

    def fake_update_trade_exit(trade_id, exit_time, profit):
        exit_updates["trade_id"] = trade_id
        exit_updates["profit"] = profit

    monkeypatch.setattr(engine_simulator, "update_trade_exit", fake_update_trade_exit)
    monkeypatch.setattr(engine_simulator, "save_portfolio_snapshot", lambda balance, count: None)
    monkeypatch.setattr(engine_simulator, "log_trade", DummyTradeLogger.log_trade)

    sim = engine_simulator.PaperTradingSimulator()
    sim.positions["SOLUSDT:SPOT"] = {
        "symbol": "SOLUSDT",
        "mode": "SPOT",
        "quantity": 1.0,
        "entry_price": 10,
        "entry_time": datetime.now(),
        "db_id": 101,
        "side": "LONG",
        "entry_reason": "initial",
        "peak_pnl_pct": 0.0,
        "trailing_active": False,
    }

    res = sim.exit_position("SOLUSDT", current_price=12, reason="target")
    # raw_profit = (12 - 10) * 1 = 2.0; fee = 10 * 0.0012 = 0.012; net = 1.988
    assert res["pnl"] == pytest.approx(1.988, abs=0.001)
    assert exit_updates["trade_id"] == 101
