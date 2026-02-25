import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    API_KEY = os.getenv("COINDCX_API_KEY", "07b543d42e053db808c3397776133913eba2f9cfea7c9f0b")
    API_SECRET = os.getenv("COINDCX_API_SECRET")
    TRADING_MODE = os.getenv("TRADING_MODE", "SIMULATION")

    # ── Ensemble Weights ──
    WEIGHT_MOMENTUM = 0.3
    WEIGHT_SWING = 0.3
    WEIGHT_LLM = 0.4              # Claude gets the most voting power

    # ── Confidence & Risk Gates ──
    MIN_ENSEMBLE_CONFIDENCE = 0.5   # Auto-tuned 03:51   # Auto-tuned 03:34   # Auto-tuned 03:00   # Auto-tuned 01:48   # Auto-tuned 01:48   # Auto-tuned 00:58   # Auto-tuned 23:39   # Auto-tuned 23:03   # Auto-tuned 14:53
    ALGO_SIGNAL_THRESHOLD = 0.10
    EARLY_STOP_LOSS_PCT = 0.003   # Auto-tuned 03:51   # Auto-tuned 03:34   # Auto-tuned 03:00   # Auto-tuned 02:17   # Auto-tuned 02:16   # Auto-tuned 01:48   # Auto-tuned 01:48   # Auto-tuned 01:15   # Auto-tuned 00:58   # Auto-tuned 00:49   # Auto-tuned 23:39   # Auto-tuned 23:21   # Auto-tuned 23:03   # Auto-tuned 22:46   # Auto-tuned 22:12   # Auto-tuned 21:55   # Auto-tuned 21:53   # Auto-tuned 21:12   # Auto-tuned 21:12   # Auto-tuned 20:54   # Auto-tuned 20:30   # Auto-tuned 18:21   # Auto-tuned 17:20      # Auto-tuned 14:53
    LLM_POLL_INTERVAL_SECONDS = 10   # Call Claude every 10s

    # ── Dynamic Exit Strategy ──
    TAKE_PROFIT_PCT = 0.005   # Auto-tuned 03:51   # Auto-tuned 03:34   # Auto-tuned 03:00   # Auto-tuned 02:17   # Auto-tuned 02:16   # Auto-tuned 01:48   # Auto-tuned 01:48   # Auto-tuned 01:15   # Auto-tuned 00:58   # Auto-tuned 00:49   # Auto-tuned 23:39   # Auto-tuned 23:21   # Auto-tuned 23:03   # Auto-tuned 22:46   # Auto-tuned 22:12   # Auto-tuned 21:55   # Auto-tuned 21:53   # Auto-tuned 21:12   # Auto-tuned 21:12   # Auto-tuned 20:54   # Auto-tuned 20:30   # Auto-tuned 18:21   # Auto-tuned 17:20          # Auto-tuned 14:53
    TRAILING_STOP_TRIGGER_PCT = 0.003  # At +0.3% profit, activate trailing stop
    TRAILING_STOP_OFFSET_PCT = 0.002   # Trail by 0.2% from peak

    # ── Timeframes ──
    MAX_TRADES_RUN = 1000          # Run indefinitely
    MANDATORY_EXIT_SECONDS = 300   # 5-min max hold
    CHECK_INTERVAL_SECONDS = 5
    POLL_INTERVAL_SECONDS = 5
    COOLDOWN_MINUTES = 0           # Immediate re-entry

    # ── Periodic Self-Improvement ──
    PERIODIC_REVIEW_TRADES = 5     # Trigger a mini-review every 5 closed trades
    PERIODIC_REVIEW_SECONDS = 600  # Also review every 10 min if any new trades

    # ── Position Sizing ──
    MAX_POSITION_SIZE_INR = 20000
    MIN_POSITION_SIZE_INR = 20000
    STOP_LOSS_PCT = 1.0
    MAX_POSITIONS = 1

    # ── Entry Filters ──
    MIN_24H_DIP_PCT = -1.0
    ENTRY_NEAR_LOW_PCT = 0.02
    MOMENTUM_WINDOW_MINS = 5
    MIN_MOMENTUM_PCT = 0.0005

    # ── AWS Bedrock LLM ──
    BEDROCK_MODEL_ID = "us.anthropic.claude-sonnet-4-6"

    # ── API ──
    REST_BASE_URL = "https://api.coindcx.com"

    # ── Asset Focus ──
    BLUE_CHIP_WHITELIST = ["BTCINR"]

config = Config()
