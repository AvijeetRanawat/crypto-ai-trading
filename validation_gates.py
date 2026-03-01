"""
Validation gate checker for rollout readiness.

Usage:
  python3 validation_gates.py
"""
import sqlite3
from pathlib import Path
from config import config
from database import DB_PATH


def _gate(label: str, ok: bool, detail: str):
    status = "PASS" if ok else "FAIL"
    print(f"[{status}] {label}: {detail}")


def main():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # Gate 1: stability (no uncaught engine errors in current log file)
    log_path = Path("trading.log")
    log_text = log_path.read_text() if log_path.exists() else ""
    engine_errors = log_text.count("Engine error:")
    _gate("Stability", engine_errors == 0, f"uncaught engine errors in log: {engine_errors}")

    # Gate 2: cost discipline
    cur.execute("SELECT COALESCE(SUM(pnl),0), COALESCE(SUM(CASE WHEN pnl>0 THEN pnl ELSE 0 END),0) FROM trades WHERE status='CLOSED'")
    net_pnl, gross_positive_pnl = cur.fetchone()
    cur.execute("SELECT COALESCE(SUM(estimated_cost_usd),0) FROM llm_usage")
    llm_cost = float(cur.fetchone()[0] or 0.0)
    ratio = (llm_cost / gross_positive_pnl * 100) if gross_positive_pnl > 0 else float("inf")
    _gate("Cost discipline", ratio <= 10.0, f"LLM/Gross+PnL={ratio:.2f}% (llm=${llm_cost:.4f}, gross+=${gross_positive_pnl:.2f})")

    # Gate 3: quality sample size and expectancy
    cur.execute("SELECT COUNT(*), COALESCE(AVG(pnl),0) FROM trades WHERE status='CLOSED'")
    closed_n, avg_pnl = cur.fetchone()
    _gate("Quality sample size", closed_n >= 150, f"closed trades={closed_n} (need >=150)")
    _gate("Net expectancy", avg_pnl > 0, f"avg pnl/trade={avg_pnl:.6f}")

    # Gate 4: drawdown
    cur.execute("SELECT COALESCE(MAX(balance_usdt),0), COALESCE(MIN(balance_usdt),0) FROM portfolio")
    max_bal, min_bal = cur.fetchone()
    drawdown = max(0.0, (max_bal or 0) - (min_bal or 0))
    _gate(
        "Drawdown cap",
        drawdown <= config.MAX_DAILY_DRAWDOWN_USD,
        f"observed drawdown=${drawdown:.2f}, cap=${config.MAX_DAILY_DRAWDOWN_USD:.2f}",
    )

    conn.close()


if __name__ == "__main__":  # pragma: no cover
    main()
