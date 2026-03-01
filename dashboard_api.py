from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

import database
import sqlite3
import os
import json
from datetime import datetime
from config import config
from news_sentiment import build_sentiment_snapshot, summarize_sentiment_with_openai
from database import save_llm_usage
from logger import logger

app = FastAPI(title="Crypto AI Trading Dashboard")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
import time

# ── Session start time — set once when this process boots ────────────────────
SESSION_START = datetime.now().isoformat()
SESSION_START_MS = int(time.time() * 1000)
SESSION_ID = database.get_runtime_context()["session_id"]

# ─────────────────────────────────────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────────────────────────────────────
def _db():
    conn = sqlite3.connect(database.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


@app.middleware("http")
async def log_all_api_requests(request, call_next):
    path = request.url.path
    if not path.startswith("/api/"):
        return await call_next(request)

    started = time.perf_counter()
    request_id = f"{int(time.time() * 1000)}-{abs(hash((request.method, path, request.url.query))) % 10000}"
    query = request.url.query or "-"
    client_host = request.client.host if request.client else "-"
    user_agent = request.headers.get("user-agent", "-")
    forwarded_for = request.headers.get("x-forwarded-for", "-")
    referer = request.headers.get("referer", "-")

    logger.info(
        "API_REQ id=%s method=%s path=%s query=%s client=%s xff=%s ua=%s referer=%s",
        request_id,
        request.method,
        path,
        query,
        client_host,
        forwarded_for,
        user_agent,
        referer,
    )

    try:
        response = await call_next(request)
    except Exception as e:
        duration_ms = int((time.perf_counter() - started) * 1000)
        logger.error(
            "API_ERR id=%s method=%s path=%s query=%s duration_ms=%s error=%s",
            request_id,
            request.method,
            path,
            query,
            duration_ms,
            e,
            exc_info=True,
        )
        raise

    duration_ms = int((time.perf_counter() - started) * 1000)
    content_length = response.headers.get("content-length", "-")
    content_type = response.headers.get("content-type", "-")
    logger.info(
        "API_RES id=%s method=%s path=%s status=%s duration_ms=%s bytes=%s content_type=%s",
        request_id,
        request.method,
        path,
        response.status_code,
        duration_ms,
        content_length,
        content_type,
    )

    if response.status_code >= 400:
        logger.warning(
            "API_WARN id=%s method=%s path=%s status=%s",
            request_id,
            request.method,
            path,
            response.status_code,
        )

    return response


# ─────────────────────────────────────────────────────────────────────────────
#  Core endpoints
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/session_start")
async def session_start():
    """Frontend uses this to detect a new session and clear stale UI state."""
    return {
        "session_start": SESSION_START,
        "session_start_ms": SESSION_START_MS
    }


@app.get("/api/warmup")
async def get_warmup(symbol: str = "BTCUSDT"):
    """Return warmup progress: how many price ticks collected vs the 35 needed."""
    MIN_TICKS = 35
    symbol = str(symbol).upper()
    if not config.is_symbol_allowed(symbol):
        symbol = "BTCUSDT"
    conn = _db()
    cur = conn.cursor()
    cur.execute(
        "SELECT COUNT(*) FROM prices WHERE symbol=? AND timestamp >= ?",
        (symbol, SESSION_START)
    )
    ticks = cur.fetchone()[0]
    conn.close()
    done = ticks >= MIN_TICKS
    return {
        "symbol": symbol,
        "ticks": min(ticks, MIN_TICKS),
        "min_ticks": MIN_TICKS,
        "pct": min(100, round(ticks / MIN_TICKS * 100)),
        "done": done,
        "seconds_remaining": max(0, (MIN_TICKS - ticks) * 60),
    }


@app.get("/api/trades/recent")
async def get_trades():
    """Return only trades from the current session."""
    conn = _db()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, symbol, side, price, quantity, entry_time, exit_time, reason, pnl, status
        FROM trades
        WHERE status='CLOSED' AND entry_time >= ?
        AND (session_id = ? OR session_id IS NULL)
        ORDER BY id DESC LIMIT 50
    """, (SESSION_START, SESSION_ID))
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
        FROM trades
        WHERE status='CLOSED' AND entry_time >= ?
        AND (session_id = ? OR session_id IS NULL)
    """, (SESSION_START, SESSION_ID))
    closed = cur.fetchall()

    wins = [t for t in closed if (t[8] or 0) > 0]
    total_pnl = sum(t[8] or 0 for t in closed)
    win_rate = (len(wins) / len(closed) * 100) if closed else 0

    # Missed signals this session
    cur.execute("""
        SELECT COUNT(*) FROM signal_events
        WHERE outcome='MISSED' AND timestamp >= ?
        AND (session_id = ? OR session_id IS NULL)
    """, (SESSION_START, SESSION_ID))
    missed_count = cur.fetchone()[0]

    cur.execute("""
        SELECT COUNT(*) FROM signal_events
        WHERE outcome='TRADED' AND timestamp >= ?
        AND (session_id = ? OR session_id IS NULL)
    """, (SESSION_START, SESSION_ID))
    traded_signals = cur.fetchone()[0]

    # LLM usage (session + day)
    midnight = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    cur.execute("""
        SELECT COALESCE(SUM(estimated_cost_usd), 0), COUNT(*), COALESCE(SUM(total_tokens), 0)
        FROM llm_usage
        WHERE timestamp >= ? AND (session_id = ? OR session_id IS NULL)
    """, (SESSION_START, SESSION_ID))
    llm_cost_session, llm_calls_session, llm_tokens_session = cur.fetchone()

    cur.execute("""
        SELECT COALESCE(SUM(estimated_cost_usd), 0), COUNT(*)
        FROM llm_usage
        WHERE timestamp >= ?
    """, (midnight,))
    llm_cost_today, llm_calls_today = cur.fetchone()

    cur.execute("""
        SELECT COUNT(*)
        FROM llm_usage
        WHERE timestamp >= ? AND (session_id = ? OR session_id IS NULL)
        AND stage = 'sonnet_decision'
    """, (SESSION_START, SESSION_ID))
    llm_decision_calls_session = cur.fetchone()[0]

    # Open position
    cur.execute(
        """
        SELECT symbol, side, price, entry_time FROM trades
        WHERE status='OPEN' AND (session_id = ? OR session_id IS NULL)
        ORDER BY id DESC LIMIT 1
        """,
        (SESSION_ID,),
    )
    open_pos = cur.fetchone()
    conn.close()

    cost_per_traded_signal = (llm_cost_session / traded_signals) if traded_signals else None
    cost_per_dollar_pnl = (llm_cost_session / total_pnl) if total_pnl > 0 else None
    llm_trade_conversion_rate = (
        (traded_signals / llm_decision_calls_session) * 100
        if llm_decision_calls_session > 0
        else 0.0
    )

    return {
        "total_pnl": round(total_pnl, 2),
        "win_rate": round(win_rate, 1),
        "total_trades": len(closed),
        "missed_count": missed_count,
        "traded_signals": traded_signals,
        "llm_cost_today": round(llm_cost_today or 0.0, 4),
        "llm_calls_today": int(llm_calls_today or 0),
        "llm_cost_session": round(llm_cost_session or 0.0, 4),
        "llm_calls_session": int(llm_calls_session or 0),
        "llm_tokens_session": int(llm_tokens_session or 0),
        "llm_decision_calls_session": int(llm_decision_calls_session or 0),
        "llm_cost_per_traded_signal": round(cost_per_traded_signal, 4) if cost_per_traded_signal is not None else None,
        "llm_cost_per_dollar_pnl": round(cost_per_dollar_pnl, 4) if cost_per_dollar_pnl is not None else None,
        "llm_trade_conversion_rate": round(llm_trade_conversion_rate, 2),
        "open_position": {
            "symbol": open_pos[0], "side": open_pos[1],
            "entry_price": open_pos[2], "entry_time": open_pos[3]
        } if open_pos else None,
    }


