"""
Session Review — Comprehensive LLM Post-Mortem

This script is run before a session reset. It:
 1. Reads ALL session data: trades, missed opportunities, signal events, and existing lessons
 2. Asks Claude Sonnet to perform a deep post-mortem analysis
 3. Extracts specific, actionable improvements (config tuning, strategy changes, code hints)
 4. Saves the insights as high-priority GOLDEN / SELF_CRITIQUE lessons that persist into the next session

Run this BEFORE reset_session.py to preserve the wisdom of the current session.
"""
import json
import sqlite3
import boto3
from datetime import datetime
from config import config
from database import DB_PATH, save_lesson, get_recent_lessons
from logger import logger


def _load_all_data():
    """Pull a comprehensive snapshot of the full session."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # All closed trades
    c.execute("""
        SELECT symbol, side, price, quantity, entry_time, exit_time, reason, pnl
        FROM trades WHERE status='CLOSED' ORDER BY id
    """)
    trades = c.fetchall()

    # All signal events
    c.execute("""
        SELECT timestamp, price, buy_votes, sell_votes, rsi, macd, bb_pct, outcome, claude_action, claude_conf
        FROM signal_events ORDER BY id
    """)
    signals = c.fetchall()

    # All existing lessons (so Claude can see what it already knows)
    c.execute("SELECT market_condition, lesson, severity FROM lessons ORDER BY id")
    lessons = c.fetchall()

    conn.close()
    return trades, signals, lessons


def _build_report(trades, signals, lessons):
    """Summarize the session data into a structured text report for Claude."""

    # Trade stats
    total = len(trades)
    wins  = [t for t in trades if t[7] > 0]
    losses= [t for t in trades if t[7] <= 0]
    net_pnl = sum(t[7] for t in trades)
    win_rate = (len(wins) / total * 100) if total else 0

    trade_lines = []
    for t in trades:
        sym, side, price, qty, entry, exit_t, reason, pnl = t
        pnl_str = f"+₹{pnl:.2f}" if pnl >= 0 else f"-₹{abs(pnl):.2f}"
        trade_lines.append(
            f"  {'✅' if pnl>0 else '❌'} {side} {sym} @ ₹{price:,.0f} | PnL: {pnl_str} | {reason[:80]}"
        )

    # Signal event analysis
    total_sigs  = len(signals)
    missed      = [s for s in signals if s[7] == 'MISSED']
    traded      = [s for s in signals if s[7] == 'TRADED']
    skipped     = [s for s in signals if s[7] == 'SKIPPED']

    miss_dir_buy  = [s for s in missed if s[2] >= s[3]]  # more buy votes
    miss_dir_sell = [s for s in missed if s[3] > s[2]]

    # RSI distribution of missed opportunities
    miss_rsi_low  = [s for s in missed if s[4] and s[4] < 35]
    miss_rsi_high = [s for s in missed if s[4] and s[4] > 65]
    miss_mid      = [s for s in missed if s[4] and 35 <= s[4] <= 65]

    # MACD crossover breakdown for missed
    from collections import Counter
    miss_macd_counts = Counter(s[5] for s in missed if s[5])

    miss_lines = []
    for s in missed[:20]:  # limit to 20 most recent
        ts, price, bv, sv, rsi, macd, bb, outcome, action, conf = s
        direction = "BUY" if bv >= sv else "SELL"
        miss_lines.append(
            f"  🟡 {ts[11:19]} {direction} ({bv}B/{sv}S) RSI:{rsi:.1f} MACD:{macd} BB:{bb:.0f}% | claude={action}({conf:.2f})"
        )

    # Existing lessons summary
    lesson_lines = [f"  [{sev}] {cond[:50]}: {les[:80]}" for cond, les, sev in lessons[-10:]]

    return f"""
SESSION SUMMARY
===============
Symbol: BTCINR  |  Duration: This session
Total Trades: {total}  |  Wins: {len(wins)} ({win_rate:.1f}%)  |  Losses: {len(losses)}
Net PnL: {'+'if net_pnl>=0 else ''}₹{net_pnl:.2f}  |  Avg PnL/trade: ₹{(net_pnl/total if total else 0):.2f}

TRADE LOG ({min(total, 30)} shown):
{chr(10).join(trade_lines[:30])}

SIGNAL INTELLIGENCE
===================
Total evaluations: {total_sigs}
  → TRADED:  {len(traded)} times
  → MISSED:  {len(missed)} times (strong signal, Claude declined)
  → SKIPPED: {len(skipped)} times (insufficient votes)

