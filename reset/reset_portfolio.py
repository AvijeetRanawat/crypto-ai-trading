#!/usr/bin/env python3
"""Reset portfolio to clean state with $1250 balance"""
import os
import sqlite3
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(__file__))
DB_PATH = os.path.join(ROOT, "trading_data.db")


def reset_portfolio():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    print("Resetting portfolio...\n")

    # Get counts before deletion
    cur.execute("SELECT COUNT(*) FROM trades")
    trades_count = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM portfolio")
    portfolio_count = cur.fetchone()[0]

    print(f"Found {trades_count} trades and {portfolio_count} portfolio snapshots")

    # Delete all trades
    cur.execute("DELETE FROM trades")
    print("Deleted all trades")

    # Delete all portfolio snapshots
    cur.execute("DELETE FROM portfolio")
    print("Deleted all portfolio snapshots")

    # Insert fresh portfolio snapshot with $1250 balance
    timestamp = datetime.now().isoformat()
    cur.execute(
        "INSERT INTO portfolio (timestamp, balance_usdt, open_positions_count) VALUES (?, ?, ?)",
        (timestamp, 1250.0, 0),
    )
    print("Created new portfolio snapshot with $1250.00 balance")

    # Clear signal events
    cur.execute("DELETE FROM signal_events")
    signals_deleted = cur.rowcount
    print(f"Deleted {signals_deleted} signal events")

    # Clear RL events
    cur.execute("DELETE FROM rl_events")
    rl_deleted = cur.rowcount
    print(f"Deleted {rl_deleted} RL events")

    conn.commit()
    conn.close()

    print("\nPortfolio reset complete!")
    print("  Balance: $1,250.00")
    print("  Trades: 0")
    print("  Open Positions: 0")


if __name__ == "__main__":
    reset_portfolio()
