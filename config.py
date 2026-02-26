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
    MIN_ENSEMBLE_CONFIDENCE = 0.6   # Auto-tuned 19:51   # Auto-tuned 16:28   # Auto-tuned 16:27   # Auto-tuned 09:01   # Auto-tuned 08:41   # Auto-tuned 08:23   # Auto-tuned 08:23   # Auto-tuned 07:38   # Auto-tuned 04:34   # Auto-tuned 04:18   # Auto-tuned 04:18   # Auto-tuned 04:01   # Auto-tuned 03:51   # Auto-tuned 03:34   # Auto-tuned 03:00   # Auto-tuned 01:48   # Auto-tuned 01:48   # Auto-tuned 00:58   # Auto-tuned 23:39   # Auto-tuned 23:03   # Auto-tuned 14:53
    ALGO_SIGNAL_THRESHOLD = 0.10
    EARLY_STOP_LOSS_PCT = 0.01   # Auto-tuned 19:51   # Auto-tuned 19:51   # Auto-tuned 19:50   # Auto-tuned 17:10   # Auto-tuned 17:09   # Auto-tuned 17:05   # Auto-tuned 16:51   # Auto-tuned 16:48   # Auto-tuned 16:47   # Auto-tuned 16:40   # Auto-tuned 16:37   # Auto-tuned 16:29   # Auto-tuned 16:28   # Auto-tuned 15:57   # Auto-tuned 15:35   # Auto-tuned 15:34   # Auto-tuned 14:10   # Auto-tuned 13:50   # Auto-tuned 13:26   # Auto-tuned 11:13   # Auto-tuned 08:53   # Auto-tuned 08:52   # Auto-tuned 08:41   # Auto-tuned 08:23   # Auto-tuned 08:23   # Auto-tuned 07:38   # Auto-tuned 07:22   # Auto-tuned 07:04   # Auto-tuned 05:53   # Auto-tuned 04:35   # Auto-tuned 04:34   # Auto-tuned 04:18   # Auto-tuned 04:18   # Auto-tuned 04:01   # Auto-tuned 03:51   # Auto-tuned 03:34   # Auto-tuned 03:00   # Auto-tuned 02:17   # Auto-tuned 02:16   # Auto-tuned 01:48   # Auto-tuned 01:48   # Auto-tuned 01:15   # Auto-tuned 00:58   # Auto-tuned 00:49   # Auto-tuned 23:39   # Auto-tuned 23:21   # Auto-tuned 23:03   # Auto-tuned 22:46   # Auto-tuned 22:12   # Auto-tuned 21:55   # Auto-tuned 21:53   # Auto-tuned 21:12   # Auto-tuned 21:12   # Auto-tuned 20:54   # Auto-tuned 20:30   # Auto-tuned 18:21   # Auto-tuned 17:20      # Auto-tuned 14:53
    LLM_POLL_INTERVAL_SECONDS = 300  # Ask Claude every 5 mins maximum

    # ── Dynamic Exit Strategy ──
    TAKE_PROFIT_PCT = 0.025   # Auto-tuned 19:51   # Auto-tuned 19:51   # Auto-tuned 19:50   # Auto-tuned 17:10   # Auto-tuned 17:09   # Auto-tuned 17:05   # Auto-tuned 16:51   # Auto-tuned 16:48   # Auto-tuned 16:47   # Auto-tuned 16:40   # Auto-tuned 16:37   # Auto-tuned 16:29   # Auto-tuned 16:28   # Auto-tuned 15:57   # Auto-tuned 15:35   # Auto-tuned 15:34   # Auto-tuned 14:10   # Auto-tuned 13:50   # Auto-tuned 13:26   # Auto-tuned 11:13   # Auto-tuned 08:53   # Auto-tuned 08:52   # Auto-tuned 08:41   # Auto-tuned 08:23   # Auto-tuned 08:23   # Auto-tuned 07:38   # Auto-tuned 07:22   # Auto-tuned 07:04   # Auto-tuned 05:53   # Auto-tuned 04:35   # Auto-tuned 04:34   # Auto-tuned 04:18   # Auto-tuned 04:18   # Auto-tuned 04:01   # Auto-tuned 03:51   # Auto-tuned 03:34   # Auto-tuned 03:00   # Auto-tuned 02:17   # Auto-tuned 02:16   # Auto-tuned 01:48   # Auto-tuned 01:48   # Auto-tuned 01:15   # Auto-tuned 00:58   # Auto-tuned 00:49   # Auto-tuned 23:39   # Auto-tuned 23:21   # Auto-tuned 23:03   # Auto-tuned 22:46   # Auto-tuned 22:12   # Auto-tuned 21:55   # Auto-tuned 21:53   # Auto-tuned 21:12   # Auto-tuned 21:12   # Auto-tuned 20:54   # Auto-tuned 20:30   # Auto-tuned 18:21   # Auto-tuned 17:20          # Auto-tuned 14:53
    TRAILING_STOP_TRIGGER_PCT = 0.003  # At +0.3% profit, activate trailing stop
    TRAILING_STOP_OFFSET_PCT = 0.002   # Trail by 0.2% from peak

    # ── Timeframes ──
    MAX_TRADES_RUN = 1000          # Run indefinitely
    MANDATORY_EXIT_SECONDS = 21600 # 6 hours max hold
    CHECK_INTERVAL_SECONDS = 60
    POLL_INTERVAL_SECONDS = 60
    COOLDOWN_MINUTES = 5           # Wait 5 mins after a trade

    # ── Periodic Self-Improvement ──
    PERIODIC_REVIEW_TRADES = 5     # Trigger a mini-review every 5 closed trades
    PERIODIC_REVIEW_SECONDS = 600  # Also review every 10 min if any new trades

    # ── Position Sizing ──
    MAX_POSITION_SIZE_USDT = 250
    MIN_POSITION_SIZE_USDT = 250
    STOP_LOSS_PCT = 1.0
    MAX_POSITIONS = 1

    # ── Entry Filters ──
    MIN_24H_DIP_PCT = -1.0
    ENTRY_NEAR_LOW_PCT = 0.02
    MOMENTUM_WINDOW_MINS = 60
    MIN_MOMENTUM_PCT = 0.0005

    # ── AWS Bedrock LLM ──
    BEDROCK_MODEL_ID = "us.anthropic.claude-3-5-sonnet-20240620-v1:0"

    # ── API ──
    REST_BASE_URL = "https://api.coindcx.com"

    # ── Asset Focus ──
    BLUE_CHIP_WHITELIST = ["BTCUSDT"]

config = Config()
