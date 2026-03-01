import json
import os
import random
import threading
from datetime import datetime

from logger import logger

try:
    import mlx.core as mx
    import mlx.nn as nn
    import mlx.optimizers as optim
except Exception:
    mx = None
    nn = None
    optim = None


def is_mlx_available() -> bool:
    return mx is not None and nn is not None and optim is not None


PROFILES = {
    "SPOT": {
        "aggressive": {
            "weight_mult": {
                "trend": 1.05,
                "momentum": 1.20,
                "volatility": 0.90,
                "liquidity": 0.92,
                "sentiment": 0.88,
                "session": 0.85,
                "performance": 0.85,
            },
            "voter_weight_mult": {
                "rsi": 1.10,
                "macd": 1.10,
                "bb": 0.95,
                "sr": 0.95,
                "candle": 0.95,
                "stochrsi": 1.10,
                "ema": 1.10,
                "volmom": 1.05,
            },
            "size_mult": 1.25,
            "confidence_bias": 0.04,
            "sentiment_gate_mult": 0.85,
        },
        "balanced": {
            "weight_mult": {},
            "voter_weight_mult": {},
            "size_mult": 1.00,
            "confidence_bias": 0.00,
            "sentiment_gate_mult": 1.00,
        },
        "breakout_hunter": {
            "weight_mult": {
                "trend": 1.10,
                "momentum": 1.28,
                "volatility": 1.05,
                "liquidity": 0.95,
                "sentiment": 0.90,
                "session": 0.90,
                "performance": 0.82,
            },
            "voter_weight_mult": {
                "rsi": 0.95,
                "macd": 1.15,
                "bb": 1.10,
                "sr": 1.05,
                "candle": 1.05,
                "stochrsi": 0.95,
                "ema": 1.15,
                "volmom": 1.10,
            },
            "size_mult": 1.35,
            "confidence_bias": 0.05,
            "sentiment_gate_mult": 0.90,
        },
    },
    "FUTURES": {
        "aggressive": {
            "weight_mult": {
                "vote_imbalance": 1.10,
                "regime": 1.05,
                "momentum": 1.18,
                "volatility": 1.05,
                "liquidity": 0.92,
                "sentiment": 0.88,
                "session": 0.88,
            },
            "voter_weight_mult": {
                "rsi": 1.05,
                "macd": 1.10,
                "bb": 0.90,
                "sr": 0.90,
                "candle": 0.95,
                "stochrsi": 1.10,
                "ema": 1.15,
                "volmom": 1.10,
            },
            "size_mult": 1.30,
            "leverage_mult": 1.20,
            "confidence_bias": 0.05,
            "sentiment_gate_mult": 0.92,
        },
        "balanced": {
            "weight_mult": {},
            "voter_weight_mult": {},
            "size_mult": 1.00,
            "leverage_mult": 1.00,
            "confidence_bias": 0.00,
            "sentiment_gate_mult": 1.00,
        },
        "trend_rider": {
            "weight_mult": {
                "vote_imbalance": 1.12,
                "regime": 1.14,
                "momentum": 1.24,
                "volatility": 0.92,
                "liquidity": 0.95,
                "sentiment": 0.90,
                "session": 0.90,
            },
            "voter_weight_mult": {
                "rsi": 0.95,
                "macd": 1.20,
                "bb": 0.95,
                "sr": 1.00,
                "candle": 1.05,
                "stochrsi": 0.95,
                "ema": 1.20,
                "volmom": 1.10,
            },
            "size_mult": 1.36,
            "leverage_mult": 1.28,
            "confidence_bias": 0.06,
            "sentiment_gate_mult": 0.95,
        },
    },
    "OPTIONS": {
        "aggressive": {
            "weight_mult": {
                "vote_imbalance": 1.10,
                "regime": 1.00,
                "momentum": 1.12,
                "volatility": 1.20,
                "liquidity": 0.90,
                "sentiment": 0.85,
                "session": 0.90,
                "edge": 1.08,
            },
            "voter_weight_mult": {
                "rsi": 1.00,
                "macd": 1.05,
                "bb": 1.05,
                "sr": 0.95,
                "candle": 0.95,
                "stochrsi": 1.10,
                "ema": 1.05,
                "volmom": 1.00,
            },
            "size_mult": 1.22,
            "confidence_bias": 0.04,
            "sentiment_gate_mult": 0.90,
        },
        "balanced": {
            "weight_mult": {},
            "voter_weight_mult": {},
            "size_mult": 1.00,
            "confidence_bias": 0.00,
            "sentiment_gate_mult": 1.00,
        },
        "volatility_seller": {
            "weight_mult": {
                "vote_imbalance": 0.95,
                "regime": 1.00,
                "momentum": 0.92,
                "volatility": 1.32,
                "liquidity": 1.02,
                "sentiment": 0.90,
                "session": 1.00,
                "edge": 1.10,
            },
            "voter_weight_mult": {
                "rsi": 0.95,
                "macd": 0.95,
                "bb": 1.10,
                "sr": 1.10,
                "candle": 0.95,
                "stochrsi": 0.90,
                "ema": 0.95,
                "volmom": 0.95,
            },
            "size_mult": 1.18,
            "confidence_bias": 0.03,
            "sentiment_gate_mult": 0.96,
        },
    },
}


