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


def test_rl_weight_agent_weights_actually_learn(tmp_path):
    """Verify that weight multipliers change meaningfully over repeated updates.

    The old _adapt_weight_mult produced ~0.01% changes.  The new persistent
    weight learning should produce visible drift after a sequence of updates.
    """
    state_file = tmp_path / "rl_state.json"
    agent = rl_agent.RLWeightAgent(state_file=str(state_file), enabled=True, epsilon=0.0)
    features = {
        "regime": "TRENDING_UP",
        "session_quality": "HIGH",
        "volatility_pct": 0.2,
        "sentiment_score": 0.15,
        "vote_imbalance": 0.6,
        "expected_edge_pct": 0.1,
    }

    # First infer — establishes learned weights from profile defaults
    result = agent.infer("SPOT", features)
    state_key = result["state_key"]
    profile_id = result["profile_id"]
    initial_weights = dict(result["weight_mult"])

    # Need at least 3 prior updates before adaptation kicks in (prev_n >= 3)
    for _ in range(4):
        agent.update("SPOT", state_key, profile_id, reward=-0.005)

    # Now run 50 updates with a positive reward to shift weights
    for _ in range(50):
        agent.update("SPOT", state_key, profile_id, reward=0.05)

    # Re-infer and check weights changed
    result2 = agent.infer("SPOT", features)
    learned_weights = result2["weight_mult"]

    # At least one weight must have shifted by > 0.5% from its initial value
    max_change = 0.0
    for key in initial_weights:
        if key in learned_weights:
            change = abs(learned_weights[key] - initial_weights[key])
            max_change = max(max_change, change)

    assert max_change > 0.005, (
        f"Weights barely changed (max delta={max_change:.6f}). "
        f"Initial: {initial_weights}, Learned: {learned_weights}"
    )


def test_rl_weight_agent_weights_persist_across_reload(tmp_path):
    """Verify learned weights survive agent reload from disk."""
    state_file = tmp_path / "rl_state.json"
    agent = rl_agent.RLWeightAgent(state_file=str(state_file), enabled=True, epsilon=0.0)
    features = {
        "regime": "TRENDING_UP",
        "session_quality": "HIGH",
        "volatility_pct": 0.2,
        "sentiment_score": 0.15,
        "vote_imbalance": 0.6,
        "expected_edge_pct": 0.1,
    }

    result = agent.infer("SPOT", features)
    state_key = result["state_key"]
    profile_id = result["profile_id"]

    # Accumulate some learning
    for _ in range(20):
        agent.update("SPOT", state_key, profile_id, reward=0.03)
    agent.flush()

    # Reload and check learned weights are preserved
    agent2 = rl_agent.RLWeightAgent(state_file=str(state_file), enabled=True, epsilon=0.0)
    result2 = agent2.infer("SPOT", features)

    # Learned weights dict should exist in the reloaded state
    w_table = agent2.state.get("w", {}).get("SPOT", {})
    assert state_key in w_table, "Learned weights not found after reload"
    assert "wm" in w_table[state_key], "weight_mult not in learned weights"
    assert "vm" in w_table[state_key], "voter_weight_mult not in learned weights"


def test_rl_weight_agent_negative_advantage_dampens(tmp_path):
    """Negative reward advantage should push weights toward 1.0 (neutral)."""
    state_file = tmp_path / "rl_state.json"
    agent = rl_agent.RLWeightAgent(state_file=str(state_file), enabled=True, epsilon=0.0)
    features = {
        "regime": "TRENDING_UP",
        "session_quality": "HIGH",
        "volatility_pct": 0.2,
        "sentiment_score": 0.15,
        "vote_imbalance": 0.6,
        "expected_edge_pct": 0.1,
    }

    result = agent.infer("SPOT", features)
    state_key = result["state_key"]
    profile_id = result["profile_id"]
    initial_weights = dict(result["weight_mult"])

    # Establish a baseline with moderate rewards, then hit with bad ones
    for _ in range(5):
        agent.update("SPOT", state_key, profile_id, reward=0.01)

    # Apply strongly negative rewards
    for _ in range(50):
        agent.update("SPOT", state_key, profile_id, reward=-0.10)

    result2 = agent.infer("SPOT", features)
    learned = result2["weight_mult"]

    # Weights that were far from 1.0 should have moved closer to 1.0
    for key in initial_weights:
        if key in learned and abs(initial_weights[key] - 1.0) > 0.05:
            initial_distance = abs(initial_weights[key] - 1.0)
            learned_distance = abs(learned[key] - 1.0)
            # Allow some tolerance for noise, but trend should be toward 1.0
            assert learned_distance < initial_distance + 0.05, (
                f"Weight '{key}' moved further from 1.0: "
                f"initial={initial_weights[key]}, learned={learned[key]}"
            )


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
