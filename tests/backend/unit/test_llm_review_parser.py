from strategies.llm import _parse_json_object


def test_parse_json_object_accepts_fenced_json():
    payload = """```json
{
  "verdict": "SUPPORT",
  "confidence": 0.77,
  "reason": "alignment",
  "suggested_action": "BUY"
}
```"""
    parsed = _parse_json_object(payload)
    assert parsed["verdict"] == "SUPPORT"
    assert parsed["suggested_action"] == "BUY"


def test_parse_json_object_recovers_from_wrapped_text_and_trailing_commas():
    payload = """
Model response:
{
  "verdict": "OPPOSE",
  "confidence": 0.61,
  "reason": "risk mismatch",
  "suggested_action": "SKIP",
}
Thanks.
"""
    parsed = _parse_json_object(payload)
    assert parsed["verdict"] == "OPPOSE"
    assert parsed["suggested_action"] == "SKIP"


def test_parse_json_object_recovers_from_unterminated_reason_string():
    payload = """
{
  "verdict": "OPPOSE",
  "confidence": 0.41,
  "reason": "unterminated rationale
  "suggested_action": "SKIP"
}
"""
    parsed = _parse_json_object(payload)
    assert parsed["verdict"] == "OPPOSE"
    assert parsed["suggested_action"] == "SKIP"
    assert parsed["confidence"] == 0.41
