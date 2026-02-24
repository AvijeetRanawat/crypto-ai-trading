"""
Missed Opportunity Analyzer — Self-Critique Learning Agent

After accumulating N missed opportunities (strong signal setups Claude declined),
this agent reviews them with Claude and asks:
  "What rule should you have applied here?"

The response is stored as a SELF_CRITIQUE lesson, which gets injected into
future prompts to teach Claude when to pull the trigger.
"""
import json
from database import get_missed_opportunities, save_lesson
from logger import logger


class MissedOpportunityAnalyzer:
    def __init__(self, bedrock_client, model_id: str):
        self.bedrock = bedrock_client
        self.model_id = model_id
        self.analyzed_count = 0

    def should_run(self, symbol: str, threshold: int = 5) -> bool:
        """Run whenever there are at least `threshold` unanalyzed missed opportunities."""
        missed = get_missed_opportunities(symbol, min_votes=3, limit=threshold)
        return len(missed) >= threshold

    def analyze(self, symbol: str):
        """Ask Claude to reflect on missed opportunities and derive new rules."""
        missed = get_missed_opportunities(symbol, min_votes=3, limit=10)
        if not missed:
            return

        logger.info(f"🔍 MissedOpportunityAnalyzer: Reviewing {len(missed)} missed setups for {symbol}...")

        # Format missed opportunities for Claude
        cases = []
        for i, row in enumerate(missed, 1):
            ts, price, buy_v, sell_v, rsi, macd, bb_pct, claude_action, claude_conf = row
            direction = "BUY" if buy_v >= sell_v else "SELL"
            cases.append(
                f"  Case {i}: Time={ts[11:19]} | Price=₹{price:,.0f} | "
                f"Signal={direction} ({buy_v if direction=='BUY' else sell_v}/5 tools) | "
                f"RSI={rsi:.1f} | MACD={macd} | BB={bb_pct:.0f}% | "
                f"You said: {claude_action or 'NEUTRAL'} (conf: {claude_conf or 0:.2f})"
            )

        cases_text = "\n".join(cases)

        prompt = f"""You are a self-improving trading AI reviewing setups you declined to trade.

These are {len(missed)} situations where 3+ of your technical analysis tools signaled a clear opportunity,
but you output NEUTRAL or low confidence:

{cases_text}

For each case, the signal was strong. Review the patterns:
- Were there common RSI/MACD/BB conditions you consistently avoided?
- Were your confidence thresholds too high for certain signal combinations?
- What specific rule would have helped you capture these opportunities profitably?

Identify the TOP 2 self-improvement rules in this EXACT JSON format:
{{
  "rules": [
    {{
      "condition": "short description of the market condition you missed",
      "rule": "specific actionable rule for next time (1 sentence)",
      "confidence_adjustment": "e.g. lower threshold to 0.45 when RSI<30 + MACD bullish"
    }},
    {{
      "condition": "...",
      "rule": "...",
      "confidence_adjustment": "..."
    }}
  ]
}}

Output only valid JSON, no markdown."""

        body = json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 400,
            "temperature": 0.2,
            "messages": [{"role": "user", "content": [{"type": "text", "text": prompt}]}]
        })

        try:
            response = self.bedrock.invoke_model(
                body=body, modelId=self.model_id,
                accept="application/json", contentType="application/json"
            )
            body_text = json.loads(response.get('body').read())
            result_text = body_text.get('content')[0].get('text')
            result = json.loads(result_text)

            for rule in result.get("rules", []):
                condition = rule.get("condition", "Missed setup")
                lesson_text = f"{rule.get('rule', '')} | Adj: {rule.get('confidence_adjustment', '')}"
                save_lesson(
                    condition=f"SELF_CRITIQUE: {condition}",
                    lesson=lesson_text,
                    severity="SELF_CRITIQUE"
                )
                logger.info(f"📚 New self-critique rule: [{condition}] → {lesson_text}")

            self.analyzed_count += len(missed)
            logger.info(f"✅ MissedOpportunityAnalyzer: Stored {len(result.get('rules', []))} new rules.")

        except json.JSONDecodeError:
            logger.error("MissedOpportunityAnalyzer: JSON parse error from LLM.")
        except Exception as e:
            logger.error(f"MissedOpportunityAnalyzer error: {e}")
