"""
Session Review — Full Post-Mortem & Periodic Mini-Review

Two entry points:
  1. run_review()         — Comprehensive end-of-session analysis (run before reset)
  2. run_mini_review(n)   — Lightweight periodic review of the last N trades (runs in background while bot trades)

Both:
  - Ask Claude to analyze patterns in recent trades and missed opportunities
  - Save new GOLDEN / SELF_CRITIQUE lessons to DB
  - Auto-apply safe config tuning (confidence threshold, stop-loss, take-profit)
  - Commit changes to GitHub
"""
import json
import re
import sqlite3
import subprocess
import boto3
from datetime import datetime
from typing import Optional
from config import config
from database import DB_PATH, save_lesson
from logger import logger


# ─────────────────────────────────────────────────────────────────────────────
#  Data Loaders
# ─────────────────────────────────────────────────────────────────────────────
def _load_recent_data(since_trade_id: int = 0, limit_trades: int = 30, limit_signals: int = 80):
    """Load recent trades and signal events (from a given trade ID onwards)."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute("""
        SELECT id, symbol, side, price, quantity, entry_time, exit_time, reason, pnl
        FROM trades WHERE status='CLOSED' AND id > ?
        ORDER BY id DESC LIMIT ?
    """, (since_trade_id, limit_trades))
    trades = c.fetchall()

    c.execute("""
        SELECT timestamp, price, buy_votes, sell_votes, rsi, macd, bb_pct, outcome, claude_action, claude_conf
        FROM signal_events WHERE id > (SELECT COALESCE(MAX(id),0) - ? FROM signal_events)
        ORDER BY id
    """, (limit_signals,))
    signals = c.fetchall()

    c.execute("SELECT market_condition, lesson, severity FROM lessons ORDER BY id DESC LIMIT 8")
    lessons = c.fetchall()

    conn.close()
    return trades, signals, lessons


def _build_compact_report(trades, signals, lessons, label: str = "PERIODIC") -> str:
    """Build a compact session report for Claude."""
    total = len(trades)
    wins  = [t for t in trades if t[8] > 0]
    losses= [t for t in trades if t[8] <= 0]
    net   = sum(t[8] for t in trades)
    wr    = (len(wins) / total * 100) if total else 0

    trade_lines = [
        f"  {'✅' if t[8]>0 else '❌'} {t[2]} {t[1]} @ ₹{t[3]:,.0f} → PnL: {'+'if t[8]>=0 else ''}₹{t[8]:.0f} | {t[7][:70]}"
        for t in trades[-20:]
    ]

    missed = [s for s in signals if s[7] == 'MISSED']
    from collections import Counter
    macd_counts = Counter(s[5] for s in missed if s[5])
    rsi_suspect = [s for s in missed if s[4] and (s[4] < 5 or s[4] > 95)]

    lesson_lines = [f"  [{sev}] {cond[:45]}: {les[:70]}" for cond, les, sev in lessons]

    return f"""
{label} REVIEW — {datetime.now().strftime('%Y-%m-%d %H:%M')}
{'='*55}
Trades analyzed: {total} | Wins: {len(wins)} ({wr:.0f}%) | Losses: {len(losses)} | Net PnL: ₹{net:.0f}

RECENT TRADES:
{chr(10).join(trade_lines) or '  (none yet)'}

MISSED OPPORTUNITIES: {len(missed)}
  MACD on misses: {dict(macd_counts.most_common(4))}
  Suspect RSI extremes (< 5 or > 95): {len(rsi_suspect)}
  Recent missed: {', '.join(f"{s[7]}/{s[2]}B{s[3]}S/RSI{s[4]:.0f}" for s in missed[-5:])}

EXISTING LESSONS (most recent 8):
{chr(10).join(lesson_lines) or '  (none yet)'}
""".strip()


# ─────────────────────────────────────────────────────────────────────────────
#  LLM Call
# ─────────────────────────────────────────────────────────────────────────────
def _call_claude(bedrock_client, report: str, is_mini: bool = False) -> Optional[dict]:
    """Ask Claude to analyze the report and return actionable JSON."""
    depth_note = "Focus on 2-3 key observations (this is a quick mid-session check)." if is_mini else \
                 "This is an end-of-session deep-dive. Be thorough."

    prompt = f"""You are an expert algorithmic trading strategist doing a {'mid-session' if is_mini else 'full post-mortem'} review.

