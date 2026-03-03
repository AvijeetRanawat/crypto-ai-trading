import json
import os
import random
import threading
import time
import atexit
from datetime import datetime

import config
from logger import logger

_ENABLE_MLX_ENV = str(os.getenv("ENABLE_MLX_RL_AGENT", "false")).strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
_DISABLE_MLX_ENV = str(os.getenv("DISABLE_MLX", "0")).strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}

if _ENABLE_MLX_ENV and not _DISABLE_MLX_ENV:
    try:
        import mlx.core as mx
        import mlx.nn as nn
        import mlx.optimizers as optim
    except Exception:
        mx = None
        nn = None
        optim = None
else:
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
        self._unsaved_updates = 0
        self._last_save_monotonic = time.monotonic()

        self.profiles = PROFILES
        self.state = {"q": {}, "n": {}, "meta": {"epsilon": self.epsilon, "updated_at": ""}}
        self._load()
        atexit.register(self.flush)

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
            self._last_save_monotonic = time.monotonic()
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

            # ── Persistent learned weights: accumulate via profile-conditioned gradient ──
            learned = self._get_or_init_learned_weights(mode, state_key, profile_id)
            adapted_weights = dict(learned.get("wm", {})) or dict(profile.get("weight_mult", {}))
            adapted_voter_weights = dict(learned.get("vm", {})) or dict(profile.get("voter_weight_mult", {}))

            # ── Detailed RL infer log ──
            q_summary = {pid: round(float(q_mode.get(pid, 0.0)), 5) for pid in profile_ids}
            n_summary = {pid: int(n_mode.get(pid, 0) or 0) for pid in profile_ids}
            best_pid = max(profile_ids, key=lambda p: float(q_mode.get(p, 0.0)))
            logger.info(
                "RL_INFER mode=%s  decision=%s  chosen=%s  eps=%.4f\n"
                "  state     : %s\n"
                "  q_values  : %s\n"
                "  n_visits  : %s\n"
                "  best_q_pid: %s (q=%+.5f)  size_mult=%.2f  conf_bias=%+.3f",
                mode, decision_type, profile_id, float(self.epsilon),
                state_key,
                {k: f"{v:+.5f}" for k, v in q_summary.items()},
                n_summary,
                best_pid, float(q_mode.get(best_pid, 0.0)),
                float(profile.get("size_mult", 1.0)),
                float(profile.get("confidence_bias", 0.0)),
            )

            return {
                "mode": mode,
                "state_key": state_key,
                "profile_id": profile_id,
                "weight_mult": adapted_weights,
                "voter_weight_mult": adapted_voter_weights,
                "size_mult": float(profile.get("size_mult", 1.0) or 1.0),
                "leverage_mult": float(profile.get("leverage_mult", 1.0) or 1.0),
                "confidence_bias": float(profile.get("confidence_bias", 0.0) or 0.0),
                "sentiment_gate_mult": float(profile.get("sentiment_gate_mult", 1.0) or 1.0),
                "decision_type": decision_type,
                "q_value": float(q_mode.get(profile_id, 0.0)),
                "epsilon": float(self.epsilon),
            }

    def _get_or_init_learned_weights(self, mode: str, state_key: str, profile_id: str) -> dict:
        """
        Get persistently stored learned weights for (mode, state_key).
        Initializes from selected profile's defaults on first access.
        All weight keys from every profile in this mode are included so that
        cross-profile learning can happen (each profile proposes direction
        for every key).
        """
        w_table = self.state.setdefault("w", {}).setdefault(mode, {})
        entry = w_table.get(state_key)
        if entry is not None:
            return entry

        # Collect the union of weight keys across all profiles for this mode
        all_wm_keys: set = set()
        all_vm_keys: set = set()
        for pdata in self.profiles.get(mode, {}).values():
            all_wm_keys.update(pdata.get("weight_mult", {}).keys())
            all_vm_keys.update(pdata.get("voter_weight_mult", {}).keys())

        # Seed from selected profile; missing keys default to 1.0 (neutral)
        selected = self.profiles.get(mode, {}).get(profile_id, {})
        wm = {k: round(float(selected.get("weight_mult", {}).get(k, 1.0)), 4) for k in all_wm_keys}
        vm = {k: round(float(selected.get("voter_weight_mult", {}).get(k, 1.0)), 4) for k in all_vm_keys}

        entry = {"wm": wm, "vm": vm, "reward_ema": 0.0}
        w_table[state_key] = entry
        return entry

    def _update_learned_weights(self, mode: str, state_key: str, profile_id: str, reward: float, prev_n: int):
        """
        Update persistently stored learned weights using profile-conditioned gradient.

        Each profile's weight_mult values act as *directional proposals*.  When a
        profile is selected and the resulting reward exceeds the running baseline
        (positive advantage), learned weights are nudged toward that profile's
        proposals.  Negative advantage nudges them away.

        This replaces the old _adapt_weight_mult which produced ~0.01% changes
        because it derived adjustments from near-zero Q-value differences.
        The new approach:
          1. Stores weights persistently — changes accumulate.
          2. Uses normalized reward advantage (~0.1–1.0 range) instead of raw
             Q-value deltas (~0.001).
          3. Profile proposals provide per-key gradient direction automatically.
          4. Exploration noise (30% chance per update, decaying with evidence)
             lets weights explore directions not covered by any profile.
        """
        if prev_n < 1:
            return  # Need at least one prior visit before adapting

        w_table = self.state.setdefault("w", {}).setdefault(mode, {})
        entry = w_table.get(state_key)
        if entry is None:
            return

        # ── Update reward baseline (EMA) ──
        baseline = float(entry.get("reward_ema", 0.0) or 0.0)
        ema_decay = 0.95
        new_baseline = baseline * ema_decay + reward * (1 - ema_decay)
        entry["reward_ema"] = round(new_baseline, 8)

        # ── Normalized advantage ──
        advantage = (reward - baseline) / max(abs(baseline), 0.002)
        advantage = max(-1.0, min(1.0, advantage))

        if abs(advantage) < 0.01:
            return  # Negligible signal — skip to avoid noise accumulation

        # ── Profile-conditioned gradient update ──
        profile = self.profiles.get(mode, {}).get(profile_id, {})
        weight_lr = float(getattr(config, "RL_WEIGHT_ADAPT_LR", 0.15))

        for w_key, p_key in (("wm", "weight_mult"), ("vm", "voter_weight_mult")):
            profile_w = profile.get(p_key, {})
            learned_w = entry.get(w_key, {})
            if not learned_w:
                continue

            # Ensure all profile keys exist in learned weights
            for key in profile_w:
                if key not in learned_w:
                    learned_w[key] = round(float(profile_w[key]), 4)

            for key in list(learned_w.keys()):
                current = float(learned_w[key])
                profile_target = float(profile_w.get(key, 1.0))
                if advantage > 0:
                    # Positive: reinforce profile's bets — move toward profile target
                    diff = profile_target - current
                else:
                    # Negative: dampen toward neutral (1.0)
                    diff = 1.0 - current
                adjustment = weight_lr * abs(advantage) * diff
                learned_w[key] = round(max(0.5, min(2.0, current + adjustment)), 4)

            # Exploration noise: 30% chance, decays with evidence
            if random.random() < 0.3:
                noise_std = 0.015 / (1.0 + prev_n * 0.005)
                for key in learned_w:
                    noisy = float(learned_w[key]) + random.gauss(0, noise_std)
                    learned_w[key] = round(max(0.5, min(2.0, noisy)), 4)

    def update(
        self,
        mode: str,
        state_key: str,
        profile_id: str,
        reward: float,
        adapt_weights: bool = True,
    ):
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

            # ── Epsilon warm-restart: if all Q-values for this mode are ≤ 0
            # and we have 100+ updates, the agent has never seen a trade reward.
            # Boost epsilon to re-explore instead of exploiting worthless Q-values.
            all_q_neg = all(
                float(q_row.get(pid, 0.0) or 0.0) <= 0
                for q_row in self.state["q"].get(mode, {}).values()
                for pid in q_row
            )
            mode_total_n = sum(
                sum(v.values()) for v in self.state["n"].get(mode, {}).values()
            )
            if all_q_neg and mode_total_n > 100:
                # Keep epsilon at a meaningful exploration level
                self.epsilon = max(self.epsilon, 0.15)
            else:
                self.epsilon = max(self.min_epsilon, self.epsilon * self.epsilon_decay)

            # Skip/opportunity penalties should still train Q-values, but they
            # should not directly mutate learned multipliers. This keeps weight
            # adaptation tied to realized trade outcomes.
            if bool(adapt_weights):
                self._update_learned_weights(mode, state_key, profile_id, reward, prev_n)

            # Persist aggressively during early learning so short runs don't lose RL state.
            self._unsaved_updates += 1
            total_n_mode = sum(
                int(sum(v.values())) for v in self.state["n"].get(mode, {}).values() if v
            )
            save_threshold = 1 if total_n_mode < 25 else 10
            if self._unsaved_updates >= save_threshold or (time.monotonic() - self._last_save_monotonic) >= 30.0:
                self._save()
                self._unsaved_updates = 0
            q_all = {
                pid: round(float(self.state["q"][mode].get(state_key, {}).get(pid, 0.0)), 5)
                for pid in self.profiles.get(mode, {}).keys()
            }
            logger.info(
                "RL_UPDATE mode=%s  profile=%s  reward=%+.5f  q: %.5f → %.5f (δ%+.5f)  n=%d  eps=%.4f\n"
                "  state        : %s\n"
                "  all_q        : %s\n"
                "  mode_total_n : %d",
                mode, profile_id, reward, prev_q, new_q, new_q - prev_q, prev_n + 1, self.epsilon,
                state_key,
                {k: f"{v:+.5f}" for k, v in q_all.items()},
                total_n_mode,
            )

    def flush(self):
        """Force-save any pending unsaved updates."""
        with self._lock:
            if self._unsaved_updates > 0:
                self._save()
                self._unsaved_updates = 0




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
                with open(self.state_file, "r") as f:
                    data = json.load(f)
                mlx_meta = data.get("mlx_meta", {})
                self.epsilon = float(mlx_meta.get("epsilon", self.epsilon))
                logger.info("MLX RL state loaded: epsilon=%.4f", self.epsilon)
        except Exception as e:
            logger.warning("MLX RL state load failed: %s", e)

    def _save_state(self):
        """Persist MLX agent metadata alongside the tabular RL weights file."""
        if not self.enabled:
            return
        try:
            data = {}
            if os.path.exists(self.state_file):
                with open(self.state_file, "r") as f:
                    data = json.load(f)
            data["mlx_meta"] = {
                "epsilon": round(self.epsilon, 6),
            }
            tmp = self.state_file + ".tmp"
            with open(tmp, "w") as f:
                json.dump(data, f, indent=2)
            os.replace(tmp, self.state_file)
        except Exception as e:
            logger.warning("MLX RL state save failed: %s", e)

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
            # Batched persistence: save every 10 updates
            self._mlx_unsaved = getattr(self, '_mlx_unsaved', 0) + 1
            if self._mlx_unsaved >= 10:
                self._save_state()
                self._mlx_unsaved = 0
            logger.info(
                "MLX_RL_UPDATE mode=%s profile=%s reward=%.6f loss=%.6f eps=%.4f",
                mode,
                profile_id,
                float(reward),
                float(loss),
                self.epsilon,
            )