MISSED OPPORTUNITIES BREAKDOWN:
  Direction: {len(miss_dir_buy)} Buy setups / {len(miss_dir_sell)} Sell setups missed
  RSI zones: {len(miss_rsi_low)} oversold (<35), {len(miss_rsi_high)} overbought (>65), {len(miss_mid)} neutral (35-65)
  MACD state on missed: {dict(miss_macd_counts.most_common(5))}

RECENT MISSED OPPORTUNITIES (last 20):
{chr(10).join(miss_lines) if miss_lines else '  None yet.'}

EXISTING LESSONS IN MEMORY ({len(lessons)} total, last 10):
{chr(10).join(lesson_lines) if lesson_lines else '  None yet.'}
""".strip()


def run_review():
    """Entry point: run the post-mortem analysis and save insights."""
    logger.info("=" * 60)
    logger.info("🔬 SESSION REVIEW STARTING — Pulling all data...")
    
    trades, signals, lessons = _load_all_data()
    
    total = len(trades)
    missed = [s for s in signals if s[7] == 'MISSED']
    
    logger.info(f"   Trades: {total}  |  Missed Opportunities: {len(missed)}")
    
    if total == 0 and len(missed) == 0:
        logger.warning("⚠️  No session data yet — nothing to review. Run the bot for at least one session first.")
        return

    # Build the report
    report = _build_report(trades, signals, lessons)
    print("\n" + "=" * 60)
    print(report)
    print("=" * 60 + "\n")

    # Call Claude for the post-mortem
    logger.info("🧠 Sending full session report to Claude for post-mortem analysis...")
    
    try:
        bedrock = boto3.client(service_name='bedrock-runtime', region_name='us-east-1')
    except Exception as e:
        logger.error(f"Could not initialize Bedrock: {e}")
        return

    prompt = f"""You are an expert algorithmic trading strategist. 

You have run a paper trading session on BTC/INR and here is the complete data:

{report}

Perform a thorough post-mortem analysis and provide:

1. PATTERN ANALYSIS: What patterns do you see in the missed opportunities?
   - Were the misses concentrated in specific RSI zones, MACD states, or BB positions?
   - Were your confidence thresholds too conservative?
   - Did you miss more BUY or SELL setups, and why?

2. TRADE QUALITY REVIEW: For losing trades, what signals were likely false?
   - What market conditions led to losses?
   - What should you NEVER do again?

3. SELF-IMPROVEMENT RULES: Provide 5 specific, immediately actionable rules.
   Format each as:
   Rule N: [Condition to look for] → [Action to take]
   Example: "Rule 1: If RSI < 30 AND MACD BULLISH_CROSS AND BB < 20% → Set confidence threshold to 0.45 (lower the bar)"

4. SYSTEM TUNING: Based on this session, suggest adjustments to:
   - Confidence threshold (MIN_ENSEMBLE_CONFIDENCE)
   - Stop loss / take profit percentages
   - Whether to be more aggressive or conservative on BUY vs SELL