class RLWeightAgent:
    """
    Lightweight online RL agent (contextual bandit style).
    Chooses a weight profile per mode+state and updates expected value from rewards.
    """

    def __init__(
        self,
        state_file: str,
        enabled: bool = True,
        epsilon: float = 0.18,
        min_epsilon: float = 0.05,
        epsilon_decay: float = 0.999,
        learning_rate: float = 0.12,
    ):
        self.enabled = bool(enabled)
        self.state_file = state_file
        self.epsilon = max(0.0, float(epsilon))
        self.min_epsilon = max(0.0, float(min_epsilon))
        self.epsilon_decay = max(0.90, float(epsilon_decay))
        self.learning_rate = max(0.001, min(1.0, float(learning_rate)))
        self._lock = threading.RLock()

        self.profiles = PROFILES
        self.state = {"q": {}, "n": {}, "meta": {"epsilon": self.epsilon, "updated_at": ""}}
        self._load()

    def _default_mode_tables(self, mode: str):
        if mode not in self.state["q"]:
            self.state["q"][mode] = {}
        if mode not in self.state["n"]:
            self.state["n"][mode] = {}

    def _load(self):
        if not self.enabled:
            return
        try:
            if not os.path.exists(self.state_file):
                return
            with open(self.state_file, "r", encoding="utf-8") as f:
                raw = json.load(f)
            if isinstance(raw, dict):
                self.state = raw
                self.epsilon = float(raw.get("meta", {}).get("epsilon", self.epsilon))
        except Exception as e:
            logger.warning("RL agent state load failed: %s", e)

    def _save(self):
        if not self.enabled:
            return
        try:
            os.makedirs(os.path.dirname(self.state_file), exist_ok=True)
            self.state["meta"] = {
                "epsilon": round(self.epsilon, 6),
                "updated_at": datetime.now().isoformat(),
            }
            with open(self.state_file, "w", encoding="utf-8") as f:
                json.dump(self.state, f, indent=2, sort_keys=True)
        except Exception as e:
            logger.warning("RL agent state save failed: %s", e)

    @staticmethod
    def bucketize_features(features: dict) -> str:
        regime = str(features.get("regime", "UNKNOWN")).upper()
        session = str(features.get("session_quality", "LOW")).upper()
        vol = float(features.get("volatility_pct", 0.0) or 0.0)
        sentiment = float(features.get("sentiment_score", 0.0) or 0.0)
        vote = float(features.get("vote_imbalance", 0.0) or 0.0)
        edge = float(features.get("expected_edge_pct", 0.0) or 0.0)

        if vol < 0.04:
            vol_b = "low"
        elif vol < 0.20:
            vol_b = "mid"
        else:
            vol_b = "high"
        if sentiment > 0.10:
            sent_b = "pos"
        elif sentiment < -0.10:
            sent_b = "neg"
        else:
            sent_b = "flat"
        vote_b = "strong" if vote >= 0.5 else ("mid" if vote >= 0.25 else "weak")
        edge_b = "pos" if edge > 0.08 else ("flat" if edge > 0.0 else "neg")
        return f"r={regime}|sess={session}|vol={vol_b}|sent={sent_b}|vote={vote_b}|edge={edge_b}"

    def infer(self, mode: str, features: dict) -> dict:
        mode = str(mode or "SPOT").upper()
        state_key = self.bucketize_features(features or {})
        mode_profiles = self.profiles.get(mode, {})
        profile_ids = list(mode_profiles.keys()) or ["balanced"]
        with self._lock:
            self._default_mode_tables(mode)
            q_mode = self.state["q"][mode].setdefault(state_key, {})
            n_mode = self.state["n"][mode].setdefault(state_key, {})
            for pid in profile_ids:
                q_mode.setdefault(pid, 0.0)
                n_mode.setdefault(pid, 0)

            explore = self.enabled and random.random() < self.epsilon
            if explore:
                profile_id = random.choice(profile_ids)
                decision_type = "explore"
            else:
                # If this exact state is cold/flat, transfer learning from mode-level profile averages.
                if all(abs(float(q_mode.get(pid, 0.0))) < 1e-9 for pid in profile_ids):
                    q_tables = self.state["q"].get(mode, {})
                    n_tables = self.state["n"].get(mode, {})
                    global_scores = {}
                    for pid in profile_ids:
                        weighted_sum = 0.0
                        weight_total = 0.0
                        for state, q_row in q_tables.items():
                            n_row = n_tables.get(state, {})
                            n = float(n_row.get(pid, 0) or 0)
                            if n <= 0:
                                continue
                            weighted_sum += float(q_row.get(pid, 0.0) or 0.0) * n
                            weight_total += n
                        global_scores[pid] = (weighted_sum / weight_total) if weight_total > 0 else 0.0
                    profile_id = max(profile_ids, key=lambda p: float(global_scores.get(p, 0.0)))
                    decision_type = "exploit_global"
                else:
                    profile_id = max(profile_ids, key=lambda p: float(q_mode.get(p, 0.0)))
                    decision_type = "exploit"

            profile = mode_profiles.get(
                profile_id,
                {"weight_mult": {}, "size_mult": 1.0, "confidence_bias": 0.0, "sentiment_gate_mult": 1.0},
            )
            return {
                "mode": mode,
                "state_key": state_key,
                "profile_id": profile_id,
                "weight_mult": dict(profile.get("weight_mult", {})),
                "voter_weight_mult": dict(profile.get("voter_weight_mult", {})),
                "size_mult": float(profile.get("size_mult", 1.0) or 1.0),
                "leverage_mult": float(profile.get("leverage_mult", 1.0) or 1.0),
                "confidence_bias": float(profile.get("confidence_bias", 0.0) or 0.0),
                "sentiment_gate_mult": float(profile.get("sentiment_gate_mult", 1.0) or 1.0),
                "decision_type": decision_type,
                "q_value": float(q_mode.get(profile_id, 0.0)),
                "epsilon": float(self.epsilon),
            }

    def update(self, mode: str, state_key: str, profile_id: str, reward: float):
        if not self.enabled:
            return
        mode = str(mode or "SPOT").upper()
        reward = float(reward or 0.0)
        with self._lock:
            self._default_mode_tables(mode)
            q_mode = self.state["q"][mode].setdefault(state_key, {})
            n_mode = self.state["n"][mode].setdefault(state_key, {})
            prev_q = float(q_mode.get(profile_id, 0.0))
            prev_n = int(n_mode.get(profile_id, 0))
            alpha = self.learning_rate / (1.0 + (prev_n * 0.02))
            new_q = prev_q + alpha * (reward - prev_q)
            q_mode[profile_id] = round(new_q, 8)
            n_mode[profile_id] = prev_n + 1
            self.epsilon = max(self.min_epsilon, self.epsilon * self.epsilon_decay)
            self._save()
            logger.info(
                "RL_UPDATE mode=%s state=%s profile=%s reward=%.5f q_prev=%.5f q_new=%.5f n=%s eps=%.4f",
                mode,
                state_key,
                profile_id,
                reward,
                prev_q,
                new_q,
                prev_n + 1,
                self.epsilon,
            )




