import json
import boto3
from strategies.base import BaseStrategy, Signal
from config import config
from logger import logger
from database import get_recent_lessons

class LLMAgent(BaseStrategy):
    """
    AWS Bedrock LLM Agent — The Primary Decision Maker
    Claude Sonnet 4.6 receives all 10 tool outputs and past lessons,
    then makes the final BUY/SELL/NEUTRAL judgment.
    """
    def __init__(self):
        super().__init__("LLM", config.WEIGHT_LLM)
        self.weight = config.WEIGHT_LLM
        
        try:
            self.bedrock = boto3.client(service_name='bedrock-runtime', region_name='us-east-1')
            logger.info(f"Initialized AWS Bedrock client for model: {config.BEDROCK_MODEL_ID}")
        except Exception as e:
            logger.error(f"Failed to initialize boto3 Bedrock client: {e}")
            self.bedrock = None

    def _build_lessons_context(self):
        lessons = get_recent_lessons(limit=5)
        if not lessons:
            return ""
        
        lines = []
        for i, (condition, lesson, severity) in enumerate(lessons, 1):
            emoji = "🏆" if severity == "GOLDEN" else ("✅" if severity == "WIN" else "❌")
            lines.append(f"  {i}. {emoji} [{severity}] {condition} → {lesson}")
        
        return "\n<PAST_LESSONS>\n" + "\n".join(lines) + "\n</PAST_LESSONS>\n"

    def analyze_with_tools(self, symbol, current_price, history, meta, tool_outputs) -> Signal:
        if not self.bedrock or len(history) < 2:
            return Signal("NEUTRAL", 0.0, self.weight, "Bedrock not ready.")

        oldest_price = history[0]
        recent_price = history[-2]
        session_change_pct = ((current_price - oldest_price) / oldest_price) * 100
        recent_change_pct = ((current_price - recent_price) / recent_price) * 100
        
        high_24h = meta.get('high', current_price)
        low_24h = meta.get('low', current_price)
        vol_24h = meta.get('volume', 0)
        change_24h = meta.get('change_24h', 0)

        # ── Build Pro Signals Table ──────────────────────────────────────
        # Separate pro tools from utility tools for cleaner prompt layout
        PRO_TOOL_NAMES = {"RSI (14)", "MACD (12,26,9)", "Bollinger Bands (20,2)", 
                          "Support & Resistance", "Candle Patterns"}
        
        pro_block = "<PRO_SIGNALS>\n"
        buy_count = 0
        sell_count = 0
        for t in tool_outputs:
            if t["name"] in PRO_TOOL_NAMES:
                sig = t.get("signal", "NEUTRAL")
                is_bullish = sig in ("STRONG_BUY", "BUY", "BULLISH_CROSS", "BULLISH_ENGULFING", "HAMMER", "WATCH_BUY")
                is_bearish = sig in ("STRONG_SELL", "SELL", "BEARISH_CROSS", "BEARISH_ENGULFING", "SHOOTING_STAR", "WATCH_SELL")
                direction = "📈 BULLISH" if is_bullish else ("📉 BEARISH" if is_bearish else "➡️ NEUTRAL")
                if is_bullish: buy_count += 1
                if is_bearish: sell_count += 1
                pro_block += f"  [{t['name']}] {direction}: {t['data']}\n"
        pro_block += f"  SIGNAL SCORE: {buy_count} BULLISH / {sell_count} BEARISH (need 2+ to act)\n"
        pro_block += "</PRO_SIGNALS>"

        utility_block = "<CONTEXT_TOOLS>\n"
        for t in tool_outputs:
            if t["name"] not in PRO_TOOL_NAMES:
                utility_block += f"  [{t['name']}]: {t.get('data', 'N/A')}\n"
        utility_block += "</CONTEXT_TOOLS>"

        lessons_block = self._build_lessons_context()

        prompt = f"""You are an expert crypto scalp trader AI. Your task is to make a precise BUY/SELL/NEUTRAL decision.

<MARKET_DATA>
Symbol: {symbol} | Price: ₹{current_price:,.2f}
24h: High ₹{high_24h:,.2f} | Low ₹{low_24h:,.2f} | Vol: {vol_24h:,.0f} | Change: {change_24h:+.2f}%
Session change: {session_change_pct:+.4f}% | Last tick: {recent_change_pct:+.4f}%
</MARKET_DATA>

{pro_block}

{utility_block}

{lessons_block}

DECISION RULES:
1. PRO SIGNALS are your primary inputs. 2+ agreeing = high-probability setup.
2. RSI < 30 + MACD bullish = very strong BUY. RSI > 70 + MACD bearish = very strong SELL.
3. Price near Support + Hammer candle = BUY. Price near Resistance + Shooting Star = SELL.
4. If pro signals conflict (e.g. 2 BUY, 2 SELL) → NEUTRAL.
5. Context tools (velocity, volume, order book) confirm or disqualify — use them to filter noise.
6. Past lessons encode previous mistakes — never repeat them.
7. If a losing streak ≥ 2 exists → raise confidence bar to 0.75+ before entering.

CONFIDENCE GUIDE:
- 5+ pro signals agree → confidence 0.80-0.95
- 3-4 pro signals agree → confidence 0.60-0.79  
- 2 pro signals agree → confidence 0.45-0.59
- <2 agree → NEUTRAL

Output strictly valid JSON (no markdown):
{{
    "action": "BUY" | "SELL" | "NEUTRAL",
    "confidence": 0.00,
    "reason": "cite the 2-3 most important signals supporting your call"
}}
"""
        
        body = json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 200,
            "temperature": 0.1,
            "messages": [
                {"role": "user", "content": [{"type": "text", "text": prompt}]}
            ]
        })

        try:
            logger.info(f"🧠 Querying Claude for {symbol} ({buy_count}B/{sell_count}S pro signals)...")
            response = self.bedrock.invoke_model(
                body=body,
                modelId=config.BEDROCK_MODEL_ID,
                accept="application/json",
                contentType="application/json"
            )
            
            response_body = json.loads(response.get('body').read())
            llm_text = response_body.get('content')[0].get('text')
            
            # Strip markdown code fences if present (Claude sometimes wraps JSON)
            llm_text = llm_text.strip()
            if llm_text.startswith('```'):
                llm_text = llm_text.split('```')[-2] if llm_text.count('```') >= 2 else llm_text
                llm_text = llm_text.lstrip('json').strip()
            
            result = json.loads(llm_text)
            action = result.get("action", "NEUTRAL")
            confidence = float(result.get("confidence", 0.0))
            reason = result.get("reason", "LLM decision")
            
            logger.info(f"🧠 Claude: {action} ({confidence:.2f}) — {reason}")
            return Signal(action, confidence, self.weight, f"Claude: {reason}")
            
        except json.JSONDecodeError:
            logger.error("LLM JSON parse error.")
            return Signal("NEUTRAL", 0.0, self.weight, "LLM JSON error")
        except Exception as e:
            logger.error(f"Bedrock API Error: {e}")
            return Signal("NEUTRAL", 0.0, self.weight, f"AWS Error")

    def analyze(self, symbol, current_price, history, meta) -> Signal:
        return self.analyze_with_tools(symbol, current_price, history, meta, [])
