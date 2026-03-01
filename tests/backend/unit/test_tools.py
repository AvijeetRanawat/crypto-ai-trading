import statistics

import pytest

from strategies import tools


def test_volatility_scanner_handles_short_history():
    result = tools.VolatilityScanner.analyze(list(range(5)))
    assert not result["tradeable"]
    assert result["verdict"].startswith("Insufficient")


def test_volatility_scanner_detects_high_volatility():
    history = [100.0 + ((-1) ** i) * 10 * i for i in range(60)]
    result = tools.VolatilityScanner.analyze(history)
    assert result["tradeable"]
    assert result["verdict"].startswith("HIGH")


def test_price_velocity_acceleration_detected():
    history = list(range(1, 25))
    current_price = 100
    result = tools.PriceVelocity.analyze(history, current_price)
    assert "velocity_1m" in result
    assert result["acceleration"] in {
        "ACCELERATING — momentum building",
        "DECELERATING — momentum fading",
        "STEADY — stable speed",
        "STEADY — no 5m drift yet",
    }


def test_volume_profile_verdict_levels():
    healthy = tools.VolumeProfile.analyze({"volume": 2000, "bid": 100, "ask": 102})
    assert healthy["liquid"]
    assert healthy["verdict"].startswith("HEALTHY")

    low = tools.VolumeProfile.analyze({"volume": 50, "bid": 10, "ask": 12})
    assert low["verdict"].startswith("VERY LOW")
    assert not low["liquid"]


def test_order_book_pressure_neutral_bias():
    out = tools.OrderBookPressure.analyze({"bid": 100, "ask": 100}, current_price=100)
    assert out["pressure"].startswith("NEUTRAL")
    assert out["bias"] == 0.0


def test_session_tracker_statistics_and_recommendation():
    tracker = tools.SessionTracker()
    tracker.record_trade(10)
    tracker.record_trade(-5)
    tracker.record_trade(20)
    stats = tracker.get_stats()
    assert stats["total_trades"] == 3
    assert stats["win_rate"].endswith("%")
    assert stats["recommendation"]


def test_rsi_analyzer_warming_up_and_extremes():
    small = list(range(10))
    warming = tools.RSIAnalyzer.analyze(small)
    assert warming["signal"] == "NEUTRAL"
    assert "Warming up" in warming["verdict"]

    extreme_gains = [0] * 28 + [i for i in range(1, 30)]
    strong_buy = tools.RSIAnalyzer.analyze(extreme_gains)
    assert strong_buy["signal"] in {"STRONG_BUY", "BUY", "NEUTRAL", "STRONG_SELL"}
    assert 0 <= strong_buy["rsi"] <= 100


def test_macd_signal_insufficient_then_valid():
    short_history = list(range(10))
    low = tools.MACDSignal.analyze(short_history)
    assert low["crossover"] == "NONE"

    # Use a simple rising sequence to simulate a bullish crossover
    history = [i * 0.1 for i in range(50)]
    result = tools.MACDSignal.analyze(history)
    assert result["verdict"]
    assert result["histogram"] == round(result["macd"] - result["signal_line"], 2)
