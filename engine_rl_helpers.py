from datetime import datetime
import re

from logger import logger
from config import config
from database import save_rl_event
from rl_tuning import get_value as rl_cfg

_NON_ACTIONABLE_SKIP_REASONS = {
    "post_close_cooldown",
    "entry_lockout",
    "duplicate_block",
    "direction_block",
    "pre_policy_reject",
    "post_policy_reject",
}


def _is_non_actionable_skip_reason(reason: str) -> bool:
    reason_norm = str(reason or "").strip().lower()
    if not reason_norm:
        return False
    canonical = re.sub(r"[^a-z0-9]+", "_", reason_norm).strip("_")
    if canonical in _NON_ACTIONABLE_SKIP_REASONS:
        return True
    return any(token in canonical for token in _NON_ACTIONABLE_SKIP_REASONS)


def _canonical_skip_reason(reason: str) -> str:
    reason_norm = str(reason or "").strip().lower()
    if not reason_norm:
        return ""
    return re.sub(r"[^a-z0-9]+", "_", reason_norm).strip("_")


def rl_infer(engine, mode: str, regime: str, session_quality: str, volatility_pct: float, sentiment_score: float, vote_imbalance: float, expected_edge_pct: float) -> dict:
    return engine.rl_agent.infer(
        mode=mode,
        features={
            "regime": regime,
            "session_quality": session_quality,
            "volatility_pct": volatility_pct,
            "sentiment_score": sentiment_score,
            "vote_imbalance": vote_imbalance,
            "expected_edge_pct": expected_edge_pct,
        },
    )


def rl_apply_weight_multipliers(weights: dict, rl_inference: dict) -> dict:
    adjusted = dict(weights or {})
    for key, mult in (rl_inference.get("weight_mult") or {}).items():
        if key in adjusted:
            adjusted[key] = max(0.0, float(adjusted[key]) * float(mult))
    return adjusted


def attach_rl_metadata(engine, mode: str, result: dict, kwargs: dict) -> dict:
    if not isinstance(result, dict):
        return result
    if result.get("rl_profile_id") and result.get("rl_state_key"):
        return result
    rl_context = dict((kwargs or {}).get("rl_context") or {})
    if rl_context.get("profile_id") and rl_context.get("state_key"):
        result["rl_profile_id"] = rl_context.get("profile_id", "")
        result["rl_state_key"] = rl_context.get("state_key", "")
        result["rl_decision_type"] = rl_context.get("decision_type", "")
        return result
    try:
        regime_result = kwargs.get("regime_result") or {}
        session_filt = kwargs.get("session_filt") or {}
        vol_result = kwargs.get("vol_result") or {}
        sentiment_snapshot = kwargs.get("sentiment_snapshot") or {}
        buy_count = int(kwargs.get("buy_count", 0) or 0)
        sell_count = int(kwargs.get("sell_count", 0) or 0)
        vote_imbalance = min(1.0, abs(buy_count - sell_count) / 8.0)
        rl_inf = rl_infer(
            engine,
            mode=mode,
            regime=str(regime_result.get("regime", "UNKNOWN")).upper(),
            session_quality=str(session_filt.get("quality", "LOW")).upper(),
            volatility_pct=float(vol_result.get("volatility_pct", 0.0) or 0.0),
            sentiment_score=float(sentiment_snapshot.get("sentiment_score", 0.0) or 0.0),
            vote_imbalance=vote_imbalance,
            expected_edge_pct=float(kwargs.get("expected_edge_pct", 0.0) or 0.0),
        )
        result["rl_profile_id"] = rl_inf.get("profile_id", "")
        result["rl_state_key"] = rl_inf.get("state_key", "")
        result["rl_decision_type"] = rl_inf.get("decision_type", "")
    except Exception:
        pass
    return result


def rl_loss_penalty_cap(pnl_reward: float = None) -> float:
    if pnl_reward is not None:
        pnl_reward = float(pnl_reward or 0.0)
        if pnl_reward < 0:
            return max(0.0005, abs(pnl_reward))
    return max(0.0005, float(config.EARLY_STOP_LOSS_PCT))


