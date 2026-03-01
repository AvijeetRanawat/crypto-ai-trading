import json
import time
import boto3
import requests
from strategies.base import BaseStrategy, Signal
from config import config
from logger import logger
from database import get_recent_lessons, get_distilled_rules

# ── LLM Response Cache ─────────────────────────────────────────────────────────
# Key: (rsi_tier, macd, bb_zone, buy_votes, sell_votes, regime)
# Value: (Signal, timestamp)
_response_cache: dict = {}
_CACHE_TTL_SECONDS = 60


def _cache_key(rsi, macd, bb_pct, buy_votes, sell_votes, regime):
    """A lightweight representation of the current market state."""
    rsi_tier = "LOW" if rsi < 35 else ("HIGH" if rsi > 65 else "MID")
    bb_zone = "BELOW" if bb_pct < 20 else ("ABOVE" if bb_pct > 80 else "MID")
    return (rsi_tier, str(macd), bb_zone, buy_votes, sell_votes, regime)


def _strip_fences(text: str) -> str:
    text = (text or "").strip()
    if text.startswith("```"):
        parts = text.split("```")
        text = parts[2].strip() if len(parts) > 2 else parts[-1].strip()
        text = text.lstrip("json").strip()
    return text


def _estimate_tokens(text: str) -> int:
    # Conservative approximation for runtime budgeting when provider usage is missing.
    return max(1, int(len(text or "") / 4))


