import json
import requests

from config import config
from logger import logger
from database import get_recent_lessons, save_lesson


def _call_llm(prompt: str, bedrock_client=None, max_tokens: int = 400, temperature: float = 0.3) -> str | None:
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

class MetaOptimizer:
    """
    Post-Session Meta-Learning Agent.
    After a full session of trades, this agent reads ALL accumulated lessons,
    asks the LLM to distill them into 3 "golden rules", and stores
    the optimized ruleset for future sessions to bootstrap from.
    """
    def __init__(self, bedrock_client=None):
        self.bedrock = bedrock_client

    def optimize(self):
        if not self.bedrock and not (config.LLM_PROVIDER == "OPENAI" and config.OPENAI_API_KEY):
            logger.warning("Meta-Optimizer skipped: no LLM client available.")
            return

        lessons = get_recent_lessons(limit=20)
        if not lessons or len(lessons) < 2:
            logger.info("Meta-Optimizer: Not enough lessons to optimize yet.")
            return

        lessons_text = ""
        for i, (condition, lesson, severity) in enumerate(lessons, 1):
            lessons_text += f"{i}. [{severity}] {condition} → {lesson}\n"

        prompt = f"""You are a trading strategy optimizer. Below are lessons from recent trades.

<RAW_LESSONS>
{lessons_text}
</RAW_LESSONS>

TASK:
Analyze ALL the lessons above and distill them into exactly 3 GOLDEN RULES.
These rules should:
1. Combine redundant lessons into concise principles
2. Prioritize loss-prevention over profit-seeking
3. Be actionable and specific (not vague)

Output strictly valid JSON, no markdown:
{{
    "golden_rules": [
        "Rule 1 text",
        "Rule 2 text",
        "Rule 3 text"
    ],
    "pattern_detected": "1-sentence summary of the main pattern across all lessons"
}}
"""

        try:
            logger.info("🎓 Meta-Optimizer: Distilling lessons into Golden Rules...")
            llm_text = _call_llm(prompt, bedrock_client=self.bedrock, max_tokens=400, temperature=0.3)
            if not llm_text:
                logger.error("Meta-Optimizer: No response from LLM.")
                return None

            # Strip markdown fences if present
            if llm_text.startswith("```"):
                parts = llm_text.split("```")
                llm_text = parts[1].strip() if len(parts) > 1 else parts[-1].strip()
                if llm_text.lower().startswith("json"):
                    llm_text = llm_text[4:].strip()
            result = json.loads(llm_text)

            golden_rules = result.get("golden_rules", [])
            pattern = result.get("pattern_detected", "")

            # Save the golden rules as a single meta-lesson
            rules_text = " | ".join(golden_rules)
            save_lesson(
                condition=f"META-OPTIMIZER: {pattern}",
                lesson=rules_text,
                severity="GOLDEN"
            )

            for i, rule in enumerate(golden_rules, 1):
                logger.info(f"🏆 Golden Rule #{i}: {rule}")

            return golden_rules

        except Exception as e:
            logger.error(f"Meta-Optimizer error: {e}")
            return None
