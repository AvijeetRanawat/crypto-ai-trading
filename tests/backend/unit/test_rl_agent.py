from pathlib import Path

import pytest

import rl_agent


def test_rl_weight_agent_infer_and_update(tmp_path):
    state_file = tmp_path / "rl_state.json"
    agent = rl_agent.RLWeightAgent(state_file=str(state_file), enabled=True, epsilon=0.0)
    features = {
        "regime": "TRENDING_UP",
        "session_quality": "HIGH",
        "volatility_pct": 0.2,
        "sentiment_score": 0.1,
        "vote_imbalance": 0.5,
        "expected_edge_pct": 0.1,
    }
    result = agent.infer("SPOT", features)
    assert result["profile_id"] in rl_agent.PROFILES["SPOT"]
    assert result["state_key"]
    agent.update("SPOT", result["state_key"], result["profile_id"], reward=0.01)


def test_mlx_agent_infer_and_update(tmp_path):
    if not rl_agent.is_mlx_available():
        pytest.skip("mlx not available")
    state_file = tmp_path / "mlx_state.json"
    agent = rl_agent.MLXWeightAgent(
        state_file=str(state_file),
        enabled=True,
        epsilon=0.0,
        learning_rate=0.05,
        hidden_size=8,
    )
    features = {
        "regime": "TRENDING_UP",
        "session_quality": "HIGH",
        "volatility_pct": 0.2,
        "sentiment_score": 0.1,
        "vote_imbalance": 0.5,
        "expected_edge_pct": 0.1,
    }
    result = agent.infer("SPOT", features)
    assert result["profile_id"] in rl_agent.PROFILES["SPOT"]
    assert result["state_key"]
    agent.update("SPOT", result["state_key"], result["profile_id"], reward=0.02)