class MLXWeightAgent:
    """
    Lightweight MLX-based contextual bandit for per-mode weight profiles.
    Falls back to epsilon-greedy selection and online MSE updates.
    """

    def __init__(
        self,
        state_file: str,
        enabled: bool = True,
        epsilon: float = 0.18,
        min_epsilon: float = 0.05,
        epsilon_decay: float = 0.999,
        learning_rate: float = 0.05,
        hidden_size: int = 16,
    ):
        self.enabled = bool(enabled) and mx is not None
        self.state_file = state_file
        self.epsilon = max(0.0, float(epsilon))
        self.min_epsilon = max(0.0, float(min_epsilon))
        self.epsilon_decay = max(0.90, float(epsilon_decay))
        self.learning_rate = max(0.001, min(1.0, float(learning_rate)))
        self.hidden_size = int(hidden_size or 16)
        self._lock = threading.RLock()

        self.profiles = PROFILES
        self._last_features = {}

        self.models = {}
        self.optimizers = {}
        self._load_state()

    def _load_state(self):
        if not self.enabled:
            return
        try:
            if os.path.exists(self.state_file):
                # Placeholder for future persistence; current model is trained online.
                pass
        except Exception as e:
            logger.warning("MLX RL state load failed: %s", e)

    def _ensure_model(self, mode: str):
        if mode in self.models:
            return
        if not self.enabled:
            return
        profile_count = len(self.profiles.get(mode, {}))
        if profile_count <= 0:
            return

        class MLP(nn.Module):
            def __init__(self, in_dim: int, hidden: int, out_dim: int):
                super().__init__()
                self.fc1 = nn.Linear(in_dim, hidden)
                self.fc2 = nn.Linear(hidden, out_dim)

            def __call__(self, x):
                x = nn.tanh(self.fc1(x))
                return self.fc2(x)

        model = MLP(6, self.hidden_size, profile_count)
        self.models[mode] = model
        self.optimizers[mode] = optim.Adam(learning_rate=self.learning_rate)

    @staticmethod
    def _featurize(features: dict):
        regime_map = {
            "TRENDING_UP": 1.0,
            "TRENDING_DOWN": -1.0,
            "CHOPPY": 0.0,
            "WARMING_UP": 0.0,
            "UNKNOWN": 0.0,
        }
        session_map = {"HIGH": 1.0, "MODERATE": 0.5, "LOW": 0.0}
        regime = regime_map.get(str(features.get("regime", "UNKNOWN")).upper(), 0.0)
        session = session_map.get(str(features.get("session_quality", "LOW")).upper(), 0.0)
        vol = float(features.get("volatility_pct", 0.0) or 0.0)
        sentiment = float(features.get("sentiment_score", 0.0) or 0.0)
        vote = float(features.get("vote_imbalance", 0.0) or 0.0)
        edge = float(features.get("expected_edge_pct", 0.0) or 0.0)
        return [regime, session, vol, sentiment, vote, edge]

    def _select_profile(self, mode: str, q_values: list) -> str:
        names = list(self.profiles.get(mode, {}).keys())
        if not names:
            return "balanced"
        if random.random() < self.epsilon:
            return random.choice(names)
        best_idx = max(range(len(q_values)), key=lambda i: q_values[i])
        return names[best_idx]

    def infer(self, mode: str, features: dict) -> dict:
        if not self.enabled:
            return {
                "profile_id": "balanced",
                "state_key": "",
                "decision_type": "heuristic",
                "weight_mult": {},
                "sentiment_gate_mult": 1.0,
            }
        with self._lock:
            self._ensure_model(mode)
            if mode not in self.models:
                return {
                    "profile_id": "balanced",
                    "state_key": "",
                    "decision_type": "fallback",
                    "weight_mult": {},
                    "sentiment_gate_mult": 1.0,
                }
        feature_vec = self._featurize(features)
        x = mx.array([feature_vec], dtype=mx.float32)
        q = self.models[mode](x)[0]
        q_list = list(map(float, q.tolist()))
        profile_id = self._select_profile(mode, q_list)
        self._last_features[(mode, RLWeightAgent.bucketize_features(features))] = feature_vec
        self.epsilon = max(self.min_epsilon, self.epsilon * self.epsilon_decay)
        profile = self.profiles[mode][profile_id]
        logger.info(
            "MLX_RL_INFER mode=%s profile=%s q=%.6f eps=%.4f",
            mode,
            profile_id,
            max(q_list) if q_list else 0.0,
            self.epsilon,
        )
        return {
            "profile_id": profile_id,
            "state_key": RLWeightAgent.bucketize_features(features),
            "decision_type": "mlx",
            "weight_mult": profile.get("weight_mult", {}),
            "voter_weight_mult": profile.get("voter_weight_mult", {}),
            "size_mult": profile.get("size_mult", 1.0),
            "leverage_mult": profile.get("leverage_mult", 1.0),
            "confidence_bias": profile.get("confidence_bias", 0.0),
            "sentiment_gate_mult": profile.get("sentiment_gate_mult", 1.0),
            "q_value": max(q_list) if q_list else 0.0,
        }

    def update(self, mode: str, state_key: str, profile_id: str, reward: float):
        if not self.enabled:
            return
        with self._lock:
            self._ensure_model(mode)
            model = self.models.get(mode)
            opt = self.optimizers.get(mode)
            if not model or not opt:
                return
            profile_names = list(self.profiles.get(mode, {}).keys())
            if profile_id not in profile_names:
                return
            target_idx = profile_names.index(profile_id)

            feature_vec = self._last_features.get((mode, state_key))
            if feature_vec is None:
                return

            def loss_fn(params):
                model.update(params)
                x = mx.array([feature_vec], dtype=mx.float32)
                preds = model(x)[0]
                pred = preds[target_idx]
                return mx.mean((pred - reward) ** 2)

            loss, grads = mx.value_and_grad(loss_fn)(model.parameters())
            opt.update(model.parameters(), grads)
            mx.eval(model.parameters(), loss)
            logger.info(
                "MLX_RL_UPDATE mode=%s profile=%s reward=%.6f loss=%.6f eps=%.4f",
                mode,
                profile_id,
                float(reward),
                float(loss),
                self.epsilon,
            )
