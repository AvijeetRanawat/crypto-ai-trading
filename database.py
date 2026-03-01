import json
import os
import sqlite3
from datetime import datetime, timedelta
from logger import logger

DB_PATH = "trading_data.db"

RUNTIME_SESSION_ID = os.getenv("TRADING_SESSION_ID", datetime.now().strftime("%Y%m%dT%H%M%S"))
RUNTIME_PROCESS_ID = os.getpid()


def _runtime_session_id() -> str:
    return os.getenv("TRADING_SESSION_ID", RUNTIME_SESSION_ID)


def _runtime_process_id() -> int:
    return os.getpid()


def get_runtime_context() -> dict:
    return {"session_id": _runtime_session_id(), "process_id": _runtime_process_id()}


def _conn():
    return sqlite3.connect(DB_PATH)


def _column_exists(cursor, table: str, column: str) -> bool:
    cursor.execute(f"PRAGMA table_info({table})")
    cols = [r[1] for r in cursor.fetchall()]
    return column in cols


def _ensure_column(cursor, table: str, column: str, column_def: str):
    if not _column_exists(cursor, table, column):
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_def}")


def init_db():
    conn = _conn()
    cursor = conn.cursor()

    # Trades Table
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT,
            side TEXT,
            price REAL,
            quantity REAL,
            entry_time TEXT,
            exit_time TEXT,
            reason TEXT,
            pnl REAL,
            status TEXT,
            session_id TEXT,
            process_id INTEGER,
            decision_source TEXT,
            deterministic_conf REAL,
            llm_conf REAL,
            llm_cost_usd REAL
        )
        """
    )

    # Portfolio Table
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS portfolio (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            balance_usdt REAL,
            open_positions_count INTEGER
        )
        """
    )

    # Lessons Table (Learning)
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS lessons (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            market_condition TEXT,
            lesson TEXT,
            severity TEXT
        )
        """
    )

    # Intent Table (Dashboard)
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS intent (
            id INTEGER PRIMARY KEY DEFAULT 1,
            timestamp TEXT,
            message TEXT,
            targets TEXT
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS intent_mode (
            mode TEXT PRIMARY KEY,
            timestamp TEXT,
            message TEXT,
            targets TEXT
        )
        """
    )

    # Prices Table
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS prices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            symbol TEXT,
            price REAL
        )
        """
    )

    # Signal Events Table (vote tracking + attribution)
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS signal_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            symbol TEXT,
            price REAL,
            buy_votes INTEGER,
            sell_votes INTEGER,
            weighted_buy REAL,
            weighted_sell REAL,
            total_weight REAL,
            rsi REAL,
            macd TEXT,
            bb_pct REAL,
            outcome TEXT,
            claude_action TEXT,
            claude_conf REAL,
            session_id TEXT,
            process_id INTEGER,
            decision_source TEXT,
            deterministic_action TEXT,
            deterministic_conf REAL,
            llm_cost_usd REAL,
            llm_tokens INTEGER
        )
        """
    )

    # LLM Usage Table (runtime budgeting + attribution)
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS llm_usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            session_id TEXT,
            process_id INTEGER,
            symbol TEXT,
            stage TEXT,
            model_id TEXT,
            input_tokens INTEGER,
            output_tokens INTEGER,
            total_tokens INTEGER,
            latency_ms INTEGER,
            estimated_cost_usd REAL,
            decision_context TEXT
        )
        """
    )
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_llm_usage_ts ON llm_usage(timestamp)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_llm_usage_session ON llm_usage(session_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_llm_usage_stage ON llm_usage(stage)")

    # RL Events Table (reward/penalty attribution)
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS rl_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            session_id TEXT,
            process_id INTEGER,
            symbol TEXT,
            mode TEXT,
            profile_id TEXT,
            state_key TEXT,
            event_type TEXT,
            reason TEXT,
            reward REAL,
            penalty REAL,
            raw_penalty REAL,
            pnl_reward REAL,
            hold_secs REAL
        )
        """
    )
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_rl_events_ts ON rl_events(timestamp)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_rl_events_session ON rl_events(session_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_rl_events_type ON rl_events(event_type)")

    # Strategy Rules Table (Distilled knowledge)
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS strategy_rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT UNIQUE,
            rule TEXT,
            source_count INTEGER,
            last_updated TEXT
        )
        """
    )

    # Migration safety for existing DBs.
    _ensure_column(cursor, "trades", "session_id", "TEXT")
    _ensure_column(cursor, "trades", "process_id", "INTEGER")
    _ensure_column(cursor, "trades", "decision_source", "TEXT")
    _ensure_column(cursor, "trades", "deterministic_conf", "REAL")
    _ensure_column(cursor, "trades", "llm_conf", "REAL")
    _ensure_column(cursor, "trades", "llm_cost_usd", "REAL")

    _ensure_column(cursor, "signal_events", "session_id", "TEXT")
    _ensure_column(cursor, "signal_events", "process_id", "INTEGER")
    _ensure_column(cursor, "signal_events", "decision_source", "TEXT")
    _ensure_column(cursor, "signal_events", "deterministic_action", "TEXT")
    _ensure_column(cursor, "signal_events", "deterministic_conf", "REAL")
    _ensure_column(cursor, "signal_events", "llm_cost_usd", "REAL")
    _ensure_column(cursor, "signal_events", "llm_tokens", "INTEGER")
    _ensure_column(cursor, "signal_events", "weighted_buy", "REAL")
    _ensure_column(cursor, "signal_events", "weighted_sell", "REAL")
    _ensure_column(cursor, "signal_events", "total_weight", "REAL")

    # Seed single record
    cursor.execute('INSERT OR IGNORE INTO intent (id, message, targets) VALUES (1, "Scanning...", "[]")')

    conn.commit()
    conn.close()
    logger.info(
        f"Database initialized successfully. session_id={_runtime_session_id()} process_id={_runtime_process_id()}"
    )


def save_price(symbol, price):
    conn = _conn()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO prices (timestamp, symbol, price)
        VALUES (?, ?, ?)
        """,
        (datetime.now().isoformat(), symbol, price),
    )
    conn.commit()
    conn.close()


