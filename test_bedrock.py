import boto3
import json

def test():
    print("Initializing Bedrock client...")
    bedrock = boto3.client(service_name='bedrock-runtime', region_name='us-east-1')
    
    prompt = "Hello! Are you Claude responding from AWS Bedrock? Please keep your answer to one sentence."
    
    body = json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 100,
        "temperature": 0.2,
        "messages": [
            {
                "role": "user",
                "content": [{"type": "text", "text": prompt}]
            }
        ]
    })

    print(f"Invoking us.anthropic.claude-sonnet-4-6...")
    try:
        response = bedrock.invoke_model(
            body=body,
            modelId="us.anthropic.claude-sonnet-4-6",
            accept="application/json",
            contentType="application/json"
        )
        response_body = json.loads(response.get('body').read())
        text = response_body.get('content')[0].get('text')
        print(f"\n✅ SUCCESS! Claude replied:\n{text}")
    except Exception as e:
        print(f"\n❌ ERROR connecting to Bedrock: {e}")

if __name__ == '__main__':
    test()