def rl_reward_skip_opportunity(engine, mode: str, policy_eval: dict, expected_edge_pct: float, reason: str, symbol: str = None):
    if not bool(config.ENABLE_RL_WEIGHT_AGENT):
        return
    state_key = str((policy_eval or {}).get("rl_state_key", "") or "")
    profile_id = str((policy_eval or {}).get("rl_profile_id", "") or "")
    if not state_key or not profile_id:
        return
    canonical_reason = _canonical_skip_reason(reason) or str(reason or "")
    if _is_non_actionable_skip_reason(canonical_reason):
        save_rl_event(
            mode=mode,
            profile_id=profile_id,
            state_key=state_key,
            event_type="SKIP_OPPORTUNITY",
            reason=canonical_reason,
            symbol=symbol,
            reward=0.0,
            penalty=0.0,
            raw_penalty=0.0,
            pnl_reward=0.0,
            hold_secs=0.0,
        )
        logger.info(
            "RL_SKIP_NO_PENALTY mode=%s profile=%s reason=%s edge=%.4f",
            mode,
            profile_id,
            canonical_reason,
            float(expected_edge_pct or 0.0),
        )
        return
    edge_norm = max(0.0, float(expected_edge_pct or 0.0)) / max(float(rl_cfg("MIN_EXPECTED_EDGE_PCT")), 0.001)
    mode_key = str(mode or "SPOT").upper()
    mode_updates = int(getattr(engine, "rl_updates_by_mode", {}).get(mode_key, 0) or 0)
    mode_trade_rewards = int(getattr(engine, "rl_trade_rewards_by_mode", {}).get(mode_key, 0) or 0)
    penalty_scale = 1.0
    if mode_updates < int(rl_cfg("RL_SKIP_PENALTY_WARMUP_UPDATES")):
        penalty_scale *= float(rl_cfg("RL_SKIP_PENALTY_WARMUP_SCALE"))
    if mode_trade_rewards < int(rl_cfg("RL_MIN_CLOSED_TRADES_BEFORE_STRICT_GATES")):
        penalty_scale *= float(rl_cfg("RL_SKIP_PENALTY_LOW_TRADE_SCALE"))
    raw_penalty = float(rl_cfg("RL_OPPORTUNITY_COST_PENALTY")) * min(2.5, 0.5 + edge_norm) * max(0.1, penalty_scale)
    # Edge-proportional cap: low-edge skips get small penalties, high-edge
    # skips get larger ones.  This keeps the training signal informative
    # instead of clamping everything to a single value.
    cap_ceiling = float(rl_cfg("RL_SKIP_PENALTY_CAP"))
    cap_floor = float(rl_cfg("RL_SKIP_PENALTY_FLOOR"))
    edge_frac = min(1.0, edge_norm / 2.5)  # 0..1 based on edge quality
    penalty_cap = cap_floor + (cap_ceiling - cap_floor) * edge_frac
    penalty = max(cap_floor, min(abs(raw_penalty), penalty_cap))
    reward = -abs(penalty)
    engine.rl_agent.update(mode, state_key, profile_id, reward, adapt_weights=False)
    if hasattr(engine, "rl_updates_by_mode"):
        engine.rl_updates_by_mode[mode_key] = int(engine.rl_updates_by_mode.get(mode_key, 0) or 0) + 1
    save_rl_event(
        mode=mode,
        profile_id=profile_id,
        state_key=state_key,
        event_type="SKIP_OPPORTUNITY",
        reason=canonical_reason,
        symbol=symbol,
        reward=reward,
        penalty=penalty,
        raw_penalty=raw_penalty,
        pnl_reward=0.0,
        hold_secs=0.0,
    )
    logger.info(
        "RL_SKIP_PENALTY mode=%s profile=%s reason=%s edge=%.4f raw_pen=%.5f cap=%.5f scale=%.3f updates=%s closes=%s reward=%.5f",
        mode,
        profile_id,
        canonical_reason,
        float(expected_edge_pct or 0.0),
        float(raw_penalty),
        float(penalty_cap),
        float(max(0.1, penalty_scale)),
        mode_updates,
        mode_trade_rewards,
        reward,
    )
