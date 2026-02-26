import sqlite3
from datetime import datetime
from logger import logger

DB_PATH = "trading_data.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Trades Table
    cursor.execute('''
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
            status TEXT
        )
    ''')
    
    # Portfolio Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS portfolio (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            balance_usdt REAL,
            open_positions_count INTEGER
        )
    ''')
    
    # Lessons Table (Learning)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS lessons (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            market_condition TEXT,
            lesson TEXT,
            severity TEXT
        )
    ''')

    # Intent Table (Dashboard)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS intent (
            id INTEGER PRIMARY KEY DEFAULT 1,
            timestamp TEXT,
            message TEXT,
            targets TEXT
        )
    ''')
    
    # Prices Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS prices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            symbol TEXT,
            price REAL
        )
    ''')
    
    # Signal Events Table (vote tracking + opportunity recording)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS signal_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            symbol TEXT,
            price REAL,
            buy_votes INTEGER,
            sell_votes INTEGER,
            rsi REAL,
            macd TEXT,
            bb_pct REAL,
            outcome TEXT,
            claude_action TEXT,
            claude_conf REAL
        )
    ''')

    # Strategy Rules Table (Distilled knowledge)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS strategy_rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT UNIQUE,
            rule TEXT,
            source_count INTEGER,
            last_updated TEXT
        )
    ''')

    # Seed single record
    cursor.execute('INSERT OR IGNORE INTO intent (id, message, targets) VALUES (1, "Scanning...", "[]")')
    
    conn.commit()
    conn.close()
    logger.info("Database initialized successfully.")

def save_price(symbol, price):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO prices (timestamp, symbol, price)
        VALUES (?, ?, ?)
    ''', (datetime.now().isoformat(), symbol, price))
    conn.commit()
    conn.close()

def save_trade(symbol, side, price, quantity, entry_time, reason, status="OPEN", exit_time=None, pnl=0.0):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO trades (symbol, side, price, quantity, entry_time, exit_time, reason, pnl, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (symbol, side, price, quantity, entry_time.isoformat(), 
          exit_time.isoformat() if exit_time else None, 
          reason, pnl, status))
    trade_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return trade_id

def update_trade_exit(trade_id, exit_time, pnl, status="CLOSED"):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE trades SET exit_time = ?, pnl = ?, status = ? WHERE id = ?
    ''', (exit_time.isoformat(), pnl, status, trade_id))
    conn.commit()
    conn.close()

def save_portfolio_snapshot(balance, positions_count):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO portfolio (timestamp, balance_usdt, open_positions_count)
        VALUES (?, ?, ?)
    ''', (datetime.now().isoformat(), balance, positions_count))
    conn.commit()
    conn.close()

def save_lesson(condition, lesson, severity="INFO"):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO lessons (timestamp, market_condition, lesson, severity)
        VALUES (?, ?, ?, ?)
    ''', (datetime.now().isoformat(), condition, lesson, severity))
    conn.commit()
    conn.close()

def update_intent(message, targets_list):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE intent SET timestamp = ?, message = ?, targets = ? WHERE id = 1
    ''', (datetime.now().isoformat(), message, str(targets_list)))
    conn.commit()
    conn.close()

def get_intent():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM intent WHERE id = 1')
    intent = cursor.fetchone()
    conn.close()
    return intent

def get_recent_trades(limit=10):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM trades ORDER BY id DESC LIMIT ?', (limit,))
    trades = cursor.fetchall()
    conn.close()
    return trades

def get_portfolio_history(limit=50):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM portfolio ORDER BY id DESC LIMIT ?', (limit,))
    history = cursor.fetchall()
    conn.close()
    return history

def get_recent_lessons(limit=5):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT market_condition, lesson, severity FROM lessons ORDER BY id DESC LIMIT ?', (limit,))
    lessons = cursor.fetchall()
    conn.close()
    return lessons

def get_price_history(symbol, limit=200):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT timestamp, price FROM prices WHERE symbol = ? ORDER BY id DESC LIMIT ?', (symbol, limit))
    history = cursor.fetchall()
    conn.close()
    return history

def save_signal_event(symbol, price, buy_votes, sell_votes, rsi, macd, bb_pct, outcome, claude_action=None, claude_conf=None):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO signal_events (timestamp, symbol, price, buy_votes, sell_votes, rsi, macd, bb_pct, outcome, claude_action, claude_conf)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (datetime.now().isoformat(), symbol, price, buy_votes, sell_votes,
          round(rsi, 2), macd, round(bb_pct, 1), outcome, claude_action, claude_conf))
    conn.commit()
    conn.close()

def get_signal_history(symbol, limit=200):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT timestamp, price, buy_votes, sell_votes, rsi, macd, bb_pct, outcome, claude_action, claude_conf
        FROM signal_events WHERE symbol = ? ORDER BY id DESC LIMIT ?
    ''', (symbol, limit))
    rows = cursor.fetchall()
    conn.close()
    return rows

def get_missed_opportunities(symbol, min_votes=3, limit=20):
    """Returns strong signal events where no trade was taken."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT timestamp, price, buy_votes, sell_votes, rsi, macd, bb_pct, claude_action, claude_conf
        FROM signal_events
        WHERE symbol = ? AND outcome = 'MISSED'
        AND (buy_votes >= ? OR sell_votes >= ?)
        ORDER BY id DESC LIMIT ?
    ''', (symbol, min_votes, min_votes, limit))
    rows = cursor.fetchall()
    conn.close()
    return rows

def save_distilled_rule(category, rule, source_count):
    """Saves or updates a master rule in the strategy_rules table."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO strategy_rules (category, rule, source_count, last_updated)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(category) DO UPDATE SET
            rule=excluded.rule,
            source_count=excluded.source_count,
            last_updated=excluded.last_updated
    ''', (category, rule, source_count, datetime.now().isoformat()))
    conn.commit()
    conn.close()

def get_distilled_rules():
    """Returns all summarized rules from the strategy_rules table."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT category, rule, source_count FROM strategy_rules')
    rows = cursor.fetchall()
    conn.close()
    return rows
