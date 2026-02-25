import json

from config import config
from logger import logger
from database import get_recent_lessons, save_lesson

class MetaOptimizer:
    """
    Post-Session Meta-Learning Agent.
    After a full session of trades, this agent reads ALL accumulated lessons,
    asks Claude to distill them into 3 "golden rules", and stores
    the optimized ruleset for future sessions to bootstrap from.
    """
    def __init__(self, bedrock_client):
        self.bedrock = bedrock_client

    def optimize(self):
        if not self.bedrock:
            logger.warning("Meta-Optimizer skipped: no Bedrock client.")
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

        body = json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 400,
            "temperature": 0.3,
            "messages": [
                {"role": "user", "content": [{"type": "text", "text": prompt}]}
            ]
        })

        try:
            logger.info("🎓 Meta-Optimizer: Distilling lessons into Golden Rules...")
            response = self.bedrock.invoke_model(
                body=body,
                modelId=config.BEDROCK_MODEL_ID,
                accept="application/json",
                contentType="application/json"
            )

            response_body = json.loads(response.get('body').read())
            llm_text = response_body.get('content')[0].get('text')
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