Output as valid JSON ONLY, no markdown:
{{
  "summary": "2-3 sentence executive summary of performance",
  "missed_opportunity_pattern": "what you consistently missed and why",
  "loss_pattern": "what caused the losing trades",
  "rules": [
    {{"condition": "...", "action": "...", "priority": "GOLDEN|HIGH|MEDIUM"}},
    ...5 rules total
  ],
  "config_suggestions": {{
    "confidence_threshold": 0.XX,
    "stop_loss_pct": 0.XXX,
    "take_profit_pct": 0.XXX,
    "be_more_aggressive_on": "BUY|SELL|BOTH|NEITHER"
  }}
}}"""

    body = json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 1500,
        "temperature": 0.1,
        "messages": [{"role": "user", "content": [{"type": "text", "text": prompt}]}]
    })

    try:
        response = bedrock.invoke_model(
            body=body, modelId=config.BEDROCK_MODEL_ID,
            accept="application/json", contentType="application/json"
        )
        body_text = json.loads(response.get('body').read())
        raw = body_text.get('content')[0].get('text', '').strip()
        
        # Strip markdown fences
        if raw.startswith('```'):
            raw = raw.split('```')[-2].lstrip('json').strip()

        analysis = json.loads(raw)
        
        print("\n" + "🧠 " + "=" * 57)
        print("CLAUDE'S POST-MORTEM ANALYSIS")
        print("=" * 60)
        print(f"Summary: {analysis.get('summary', '')}")
        print(f"Missed Pattern: {analysis.get('missed_opportunity_pattern', '')}")
        print(f"Loss Pattern: {analysis.get('loss_pattern', '')}")
        print()
        
        # Save each rule as a lesson
        rules_saved = 0
        for i, rule in enumerate(analysis.get('rules', []), 1):
            cond    = rule.get('condition', f'Rule {i}')
            action  = rule.get('action', '')
            priority = rule.get('priority', 'HIGH')
            
            severity = "GOLDEN" if priority == "GOLDEN" else ("WIN" if priority == "HIGH" else "INFO")
            lesson_text = f"[POST-MORTEM RULE] {action}"
            
            save_lesson(condition=f"SESSION REVIEW: {cond}", lesson=lesson_text, severity=severity)
            rules_saved += 1
            print(f"  📚 Rule {i} [{priority}]: {cond} → {action}")
        
        # Save the summary as a GOLDEN lesson
        summary_text = (
            f"Session: {total} trades, {len(missed)} missed. "
            f"Missed pattern: {analysis.get('missed_opportunity_pattern', '')}. "
            f"Loss pattern: {analysis.get('loss_pattern', '')}."
        )
        save_lesson(
            condition=f"SESSION POST-MORTEM {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            lesson=summary_text,
            severity="GOLDEN"
        )
        
        # Print config suggestions
        cfg = analysis.get('config_suggestions', {})
        print()
        print("⚙️  RECOMMENDED CONFIG CHANGES:")
        print(f"   MIN_ENSEMBLE_CONFIDENCE → {cfg.get('confidence_threshold', '(unchanged)')}")
        print(f"   EARLY_STOP_LOSS_PCT    → {cfg.get('stop_loss_pct', '(unchanged)')}")
        print(f"   TAKE_PROFIT_PCT        → {cfg.get('take_profit_pct', '(unchanged)')}")
        print(f"   Focus bias             → {cfg.get('be_more_aggressive_on', '(unchanged)')}")
        print()
        print(f"✅ Saved {rules_saved + 1} lessons to DB. These carry over into the next session.")
        print("=" * 60)
        
        # Apply the config suggestions automatically
        _apply_config_suggestions(cfg)
        
        logger.info(f"✅ Session Review complete. {rules_saved + 1} lessons saved.")
        return analysis

    except json.JSONDecodeError as e:
        logger.error(f"Session Review JSON parse error: {e}")
    except Exception as e:
        logger.error(f"Session Review error: {e}", exc_info=True)


def _apply_config_suggestions(cfg: dict):
    """Automatically apply Claude's configuration suggestions to config.py."""
    import re
    config_path = "config.py"
    
    try:
        with open(config_path, "r") as f:
            content = f.read()
        
        original = content
        changes = []
        
        if cfg.get('confidence_threshold'):
            t = float(cfg['confidence_threshold'])
            if 0.05 <= t <= 0.5:
                content = re.sub(
                    r'(MIN_ENSEMBLE_CONFIDENCE\s*=\s*)\S+',
                    f'\\g<1>{t}   # Auto-tuned by session review',
                    content
                )
                changes.append(f"MIN_ENSEMBLE_CONFIDENCE → {t}")
        
        if cfg.get('stop_loss_pct'):
            sl = float(cfg['stop_loss_pct'])
            if 0.001 <= sl <= 0.01:
                content = re.sub(
                    r'(EARLY_STOP_LOSS_PCT\s*=\s*)\S+',
                    f'\\g<1>{sl}   # Auto-tuned by session review',
                    content
                )
                changes.append(f"EARLY_STOP_LOSS_PCT → {sl}")
        
        if cfg.get('take_profit_pct'):
            tp = float(cfg['take_profit_pct'])
            if 0.001 <= tp <= 0.02:
                content = re.sub(
                    r'(TAKE_PROFIT_PCT\s*=\s*)\S+',
                    f'\\g<1>{tp}   # Auto-tuned by session review',
                    content
                )
                changes.append(f"TAKE_PROFIT_PCT → {tp}")
        
        if content != original:
            with open(config_path, "w") as f:
                f.write(content)
            for c in changes:
                logger.info(f"⚙️  Auto-applied config change: {c}")
        else:
            logger.info("⚙️  No config changes were applied (values out of safe range or unchanged).")
    
    except Exception as e:
        logger.error(f"Could not auto-apply config suggestions: {e}")


if __name__ == "__main__":
    run_review()
