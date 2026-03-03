# Reset Scripts

Utility scripts for wiping state between runs. Run from the project root.

---

## `reset_portfolio.py`

Hard reset of all trading data. Use when you want a completely clean slate.

**Clears:**
- All trades
- Portfolio snapshots
- Signal events
- RL events

**Sets balance to:** $1,250.00

```bash
python3 reset/reset_portfolio.py
```

---

## `reset_session.py`

Soft reset that preserves accumulated wisdom. Use between trading sessions
when you want a fresh start but keep all learned lessons.

**Clears:**
- Trades, portfolio snapshots, signal events, price ticks
- Resets autoincrement IDs to 1

**Preserves:**
- All lessons (golden rules, self-critiques, post-mortems)

Prompts for confirmation before running.

```bash
python3 reset/reset_session.py
```

---

## `reset_rl_weights.py`

Resets the RL agent's Q-values back to zero and restores epsilon to 0.18.
Use when the agent has learned bad habits and needs to start fresh.

**Clears:**
- All Q-values and visit counts (`data/rl_weights.json`)
- RL events from the database (pass `--keep-events` to skip this)

**Backs up** the current weights to `data/rl_weights.json.bak` before overwriting.

```bash
# Full reset (clears rl_events table too)
python3 reset/reset_rl_weights.py

# Reset weights only, keep event history
python3 reset/reset_rl_weights.py --keep-events
```

---

## `reset_all.py`

Runs a full system reset in one command. Prompts for confirmation, then
calls `reset_portfolio` and `reset_rl_weights` in sequence.

```bash
python3 reset/reset_all.py
```