class LLMAgent(BaseStrategy):
    """
    AWS Bedrock LLM tie-breaker agent.
    Returns a Signal with structured `meta["llm_usage"]` events so the engine can
    persist token/cost attribution and enforce runtime budgets.
    """

    HAIKU_MODEL_ID = config.HAIKU_MODEL_ID

    def __init__(self):
        super().__init__("LLM", config.WEIGHT_LLM)
        self.weight = config.WEIGHT_LLM
        self.provider = config.LLM_PROVIDER
        self.ready = False
        self.cache_hits = 0
        self.haiku_rejects = 0
        self.bedrock = None
        self.openai_api_key = config.OPENAI_API_KEY

        if self.provider == "OPENAI":
            if not self.openai_api_key:
                logger.error("OPENAI provider selected but OPENAI_API_KEY is not set.")
                return
            self.ready = True
            logger.info(f"Initialized OpenAI client for model: {config.OPENAI_MODEL_ID}")
            return

        try:
            self.bedrock = boto3.client(service_name="bedrock-runtime", region_name="us-east-1")
            self.ready = True
            logger.info(f"Initialized AWS Bedrock client for model: {config.BEDROCK_MODEL_ID}")
        except Exception as e:
            logger.error(f"Failed to initialize boto3 Bedrock client: {e}")
            self.bedrock = None

    def _build_lessons_context(self):
        """Builds a compact context of past wisdom using distilled rules and recent critiques."""
        distilled = get_distilled_rules()
        lessons = get_recent_lessons(limit=10)

        parts = []

        if distilled:
            lines = []
            for category, rule, _count in distilled:
                lines.append(f"  - [{category} Master Rule]: {rule}")
            total_sources = sum(d[2] for d in distilled)
            parts.append(
                f"\n<MASTER_STRATEGY_RULES - Distilled from {total_sources} past lessons>\n"
                + "\n".join(lines)
                + "\n</MASTER_STRATEGY_RULES>\n"
            )

        if lessons:
            critiques = [(c, l, s) for c, l, s in lessons if s == "SELF_CRITIQUE"]
            if critiques:
                rules = []
                for _c, l, _ in critiques[:3]:
                    adj_start = l.find("| Adj:")
                    rule = l[adj_start + 7 :].strip() if adj_start >= 0 else l[:120]
                    rules.append(f"  - {rule}")
                parts.append(
                    "\n<HARD_RULES — recent self-corrections you MUST follow>\n"
                    + "\n".join(rules)
                    + "\n</HARD_RULES>\n"
                )

        others = [f"  - {c[:60]} -> {l[:100]}" for c, l, s in lessons if s != "SELF_CRITIQUE"][:3]
        if others:
            parts.append("\n<RECENT_OUTCOMES>\n" + "\n".join(others) + "\n</RECENT_OUTCOMES>\n")

        return "".join(parts)

    def _pricing_per_1m(self, model_id: str) -> tuple:
        if self.provider == "OPENAI":
            return config.OPENAI_INPUT_USD_PER_1M, config.OPENAI_OUTPUT_USD_PER_1M
        if "haiku" in (model_id or "").lower():
            return config.HAIKU_INPUT_USD_PER_1M, config.HAIKU_OUTPUT_USD_PER_1M
        return config.SONNET_INPUT_USD_PER_1M, config.SONNET_OUTPUT_USD_PER_1M

    def _invoke_openai_with_usage(
        self,
        model_id: str,
        stage: str,
        prompt: str,
        max_tokens: int,
        temperature: float,
    ) -> tuple:
        started = time.time()
        resp = requests.post(
            f"{config.OPENAI_BASE_URL.rstrip('/')}/chat/completions",
            headers={
                "Authorization": f"Bearer {self.openai_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model_id,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": max_tokens,
                "temperature": temperature,
            },
            timeout=30,
        )
        resp.raise_for_status()
        payload = resp.json()
        latency_ms = int((time.time() - started) * 1000)

        choices = payload.get("choices") or []
        msg = choices[0].get("message", {}) if choices else {}
        text = msg.get("content", "") or ""
        usage = payload.get("usage", {}) or {}
        in_tok = int(usage.get("prompt_tokens") or usage.get("input_tokens") or _estimate_tokens(prompt))
        out_tok = int(usage.get("completion_tokens") or usage.get("output_tokens") or _estimate_tokens(text))
        total_tok = int(usage.get("total_tokens") or (in_tok + out_tok))
        in_price, out_price = self._pricing_per_1m(model_id)
        cost = round((in_tok / 1_000_000) * in_price + (out_tok / 1_000_000) * out_price, 8)
        usage_event = {
            "stage": stage,
            "model_id": model_id,
            "input_tokens": in_tok,
            "output_tokens": out_tok,
            "total_tokens": total_tok,
            "latency_ms": latency_ms,
            "estimated_cost_usd": cost,
        }
        return text, usage_event

    def _invoke_with_usage(
        self,
        model_id: str,
        stage: str,
        prompt: str,
        max_tokens: int,
        temperature: float,
    ) -> tuple:
        if self.provider == "OPENAI":
            return self._invoke_openai_with_usage(model_id, stage, prompt, max_tokens, temperature)

        started = time.time()
        response = self.bedrock.invoke_model(
            body=json.dumps(
                {
                    "anthropic_version": "bedrock-2023-05-31",
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                    "messages": [{"role": "user", "content": [{"type": "text", "text": prompt}]}],
                }
            ),
            modelId=model_id,
            accept="application/json",
            contentType="application/json",
        )
        latency_ms = int((time.time() - started) * 1000)

        payload = json.loads(response.get("body").read())
        content = payload.get("content") or []
        text = ""
        if content and isinstance(content, list):
            text = content[0].get("text", "")
        usage = payload.get("usage", {}) or {}
        in_tok = int(usage.get("input_tokens") or usage.get("inputTokens") or _estimate_tokens(prompt))
        out_tok = int(usage.get("output_tokens") or usage.get("outputTokens") or _estimate_tokens(text))
        total_tok = int(usage.get("total_tokens") or usage.get("totalTokens") or (in_tok + out_tok))

        in_price, out_price = self._pricing_per_1m(model_id)
        cost = round((in_tok / 1_000_000) * in_price + (out_tok / 1_000_000) * out_price, 8)

        usage_event = {
            "stage": stage,
            "model_id": model_id,
            "input_tokens": in_tok,
            "output_tokens": out_tok,
            "total_tokens": total_tok,
            "latency_ms": latency_ms,
            "estimated_cost_usd": cost,
        }
        return text, usage_event

    def _haiku_gate(
        self,
        buy_votes: int,
        sell_votes: int,
        rsi: float,
        macd: str,
        bb_pct: float,
        regime: str,
    ) -> tuple:
        """
        Cheap Haiku pre-gate: should we even bother calling Sonnet?
        Returns (passes, usage_event_or_none).
        """
        if self.provider != "BEDROCK" or not self.bedrock:
            return True, None

        direction = "BUY" if buy_votes >= sell_votes else "SELL"
        agreement = max(buy_votes, sell_votes)

        prompt = (
            "You are a crypto trader.\n"
            f"Market snapshot: Regime={regime}, Direction={direction}, "
            f"Agreement={agreement}/8 tools, RSI={rsi:.1f}, MACD={macd}, BB={bb_pct:.0f}%\n\n"
            "Question: Is this sufficiently strong and regime-aligned for a full analysis? "
            "Reply with exactly one word: PASS or SKIP."
        )

        try:
            answer, usage_event = self._invoke_with_usage(
                model_id=self.HAIKU_MODEL_ID,
                stage="haiku_gate",
                prompt=prompt,
                max_tokens=5,
                temperature=0.0,
            )
            answer = (answer or "SKIP").strip().upper()
            passes = "PASS" in answer
            if not passes:
                self.haiku_rejects += 1
            logger.info(f"⚡ Haiku gate: {answer} (rejects: {self.haiku_rejects})")
            return passes, usage_event
        except Exception as e:
            logger.warning(f"Haiku gate failed ({e}), proceeding to Sonnet")
            return True, None

    def analyze_with_tools(
        self,
        symbol,
        current_price,
        history,
        meta,
        tool_outputs,
        buy_count=0,
        sell_count=0,
        regime="UNKNOWN",
        rsi=50.0,
        macd="UNKNOWN",
        bb_pct=50.0,
    ) -> Signal:
        usage_events = []
        if not self.ready or len(history) < 2:
            return Signal("NEUTRAL", 0.0, self.weight, "LLM not ready.", meta={"llm_usage": usage_events})

        key = _cache_key(rsi, macd, bb_pct, buy_count, sell_count, regime)
        if key in _response_cache:
            cached_signal, cached_time = _response_cache[key]
            age = time.time() - cached_time
            if age < _CACHE_TTL_SECONDS:
                self.cache_hits += 1
                logger.info(
                    f"💾 Cache HIT (age:{age:.0f}s, hits:{self.cache_hits}) "
                    f"→ {cached_signal.action} ({cached_signal.confidence:.2f})"
                )
                return Signal(
                    cached_signal.action,
                    cached_signal.confidence,
                    self.weight,
                    f"[CACHED] {cached_signal.reason}",
                    meta={"llm_usage": usage_events, "decision_source": "LLM_CACHE"},
                )

        passes, gate_usage = self._haiku_gate(buy_count, sell_count, rsi, macd, bb_pct, regime)
        if gate_usage:
            usage_events.append(gate_usage)
        if not passes:
            return Signal(
                "NEUTRAL",
                0.0,
                self.weight,
                "Haiku gate: signal not strong enough for deep analysis",
                meta={"llm_usage": usage_events, "decision_source": "LLM_GATE_SKIP"},
            )

        oldest_price = history[0]
        session_change_pct = ((current_price - oldest_price) / oldest_price) * 100
        recent_change_pct = ((current_price - history[-2]) / history[-2]) * 100
        high_24h = meta.get("high", current_price)
        low_24h = meta.get("low", current_price)
        vol_24h = meta.get("volume", 0)
        change_24h = meta.get("change_24h", 0)

        lessons_ctx = self._build_lessons_context()
        tool_block = "\n".join([f"  - {t['name']}: {t['data']}" for t in tool_outputs])

        pro_lines = "\n".join(
            [
                t["data"]
                for t in tool_outputs
                if t["name"] in ("RSI (14)", "MACD Signal", "Bollinger Bands", "Support & Resistance", "Candle Patterns")
            ]
        )

        prompt = f"""You are a disciplined crypto trading tie-breaker.

<MARKET_CONTEXT>
Symbol: {symbol}
Price: ${current_price:,.2f}
24h High/Low: ${high_24h:,.0f} / ${low_24h:,.0f}
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

REGIME RULE: Market is {regime}. {"Only consider LONG (BUY) trades." if regime == "BULL" else "Only consider SHORT (SELL) trades." if regime == "BEAR" else "Be conservative."}

Output strictly valid JSON (no markdown):
{{
    "action": "BUY" | "SELL" | "NEUTRAL",
    "confidence": 0.00,
    "reason": "2-3 key signals only"
}}"""

        try:
            model_id = config.OPENAI_MODEL_ID if self.provider == "OPENAI" else config.BEDROCK_MODEL_ID
            logger.info(f"🧠 Querying {self.provider} for {symbol} ({buy_count}B/{sell_count}S | regime={regime})...")
            llm_text, usage_event = self._invoke_with_usage(
                model_id=model_id,
                stage="sonnet_decision",
                prompt=prompt,
                max_tokens=200,
                temperature=0.1,
            )
            usage_events.append(usage_event)

            result = json.loads(_strip_fences(llm_text))
            action = result.get("action", "NEUTRAL")
            confidence = float(result.get("confidence", 0.0))
            reason = result.get("reason", "LLM decision")

            sig = Signal(
                action,
                confidence,
                self.weight,
                f"{self.provider}: {reason}",
                meta={"llm_usage": usage_events, "decision_source": "LLM_TIEBREAKER"},
            )
            logger.info(f"🧠 {self.provider}: {action} ({confidence:.2f}) — {reason}")
            _response_cache[key] = (sig, time.time())
            return sig

        except json.JSONDecodeError:
            logger.error("LLM JSON parse error.")
            return Signal(
                "NEUTRAL",
                0.0,
                self.weight,
                "LLM JSON error",
                meta={"llm_usage": usage_events, "decision_source": "LLM_ERROR"},
            )
        except Exception as e:
            logger.error(f"LLM API Error ({self.provider}): {e}")
            return Signal(
                "NEUTRAL",
                0.0,
                self.weight,
                "LLM provider error",
                meta={"llm_usage": usage_events, "decision_source": "LLM_ERROR"},
            )

    def analyze(self, symbol, current_price, history, meta) -> Signal:
        return self.analyze_with_tools(symbol, current_price, history, meta, [])