def save_trade(
    symbol,
    side,
    price,
    quantity,
    entry_time,
    reason,
    status="OPEN",
    exit_time=None,
    pnl=0.0,
    session_id=None,
    process_id=None,
    decision_source=None,
    deterministic_conf=None,
    llm_conf=None,
    llm_cost_usd=None,
):
    conn = _conn()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO trades (
            symbol, side, price, quantity, entry_time, exit_time, reason, pnl, status,
            session_id, process_id, decision_source, deterministic_conf, llm_conf, llm_cost_usd
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            symbol,
            side,
            price,
            quantity,
            entry_time.isoformat(),
            exit_time.isoformat() if exit_time else None,
            reason,
            pnl,
            status,
            session_id or _runtime_session_id(),
            process_id or _runtime_process_id(),
            decision_source,
            deterministic_conf,
            llm_conf,
            llm_cost_usd,
        ),
    )
    trade_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return trade_id


def update_trade_exit(trade_id, exit_time, pnl, status="CLOSED"):
    conn = _conn()
    cursor = conn.cursor()
    cursor.execute(
        """
        UPDATE trades SET exit_time = ?, pnl = ?, status = ? WHERE id = ?
        """,
        (exit_time.isoformat(), pnl, status, trade_id),
    )
    conn.commit()
    conn.close()


def save_portfolio_snapshot(balance, positions_count):
    conn = _conn()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO portfolio (timestamp, balance_usdt, open_positions_count)
        VALUES (?, ?, ?)
        """,
        (datetime.now().isoformat(), balance, positions_count),
    )
    conn.commit()
    conn.close()


def save_lesson(condition, lesson, severity="INFO"):
    conn = _conn()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO lessons (timestamp, market_condition, lesson, severity)
        VALUES (?, ?, ?, ?)
        """,
        (datetime.now().isoformat(), condition, lesson, severity),
    )
    conn.commit()
    conn.close()


def update_intent(message, targets_list, mode: str = None):
    conn = _conn()
    cursor = conn.cursor()
    cursor.execute(
        """
        UPDATE intent SET timestamp = ?, message = ?, targets = ? WHERE id = 1
        """,
        (datetime.now().isoformat(), message, json.dumps(targets_list)),
    )
    if mode:
        mode_norm = str(mode).upper()
        cursor.execute(
            """
            INSERT INTO intent_mode (mode, timestamp, message, targets)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(mode) DO UPDATE SET
                timestamp=excluded.timestamp,
                message=excluded.message,
                targets=excluded.targets
            """,
            (mode_norm, datetime.now().isoformat(), message, json.dumps(targets_list)),
        )
    conn.commit()
    conn.close()


