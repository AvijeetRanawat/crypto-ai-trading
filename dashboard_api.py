from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

import database
import sqlite3
import os
import json
from datetime import datetime

app = FastAPI(title="Crypto AI Trading Dashboard")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Session start time — set once when this process boots ────────────────────
SESSION_START = datetime.utcnow().isoformat()

# ─────────────────────────────────────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────────────────────────────────────
def _db():
    conn = sqlite3.connect(database.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# ─────────────────────────────────────────────────────────────────────────────
#  Core endpoints
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/session_start")
async def session_start():
    """Frontend uses this to detect a new session and clear stale UI state."""
    return {"session_start": SESSION_START}


@app.get("/api/trades/recent")
async def get_trades():
    """Return only trades from the current session."""
    conn = _db()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, symbol, side, price, quantity, entry_time, exit_time, reason, pnl, status
        FROM trades
        WHERE status='CLOSED' AND entry_time >= ?
        ORDER BY id DESC LIMIT 50
    """, (SESSION_START,))
    rows = cur.fetchall()
    conn.close()
    return [
        {
            "id": r[0], "symbol": r[1], "side": r[2], "price": r[3],
            "quantity": r[4], "entry_time": r[5], "exit_time": r[6],
            "reason": r[7], "pnl": r[8], "status": r[9]
        } for r in rows
    ]


@app.get("/api/portfolio/history")
async def get_portfolio():
    """Equity curve — session only."""
    conn = _db()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, timestamp, balance_usdt, open_positions_count
        FROM portfolio
        WHERE timestamp >= ?
        ORDER BY id ASC LIMIT 300
    """, (SESSION_START,))
    rows = cur.fetchall()
    conn.close()
    return [{"id": r[0], "timestamp": r[1], "balance": r[2], "positions": r[3]} for r in rows]


@app.get("/api/portfolio/summary")
async def get_portfolio_summary():
    """Aggregated session stats: PnL, win rate, open position."""
    conn = _db()
    cur = conn.cursor()

    # Session closed trades
    cur.execute("""
        SELECT id, symbol, side, price, quantity, entry_time, exit_time, reason, pnl, status
        FROM trades WHERE status='CLOSED' AND entry_time >= ?
    """, (SESSION_START,))
    closed = cur.fetchall()

    wins = [t for t in closed if (t[8] or 0) > 0]
    total_pnl = sum(t[8] or 0 for t in closed)
    win_rate = (len(wins) / len(closed) * 100) if closed else 0

    # Missed signals this session
    cur.execute("""
        SELECT COUNT(*) FROM signal_events
        WHERE outcome='MISSED' AND timestamp >= ?
    """, (SESSION_START,))
    missed_count = cur.fetchone()[0]

    # Open position
    cur.execute("""
        SELECT symbol, side, price, entry_time FROM trades
        WHERE status='OPEN' ORDER BY id DESC LIMIT 1
    """)
    open_pos = cur.fetchone()
    conn.close()

    return {
        "total_pnl": round(total_pnl, 2),
        "win_rate": round(win_rate, 1),
        "total_trades": len(closed),
        "missed_count": missed_count,
        "open_position": {
            "symbol": open_pos[0], "side": open_pos[1],
            "entry_price": open_pos[2], "entry_time": open_pos[3]
        } if open_pos else None,
    }


@app.get("/api/market/history")
async def get_market_history(symbol: str = "BTCUSDT"):
    """Price chart — session only."""
    conn = _db()
    cur = conn.cursor()
    cur.execute("""
        SELECT timestamp, price FROM prices
        WHERE symbol=? AND timestamp >= ?
        ORDER BY timestamp ASC LIMIT 500
    """, (symbol, SESSION_START))
    rows = cur.fetchall()
    conn.close()
    return [{"timestamp": r[0], "price": r[1]} for r in rows]


@app.get("/api/lessons")
async def get_lessons():
    """Most recent lessons (lifetime — lessons carry over across sessions)."""
    conn = _db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM lessons ORDER BY id DESC LIMIT 15")
    rows = cur.fetchall()
    conn.close()
    return [
        {"id": r[0], "timestamp": r[1], "condition": r[2], "lesson": r[3], "severity": r[4]}
        for r in rows
    ]


