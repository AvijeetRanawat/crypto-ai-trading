import json
import os
import threading
from typing import Any

from config import config

_LOCK = threading.Lock()
_CACHED_MTIME: int | None = None
_OVERRIDES: dict[str, Any] = {}

_PATH = os.path.join(os.path.dirname(__file__), "data", "rl_tuning_overrides.json")

_SPECS: dict[str, dict[str, Any]] = {
    "MIN_EXPECTED_EDGE_PCT": {"type": "float", "default": float(config.MIN_EXPECTED_EDGE_PCT), "min": 0.0, "max": 0.5},
    "RL_OPPORTUNITY_COST_PENALTY": {"type": "float", "default": float(config.RL_OPPORTUNITY_COST_PENALTY), "min": 0.0, "max": 1.0},
    "RL_SKIP_PENALTY_CAP": {"type": "float", "default": float(config.RL_SKIP_PENALTY_CAP), "min": 0.0, "max": 1.0},
    "RL_SKIP_PENALTY_FLOOR": {"type": "float", "default": float(config.RL_SKIP_PENALTY_FLOOR), "min": 0.0, "max": 1.0},
    "RL_OPEN_TRADE_COST_PENALTY": {"type": "float", "default": float(config.RL_OPEN_TRADE_COST_PENALTY), "min": 0.0, "max": 1.0},
    "RL_SKIP_PRESSURE_START": {"type": "int", "default": int(config.RL_SKIP_PRESSURE_START), "min": 0, "max": 1000},
    "RL_SKIP_PRESSURE_STEP": {"type": "float", "default": float(config.RL_SKIP_PRESSURE_STEP), "min": 0.0, "max": 1.0},
    "RL_SKIP_PRESSURE_MAX": {"type": "float", "default": float(config.RL_SKIP_PRESSURE_MAX), "min": 0.0, "max": 1.0},
    "RL_SKIP_PRESSURE_EDGE_MIN": {"type": "float", "default": float(config.RL_SKIP_PRESSURE_EDGE_MIN), "min": 0.0, "max": 1.0},
    "RL_MIN_TRADES_BEFORE_STRICT_GATES": {"type": "int", "default": int(config.RL_MIN_TRADES_BEFORE_STRICT_GATES), "min": 0, "max": 5000},
    "RL_MIN_CLOSED_TRADES_BEFORE_STRICT_GATES": {"type": "int", "default": int(config.RL_MIN_CLOSED_TRADES_BEFORE_STRICT_GATES), "min": 0, "max": 5000},
    "RL_UNDERSAMPLED_MIN_PRO_MULT": {"type": "float", "default": float(config.RL_UNDERSAMPLED_MIN_PRO_MULT), "min": 0.1, "max": 2.0},
    "RL_UNDERSAMPLED_DIR_THRESHOLD_MULT": {"type": "float", "default": float(config.RL_UNDERSAMPLED_DIR_THRESHOLD_MULT), "min": 0.1, "max": 2.0},
    "RL_UNDERSAMPLED_EDGE_THRESHOLD_MULT": {"type": "float", "default": float(config.RL_UNDERSAMPLED_EDGE_THRESHOLD_MULT), "min": 0.1, "max": 2.0},
    "RL_FORCE_ENTRY_ON_SKIP_STREAK": {"type": "bool", "default": bool(config.RL_FORCE_ENTRY_ON_SKIP_STREAK)},
    "RL_FORCE_ENTRY_SKIP_STREAK": {"type": "int", "default": int(config.RL_FORCE_ENTRY_SKIP_STREAK), "min": 0, "max": 5000},
    "RL_FORCE_ENTRY_MAX_TRADES": {"type": "int", "default": int(config.RL_FORCE_ENTRY_MAX_TRADES), "min": 0, "max": 5000},
    "RL_FORCE_ENTRY_MIN_EDGE_PCT": {"type": "float", "default": float(config.RL_FORCE_ENTRY_MIN_EDGE_PCT), "min": 0.0, "max": 1.0},
    "RL_SKIP_PENALTY_WARMUP_UPDATES": {"type": "int", "default": int(config.RL_SKIP_PENALTY_WARMUP_UPDATES), "min": 0, "max": 100000},
    "RL_SKIP_PENALTY_WARMUP_SCALE": {"type": "float", "default": float(config.RL_SKIP_PENALTY_WARMUP_SCALE), "min": 0.0, "max": 5.0},
    "RL_SKIP_PENALTY_LOW_TRADE_SCALE": {"type": "float", "default": float(config.RL_SKIP_PENALTY_LOW_TRADE_SCALE), "min": 0.0, "max": 5.0},
}