def get_intent(mode: str = None):
    conn = _conn()
    cursor = conn.cursor()
    intent = None
    if mode:
        cursor.execute("SELECT * FROM intent_mode WHERE mode = ?", (str(mode).upper(),))
        intent = cursor.fetchone()
    if not intent:
        cursor.execute("SELECT * FROM intent WHERE id = 1")
        intent = cursor.fetchone()
    conn.close()
    return intent


def get_recent_trades(limit=10):
    conn = _conn()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT * FROM trades ORDER BY id DESC LIMIT ?
        """,
        (limit,),
    )
    trades = cursor.fetchall()
    conn.close()
    return trades


def get_portfolio_history(limit=50):
    conn = _conn()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT * FROM portfolio ORDER BY id DESC LIMIT ?
        """,
        (limit,),
    )
    history = cursor.fetchall()
    conn.close()
    return history


def get_recent_lessons(limit=5):
    conn = _conn()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT market_condition, lesson, severity FROM lessons ORDER BY id DESC LIMIT ?
        """,
        (limit,),
    )
    lessons = cursor.fetchall()
    conn.close()
    return lessons


def get_price_history(symbol, limit=200):
    conn = _conn()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT timestamp, price FROM prices WHERE symbol = ? ORDER BY id DESC LIMIT ?
        """,
        (symbol, limit),
    )
    history = cursor.fetchall()
    conn.close()
    return history


def save_signal_event(
    symbol,
    price,
    buy_votes,
    sell_votes,
    weighted_buy,
    weighted_sell,
    total_weight,
    rsi,
    macd,
    bb_pct,
    outcome,
    claude_action=None,
    claude_conf=None,
    session_id=None,
    process_id=None,
    decision_source=None,
    deterministic_action=None,
    deterministic_conf=None,
    llm_cost_usd=None,
    llm_tokens=None,
):
    conn = _conn()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO signal_events (
            timestamp, symbol, price, buy_votes, sell_votes, weighted_buy, weighted_sell, total_weight, rsi, macd, bb_pct,
            outcome, claude_action, claude_conf, session_id, process_id,
            decision_source, deterministic_action, deterministic_conf, llm_cost_usd, llm_tokens
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            datetime.now().isoformat(),
            symbol,
            price,
            buy_votes,
            sell_votes,
            weighted_buy,
            weighted_sell,
            total_weight,
            round(rsi, 2),
            macd,
            round(bb_pct, 1),
            outcome,
            claude_action,
            claude_conf,
            session_id or _runtime_session_id(),
            process_id or _runtime_process_id(),
            decision_source,
            deterministic_action,
            deterministic_conf,
            llm_cost_usd,
            llm_tokens,
        ),
    )
    conn.commit()
    conn.close()


def save_llm_usage(
    stage: str,
    model_id: str,
    input_tokens: int,
    output_tokens: int,
    total_tokens: int,
    latency_ms: int,
    estimated_cost_usd: float,
    symbol: str = None,
    decision_context: str = None,
    session_id: str = None,
    process_id: int = None,
):
    conn = _conn()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO llm_usage (
            timestamp, session_id, process_id, symbol, stage, model_id,
            input_tokens, output_tokens, total_tokens, latency_ms, estimated_cost_usd, decision_context
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            datetime.now().isoformat(),
            session_id or _runtime_session_id(),
            process_id or _runtime_process_id(),
            symbol,
            stage,
            model_id,
            int(input_tokens or 0),
            int(output_tokens or 0),
            int(total_tokens or 0),
            int(latency_ms or 0),
            float(estimated_cost_usd or 0.0),
            decision_context,
        ),
    )
    conn.commit()
    conn.close()


def save_rl_event(
    mode: str,
    profile_id: str,
    state_key: str,
    event_type: str,
    reason: str = None,
    symbol: str = None,
    reward: float = 0.0,
    penalty: float = 0.0,
    raw_penalty: float = 0.0,
    pnl_reward: float = 0.0,
    hold_secs: float = 0.0,
    session_id: str = None,
    process_id: int = None,
):
    conn = _conn()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO rl_events (
            timestamp, session_id, process_id, symbol, mode, profile_id, state_key,
            event_type, reason, reward, penalty, raw_penalty, pnl_reward, hold_secs
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            datetime.now().isoformat(),
            session_id or _runtime_session_id(),
            process_id or _runtime_process_id(),
            symbol,
            mode,
            profile_id,
            state_key,
            event_type,
            reason,
            float(reward or 0.0),
            float(penalty or 0.0),
            float(raw_penalty or 0.0),
            float(pnl_reward or 0.0),
            float(hold_secs or 0.0),
        ),
    )
    conn.commit()
    conn.close()


