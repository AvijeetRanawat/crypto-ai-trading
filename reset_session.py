"""
Session Reset — Wipes transient session data while PRESERVING all lessons and golden rules.

This lets you start a fresh session with a clean balance and trade history,
but with all the hard-won wisdom from previous sessions intact.

What gets CLEARED:
  - trades table (trade history)
  - portfolio table (equity snapshots)  
  - signal_events table (vote history)
  - prices table (raw price ticks)

What gets PRESERVED:
  - lessons table (ALL lessons — golden rules, self-critiques, post-mortems)
  - intent table (reset to "Scanning...")

Usage:
  python3 reset_session.py
"""
import sqlite3
from database import DB_PATH
from logger import logger


def reset_session():
    logger.info("🔄 SESSION RESET — Preserving lessons, clearing session data...")

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Count before
    c.execute("SELECT COUNT(*) FROM trades"); trades_n = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM portfolio"); port_n = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM signal_events"); sig_n = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM prices"); price_n = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM lessons"); lessons_n = c.fetchone()[0]

    logger.info(f"   Before reset: {trades_n} trades | {sig_n} signals | {price_n} prices | {lessons_n} lessons (kept)")

    # Clear transient tables
    c.execute("DELETE FROM trades")
    c.execute("DELETE FROM portfolio")
    c.execute("DELETE FROM signal_events")
    c.execute("DELETE FROM prices")

    # Reset SQLite autoincrement counters so IDs start from 1 again
    c.execute("DELETE FROM sqlite_sequence WHERE name IN ('trades','portfolio','signal_events','prices')")

    # Reset intent
    c.execute("UPDATE intent SET message='New session starting...', targets='[]' WHERE id=1")

    conn.commit()
    conn.close()

    logger.info(f"   ✅ Cleared: {trades_n} trades, {port_n} portfolio snapshots, {sig_n} signal events, {price_n} price ticks")
    logger.info(f"   ✅ Preserved: {lessons_n} lessons (all golden rules and self-critiques kept)")
    logger.info("🆕 Session is RESET. Starting fresh with $1,250 balance and accumulated wisdom.")
    print()
    print("=" * 60)
    print("  SESSION RESET COMPLETE")
    print(f"  {lessons_n} lessons PRESERVED for next session")
    print("  Balance reset to $1,250")
    print("  Run: python3 run.py")
    print("=" * 60)


if __name__ == "__main__":  # pragma: no cover
    # Safety prompt
    print("⚠️  This will CLEAR all trades, prices, and signal history.")
    print("   Lessons and golden rules will be PRESERVED.")
    confirm = input("   Type 'yes' to confirm: ").strip().lower()
    if confirm == 'yes':
        reset_session()
    else:
        print("Reset cancelled.")
