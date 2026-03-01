import sqlite3
from pathlib import Path

import logger
import reset_session
import validation_gates


def _init_min_db(db_path: Path):
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS trades (status TEXT, pnl REAL)")
    cur.execute("CREATE TABLE IF NOT EXISTS llm_usage (estimated_cost_usd REAL)")
    cur.execute("CREATE TABLE IF NOT EXISTS portfolio (balance_usdt REAL)")
    cur.execute("CREATE TABLE IF NOT EXISTS signal_events (id INTEGER PRIMARY KEY AUTOINCREMENT)")
    cur.execute("CREATE TABLE IF NOT EXISTS prices (id INTEGER PRIMARY KEY AUTOINCREMENT)")
    cur.execute("CREATE TABLE IF NOT EXISTS lessons (id INTEGER PRIMARY KEY AUTOINCREMENT)")
    cur.execute("CREATE TABLE IF NOT EXISTS intent (id INTEGER PRIMARY KEY, message TEXT, targets TEXT)")
    cur.execute("INSERT OR IGNORE INTO intent (id, message, targets) VALUES (1, 'Scanning...', '[]')")
    conn.commit()
    conn.close()


def test_log_trade_with_and_without_id(caplog):
    with caplog.at_level("INFO"):
        logger.log_trade("BUY", "BTCUSDT", 100.0, 1.0, "reason")
        logger.log_trade("SELL", "ETHUSDT", 200.0, 2.0, "reason2", trade_id=7)

    joined = "\n".join(caplog.messages)
    assert "TRADE_LOG: BUY | BTCUSDT" in joined
    assert "ID: 7" in joined


def test_validation_gates_main_pass_and_fail_paths(tmp_path, monkeypatch, capsys):
    db_path = tmp_path / "gates.db"
    _init_min_db(db_path)

    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    # First run: mostly passing gates.
    cur.executemany("INSERT INTO trades (status, pnl) VALUES (?, ?)", [("CLOSED", 2.0)] * 160)
    cur.executemany("INSERT INTO llm_usage (estimated_cost_usd) VALUES (?)", [(0.1,), (0.2,)])
    cur.executemany("INSERT INTO portfolio (balance_usdt) VALUES (?)", [(1250.0,), (1249.0,), (1248.0,)])
    conn.commit()
    conn.close()

    monkeypatch.setattr(validation_gates, "DB_PATH", str(db_path))
    monkeypatch.setattr(validation_gates.config, "MAX_DAILY_DRAWDOWN_USD", 10.0)
    monkeypatch.chdir(tmp_path)
    Path("trading.log").write_text("all good")

    validation_gates.main()
    out = capsys.readouterr().out
    assert "[PASS] Stability" in out
    assert "[PASS] Cost discipline" in out
    assert "[PASS] Quality sample size" in out
    assert "[PASS] Net expectancy" in out

    # Second run: exercise failing branches (missing log file + zero gross positive pnl).
    Path("trading.log").unlink()
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.execute("DELETE FROM trades")
    cur.execute("DELETE FROM llm_usage")
    cur.execute("DELETE FROM portfolio")
    cur.executemany("INSERT INTO trades (status, pnl) VALUES (?, ?)", [("CLOSED", -1.0), ("CLOSED", -2.0)])
    cur.execute("INSERT INTO llm_usage (estimated_cost_usd) VALUES (5.0)")
    cur.executemany("INSERT INTO portfolio (balance_usdt) VALUES (?)", [(1000.0,), (900.0,)])
    conn.commit()
    conn.close()

    validation_gates.main()
    out2 = capsys.readouterr().out
    assert "[FAIL] Cost discipline" in out2
    assert "[FAIL] Quality sample size" in out2
    assert "[FAIL] Net expectancy" in out2
    assert "[FAIL] Drawdown cap" in out2


def test_reset_session_clears_transient_data_and_keeps_lessons(tmp_path, monkeypatch, capsys):
    db_path = tmp_path / "reset.db"
    _init_min_db(db_path)

    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.executemany("INSERT INTO trades (status, pnl) VALUES (?, ?)", [("OPEN", 0.0), ("CLOSED", 1.0)])
    cur.executemany("INSERT INTO portfolio (balance_usdt) VALUES (?)", [(1250.0,), (1240.0,)])
    cur.executemany("INSERT INTO signal_events DEFAULT VALUES", [(), ()])
    cur.executemany("INSERT INTO prices DEFAULT VALUES", [(), (), ()])
    cur.executemany("INSERT INTO lessons DEFAULT VALUES", [(), ()])
    conn.commit()
    conn.close()

    monkeypatch.setattr(reset_session, "DB_PATH", str(db_path))
    reset_session.reset_session()

    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM trades")
    trades_n = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM portfolio")
    port_n = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM signal_events")
    sig_n = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM prices")
    price_n = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM lessons")
    lessons_n = cur.fetchone()[0]
    cur.execute("SELECT message, targets FROM intent WHERE id=1")
    intent = cur.fetchone()
    conn.close()

    assert trades_n == 0
    assert port_n == 0
    assert sig_n == 0
    assert price_n == 0
    assert lessons_n == 2
    assert intent == ("New session starting...", "[]")

    printed = capsys.readouterr().out
    assert "SESSION RESET COMPLETE" in printed
