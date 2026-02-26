import boto3
import json
import time

# Configuration matches the bot's settings
SONNET_MODEL_ID = "us.anthropic.claude-sonnet-4-6"
HAIKU_MODEL_ID = "us.anthropic.claude-haiku-4-5-20251001-v1:0"

def test_model(model_name, model_id, prompt):
    print(f"\n--- Testing {model_name} ({model_id}) ---")
    bedrock = boto3.client(service_name='bedrock-runtime', region_name='us-east-1')
    
    body = json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 300,
        "temperature": 0.2,
        "messages": [
            {
                "role": "user",
                "content": [{"type": "text", "text": prompt}]
            }
        ]
    })

    start_time = time.time()
    try:
        response = bedrock.invoke_model(
            body=body,
            modelId=model_id,
            accept="application/json",
            contentType="application/json"
        )
        response_body = json.loads(response.get('body').read())
        text = response_body.get('content')[0].get('text')
        latency = time.time() - start_time
        print(f"✅ SUCCESS! Latency: {latency:.2f}s")
        print(f"Response:\n{text}")
    except Exception as e:
        print(f"❌ ERROR: {e}")

if __name__ == "__main__":
    god_prompt = "You are a crypto finance trader expert god level. Analyze the following setup: BTC is up 5% in 1 hour, RSI is 85, and it just hit the upper Bollinger Band. What is your 'god level' advice for a scalp trader?"
    
    # 1. Test Haiku 4.5 (Gate)
    test_model("Claude Haiku 4.5", HAIKU_MODEL_ID, god_prompt)
    
    # 2. Test Sonnet 4.6 (Core Analysis)
    test_model("Claude Sonnet 4.6", SONNET_MODEL_ID, god_prompt)
