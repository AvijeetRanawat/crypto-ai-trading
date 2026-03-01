import os
from dotenv import load_dotenv

load_dotenv()


def _env_bool(name: str, default: bool) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except Exception:
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except Exception:
        return default


class Config:
    EXCHANGE = os.getenv("EXCHANGE", "COINDCX").strip().upper()
    if EXCHANGE not in {"COINDCX", "BINANCE"}:
        EXCHANGE = "COINDCX"

    COINDCX_API_KEY = os.getenv("COINDCX_API_KEY", "")
    COINDCX_API_SECRET = os.getenv("COINDCX_API_SECRET")
    BINANCE_API_KEY = os.getenv("BINANCE_API_KEY", "")
    BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET", os.getenv("BINANCE_SECRET_KEY"))

    API_KEY = BINANCE_API_KEY if EXCHANGE == "BINANCE" else COINDCX_API_KEY
    API_SECRET = BINANCE_API_SECRET if EXCHANGE == "BINANCE" else COINDCX_API_SECRET
    TRADING_MODE = os.getenv("TRADING_MODE", "SIMULATION")
    LLM_PROVIDER = os.getenv("LLM_PROVIDER", "BEDROCK").strip().upper()
    if LLM_PROVIDER not in {"BEDROCK", "OPENAI"}:
        LLM_PROVIDER = "BEDROCK"

    # ── Ensemble Weights ──
    WEIGHT_MOMENTUM = _env_float("WEIGHT_MOMENTUM", 0.35)
    WEIGHT_SWING = _env_float("WEIGHT_SWING", 0.35)
    WEIGHT_LLM = _env_float("WEIGHT_LLM", 0.30)

    # ── Confidence & Risk Gates ──
    MIN_ENSEMBLE_CONFIDENCE = _env_float("MIN_ENSEMBLE_CONFIDENCE", 0.65)
    ALGO_SIGNAL_THRESHOLD = _env_float("ALGO_SIGNAL_THRESHOLD", 0.10)
    EARLY_STOP_LOSS_PCT = _env_float("EARLY_STOP_LOSS_PCT", 0.003)
    LLM_POLL_INTERVAL_SECONDS = _env_int("LLM_POLL_INTERVAL_SECONDS", 600)

    # ── Dynamic Exit Strategy ──
    TAKE_PROFIT_PCT = _env_float("TAKE_PROFIT_PCT", 0.006)
    TRAILING_STOP_TRIGGER_PCT = _env_float("TRAILING_STOP_TRIGGER_PCT", 0.004)
    TRAILING_STOP_OFFSET_PCT = _env_float("TRAILING_STOP_OFFSET_PCT", 0.0025)

    # ── Timeframes ──
    MAX_TRADES_RUN = _env_int("MAX_TRADES_RUN", 1000)
    MANDATORY_EXIT_SECONDS = _env_int("MANDATORY_EXIT_SECONDS", 21600)
    CHECK_INTERVAL_SECONDS = _env_int("CHECK_INTERVAL_SECONDS", 60)
    POLL_INTERVAL_SECONDS = _env_int("POLL_INTERVAL_SECONDS", 60)
    COOLDOWN_MINUTES = _env_int("COOLDOWN_MINUTES", 5)

    # ── Runtime Safety / Cost Controls ──
    ENABLE_PERIODIC_REVIEW = _env_bool("ENABLE_PERIODIC_REVIEW", False)
    ENABLE_DISTILLATION = _env_bool("ENABLE_DISTILLATION", False)
    ENABLE_RUNTIME_GIT_PUSH = _env_bool("ENABLE_RUNTIME_GIT_PUSH", False)
    ENABLE_RUNTIME_CONFIG_AUTOTUNE = _env_bool("ENABLE_RUNTIME_CONFIG_AUTOTUNE", False)
    ENABLE_RETROSPECTIVE = _env_bool("ENABLE_RETROSPECTIVE", False)
    ENABLE_META_OPTIMIZER = _env_bool("ENABLE_META_OPTIMIZER", False)
    ENABLE_MISSED_OPPORTUNITY_ANALYZER = _env_bool("ENABLE_MISSED_OPPORTUNITY_ANALYZER", False)
    ENABLE_PYRAMIDING = _env_bool("ENABLE_PYRAMIDING", False)
    ENABLE_END_OF_SESSION_REVIEW = _env_bool("ENABLE_END_OF_SESSION_REVIEW", False)

    # Required by plan
    LLM_DAILY_BUDGET_USD = _env_float("LLM_DAILY_BUDGET_USD", 5.0)
    LLM_MAX_CALLS_PER_HOUR = _env_int("LLM_MAX_CALLS_PER_HOUR", 8)
    MAX_DAILY_DRAWDOWN_USD = _env_float("MAX_DAILY_DRAWDOWN_USD", 25.0)
    ENABLE_SENTIMENT_GATE = _env_bool("ENABLE_SENTIMENT_GATE", True)
    SENTIMENT_MIN_ABS_SCORE = _env_float("SENTIMENT_MIN_ABS_SCORE", 0.08)
    SENTIMENT_DIRECTIONAL_FLOOR = _env_float("SENTIMENT_DIRECTIONAL_FLOOR", 0.05)
    SENTIMENT_MIN_ARTICLES = _env_int("SENTIMENT_MIN_ARTICLES", 3)

    # Additional guardrails for deterministic-first flow
    MIN_NEW_CLOSED_TRADES_FOR_REVIEW = _env_int("MIN_NEW_CLOSED_TRADES_FOR_REVIEW", 10)
    MIN_NEW_CLOSED_TRADES_FOR_DISTILLATION = _env_int("MIN_NEW_CLOSED_TRADES_FOR_DISTILLATION", 10)
    FEE_SLIPPAGE_BUFFER_PCT = _env_float("FEE_SLIPPAGE_BUFFER_PCT", 0.12)
    MIN_EXPECTED_EDGE_PCT = _env_float("MIN_EXPECTED_EDGE_PCT", 0.05)
    MAX_RISK_PER_TRADE_PCT_BALANCE = _env_float("MAX_RISK_PER_TRADE_PCT_BALANCE", 0.10)
    MAX_CONSECUTIVE_LOSSES = _env_int("MAX_CONSECUTIVE_LOSSES", 3)

    # ── Periodic Self-Improvement ──
    PERIODIC_REVIEW_TRADES = _env_int("PERIODIC_REVIEW_TRADES", 5)
    PERIODIC_REVIEW_SECONDS = _env_int("PERIODIC_REVIEW_SECONDS", 600)

    # ── Position Sizing ──
    MAX_POSITION_SIZE_USDT = _env_float("MAX_POSITION_SIZE_USDT", 250)
    MIN_POSITION_SIZE_USDT = _env_float("MIN_POSITION_SIZE_USDT", 125)
    STOP_LOSS_PCT = _env_float("STOP_LOSS_PCT", 1.0)
    MAX_POSITIONS = _env_int("MAX_POSITIONS", 1)

    # ── Entry Filters ──
    MIN_24H_DIP_PCT = _env_float("MIN_24H_DIP_PCT", -1.0)
    ENTRY_NEAR_LOW_PCT = _env_float("ENTRY_NEAR_LOW_PCT", 0.02)
    MOMENTUM_WINDOW_MINS = _env_int("MOMENTUM_WINDOW_MINS", 60)
    MIN_MOMENTUM_PCT = _env_float("MIN_MOMENTUM_PCT", 0.0005)

    # ── AWS Bedrock LLM ──
    BEDROCK_MODEL_ID = os.getenv("BEDROCK_MODEL_ID", "us.anthropic.claude-sonnet-4-6")
    HAIKU_MODEL_ID = os.getenv("HAIKU_MODEL_ID", "us.anthropic.claude-haiku-4-5-20251001-v1:0")
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
    OPENAI_MODEL_ID = os.getenv("OPENAI_MODEL_ID", "gpt-4.1-mini")
    OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    OPENAI_NEWS_SUMMARY_MODEL_ID = os.getenv("OPENAI_NEWS_SUMMARY_MODEL_ID", "gpt-4.1-mini")
    ALPHAVANTAGE_API_KEY = os.getenv("ALPHAVANTAGE_API_KEY", "")
    CRYPTOCOMPARE_API_KEY = os.getenv("CRYPTOCOMPARE_API_KEY", "")

    # Approximate costs (USD / 1M tokens), used for runtime budgeting
    SONNET_INPUT_USD_PER_1M = _env_float("SONNET_INPUT_USD_PER_1M", 3.00)
    SONNET_OUTPUT_USD_PER_1M = _env_float("SONNET_OUTPUT_USD_PER_1M", 15.00)
    HAIKU_INPUT_USD_PER_1M = _env_float("HAIKU_INPUT_USD_PER_1M", 0.80)
    HAIKU_OUTPUT_USD_PER_1M = _env_float("HAIKU_OUTPUT_USD_PER_1M", 4.00)
    OPENAI_INPUT_USD_PER_1M = _env_float("OPENAI_INPUT_USD_PER_1M", 0.40)
    OPENAI_OUTPUT_USD_PER_1M = _env_float("OPENAI_OUTPUT_USD_PER_1M", 1.60)
    OPENAI_NEWS_SUMMARY_INPUT_USD_PER_1M = _env_float("OPENAI_NEWS_SUMMARY_INPUT_USD_PER_1M", OPENAI_INPUT_USD_PER_1M)
    OPENAI_NEWS_SUMMARY_OUTPUT_USD_PER_1M = _env_float("OPENAI_NEWS_SUMMARY_OUTPUT_USD_PER_1M", OPENAI_OUTPUT_USD_PER_1M)

    # ── API ──
    COINDCX_REST_BASE_URL = os.getenv("COINDCX_REST_BASE_URL", "https://api.coindcx.com")
    BINANCE_REST_BASE_URL = os.getenv("BINANCE_REST_BASE_URL", "https://api.binance.us")
    DEFAULT_REST_BASE_URL = BINANCE_REST_BASE_URL if EXCHANGE == "BINANCE" else COINDCX_REST_BASE_URL
    REST_BASE_URL = os.getenv("REST_BASE_URL", DEFAULT_REST_BASE_URL)

    # ── Asset Focus ──
    BLUE_CHIP_WHITELIST = [
        s.strip().upper()
        for s in os.getenv("BLUE_CHIP_WHITELIST", "BTCUSDT,ETHUSDT,SOLUSDT,ETHBTC,SOLBTC,SOLETH").split(",")
        if s.strip()
    ]

    @classmethod
    def is_symbol_allowed(cls, symbol: str) -> bool:
        return str(symbol).upper() in set(cls.BLUE_CHIP_WHITELIST)


config = Config()
