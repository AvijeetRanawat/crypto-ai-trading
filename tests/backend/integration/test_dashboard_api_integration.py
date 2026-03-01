import sqlite3
import asyncio

import database


def _insert_signal(cur, decision_source: str, outcome: str = "SKIPPED"):
    cur.execute(
        """
        INSERT INTO signal_events (
            timestamp, symbol, price, buy_votes, sell_votes, rsi, macd, bb_pct,
            outcome, claude_action, claude_conf, session_id, process_id,
            decision_source, deterministic_action, deterministic_conf, llm_cost_usd, llm_tokens
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "2026-01-01T00:00:00",
            "BTCUSDT",
            100000.0,
            5,
            2,
            44.0,
            "BULLISH_CROSS",
            61.0,
            outcome,
            None,
            None,
            "test-session",
            999,
            decision_source,
            "LONG",
            0.77,
            0.0,
            0,
        ),
    )


def test_strategy_diagnostics_counts_mode_and_global_sources(api_module, isolated_db):
    conn = sqlite3.connect(str(isolated_db))
    cur = conn.cursor()

    _insert_signal(cur, "SPOT_DETERMINISTIC", outcome="TRADED")
    _insert_signal(cur, "REGIME_CHOPPY_SKIP", outcome="SKIPPED")
    _insert_signal(cur, "LLM_BUDGET_BLOCK", outcome="SKIPPED")
    conn.commit()
    conn.close()

    trade_id = database.save_trade(
        symbol="BTCUSDT",
        side="LONG",
        price=100000.0,
        quantity=0.01,
        entry_time=__import__("datetime").datetime.now(),
        reason="integration traded",
        session_id="test-session",
        process_id=999,
        decision_source="SPOT_DETERMINISTIC",
        deterministic_conf=0.77,
    )
    database.update_trade_exit(trade_id, __import__("datetime").datetime.now(), 12.34)

    payload = asyncio.run(api_module.get_strategy_diagnostics(symbol="BTCUSDT", mode="SPOT"))

    assert payload["mode"] == "SPOT"
    assert payload["session_signals"]["total"] == 3
    assert payload["session_signals"]["traded"] == 1
    assert payload["session_signals"]["skipped"] == 2
    assert payload["session_trades"]["closed"] == 1
    assert payload["session_trades"]["wins"] == 1
    assert payload["latest_trade_reason"] == "integration traded"
    assert len(payload["recent_decisions"]) >= 1


def test_warmup_and_regime_endpoints_use_configured_min_ticks(api_module, seed_basic_market_data):
    warmup = asyncio.run(api_module.get_warmup(symbol="BTCUSDT"))
    assert warmup["min_ticks"] == 10
    assert warmup["done"] is True

    regime = asyncio.run(api_module.get_regime(symbol="BTCUSDT"))
    assert regime["symbol"] == "BTCUSDT"
    assert "regime" in regime
    assert "atr_verdict" in regime