@app.get("/api/intent")
async def get_intent():
    intent = database.get_intent()
    if not intent:
        return {"message": "Scanning markets...", "targets": []}
    try:
        targets = json.loads(intent[3]) if intent[3] else []
    except Exception:
        try:
            targets = eval(intent[3]) if intent[3] else []
        except Exception:
            targets = []
    return {"timestamp": intent[1], "message": intent[2], "targets": targets}


@app.get("/api/logs")
async def get_logs(lines: int = 60):
    """Read from the consolidated trading.log file (cleared on restart)."""
    log_path = os.path.join(os.path.dirname(__file__), "trading.log")
    if not os.path.exists(log_path):
        return {"logs": ["No log file found. Start the trading engine first."]}
    try:
        with open(log_path, "r") as f:
            all_lines = f.readlines()
            return {"logs": all_lines[-lines:]}
    except Exception as e:
        return {"logs": [f"Error reading log: {e}"]}


@app.get("/api/signals/history")
async def get_signals_history(symbol: str = "BTCUSDT", limit: int = 200):
    """Signal events — session only."""
    conn = _db()
    cur = conn.cursor()
    cur.execute("""
        SELECT timestamp, price, buy_votes, sell_votes, rsi, macd, bb_pct, outcome, claude_action, claude_conf
        FROM signal_events
        WHERE symbol=? AND timestamp >= ?
        ORDER BY id DESC LIMIT ?
    """, (symbol, SESSION_START, limit))
    rows = cur.fetchall()
    conn.close()
    return [
        {
            "timestamp": r[0], "price": r[1],
            "buy_votes": r[2], "sell_votes": r[3],
            "rsi": r[4], "macd": r[5], "bb_pct": r[6],
            "outcome": r[7], "claude_action": r[8], "claude_conf": r[9],
        }
        for r in reversed(rows)
    ]


@app.get("/api/regime")
async def get_regime():
    """Run regime/ATR/session snapshot from latest prices in DB."""
    from strategies.tools import MarketRegimeDetector, ATRTracker, SessionTimeFilter

    session = SessionTimeFilter.analyze()

    try:
        conn = sqlite3.connect(database.DB_PATH)
        cur = conn.cursor()
        cur.execute(
            "SELECT price FROM prices WHERE symbol='BTCUSDT' "
            "ORDER BY timestamp DESC LIMIT 200"
        )
        rows = cur.fetchall()
        conn.close()
    except Exception as e:
        return {
            "regime": "ERROR", "verdict": str(e),
            "session": session["session"],
            "session_quality": session["quality"],
            "session_verdict": session["verdict"],
        }

    if len(rows) < 30:
        return {
            "regime": "WARMING_UP", "strength": 0,
            "verdict": f"Warming up ({len(rows)}/30 prices collected)",
            "atr_sl": 0.004, "atr_tp": 0.008, "atr_verdict": "ATR: warming up",
            "session": session["session"],
            "session_quality": session["quality"],
            "session_verdict": session["verdict"],
        }

    prices = [r[0] for r in reversed(rows)]
    regime = MarketRegimeDetector.analyze(prices)
    atr    = ATRTracker.analyze(prices)
    return {
        "regime":          regime["regime"],
        "strength":        regime["strength"],
        "ema20":           regime.get("ema20", 0),
        "ema50":           regime.get("ema50", 0),
        "trade_direction": regime["trade_direction"],
        "verdict":         regime["verdict"],
        "atr_sl":          atr["stop_loss_pct"],
        "atr_tp":          atr["take_profit_pct"],
        "atr_verdict":     atr["verdict"],
        "session":         session["session"],
        "session_quality": session["quality"],
        "session_verdict": session["verdict"],
    }


# ─────────────────────────────────────────────────────────────────────────────
#  Static frontend
# ─────────────────────────────────────────────────────────────────────────────
if os.path.exists("static"):
    app.mount("/", StaticFiles(directory="static", html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
