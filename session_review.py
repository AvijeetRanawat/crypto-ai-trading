"""
Session Review — Full Post-Mortem & Periodic Mini-Review.

In profit-first mode, runtime mutating actions (config rewrite/git push) are disabled
by default and controlled by config flags.
"""
import json
import re
import sqlite3
import subprocess
import boto3
from datetime import datetime
from typing import Optional
from config import config
from database import DB_PATH, save_lesson, get_runtime_context
from logger import logger


def _load_recent_data(
    since_trade_id: int = 0,
    limit_trades: int = 30,
    limit_signals: int = 80,
    session_id: str = None,
):
    """Load recent trades and signal events."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    session_id = session_id or get_runtime_context()["session_id"]
    c.execute(
        """
        SELECT id, symbol, side, price, quantity, entry_time, exit_time, reason, pnl
        FROM trades
        WHERE status='CLOSED' AND id > ? AND (session_id = ? OR session_id IS NULL)
        ORDER BY id DESC LIMIT ?
        """,
        (since_trade_id, session_id, limit_trades),
    )
    trades = c.fetchall()

    c.execute(
        """
        SELECT timestamp, price, buy_votes, sell_votes, rsi, macd, bb_pct, outcome, claude_action, claude_conf
        FROM signal_events
        WHERE (session_id = ? OR session_id IS NULL)
        AND id > (SELECT COALESCE(MAX(id),0) - ? FROM signal_events)
        ORDER BY id
        """,
        (session_id, limit_signals),
    )
    signals = c.fetchall()

    c.execute("SELECT market_condition, lesson, severity FROM lessons ORDER BY id DESC LIMIT 8")
    lessons = c.fetchall()

    conn.close()
    return trades, signals, lessons


def _build_compact_report(trades, signals, lessons, label: str = "PERIODIC") -> str:
    total = len(trades)
    wins = [t for t in trades if t[8] > 0]
    losses = [t for t in trades if t[8] <= 0]
    net = sum(t[8] for t in trades)
    wr = (len(wins) / total * 100) if total else 0

    trade_lines = [
        f"  {'✅' if t[8] > 0 else '❌'} {t[2]} {t[1]} @ ${t[3]:,.0f} "
        f"→ PnL: {'+' if t[8] >= 0 else ''}${t[8]:.2f} | {t[7][:70]}"
        for t in trades[-20:]
    ]

    missed = [s for s in signals if s[7] == "MISSED"]
    from collections import Counter

    macd_counts = Counter(s[5] for s in missed if s[5])
    rsi_suspect = [s for s in missed if s[4] and (s[4] < 5 or s[4] > 95)]
    lesson_lines = [f"  [{sev}] {cond[:45]}: {les[:70]}" for cond, les, sev in lessons]

    return f"""
{label} REVIEW — {datetime.now().strftime('%Y-%m-%d %H:%M')}
{'='*55}
Trades analyzed: {total} | Wins: {len(wins)} ({wr:.0f}%) | Losses: {len(losses)} | Net PnL: ${net:.2f}

RECENT TRADES:
{chr(10).join(trade_lines) or '  (none yet)'}

MISSED OPPORTUNITIES: {len(missed)}
  MACD on misses: {dict(macd_counts.most_common(4))}
  Suspect RSI extremes (< 5 or > 95): {len(rsi_suspect)}
  Recent missed: {', '.join(f"{s[7]}/{s[2]}B{s[3]}S/RSI{s[4]:.0f}" for s in missed[-5:])}

EXISTING LESSONS (most recent 8):
{chr(10).join(lesson_lines) or '  (none yet)'}
""".strip()


def _call_claude(bedrock_client, report: str, is_mini: bool = False) -> Optional[dict]:
    depth_note = (
        "Focus on 2-3 key observations (quick mid-session check)."
        if is_mini
        else "This is an end-of-session deep-dive. Be thorough."
    )
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

    body = json.dumps(
        {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 700 if is_mini else 1400,
            "temperature": 0.1,
            "messages": [{"role": "user", "content": [{"type": "text", "text": prompt}]}],
        }
    )

    try:
        resp = bedrock_client.invoke_model(
            body=body,
            modelId=config.BEDROCK_MODEL_ID,
            accept="application/json",
            contentType="application/json",
        )
        raw = json.loads(resp.get("body").read()).get("content")[0].get("text", "").strip()
        if raw.startswith("```"):
            raw = raw.split("```")[-2].lstrip("json").strip()
        return json.loads(raw)
    except Exception as e:
        logger.error(f"Review LLM error: {e}")
        return None


def _apply_config(cfg: dict) -> list:
    """Apply Claude's config suggestions to config.py."""
    if not cfg:
        return []
    if not config.ENABLE_RUNTIME_CONFIG_AUTOTUNE:
        logger.info("⏸ Config auto-tune disabled (ENABLE_RUNTIME_CONFIG_AUTOTUNE=false).")
        return []

    config_path = "config.py"
    changes = []
    try:
        with open(config_path, "r") as f:
            content = f.read()
        original = content

        patches = [
            ("confidence_threshold", "MIN_ENSEMBLE_CONFIDENCE", 0.50, 0.90),
            ("stop_loss_pct", "EARLY_STOP_LOSS_PCT", 0.001, 0.020),
            ("take_profit_pct", "TAKE_PROFIT_PCT", 0.001, 0.030),
        ]
        for key, param, lo, hi in patches:
            val = cfg.get(key)
            if val and isinstance(val, (int, float)) and lo <= float(val) <= hi:
                val = round(float(val), 4)
                new_content = re.sub(
                    rf"({re.escape(param)}\s*=\s*)\S+",
                    f"\\g<1>{val}   # Auto-tuned {datetime.now().strftime('%H:%M')}",
                    content,
                )
                if new_content != content:
                    content = new_content
                    changes.append(f"{param} → {val}")

        if content != original:
            with open(config_path, "w") as f:
                f.write(content)
            for c in changes:
                logger.info(f"⚙️ Config updated: {c}")
    except Exception as e:
        logger.error(f"Config auto-tune error: {e}")
    return changes