{report}

{depth_note}

Provide {'2' if is_mini else '3'} specific improvement rules and config suggestions.

Output ONLY valid JSON, no markdown:
{{
  "summary": "1-2 sentence insight on what's working/failing",
  "key_pattern": "the most important pattern you see right now",
  "rules": [
    {{"condition": "...", "action": "...", "priority": "GOLDEN|HIGH|MEDIUM"}}
  ],
  "config_suggestions": {{
    "confidence_threshold": 0.XX_or_null,
    "stop_loss_pct": 0.XXX_or_null,
    "take_profit_pct": 0.XXX_or_null,
    "be_more_aggressive_on": "BUY|SELL|BOTH|NEITHER"
  }}
}}"""

    body = json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 700 if is_mini else 1400,
        "temperature": 0.1,
        "messages": [{"role": "user", "content": [{"type": "text", "text": prompt}]}]
    })

    try:
        resp = bedrock_client.invoke_model(
            body=body, modelId=config.BEDROCK_MODEL_ID,
            accept="application/json", contentType="application/json"
        )
        raw = json.loads(resp.get('body').read()).get('content')[0].get('text', '').strip()
        if raw.startswith('```'):
            raw = raw.split('```')[-2].lstrip('json').strip()
        return json.loads(raw)
    except Exception as e:
        logger.error(f"Review LLM error: {e}")
        return None


# ─────────────────────────────────────────────────────────────────────────────
#  Config Auto-Tuning
# ─────────────────────────────────────────────────────────────────────────────
def _apply_config(cfg: dict) -> list[str]:
    """Apply Claude's config suggestions to config.py. Returns list of changes made."""
    if not cfg:
        return []
    config_path = "config.py"
    changes = []
    try:
        with open(config_path, "r") as f:
            content = f.read()
        original = content

        patches = [
            ('confidence_threshold', 'MIN_ENSEMBLE_CONFIDENCE', 0.05, 0.6),
            ('stop_loss_pct',        'EARLY_STOP_LOSS_PCT',     0.001, 0.015),
            ('take_profit_pct',      'TAKE_PROFIT_PCT',         0.001, 0.025),
        ]
        for key, param, lo, hi in patches:
            val = cfg.get(key)
            if val and isinstance(val, (int, float)) and lo <= float(val) <= hi:
                val = round(float(val), 4)
                new_content = re.sub(
                    rf'({re.escape(param)}\s*=\s*)\S+',
                    f'\\g<1>{val}   # Auto-tuned {datetime.now().strftime("%H:%M")}',
                    content
                )
                if new_content != content:
                    content = new_content
                    changes.append(f"{param} → {val}")

        if content != original:
            with open(config_path, "w") as f:
                f.write(content)
            for c in changes:
                logger.info(f"⚙️  Config updated: {c}")
    except Exception as e:
        logger.error(f"Config auto-tune error: {e}")
    return changes


def _git_commit(changes: list[str], label: str = "periodic"):
    """Auto-commit any code or config changes to GitHub."""
    try:
        subprocess.run(["git", "add", "-A"], cwd=".", capture_output=True, timeout=10)
        msg = f"auto: {label} review — {', '.join(changes) if changes else 'lessons updated'} [{datetime.now().strftime('%H:%M')}]"
        result = subprocess.run(
            ["git", "commit", "-m", msg],
            cwd=".", capture_output=True, text=True, timeout=15
        )
        if "nothing to commit" not in result.stdout:
            subprocess.run(["git", "push", "origin", "main"], cwd=".", capture_output=True, timeout=20)
            logger.info(f"📦 GitHub: committed & pushed — {msg}")
        else:
            logger.info("📦 GitHub: nothing new to commit.")
    except Exception as e:
        logger.warning(f"Git commit skipped: {e}")