def get_signal_history(symbol, limit=200):
    conn = _conn()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT timestamp, price, buy_votes, sell_votes, rsi, macd, bb_pct, outcome, claude_action, claude_conf
        FROM signal_events WHERE symbol = ? ORDER BY id DESC LIMIT ?
        """,
        (symbol, limit),
    )
    rows = cursor.fetchall()
    conn.close()
    return rows


def get_missed_opportunities(symbol, min_votes=3, limit=20):
    """Returns strong signal events where no trade was taken."""
    conn = _conn()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT timestamp, price, buy_votes, sell_votes, rsi, macd, bb_pct, claude_action, claude_conf
        FROM signal_events
        WHERE symbol = ? AND outcome = 'MISSED'
        AND (buy_votes >= ? OR sell_votes >= ?)
        ORDER BY id DESC LIMIT ?
        """,
        (symbol, min_votes, min_votes, limit),
    )
    rows = cursor.fetchall()
    conn.close()
    return rows


def save_distilled_rule(category, rule, source_count):
    """Saves or updates a master rule in the strategy_rules table."""
    conn = _conn()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO strategy_rules (category, rule, source_count, last_updated)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(category) DO UPDATE SET
            rule=excluded.rule,
            source_count=excluded.source_count,
            last_updated=excluded.last_updated
        """,
        (category, rule, source_count, datetime.now().isoformat()),
    )
    conn.commit()
    conn.close()


def get_distilled_rules():
    """Returns all summarized rules from the strategy_rules table."""
    conn = _conn()
    cursor = conn.cursor()
    cursor.execute("SELECT category, rule, source_count FROM strategy_rules")
    rows = cursor.fetchall()
    conn.close()
    return rows


def get_latest_closed_trade_id() -> int:
    conn = _conn()
    cursor = conn.cursor()
    cursor.execute("SELECT COALESCE(MAX(id), 0) FROM trades WHERE status='CLOSED'")
    val = int(cursor.fetchone()[0] or 0)
    conn.close()
    return val


def get_closed_trade_count_since(since_trade_id: int = 0, session_id: str = None) -> int:
    conn = _conn()
    cursor = conn.cursor()
    if session_id:
        cursor.execute(
            """
            SELECT COUNT(*) FROM trades
            WHERE status='CLOSED' AND id > ? AND session_id = ?
            """,
            (since_trade_id, session_id),
        )
    else:
        cursor.execute(
            """
            SELECT COUNT(*) FROM trades
            WHERE status='CLOSED' AND id > ?
            """,
            (since_trade_id,),
        )
    val = int(cursor.fetchone()[0] or 0)
    conn.close()
    return val


def get_llm_usage_summary(since_iso: str = None, session_id: str = None, stage: str = None) -> dict:
    conn = _conn()
    cursor = conn.cursor()
    q = [
        "SELECT COUNT(*),",
        "COALESCE(SUM(input_tokens),0),",
        "COALESCE(SUM(output_tokens),0),",
        "COALESCE(SUM(total_tokens),0),",
        "COALESCE(SUM(estimated_cost_usd),0)",
        "FROM llm_usage WHERE 1=1",
    ]
    args = []
    if since_iso:
        q.append("AND timestamp >= ?")
        args.append(since_iso)
    if session_id:
        q.append("AND session_id = ?")
        args.append(session_id)
    if stage:
        q.append("AND stage = ?")
        args.append(stage)

    cursor.execute(" ".join(q), tuple(args))
    row = cursor.fetchone()
    conn.close()
    return {
        "calls": int(row[0] or 0),
        "input_tokens": int(row[1] or 0),
        "output_tokens": int(row[2] or 0),
        "total_tokens": int(row[3] or 0),
        "cost_usd": float(row[4] or 0.0),
    }


def get_llm_call_count_last_hour(session_id: str = None) -> int:
    since = (datetime.now() - timedelta(hours=1)).isoformat()
    return int(get_llm_usage_summary(since_iso=since, session_id=session_id)["calls"])


def get_llm_cost_today(session_id: str = None) -> float:
    midnight = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    return float(get_llm_usage_summary(since_iso=midnight, session_id=session_id)["cost_usd"])
