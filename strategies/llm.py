import json
import time
import boto3
from strategies.base import BaseStrategy, Signal
from config import config
from logger import logger
from database import get_recent_lessons

# ── LLM Response Cache ─────────────────────────────────────────────────────────
# Key: (rsi_tier, macd, bb_zone, buy_votes, sell_votes, regime)
# Value: (Signal, timestamp)
_response_cache: dict = {}
_CACHE_TTL_SECONDS = 60   # Reuse decisions for 60s if market state unchanged


def _cache_key(rsi, macd, bb_pct, buy_votes, sell_votes, regime):
    """A lightweight representation of the current market state."""
    rsi_tier = "LOW" if rsi < 35 else ("HIGH" if rsi > 65 else "MID")
    bb_zone  = "BELOW" if bb_pct < 20 else ("ABOVE" if bb_pct > 80 else "MID")
    return (rsi_tier, str(macd), bb_zone, buy_votes, sell_votes, regime)


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        parts = text.split("```")
        text = parts[2].strip() if len(parts) > 2 else parts[-1].strip()
        text = text.lstrip("json").strip()
    return text


class LLMAgent(BaseStrategy):
    """
    AWS Bedrock LLM Agent — The Primary Decision Maker (Engine v6)

    Two-stage LLM pipeline:
      Stage 1 — Haiku pre-gate (cheap): Given the vote counts, is this worth a full analysis?
                 Returns PASS / SKIP.
      Stage 2 — Sonnet full analysis (expensive): Called only if Haiku says PASS.
                 Returns BUY / SELL / NEUTRAL with confidence and reasoning.

    Response cache: If market state (RSI tier, MACD, BB zone, vote pattern, regime)
    is identical to a previous call in the last 60s, reuse that response — no new call.
    """

    # Haiku model (10× cheaper than Sonnet)
    HAIKU_MODEL_ID = "us.anthropic.claude-haiku-4-5"

    def __init__(self):
        super().__init__("LLM", config.WEIGHT_LLM)
        self.weight = config.WEIGHT_LLM
        self.cache_hits = 0
        self.haiku_rejects = 0

        try:
            self.bedrock = boto3.client(service_name='bedrock-runtime', region_name='us-east-1')
            logger.info(f"Initialized AWS Bedrock client for model: {config.BEDROCK_MODEL_ID}")
        except Exception as e:
            logger.error(f"Failed to initialize boto3 Bedrock client: {e}")
            self.bedrock = None

    def _build_lessons_context(self):
        lessons = get_recent_lessons(limit=12)
        if not lessons:
            return ""

        # Split into SELF_CRITIQUE (hard behavioural overrides) vs general lessons
        critiques = [(c, l, s) for c, l, s in lessons if s == "SELF_CRITIQUE"]
        others    = [(c, l, s) for c, l, s in lessons if s != "SELF_CRITIQUE"]

        parts = []

        # Inject top-3 self-critiques as hard rules Claude must follow
        if critiques:
            rules = []
            for c, l, _ in critiques[:3]:
                # Extract the Adj: clause which contains the concrete rule
                adj_start = l.find("| Adj:")
                rule = l[adj_start + 7:].strip() if adj_start >= 0 else l[:120]
                rules.append(f"  - {rule}")
            parts.append("\n<HARD_RULES — you MUST follow these, do NOT return NEUTRAL if conditions match>\n"
                         + "\n".join(rules)
                         + "\n</HARD_RULES>\n")

        # General lessons
        if others:
            lines = []
            for i, (condition, lesson, severity) in enumerate(others[:6], 1):
                emoji = "🏆" if severity == "GOLDEN" else ("✅" if severity == "WIN" else "❌")
                lines.append(f"  {i}. {emoji} [{severity}] {condition[:80]} → {lesson[:120]}")
            parts.append("\n<PAST_LESSONS>\n" + "\n".join(lines) + "\n</PAST_LESSONS>\n")

        return "".join(parts)

    def _haiku_gate(self, buy_votes: int, sell_votes: int, rsi: float,
                    macd: str, bb_pct: float, regime: str) -> bool:
        """
        Cheap Haiku pre-gate: should we even bother calling Sonnet?
        Returns True = worth deeper analysis, False = skip.
        Saves ~60% of Sonnet calls.
        """
        if not self.bedrock:
            return True  # Fallback: always proceed if no client

        direction = "BUY" if buy_votes >= sell_votes else "SELL"
        agreement = max(buy_votes, sell_votes)

        prompt = (
            f"Market snapshot: Regime={regime}, Direction={direction}, "
            f"Agreement={agreement}/5 tools, RSI={rsi:.1f}, MACD={macd}, BB={bb_pct:.0f}%\n\n"
            f"Question: Is this a SUFFICIENTLY STRONG and REGIME-ALIGNED signal to warrant a "
            f"full trading analysis? Reply with exactly one word: PASS or SKIP."
        )

        try:
            resp = self.bedrock.invoke_model(
                body=json.dumps({
                    "anthropic_version": "bedrock-2023-05-31",
                    "max_tokens": 5,
                    "temperature": 0.0,
                    "messages": [{"role": "user", "content": [{"type": "text", "text": prompt}]}]
                }),
                modelId=self.HAIKU_MODEL_ID,
                accept="application/json",
                contentType="application/json"
            )
            answer = json.loads(resp.get("body").read()).get("content")[0].get("text", "SKIP").strip().upper()
            passes = "PASS" in answer
            if not passes:
                self.haiku_rejects += 1
            logger.info(f"⚡ Haiku gate: {answer} (rejects: {self.haiku_rejects})")
            return passes
        except Exception as e:
            logger.warning(f"Haiku gate failed ({e}), proceeding to Sonnet")
            return True  # Fail open

    def analyze_with_tools(self, symbol, current_price, history, meta,
                           tool_outputs, buy_count=0, sell_count=0,
                           regime="UNKNOWN", rsi=50.0, macd="UNKNOWN", bb_pct=50.0) -> Signal:
        if not self.bedrock or len(history) < 2:
            return Signal("NEUTRAL", 0.0, self.weight, "Bedrock not ready.")

        # ── 1. Check response cache ────────────────────────────────────────────
        key = _cache_key(rsi, macd, bb_pct, buy_count, sell_count, regime)
        if key in _response_cache:
            cached_signal, cached_time = _response_cache[key]
            age = time.time() - cached_time
            if age < _CACHE_TTL_SECONDS:
                self.cache_hits += 1
                logger.info(f"💾 Cache HIT (age:{age:.0f}s, hits:{self.cache_hits}) → {cached_signal.action} ({cached_signal.confidence:.2f})")
                return Signal(cached_signal.action, cached_signal.confidence,
                              self.weight, f"[CACHED] {cached_signal.reason}")

        # ── 2. Haiku pre-gate ─────────────────────────────────────────────────
        if not self._haiku_gate(buy_count, sell_count, rsi, macd, bb_pct, regime):
            return Signal("NEUTRAL", 0.0, self.weight, "Haiku gate: signal not strong enough for deep analysis")

        # ── 3. Sonnet full analysis ───────────────────────────────────────────
        oldest_price = history[0]
        session_change_pct = ((current_price - oldest_price) / oldest_price) * 100
        recent_change_pct = ((current_price - history[-2]) / history[-2]) * 100
        high_24h = meta.get('high', current_price)
        low_24h  = meta.get('low', current_price)
        vol_24h  = meta.get('volume', 0)
        change_24h = meta.get('change_24h', 0)

        lessons_ctx = self._build_lessons_context()

        tool_block = "\n".join(
            [f"  - {t['name']}: {t['data']}" for t in tool_outputs]
        )

        # Extract PRO signals for vote block
        pro_lines = "\n".join([
            t['data'] for t in tool_outputs
            if t['name'] in ('RSI (14)', 'MACD Signal', 'Bollinger Bands',
                             'Support/Resistance', 'Candle Patterns')
        ])

        prompt = f"""You are an expert crypto scalp trader AI. Market regime: {regime}.

<MARKET_CONTEXT>
Symbol: {symbol}
Price: ₹{current_price:,.2f}
24h High/Low: ₹{high_24h:,.0f} / ₹{low_24h:,.0f}
24h Change: {change_24h:+.2f}%  |  Volume: {vol_24h:.0f}
Session change: {session_change_pct:+.3f}%  |  Recent (1 tick): {recent_change_pct:+.4f}%
</MARKET_CONTEXT>

<PRO_SIGNALS — {buy_count} BUY / {sell_count} SELL votes>
{pro_lines or tool_block}
</PRO_SIGNALS>

<ALL_TOOLS>
{tool_block}
</ALL_TOOLS>
{lessons_ctx}

REGIME RULE: Market is {regime}. {"Only consider LONG (BUY) trades." if regime == "BULL" else "Only consider SHORT (SELL) trades." if regime == "BEAR" else "Market is CHOPPY — be very conservative, require 4+ signals." if regime == "CHOPPY" else ""}

GOLDEN RULES:
1. Never short into an uptrend (check regime first).
2. If same direction lost 2+ times recently → skip unless 4+ pro signals agree.
3. ATR-sized stops are already applied. Your job is to decide IF to trade, not stop levels.
4. Confidence reflects signal agreement: 5 agree=0.85+, 3-4=0.65-0.80, 2=0.45-0.60, <2=NEUTRAL.

Output strictly valid JSON (no markdown):
{{
    "action": "BUY" | "SELL" | "NEUTRAL",
    "confidence": 0.00,
    "reason": "cite the 2-3 most important signals"
}}"""

        body = json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 200,
            "temperature": 0.1,
            "messages": [{"role": "user", "content": [{"type": "text", "text": prompt}]}]
        })

        try:
            logger.info(f"🧠 Querying Claude Sonnet for {symbol} ({buy_count}B/{sell_count}S | regime={regime})...")
            response = self.bedrock.invoke_model(
                body=body, modelId=config.BEDROCK_MODEL_ID,
                accept="application/json", contentType="application/json"
            )
            llm_text = json.loads(response.get('body').read()).get('content')[0].get('text', '')
            llm_text = _strip_fences(llm_text)
            result = json.loads(llm_text)

            action     = result.get("action", "NEUTRAL")
            confidence = float(result.get("confidence", 0.0))
            reason     = result.get("reason", "LLM decision")

            sig = Signal(action, confidence, self.weight, f"Claude: {reason}")
            logger.info(f"🧠 Claude: {action} ({confidence:.2f}) — {reason}")

            # Cache the result
            _response_cache[key] = (sig, time.time())

            return sig

        except json.JSONDecodeError:
            logger.error("LLM JSON parse error.")
            return Signal("NEUTRAL", 0.0, self.weight, "LLM JSON error")
        except Exception as e:
            logger.error(f"Bedrock API Error: {e}")
            return Signal("NEUTRAL", 0.0, self.weight, "AWS Error")

    def analyze(self, symbol, current_price, history, meta) -> Signal:
        return self.analyze_with_tools(symbol, current_price, history, meta, [])
