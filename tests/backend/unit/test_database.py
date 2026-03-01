import sqlite3
from datetime import datetime

import pytest

import database


@pytest.fixture(autouse=True)
def clean_db(tmp_path, monkeypatch):
    db_file = tmp_path / "trading_db.sqlite"
    monkeypatch.setattr(database, "DB_PATH", str(db_file))
    database.init_db()
    yield


def _connect():
    conn = sqlite3.connect(database.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def test_save_llm_usage_records_row():
    database.save_llm_usage(
        stage="stage",
        model_id="model-x",
        input_tokens=10,
        output_tokens=5,
        total_tokens=15,
        latency_ms=123,
        estimated_cost_usd=0.007,
        symbol="BTCUSDT",
        decision_context="context",
    )

    conn = _connect()
    cur = conn.cursor()
    cur.execute("SELECT symbol, stage, model_id, total_tokens FROM llm_usage")
    row = cur.fetchone()
    conn.close()

    assert row["symbol"] == "BTCUSDT"
    assert row["stage"] == "stage"
    assert row["model_id"] == "model-x"
    assert row["total_tokens"] == 15


def test_get_signal_history_returns_recent():
    conn = _connect()
    cur = conn.cursor()
    for idx in range(3):
        cur.execute(
            """
            INSERT INTO signal_events (timestamp, symbol, price, buy_votes, sell_votes, rsi, macd, bb_pct, outcome, claude_action, claude_conf)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                datetime.now().isoformat(),
                "BTCUSDT",
                60000 + idx,
                4,
                2,
                50,
                "0.1",
                60,
                "TRADED",
                "LONG",
                0.9,
            ),
        )
    conn.commit()
    conn.close()

    history = database.get_signal_history("BTCUSDT", limit=2)
    assert len(history) == 2
    assert all(row[0] for row in history)


def test_get_missed_opportunities_filters_by_votes():
    conn = _connect()
    cur = conn.cursor()
    for votes in (1, 5, 8):
        cur.execute(
            """
            INSERT INTO signal_events (timestamp, symbol, price, buy_votes, sell_votes, rsi, macd, bb_pct, outcome, claude_action, claude_conf)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                datetime.now().isoformat(),
                "ETHUSDT",
                1800,
                votes,
                0,
                40,
                "0.2",
                45,
                "MISSED",
                "SELL",
                0.6,
            ),
        )
    conn.commit()
    conn.close()

    results = database.get_missed_opportunities("ETHUSDT", min_votes=3, limit=5)
    assert all((row[2] >= 3 or row[3] >= 3) for row in results)
    assert len(results) == 2
