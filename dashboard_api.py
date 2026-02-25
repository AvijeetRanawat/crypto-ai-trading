from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
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

# ── Session start time (used for "fresh start" clearing on restart) ──────────
SESSION_START = datetime.utcnow().isoformat()

# ─────────────────────────────────────────────────────────────────────────────
#  Core endpoints
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/session_start")
async def session_start():
    """Frontend uses this to detect a new session and clear stale UI state."""
    return {"session_start": SESSION_START}


@app.get("/api/trades/recent")
async def get_trades():
    trades = database.get_recent_trades(limit=30)
    return [
        {
            "id": t[0], "symbol": t[1], "side": t[2], "price": t[3],
            "quantity": t[4], "entry_time": t[5], "exit_time": t[6],
            "reason": t[7], "pnl": t[8], "status": t[9]
        } for t in trades
    ]


@app.get("/api/portfolio/history")
async def get_portfolio():
    history = database.get_portfolio_history(limit=200)
    return [
        {"id": h[0], "timestamp": h[1], "balance": h[2], "positions": h[3]}
        for h in history
    ]


@app.get("/api/portfolio/summary")
async def get_portfolio_summary():
    """Aggregated stats: balance, total PnL, win rate, open position."""
    trades = database.get_recent_trades(limit=500)
    closed = [t for t in trades if t[9] == "CLOSED"]
    wins = [t for t in closed if (t[8] or 0) > 0]
    total_pnl = sum(t[8] or 0 for t in closed)
    win_rate = (len(wins) / len(closed) * 100) if closed else 0
    missed_count = 0
    try:
        conn = sqlite3.connect(database.DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM signal_events WHERE outcome='MISSED'")
        missed_count = cur.fetchone()[0]
        conn.close()
    except Exception:
        pass
    open_pos = next((t for t in trades if t[9] == "OPEN"), None)
    return {
        "total_pnl": round(total_pnl, 2),
        "win_rate": round(win_rate, 1),
        "total_trades": len(closed),
        "missed_count": missed_count,
        "open_position": {
            "symbol": open_pos[1], "side": open_pos[2],
            "entry_price": open_pos[3], "entry_time": open_pos[5]
        } if open_pos else None,
    }


@app.get("/api/market/history")
async def get_market_history(symbol: str = "BTCINR"):
    history = database.get_price_history(symbol, limit=300)
    return [{"timestamp": h[0], "price": h[1]} for h in reversed(history)]


@app.get("/api/lessons")
async def get_lessons():
    conn = sqlite3.connect(database.DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM lessons ORDER BY id DESC LIMIT 15")
    lessons = cursor.fetchall()
    conn.close()
    return [
        {"id": l[0], "timestamp": l[1], "condition": l[2],
         "lesson": l[3], "severity": l[4]}
        for l in lessons
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
async def get_logs(lines: int = 50):
    """Read from the consolidated trading.log file."""
    log_path = os.path.join(os.path.dirname(__file__), "trading.log")
    if not os.path.exists(log_path):
        # Fallback: try any timestamped log
        import glob
        candidates = sorted(glob.glob(os.path.join(
            os.path.dirname(__file__), "trading_log_*.log"
        )), key=os.path.getmtime, reverse=True)
        log_path = candidates[0] if candidates else None

    if not log_path:
        return {"logs": ["No log file found. Start the trading engine first."]}
    try:
        with open(log_path, "r") as f:
            all_lines = f.readlines()
            return {"logs": all_lines[-lines:]}
    except Exception as e:
        return {"logs": [f"Error reading log: {e}"]}


@app.get("/api/signals/history")
async def get_signals_history(symbol: str = "BTCINR", limit: int = 200):
    rows = database.get_signal_history(symbol, limit=limit)
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

    # Session filter doesn't need price data
    session = SessionTimeFilter.analyze()

    try:
        conn = sqlite3.connect(database.DB_PATH)
        cur = conn.cursor()
        cur.execute(
            "SELECT price FROM prices WHERE symbol='BTCINR' "
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
            "verdict": f"Warming up ({len(rows)}/60 prices collected)",
            "atr_sl": 0.003, "atr_tp": 0.006, "atr_verdict": "ATR: warming up",
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