@app.get("/api/market/history")
async def get_market_history(symbol: str = "BTCUSDT"):
    """Price chart — session only."""
    symbol = str(symbol).upper()
    if not config.is_symbol_allowed(symbol):
        symbol = "BTCUSDT"
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
    """Current-session lessons only. All lessons are retained in DB for long-term learning."""
    conn = _db()
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM lessons WHERE timestamp >= ? ORDER BY id DESC LIMIT 20",
        (SESSION_START,)
    )
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
async def get_logs(lines: int = 120):
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
        WHERE symbol=? AND timestamp >= ? AND (session_id = ? OR session_id IS NULL)
        ORDER BY id DESC LIMIT ?
    """, (symbol, SESSION_START, SESSION_ID, limit))
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


@app.get("/api/llm/summary")
async def get_llm_summary():
    """LLM spend/token metrics for session, today, and all-time persistence."""
    conn = _db()
    cur = conn.cursor()
    midnight = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).isoformat()

    cur.execute("""
        SELECT COALESCE(SUM(estimated_cost_usd),0), COUNT(*), COALESCE(SUM(total_tokens),0)
        FROM llm_usage
        WHERE timestamp >= ? AND (session_id = ? OR session_id IS NULL)
    """, (SESSION_START, SESSION_ID))
    cost_session, calls_session, tokens_session = cur.fetchone()

    cur.execute("""
        SELECT COALESCE(SUM(estimated_cost_usd),0), COUNT(*), COALESCE(SUM(total_tokens),0)
        FROM llm_usage
        WHERE timestamp >= ?
    """, (midnight,))
    cost_today, calls_today, tokens_today = cur.fetchone()

    cur.execute("""
        SELECT COALESCE(SUM(estimated_cost_usd),0), COUNT(*), COALESCE(SUM(total_tokens),0)
        FROM llm_usage
    """)
    cost_all_time, calls_all_time, tokens_all_time = cur.fetchone()

    cur.execute("""
        SELECT COUNT(*) FROM llm_usage
        WHERE timestamp >= ? AND (session_id = ? OR session_id IS NULL)
        AND stage = 'sonnet_decision'
    """, (SESSION_START, SESSION_ID))
    decision_calls = cur.fetchone()[0]

    cur.execute("""
        SELECT COUNT(*) FROM signal_events
        WHERE timestamp >= ? AND (session_id = ? OR session_id IS NULL) AND outcome='TRADED'
    """, (SESSION_START, SESSION_ID))
    traded_signals = cur.fetchone()[0]
    conn.close()

    conversion = (traded_signals / decision_calls * 100) if decision_calls else 0.0
    return {
        "llm_cost_session": round(cost_session or 0.0, 4),
        "llm_calls_session": int(calls_session or 0),
        "llm_tokens_session": int(tokens_session or 0),
        "llm_cost_today": round(cost_today or 0.0, 4),
        "llm_calls_today": int(calls_today or 0),
        "llm_tokens_today": int(tokens_today or 0),
        "llm_cost_all_time": round(cost_all_time or 0.0, 4),
        "llm_calls_all_time": int(calls_all_time or 0),
        "llm_tokens_all_time": int(tokens_all_time or 0),
        "llm_decision_calls_session": int(decision_calls or 0),
        "traded_signals": int(traded_signals or 0),
        "llm_trade_conversion_rate": round(conversion, 2),
    }


@app.get("/api/llm/breakdown")
async def get_llm_breakdown():
    """Model-wise token/cost breakdown for session, today, and all-time."""
    conn = _db()
    cur = conn.cursor()
    midnight = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).isoformat()

    def _rows_for(where_clause: str, params: tuple):
        cur.execute(
            f"""
            SELECT
                COALESCE(model_id, 'unknown') AS model_id,
                COUNT(*) AS calls,
                COALESCE(SUM(total_tokens), 0) AS total_tokens,
                COALESCE(SUM(input_tokens), 0) AS input_tokens,
                COALESCE(SUM(output_tokens), 0) AS output_tokens,
                COALESCE(SUM(estimated_cost_usd), 0) AS cost_usd
            FROM llm_usage
            WHERE {where_clause}
            GROUP BY COALESCE(model_id, 'unknown')
            ORDER BY total_tokens DESC
            """,
            params,
        )
        return [
            {
                "model_id": r[0],
                "calls": int(r[1] or 0),
                "total_tokens": int(r[2] or 0),
                "input_tokens": int(r[3] or 0),
                "output_tokens": int(r[4] or 0),
                "cost_usd": round(float(r[5] or 0.0), 6),
            }
            for r in cur.fetchall()
        ]

    session_rows = _rows_for("timestamp >= ? AND (session_id = ? OR session_id IS NULL)", (SESSION_START, SESSION_ID))
    today_rows = _rows_for("timestamp >= ?", (midnight,))
    all_time_rows = _rows_for("1=1", ())
    conn.close()

    return {
        "session": session_rows,
        "today": today_rows,
        "all_time": all_time_rows,
    }


@app.get("/api/regime")
async def get_regime(symbol: str = "BTCUSDT"):
    """Run regime/ATR/session snapshot from latest prices in DB."""
    from strategies.tools import MarketRegimeDetector, ATRTracker, SessionTimeFilter
    symbol = str(symbol).upper()
    if not config.is_symbol_allowed(symbol):
        symbol = "BTCUSDT"

    session = SessionTimeFilter.analyze()

    try:
        conn = sqlite3.connect(database.DB_PATH)
        cur = conn.cursor()
        cur.execute(
            "SELECT price FROM prices WHERE symbol=? "
            "ORDER BY timestamp DESC LIMIT 200"
            , (symbol,)
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
        "symbol": symbol,
    }


@app.get("/api/news/sentiment")
async def get_news_sentiment(symbol: str = "BTCUSDT"):
    """Aggregated BTC sentiment from free news/sentiment sources."""
    symbol = str(symbol).upper()
    if not config.is_symbol_allowed(symbol):
        symbol = "BTCUSDT"
    snapshot = build_sentiment_snapshot(
        alpha_key=config.ALPHAVANTAGE_API_KEY,
        cryptocompare_key=config.CRYPTOCOMPARE_API_KEY,
        symbol=symbol,
    )
    try:
        snapshot, usage_event = summarize_sentiment_with_openai(
            snapshot,
            openai_api_key=config.OPENAI_API_KEY,
            openai_base_url=config.OPENAI_BASE_URL,
            model_id=config.OPENAI_NEWS_SUMMARY_MODEL_ID,
            input_price_per_1m=config.OPENAI_NEWS_SUMMARY_INPUT_USD_PER_1M,
            output_price_per_1m=config.OPENAI_NEWS_SUMMARY_OUTPUT_USD_PER_1M,
        )
        if usage_event:
            save_llm_usage(
                stage=usage_event.get("stage", "news_sentiment_summary"),
                model_id=usage_event.get("model_id", config.OPENAI_NEWS_SUMMARY_MODEL_ID),
                input_tokens=int(usage_event.get("input_tokens", 0)),
                output_tokens=int(usage_event.get("output_tokens", 0)),
                total_tokens=int(usage_event.get("total_tokens", 0)),
                latency_ms=int(usage_event.get("latency_ms", 0)),
                estimated_cost_usd=float(usage_event.get("estimated_cost_usd", 0.0)),
                symbol=symbol,
                decision_context="dashboard_sentiment_summary",
            )
    except Exception as e:
        logger.error(f"News sentiment summary failed for {symbol}: {e}", exc_info=True)
        snapshot["llm_summary"] = {
            "text": f"LLM summary unavailable: {e}",
            "model_id": config.OPENAI_NEWS_SUMMARY_MODEL_ID,
            "timestamp": datetime.now().isoformat(),
            "cached": True,
        }
    return snapshot


@app.get("/api/news/headlines")
async def get_news_headlines(symbol: str = "BTCUSDT", limit: int = 8):
    """Latest BTC/crypto headlines from aggregated sources."""
    symbol = str(symbol).upper()
    if not config.is_symbol_allowed(symbol):
        symbol = "BTCUSDT"
    snapshot = build_sentiment_snapshot(
        alpha_key=config.ALPHAVANTAGE_API_KEY,
        cryptocompare_key=config.CRYPTOCOMPARE_API_KEY,
        symbol=symbol,
    )
    safe_limit = max(1, min(25, int(limit)))
    return {
        "updated_at": snapshot.get("updated_at"),
        "sentiment_label": snapshot.get("sentiment_label"),
        "sentiment_score": snapshot.get("sentiment_score"),
        "headlines": (snapshot.get("articles") or [])[:safe_limit],
    }


# ─────────────────────────────────────────────────────────────────────────────
#  Static frontend
# ─────────────────────────────────────────────────────────────────────────────
APP_DIR = os.path.dirname(os.path.abspath(__file__))
DIST_DIR = os.path.join(APP_DIR, "static", "dist")
LEGACY_STATIC_DIR = os.path.join(APP_DIR, "static")
if os.path.exists(os.path.join(DIST_DIR, "index.html")):
    app.mount("/", StaticFiles(directory=DIST_DIR, html=True), name="static")
elif os.path.exists(LEGACY_STATIC_DIR):
    app.mount("/", StaticFiles(directory=LEGACY_STATIC_DIR, html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
