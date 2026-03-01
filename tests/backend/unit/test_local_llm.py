from types import SimpleNamespace

import pytest

import local_llm
import news_sentiment


def test_local_llm_agent_fails_when_missing_backend(monkeypatch):
    monkeypatch.setattr(local_llm, "Llama", None)
    agent = local_llm.LocalLlmAgent("model.bin", "test-model", 0.1, 10)
    assert not agent.ready()
    text, usage = agent.complete("ping")
    assert text == ""
    assert usage == {}


def test_local_llm_agent_with_dummy_llama(monkeypatch):
    class DummyLlama:
        def __init__(self, *args, **kwargs):
            pass

        def __call__(self, prompt, max_tokens, stop):
            return {
                "choices": [{"text": "tracked"}],
                "usage": {"input_tokens": 5, "output_tokens": 3, "total_tokens": 8},
            }

    monkeypatch.setattr(local_llm, "Llama", DummyLlama)
    agent = local_llm.LocalLlmAgent("model.bin", "test-model", 0.1, 10)
    assert agent.ready()
    text, usage = agent.complete("prompt")
    assert text == "tracked"
    assert usage["total_tokens"] == 8


def test_local_summary_helper(monkeypatch):
    fake_agent = SimpleNamespace(
        ready=lambda: True,
        complete=lambda prompt: ("summary text", {"input_tokens": 3, "output_tokens": 2, "total_tokens": 5, "latency_ms": 7}),
        model_id="local-test",
    )
    monkeypatch.setattr(news_sentiment, "get_local_llm_agent", lambda: fake_agent)
    snapshot = {
        "symbol": "BTCUSDT",
        "sentiment_score": 0.2,
        "sentiment_label": "BULLISH",
        "components": {"fear_greed": {"value": 80, "value_classification": "Greed"}, "news_score": 1.0},
        "articles": [],
    }
    summary, usage = news_sentiment.summarize_sentiment_with_local_model(snapshot)
    assert summary["llm_summary"]["model_id"] == "local-test"
    assert usage["model_id"] == "local-test"
