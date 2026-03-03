import pytest

import engine_rl_helpers
from engine_rl_helpers import (
    rl_apply_weight_multipliers,
    attach_rl_metadata,
    rl_reward_skip_opportunity,
)

from config import config


class DummyEngine:
    def __init__(self):
        self.rl_agent = self
        self.infer_calls = []
        self.update_calls = []

    def infer(self, **kwargs):
        self.infer_calls.append(kwargs)
        return {"profile_id": "profile-x", "state_key": "state-x", "decision_type": "test", "weight_mult": {"limit": 0.5}}

    def update(self, mode, state_key, profile_id, reward):
        self.update_calls.append((mode, state_key, profile_id, reward))


def test_rl_apply_weight_multipliers_scales_values():
    weights = {"limit": 2.0, "stop": 1.0}
    rl_inf = {"weight_mult": {"limit": 0.25}}
    adjusted = rl_apply_weight_multipliers(weights, rl_inf)
    assert adjusted["limit"] == pytest.approx(0.5)
    assert adjusted["stop"] == 1.0


def test_attach_rl_metadata_calls_infer():
    engine = DummyEngine()
    result = attach_rl_metadata(
        engine,
        mode="SPOT",
        result={},
        kwargs={"buy_count": 3, "sell_count": 1, "regime_result": {"regime": "TREND"}, "session_filt": {"quality": "HIGH"}},
    )
    assert result["rl_profile_id"] == "profile-x"
    assert engine.infer_calls
    assert result["rl_state_key"] == "state-x"


def test_rl_reward_skip_opportunity_updates_rl_and_logs(monkeypatch):
    engine = DummyEngine()
    policy = {"rl_state_key": "state-x", "rl_profile_id": "profile-x"}

    called = {}

    def fake_save_rl_event(**kwargs):
        called.update(kwargs)

    monkeypatch.setattr(engine_rl_helpers, "save_rl_event", fake_save_rl_event)
    monkeypatch.setattr(engine_rl_helpers.config, "ENABLE_RL_WEIGHT_AGENT", True)
    monkeypatch.setattr(engine_rl_helpers.config, "RL_OPPORTUNITY_COST_PENALTY", 0.1)
    monkeypatch.setattr(engine_rl_helpers.config, "MIN_EXPECTED_EDGE_PCT", 0.01)
    monkeypatch.setattr(engine_rl_helpers.config, "EARLY_STOP_LOSS_PCT", 0.02)

    rl_reward_skip_opportunity(engine, "SPOT", policy, expected_edge_pct=0.05, reason="test", symbol="BTCUSDT")

    assert engine.update_calls
    assert called["event_type"] == "SKIP_OPPORTUNITY"
    assert called["symbol"] == "BTCUSDT"


def test_rl_reward_skip_opportunity_skips_non_actionable_penalties(monkeypatch):
    engine = DummyEngine()
    policy = {"rl_state_key": "state-x", "rl_profile_id": "profile-x"}

    called = {}

    def fake_save_rl_event(**kwargs):
        called.update(kwargs)

    monkeypatch.setattr(engine_rl_helpers, "save_rl_event", fake_save_rl_event)
    monkeypatch.setattr(engine_rl_helpers.config, "ENABLE_RL_WEIGHT_AGENT", True)

    rl_reward_skip_opportunity(
        engine,
        "SPOT",
        policy,
        expected_edge_pct=0.12,
        reason="post_close_cooldown",
        symbol="BTCUSDT",
    )

    assert not engine.update_calls
    assert called["event_type"] == "SKIP_OPPORTUNITY"
    assert called["reason"] == "post_close_cooldown"
    assert called["reward"] == 0.0
    assert called["penalty"] == 0.0
    assert called["raw_penalty"] == 0.0


def test_rl_reward_skip_opportunity_skips_non_actionable_penalties_with_reason_variants(monkeypatch):
    engine = DummyEngine()
    policy = {"rl_state_key": "state-x", "rl_profile_id": "profile-x"}

    called = {}

    def fake_save_rl_event(**kwargs):
        called.update(kwargs)

    monkeypatch.setattr(engine_rl_helpers, "save_rl_event", fake_save_rl_event)
    monkeypatch.setattr(engine_rl_helpers.config, "ENABLE_RL_WEIGHT_AGENT", True)

    rl_reward_skip_opportunity(
        engine,
        "SPOT",
        policy,
        expected_edge_pct=0.12,
        reason="post-close-cooldown (safety)",
        symbol="BTCUSDT",
    )

    assert not engine.update_calls
    assert called["event_type"] == "SKIP_OPPORTUNITY"
    assert called["reward"] == 0.0
