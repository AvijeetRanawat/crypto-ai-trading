import json
import requests

from config import config
from logger import logger
from database import save_lesson


def _call_llm(prompt: str, bedrock_client=None, max_tokens: int = 300, temperature: float = 0.3) -> str | None:
    """Call LLM via Bedrock or OpenAI depending on provider config."""
    if config.LLM_PROVIDER == "OPENAI" and config.OPENAI_API_KEY:
        try:
            resp = requests.post(
                f"{config.OPENAI_BASE_URL}/chat/completions",
                headers={"Authorization": f"Bearer {config.OPENAI_API_KEY}", "Content-Type": "application/json"},
                json={
                    "model": config.OPENAI_MODEL_ID,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                },
                timeout=30,
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"].strip()
        except Exception as e:
            logger.error(f"OpenAI LLM call failed: {e}")
            return None
    elif bedrock_client:
        body = json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": [{"role": "user", "content": [{"type": "text", "text": prompt}]}],
        })
        try:
            response = bedrock_client.invoke_model(
                body=body,
                modelId=config.BEDROCK_MODEL_ID,
                accept="application/json",
                contentType="application/json",
            )
            return json.loads(response.get("body").read()).get("content")[0].get("text", "").strip()
        except Exception as e:
            logger.error(f"Bedrock LLM call failed: {e}")
            return None
    return None

class RetrospectiveAgent:
    """
    Post-Trade Retrospective Agent.
    After every trade closes, this agent sends the trade details to the LLM
    and asks it to reason about WHY the trade succeeded or failed,
    then extracts a concise lesson to store in the database.
    Future trades will read these lessons to avoid repeating mistakes.
    """
    def __init__(self, bedrock_client=None):
        self.bedrock = bedrock_client

    def analyze_trade(self, symbol, side, entry_price, exit_price, hold_secs, entry_reason, pnl):
        if not self.bedrock and not (config.LLM_PROVIDER == "OPENAI" and config.OPENAI_API_KEY):
            logger.warning("Retrospective skipped: no LLM client available.")
            return

        outcome = "PROFIT" if pnl >= 0 else "LOSS"
        pnl_str = f"+₹{pnl:.2f}" if pnl >= 0 else f"-₹{abs(pnl):.2f}"
        pct_change = ((exit_price - entry_price) / entry_price) * 100

        prompt = f"""You are a trading post-mortem analyst. A trade just closed. Analyze it.

TRADE DETAILS:
- Symbol: {symbol}
- Side: {side} ({"bought expecting price to rise" if side == "LONG" else "shorted expecting price to fall"})
- Entry Price: ₹{entry_price:,.2f}
- Exit Price: ₹{exit_price:,.2f} ({pct_change:+.3f}%)
- Hold Time: {hold_secs} seconds
- Entry Reason: {entry_reason}
- Outcome: {outcome} ({pnl_str})

TASK:
1. In 1 sentence, explain WHY this trade resulted in a {outcome}.
2. In 1 sentence, state a CONCRETE RULE the system should follow to do better next time.

Your output MUST be strictly valid JSON with no markdown wrapping.
JSON FORMAT:
{{
    "why": "1-sentence explanation of why this happened",
    "rule": "1-sentence actionable rule for future trades"
}}
"""

        try:
            logger.info(f"🔬 Retrospective Agent analyzing {outcome} trade on {symbol}...")
            llm_text = _call_llm(prompt, bedrock_client=self.bedrock, max_tokens=300, temperature=0.3)
            if not llm_text:
                raise ValueError("No LLM response")

            # Strip markdown fences if present
            if llm_text.startswith("```"):
                parts = llm_text.split("```")
                llm_text = parts[1].strip() if len(parts) > 1 else parts[-1].strip()
                if llm_text.lower().startswith("json"):
                    llm_text = llm_text[4:].strip()
            result = json.loads(llm_text)

            why = result.get("why", "No explanation")
            rule = result.get("rule", "No rule")

            severity = "WIN" if pnl >= 0 else "LOSS"
            save_lesson(
                condition=f"{outcome} on {side} {symbol}: {why}",
                lesson=rule,
                severity=severity
            )

            logger.info(f"📚 Lesson learned: {rule}")
            return rule

        except Exception as e:
            logger.error(f"Retrospective Agent error: {e}")
            # Fallback: save a basic lesson without LLM
            save_lesson(
                condition=f"{outcome} on {side} {symbol}",
                lesson=f"Trade went {pnl_str} in {hold_secs}s. Entry reason: {entry_reason}",
                severity="LOSS" if pnl < 0 else "WIN"
            )
            return None
