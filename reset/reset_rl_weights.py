#!/usr/bin/env python3
"""Reset RL agent weights to a clean initial state.

Clears all learned Q-values and visit counts, resets epsilon to its
starting value (0.18), and optionally clears RL events from the database.
"""
import json
import os
import sqlite3
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(__file__))
WEIGHTS_PATH = os.path.join(ROOT, "data", "rl_weights.json")
DB_PATH = os.path.join(ROOT, "trading_data.db")

INITIAL_EPSILON = 0.18


def reset_rl_weights(clear_db_events: bool = True):
    # ── Back up current weights ──
    if os.path.exists(WEIGHTS_PATH):
        with open(WEIGHTS_PATH, "r", encoding="utf-8") as f:
            old = json.load(f)
        old_epsilon = old.get("meta", {}).get("epsilon", "?")
        old_states = sum(len(v) for v in old.get("n", {}).values())
        old_updates = sum(
            n for mode in old.get("n", {}).values()
            for state in mode.values()
            for n in state.values()
        )
        print(f"Current weights: epsilon={old_epsilon}, {old_states} states, {old_updates} total updates")

        backup_path = WEIGHTS_PATH + ".bak"
        with open(backup_path, "w", encoding="utf-8") as f:
            json.dump(old, f, indent=2, sort_keys=True)
        print(f"Backed up to {backup_path}")
    else:
        print("No existing weights file found")

    # ── Write fresh weights ──
    fresh = {
        "meta": {
            "epsilon": INITIAL_EPSILON,
            "updated_at": datetime.now().isoformat(),
        },
        "n": {},
        "q": {},
    }
    os.makedirs(os.path.dirname(WEIGHTS_PATH), exist_ok=True)
    with open(WEIGHTS_PATH, "w", encoding="utf-8") as f:
        json.dump(fresh, f, indent=2, sort_keys=True)
    print(f"Reset weights: epsilon={INITIAL_EPSILON}, 0 states, 0 updates")

    # ── Clear RL events from database ──
    if clear_db_events and os.path.exists(DB_PATH):
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM rl_events")
        count = cur.fetchone()[0]
        cur.execute("DELETE FROM rl_events")
        conn.commit()
        conn.close()
        print(f"Cleared {count} RL events from database")

    print("\nRL agent reset complete. Restart the engine to pick up clean weights.")


if __name__ == "__main__":
    skip_db = "--keep-events" in sys.argv
    reset_rl_weights(clear_db_events=not skip_db)
