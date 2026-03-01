import dashboard_api
import asyncio


def test_backend_smoke_endpoints(api_module, seed_basic_market_data, monkeypatch):
    def _fake_snapshot(**kwargs):
        return {
            "updated_at": "2026-01-01T00:00:00Z",
            "symbol": kwargs.get("symbol", "BTCUSDT"),
            "sentiment_score": 0.1,
            "sentiment_label": "BULLISH",
            "components": {
                "news_score": 0.2,
                "fear_greed_score": 0.1,
                "fear_greed": {
                    "value": 55,
                    "value_classification": "Greed",
                    "sentiment_score": 0.1,
                },
                "articles_count": 1,
                "sources_available": {"mock": True},
            },
            "articles": [
                {
                    "source": "Mock",
                    "title": "Mock headline",
                    "url": "https://example.com/mock",
                    "published_at": "2026-01-01T00:00:00Z",
                    "sentiment_score": 0.25,
                }
            ],
            "llm_summary": {
                "text": "Mock summary",
                "model_id": "mock-model",
                "timestamp": "2026-01-01T00:00:00Z",
                "cached": True,
            },
        }

    def _fake_summarize(snapshot, **kwargs):
        return snapshot, None

    monkeypatch.setattr(api_module, "build_sentiment_snapshot", _fake_snapshot)
    monkeypatch.setattr(api_module, "summarize_sentiment_with_llm", _fake_summarize)

    assert asyncio.run(api_module.session_start())["session_start_ms"] >= 0
    assert asyncio.run(api_module.get_warmup(symbol="BTCUSDT"))["symbol"] == "BTCUSDT"
    assert asyncio.run(api_module.get_regime(symbol="BTCUSDT"))["symbol"] == "BTCUSDT"
    assert "total_trades" in asyncio.run(api_module.get_portfolio_summary())
    assert "message" in asyncio.run(api_module.get_intent())
    assert isinstance(asyncio.run(api_module.get_signals_history(symbol="BTCUSDT", limit=10)), list)
    assert asyncio.run(api_module.get_strategy_diagnostics(symbol="BTCUSDT", mode="SPOT"))["mode"] == "SPOT"
    assert asyncio.run(api_module.get_strategy_diagnostics(symbol="BTCUSDT", mode="FUTURES"))["mode"] == "FUTURES"
    assert asyncio.run(api_module.get_strategy_diagnostics(symbol="BTCUSDT", mode="OPTIONS"))["mode"] == "OPTIONS"
    assert "llm_calls_today" in asyncio.run(api_module.get_llm_summary())
    assert "all_time" in asyncio.run(api_module.get_llm_breakdown())
    assert asyncio.run(api_module.get_news_sentiment(symbol="BTCUSDT"))["symbol"] == "BTCUSDT"