def _coerce_value(key: str, value: Any) -> Any:
    spec = _SPECS[key]
    t = spec["type"]
    if t == "bool":
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)

    if t == "int":
        parsed = int(float(value))
    else:
        parsed = float(value)

    min_v = spec.get("min")
    max_v = spec.get("max")
    if min_v is not None:
        parsed = max(min_v, parsed)
    if max_v is not None:
        parsed = min(max_v, parsed)
    return int(parsed) if t == "int" else float(parsed)


def _read_file_overrides() -> dict[str, Any]:
    try:
        with open(_PATH, "r", encoding="utf-8") as f:
            raw = json.load(f)
        if not isinstance(raw, dict):
            return {}
        cleaned: dict[str, Any] = {}
        for key, value in raw.items():
            if key in _SPECS:
                cleaned[key] = _coerce_value(key, value)
        return cleaned
    except Exception:
        return {}


def _ensure_loaded() -> None:
    global _CACHED_MTIME, _OVERRIDES
    with _LOCK:
        try:
            mtime = os.stat(_PATH).st_mtime_ns
        except FileNotFoundError:
            _CACHED_MTIME = None
            _OVERRIDES = {}
            return
        if _CACHED_MTIME == mtime:
            return
        _OVERRIDES = _read_file_overrides()
        _CACHED_MTIME = mtime


def get_value(key: str) -> Any:
    if key not in _SPECS:
        raise KeyError(f"Unsupported RL tuning key: {key}")
    _ensure_loaded()
    return _OVERRIDES.get(key, _SPECS[key]["default"])


def get_all_settings() -> dict[str, Any]:
    _ensure_loaded()
    settings = []
    for key, spec in _SPECS.items():
        overridden = key in _OVERRIDES
        settings.append(
            {
                "key": key,
                "type": spec["type"],
                "default": spec["default"],
                "value": _OVERRIDES[key] if overridden else spec["default"],
                "overridden": overridden,
                "min": spec.get("min"),
                "max": spec.get("max"),
            }
        )
    return {
        "settings": settings,
        "updated_at": str(int(os.path.getmtime(_PATH))) if os.path.exists(_PATH) else "",
    }


def update_settings(values: dict[str, Any]) -> dict[str, Any]:
    global _OVERRIDES, _CACHED_MTIME
    if not isinstance(values, dict):
        raise ValueError("values must be an object")

    _ensure_loaded()
    next_overrides = dict(_OVERRIDES)
    for key, value in values.items():
        if key not in _SPECS:
            continue
        if value is None:
            next_overrides.pop(key, None)
            continue
        next_overrides[key] = _coerce_value(key, value)

    os.makedirs(os.path.dirname(_PATH), exist_ok=True)
    tmp_path = f"{_PATH}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(next_overrides, f, indent=2, sort_keys=True)
    os.replace(tmp_path, _PATH)

    with _LOCK:
        _OVERRIDES = dict(next_overrides)
        try:
            _CACHED_MTIME = os.stat(_PATH).st_mtime_ns
        except FileNotFoundError:
            _CACHED_MTIME = None
    return get_all_settings()
