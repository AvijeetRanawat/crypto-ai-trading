import sqlite3
import os
from pathlib import Path

import database
import engine as engine_module
import session_review
from config import config
from strategies.tools import PriceVelocity


def test_price_velocity_keys_present():
    history = [100 + i for i in range(20)]
    out = PriceVelocity.analyze(history, current_price=121.0)
    assert "velocity_30s" in out
    assert "velocity_1m" in out
    assert "velocity_5m" in out
    assert "acceleration" in out


def test_symbol_allowlist_blocks_unknown_symbol():
    assert config.is_symbol_allowed("BTCUSDT") is True
    assert config.is_symbol_allowed("BTCINR") is False


def test_session_review_skips_when_not_enough_closed_trades(monkeypatch):
    monkeypatch.setattr(session_review, "_load_recent_data", lambda **_: ([], [], []))

    called = {"llm": False}

    def _should_not_call(*args, **kwargs):
        called["llm"] = True
        return {}

    monkeypatch.setattr(session_review, "_call_claude", _should_not_call)
    out = session_review.run_mini_review(bedrock_client=None, since_trade_id=7, min_closed_trades=10)
    assert out == 7
    assert called["llm"] is False


def test_db_session_process_attribution(tmp_path: Path, monkeypatch):
    test_db = tmp_path / "trading_data.db"
    monkeypatch.setattr(database, "DB_PATH", str(test_db))
    monkeypatch.setattr(database, "RUNTIME_SESSION_ID", "test-session")

    database.init_db()
    from datetime import datetime

    trade_id = database.save_trade(
        symbol="BTCUSDT",
        side="LONG",
        price=100.0,
        quantity=1.0,
        entry_time=datetime.now(),
        reason="test",
    )
    assert trade_id > 0

    database.save_signal_event(
        symbol="BTCUSDT",
        price=100.0,
        buy_votes=3,
        sell_votes=1,
        weighted_buy=3.0,
        weighted_sell=1.0,
        total_weight=8.0,
        rsi=44.2,
        macd="BULLISH",
        bb_pct=55.0,
        outcome="SKIPPED",
    )

    conn = sqlite3.connect(str(test_db))
    cur = conn.cursor()
    cur.execute("SELECT session_id, process_id FROM trades WHERE id = ?", (trade_id,))
    trade_row = cur.fetchone()
    cur.execute("SELECT session_id, process_id FROM signal_events ORDER BY id DESC LIMIT 1")
    sig_row = cur.fetchone()
    conn.close()

    assert trade_row == ("test-session", os.getpid())
    assert sig_row == ("test-session", os.getpid())


def test_engine_llm_budget_guard(monkeypatch):
    class DummyClient:
        latest_prices = {}
        ticker_meta = {}
        monitored_channels = []

    class DummyLLM:
        bedrock = None

    monkeypatch.setattr(engine_module, "LLMAgent", lambda: DummyLLM())
    eng = engine_module.TradingEngine(DummyClient())

    monkeypatch.setattr(engine_module, "get_llm_call_count_last_hour", lambda: config.LLM_MAX_CALLS_PER_HOUR)
    monkeypatch.setattr(engine_module, "get_llm_cost_today", lambda: 0.0)
    ok, reason = eng._llm_budget_ok()
    assert ok is False
    assert "hourly cap" in reason

    monkeypatch.setattr(engine_module, "get_llm_call_count_last_hour", lambda: 0)
    monkeypatch.setattr(engine_module, "get_llm_cost_today", lambda: config.LLM_DAILY_BUDGET_USD + 1.0)
    ok, reason = eng._llm_budget_ok()
    assert ok is False
    assert "daily budget" in reason


def test_engine_safe_tool_call_returns_fallback(monkeypatch):
    class DummyClient:
        latest_prices = {}
        ticker_meta = {}
        monitored_channels = []

    class DummyLLM:
        bedrock = None

    monkeypatch.setattr(engine_module, "LLMAgent", lambda: DummyLLM())
    eng = engine_module.TradingEngine(DummyClient())
    out = eng._safe_tool_call("broken_tool", lambda: 1 / 0, {"ok": False})
    assert out == {"ok": False}