def _git_commit(changes: list, label: str = "periodic"):
    """Optionally commit/push when explicitly enabled."""
    if not config.ENABLE_RUNTIME_GIT_PUSH:
        logger.info("⏸ Runtime git push disabled (ENABLE_RUNTIME_GIT_PUSH=false).")
        return

    try:
        subprocess.run(["git", "add", "-A"], cwd=".", capture_output=True, timeout=10)
        msg = (
            f"auto: {label} review — {', '.join(changes) if changes else 'lessons updated'} "
            f"[{datetime.now().strftime('%H:%M')}]"
        )
        result = subprocess.run(["git", "commit", "-m", msg], cwd=".", capture_output=True, text=True, timeout=15)
        if "nothing to commit" not in (result.stdout or ""):
            subprocess.run(["git", "push", "origin", "main"], cwd=".", capture_output=True, timeout=20)
            logger.info(f"📦 GitHub: committed & pushed — {msg}")
        else:
            logger.info("📦 GitHub: nothing new to commit.")
    except Exception as e:
        logger.warning(f"Git commit skipped: {e}")


def run_mini_review(
    bedrock_client,
    since_trade_id: int = 0,
    label: str = "PERIODIC",
    min_closed_trades: int = None,
) -> int:
    """Lightweight mid-session review."""
    min_required = min_closed_trades or config.MIN_NEW_CLOSED_TRADES_FOR_REVIEW
    trades, signals, lessons = _load_recent_data(since_trade_id=since_trade_id)

    if len(trades) < min_required:
        logger.info(
            f"🔍 Mini-review skipped: only {len(trades)} closed trades since last check "
            f"(need {min_required})."
        )
        return since_trade_id

    report = _build_compact_report(trades, signals, lessons, label=label)
    logger.info(f"\n{'='*55}\n{report}\n{'='*55}")
    logger.info(f"🧠 Mini-review: sending {len(trades)} trades to Claude...")

    analysis = _call_claude(bedrock_client, report, is_mini=True)
    if not analysis:
        return since_trade_id

    rules_saved = 0
    for rule in analysis.get("rules", []):
        sev = "GOLDEN" if rule.get("priority") == "GOLDEN" else ("WIN" if rule.get("priority") == "HIGH" else "INFO")
        save_lesson(
            condition=f"PERIODIC REVIEW: {rule.get('condition', 'Pattern')}",
            lesson=f"[AUTO] {rule.get('action', '')}",
            severity=sev,
        )
        rules_saved += 1
        logger.info(f"  📚 [{rule.get('priority')}] {rule.get('condition', '')} → {rule.get('action', '')}")

    save_lesson(
        condition=f"MINI REVIEW {datetime.now().strftime('%H:%M')}",
        lesson=f"{analysis.get('summary', '')} | Pattern: {analysis.get('key_pattern', '')}",
        severity="WIN",
    )

    changes = _apply_config(analysis.get("config_suggestions", {}))
    _git_commit(changes, label=label.lower())

    latest_id = max(t[0] for t in trades) if trades else since_trade_id
    logger.info(f"✅ Mini-review done: {rules_saved} rules saved. Next review from trade #{latest_id + 1}.")
    return latest_id


def run_review():
    """Full end-of-session post-mortem."""
    try:
        bedrock = boto3.client(service_name="bedrock-runtime", region_name="us-east-1")
    except Exception as e:
        logger.error(f"Could not init Bedrock for review: {e}")
        return

    trades, signals, lessons = _load_recent_data(limit_trades=100, limit_signals=200)
    total = len(trades)
    missed = [s for s in signals if s[7] == "MISSED"]
    logger.info(f"🔬 Full post-mortem: {total} trades, {len(missed)} missed opportunities")

    if total == 0:
        logger.warning("No closed trades to review.")
        return

    report = _build_compact_report(trades, signals, lessons, label="FULL POST-MORTEM")
    logger.info("🧠 Full review: sending to Claude...")
    analysis = _call_claude(bedrock, report, is_mini=False)
    if not analysis:
        return

    for rule in analysis.get("rules", []):
        sev = "GOLDEN" if rule.get("priority") == "GOLDEN" else ("WIN" if rule.get("priority") == "HIGH" else "INFO")
        save_lesson(
            condition=f"POST-MORTEM: {rule.get('condition', '')}",
            lesson=f"[END-SESSION] {rule.get('action', '')}",
            severity=sev,
        )
        logger.info(f"  📚 [{sev}] {rule.get('condition', '')} → {rule.get('action', '')}")

    save_lesson(
        condition=f"SESSION END {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        lesson=f"{analysis.get('summary', '')} | {analysis.get('key_pattern', '')}",
        severity="GOLDEN",
    )

    changes = _apply_config(analysis.get("config_suggestions", {}))
    _git_commit(changes, label="end-of-session")
    logger.info("✅ Full post-mortem complete.")


if __name__ == "__main__":
    run_review()

