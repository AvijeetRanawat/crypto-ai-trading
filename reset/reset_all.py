#!/usr/bin/env python3
"""Full system reset — clears all trades, portfolio, RL weights, and events.

Runs reset_portfolio and reset_rl_weights in sequence.
Prompts for confirmation before doing anything.

Usage:
  python3 reset/reset_all.py
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from reset_portfolio import reset_portfolio
from reset_rl_weights import reset_rl_weights

if __name__ == "__main__":
    print("=" * 60)
    print("  FULL SYSTEM RESET")
    print("  This will clear ALL trades, portfolio history,")
    print("  RL weights, signal events, and RL events.")
    print("  This cannot be undone (RL weights will be backed up).")
    print("=" * 60)
    confirm = input("\n  Type 'yes' to confirm: ").strip().lower()
    if confirm != "yes":
        print("Reset cancelled.")
        sys.exit(0)

    print()
    print("── Portfolio ──────────────────────────────────────────")
    reset_portfolio()

    print()
    print("── RL Weights ─────────────────────────────────────────")
    reset_rl_weights(clear_db_events=False)  # rl_events already cleared by reset_portfolio

    print()
    print("=" * 60)
    print("  FULL RESET COMPLETE")
    print("  Balance: $1,250.00 | Trades: 0 | RL: clean slate")
    print("  Run: python3 run.py")
    print("=" * 60)