# ─────────────────────────────────────────────────────────────────────────────
#  Public API
# ─────────────────────────────────────────────────────────────────────────────
def run_mini_review(bedrock_client, since_trade_id: int = 0, label: str = "PERIODIC") -> int:
    """
    Lightweight mid-session review. Runs while the bot is actively trading.
    Returns the latest trade ID so the caller can track what was already reviewed.
    """
    trades, signals, lessons = _load_recent_data(since_trade_id=since_trade_id)

    if len(trades) < 3:
        logger.info(f"🔍 Mini-review: only {len(trades)} closed trades since last check — skipping.")
        return since_trade_id

    report = _build_compact_report(trades, signals, lessons, label=label)
    logger.info(f"\n{'='*55}\n{report}\n{'='*55}")
    logger.info(f"🧠 Mini-review: sending {len(trades)} trades to Claude...")

    analysis = _call_claude(bedrock_client, report, is_mini=True)
    if not analysis:
        return since_trade_id

    # Save lessons
    rules_saved = 0
    for rule in analysis.get('rules', []):
        sev = "GOLDEN" if rule.get('priority') == 'GOLDEN' else ("WIN" if rule.get('priority') == 'HIGH' else "INFO")
        save_lesson(
            condition=f"PERIODIC REVIEW: {rule.get('condition', 'Pattern')}",
            lesson=f"[AUTO] {rule.get('action', '')}",
            severity=sev
        )
        rules_saved += 1
        logger.info(f"  📚 [{rule.get('priority')}] {rule.get('condition', '')} → {rule.get('action', '')}")

    save_lesson(
        condition=f"MINI REVIEW {datetime.now().strftime('%H:%M')}",
        lesson=f"{analysis.get('summary', '')} | Pattern: {analysis.get('key_pattern', '')}",
        severity="WIN"
    )

    # Apply config suggestions
    changes = _apply_config(analysis.get('config_suggestions', {}))

    # Auto-commit to GitHub
    _git_commit(changes, label=label.lower())

    # Return latest trade ID for next review
    latest_id = max(t[0] for t in trades) if trades else since_trade_id
    logger.info(f"✅ Mini-review done: {rules_saved} rules saved. Next review from trade #{latest_id + 1}.")
    return latest_id


def run_review():
    """Full end-of-session post-mortem. Called automatically by engine on session completion."""
    try:
        bedrock = boto3.client(service_name='bedrock-runtime', region_name='us-east-1')
    except Exception as e:
        logger.error(f"Could not init Bedrock for review: {e}")
        return

    trades, signals, lessons = _load_recent_data(limit_trades=100, limit_signals=200)
    total = len(trades)
    missed = [s for s in signals if s[7] == 'MISSED']
    logger.info(f"🔬 Full post-mortem: {total} trades, {len(missed)} missed opportunities")

    if total == 0:
        logger.warning("No closed trades to review.")
        return

    report = _build_compact_report(trades, signals, lessons, label="FULL POST-MORTEM")
    print(f"\n{'='*60}\n{report}\n{'='*60}\n")
    logger.info("🧠 Full review: sending to Claude...")

    analysis = _call_claude(bedrock, report, is_mini=False)
    if not analysis:
        return

    for rule in analysis.get('rules', []):
        sev = "GOLDEN" if rule.get('priority') == 'GOLDEN' else ("WIN" if rule.get('priority') == 'HIGH' else "INFO")
        save_lesson(
            condition=f"POST-MORTEM: {rule.get('condition', '')}",
            lesson=f"[END-SESSION] {rule.get('action', '')}",
            severity=sev
        )
        logger.info(f"  📚 [{sev}] {rule.get('condition', '')} → {rule.get('action', '')}")

    save_lesson(
        condition=f"SESSION END {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        lesson=f"{analysis.get('summary', '')} | {analysis.get('key_pattern', '')}",
        severity="GOLDEN"
    )

    changes = _apply_config(analysis.get('config_suggestions', {}))
    _git_commit(changes, label="end-of-session")
    logger.info("✅ Full post-mortem complete.")


if __name__ == "__main__":
    run_review()
