import sqlite3
import json
import boto3
from config import config
from logger import logger
from database import DB_PATH, save_distilled_rule

# Categories to group lessons by
CATEGORIES = ['RSI', 'MACD', 'Bollinger/BB', 'Trend', 'Support/Resistance', 'EMA Cross', 'Candle Patterns', 'Volume', 'Session/Time']

def distill_all():
    """Main entry point to distill hundreds of lessons into a few master rules."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    bedrock = boto3.client(service_name='bedrock-runtime', region_name='us-east-1')

    logger.info("🚀 Starting lesson distillation...")
    
    rules_generated = 0
    for category in CATEGORIES:
        # Fetch lessons matching category keywords
        # We search both market_condition and lesson text
        query_terms = category.split('/')
        where_clauses = []
        for term in query_terms:
            where_clauses.append(f"market_condition LIKE '%{term}%' OR lesson LIKE '%{term}%'")
        
        query = f"SELECT market_condition, lesson FROM lessons WHERE {' OR '.join(where_clauses)}"
        cursor.execute(query)
        rows = cursor.fetchall()
        
        if len(rows) < 3:
            logger.info(f"⏭  Skipping {category} (only {len(rows)} lessons)")
            continue
            
        logger.info(f"🧠 Distilling {len(rows)} lessons for category: {category}")
        
        # Format lessons for Claude
        lesson_text = "\n".join([f"- Context: {r[0]} | Lesson: {r[1]}" for r in rows])
        
        prompt = f"""You are a senior trading strategist. We have collected {len(rows)} micro-lessons about {category} from real trading performance. 
Your goal is to DISTILL these many small lessons into 1-2 high-level MASTER RULES that capture the core wisdom without the redundant details.

RAW LESSONS:
{lesson_text}

OUTPUT FORMAT (JSON ONLY):
{{
    "rules": [
        "Concise master rule 1",
        "Concise master rule 2 (optional)"
    ]
}}
"""

        try:
            body = json.dumps({
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 500,
                "temperature": 0.1,
                "messages": [{"role": "user", "content": [{"type": "text", "text": prompt}]}]
            })
            
            response = bedrock.invoke_model(
                body=body, modelId=config.BEDROCK_MODEL_ID,
                accept="application/json", contentType="application/json"
            )
            
            resp_body = json.loads(response.get('body').read())
            llm_text = resp_body.get('content')[0].get('text', '{}')
            
            # Clean JSON
            if "```" in llm_text:
                llm_text = llm_text.split("```")[1].replace("json", "").strip()
            
            result = json.loads(llm_text)
            master_rules = result.get("rules", [])
            
            if master_rules:
                combined_rule = " | ".join(master_rules)
                save_distilled_rule(category, combined_rule, len(rows))
                rules_generated += 1
                logger.info(f"✅ Saved distilled rule for {category} ({len(rows)} sources)")
                
        except Exception as e:
            logger.error(f"❌ Failed to distill {category}: {e}")

    conn.close()
    logger.info(f"✨ Distillation complete. Generated {rules_generated} master rules.")

if __name__ == "__main__":
    distill_all()
