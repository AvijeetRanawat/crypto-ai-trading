from datetime import datetime

import engine as engine_module


class DummyClient:
    latest_prices = {}
    ticker_meta = {}
    monitored_channels = []


class DummyLLM:
    ready = False
    provider = "NONE"
    bedrock = None


def _engine(monkeypatch):
    monkeypatch.setattr(engine_module, "LLMAgent", lambda: DummyLLM())
    return engine_module.TradingEngine(DummyClient())


def test_deterministic_decision_buy(monkeypatch):
    eng = _engine(monkeypatch)
    action, conf, reason = eng._deterministic_decision(6, 2)
    assert action == "BUY"
    assert conf >= 0.8
    assert "deterministic" in reason


def test_deterministic_decision_neutral_when_low_agreement(monkeypatch):
    eng = _engine(monkeypatch)
    action, conf, reason = eng._deterministic_decision(2, 1)
    assert action == "NEUTRAL"
    assert conf == 0.0
    assert "insufficient" in reason


def test_expected_edge_moves_with_signal_quality(monkeypatch):
    eng = _engine(monkeypatch)
    weak = eng._estimate_expected_edge_pct(3, 3, tp_pct=0.008, sl_pct=0.004)
    strong = eng._estimate_expected_edge_pct(7, 1, tp_pct=0.008, sl_pct=0.004)
    assert strong > weak


def test_add_to_position_preserves_existing_trade_state(monkeypatch):
    sim = engine_module.PaperTradingSimulator()
    sim.balance_usdt = 1000.0
    sim.positions["BTCUSDT:SPOT"] = {
        "symbol": "BTCUSDT",
        "mode": "SPOT",
        "side": "LONG",
        "entry_price": 100.0,
        "quantity": 1.0,
        "entry_time": datetime.now(),
        "db_id": 1,
        "entry_reason": "initial",
        "peak_pnl_pct": 0.12,
        "trailing_active": True,
    }

    ok = sim.add_to_position("BTCUSDT", price=120.0, amount_usdt=120.0, reason="pyramid")
    assert ok is True

    pos = sim.positions["BTCUSDT:SPOT"]
    assert round(pos["quantity"], 6) == 2.0
    assert round(pos["entry_price"], 2) == 110.0
    assert pos["trailing_active"] is False
    assert pos["peak_pnl_pct"] == 0.0
    assert "pyramid" in pos["entry_reason"]
    assert sim.balance_usdt == 880.0
