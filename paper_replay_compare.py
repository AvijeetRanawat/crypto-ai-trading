"""
Paper replay comparison helper.

Compares realized expectancy by decision source to approximate:
  1) deterministic-only outcomes
  2) LLM tie-breaker outcomes

Usage:
  python3 paper_replay_compare.py
"""
import sqlite3
from database import DB_PATH


def _print_block(title: str, row):
    n, avg_pnl, net_pnl, wins = row
    win_rate = (wins / n * 100) if n else 0.0
    print(f"{title}")
    print(f"  trades: {n}")
    print(f"  net_pnl: ${net_pnl:.4f}")
    print(f"  avg_pnl: ${avg_pnl:.6f}")
    print(f"  win_rate: {win_rate:.2f}%")


def main():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # Deterministic-only trades.
    cur.execute(
        """
        SELECT
            COUNT(*),
            COALESCE(AVG(pnl), 0),
            COALESCE(SUM(pnl), 0),
            COALESCE(SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END), 0)
        FROM trades
        WHERE status='CLOSED' AND decision_source='DETERMINISTIC'
        """
    )
    deterministic = cur.fetchone()

    # LLM tie-breaker trades.
    cur.execute(
        """
        SELECT
            COUNT(*),
            COALESCE(AVG(pnl), 0),
            COALESCE(SUM(pnl), 0),
            COALESCE(SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END), 0)
        FROM trades
        WHERE status='CLOSED' AND decision_source='LLM_TIEBREAKER'
        """
    )
    llm = cur.fetchone()

    print("=== Paper Replay Comparison ===")
    _print_block("Deterministic-only", deterministic)
    _print_block("LLM tie-breaker", llm)

    n_det = deterministic[0]
    n_llm = llm[0]
    if n_det == 0 or n_llm == 0:
        print("\nNot enough samples to compare both paths yet.")

    conn.close()


if __name__ == "__main__":
    main()

