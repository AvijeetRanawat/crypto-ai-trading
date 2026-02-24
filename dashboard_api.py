from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import database
import os

app = FastAPI()

# Enable CORS for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/api/trades/recent")
async def get_trades():
    trades = database.get_recent_trades(limit=20)
    # Convert list of tuples to list of dicts for JSON
    return [
        {
            "id": t[0], "symbol": t[1], "side": t[2], "price": t[3], 
            "quantity": t[4], "entry_time": t[5], "exit_time": t[6], 
            "reason": t[7], "pnl": t[8], "status": t[9]
        } for t in trades
    ]

@app.get("/api/portfolio/history")
async def get_portfolio():
    history = database.get_portfolio_history(limit=100)
    return [
        {"id": h[0], "timestamp": h[1], "balance": h[2], "positions": h[3]}
        for h in history
    ]

@app.get("/api/market/history")
async def get_market_history(symbol: str = "BTCINR"):
    history = database.get_price_history(symbol, limit=200)
    # Return in ASC order for Chart.js
    return [
        {"timestamp": h[0], "price": h[1]}
        for h in reversed(history)
    ]

@app.get("/api/lessons")
async def get_lessons():
    conn = database.sqlite3.connect(database.DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM lessons ORDER BY id DESC LIMIT 10')
    lessons = cursor.fetchall()
    conn.close()
    return [
        {"id": l[0], "timestamp": l[1], "condition": l[2], "lesson": l[3], "severity": l[4]}
        for l in lessons
    ]

@app.get("/api/intent")
async def get_intent():
    intent = database.get_intent()
    if not intent:
        return {"message": "Scanning markets...", "targets": []}
    return {
        "timestamp": intent[1],
        "message": intent[2],
        "targets": eval(intent[3]) if intent[3] else []
    }

@app.get("/api/logs")
async def get_logs():
    import glob
    log_files = glob.glob("trading_log_*.log")
    if not log_files:
        return {"logs": ["No log files found."]}
    
    # Get the latest log file
    latest_log = max(log_files, key=os.path.getmtime)
    try:
        with open(latest_log, "r") as f:
            # Return last 30 lines
            lines = f.readlines()
            return {"logs": lines[-30:]}
    except Exception as e:
        return {"logs": [f"Error reading logs: {e}"]}

@app.get("/api/signals/history")
async def get_signals_history(symbol: str = "BTCINR", limit: int = 150):
    rows = database.get_signal_history(symbol, limit=limit)
    return [
        {
            "timestamp": r[0], "price": r[1],
            "buy_votes": r[2], "sell_votes": r[3],
            "rsi": r[4], "macd": r[5], "bb_pct": r[6],
            "outcome": r[7], "claude_action": r[8], "claude_conf": r[9],
        }
        for r in reversed(rows)  # ASC order for charts
    ]

# Serve static files for the frontend
if os.path.exists("static"):
    app.mount("/", StaticFiles(directory="static", html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
