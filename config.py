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
    WEIGHT_LLM = 0.4         # Claude gets the most voting power      
    
    # ── Confidence & Risk Gates ──
    MIN_ENSEMBLE_CONFIDENCE = 0.15   # Skip cycle if max(buy,sell) < this
    ALGO_SIGNAL_THRESHOLD = 0.10     # Call Claude only if algo score > this
    EARLY_STOP_LOSS_PCT = 0.0015     # Exit immediately if -0.15% drawdown
    LLM_POLL_INTERVAL_SECONDS = 10   # Call Claude every 10s (was 30s — faster reaction)

    # ── Timeframes ──
    MAX_TRADES_RUN = 100           # Run for a long time
    MANDATORY_EXIT_SECONDS = 300   # 5-min max hold (scalp timeframe)
    CHECK_INTERVAL_SECONDS = 5    
    POLL_INTERVAL_SECONDS = 5     
    COOLDOWN_MINUTES = 0          # Immediate re-entry

    # ── Dynamic Exit Strategy ──
    TAKE_PROFIT_PCT = 0.005          # Exit at +0.5% profit (lock in gains)
    TRAILING_STOP_TRIGGER_PCT = 0.003  # At +0.3% profit, activate trailing stop
    TRAILING_STOP_OFFSET_PCT = 0.002   # Trail by 0.2% from peak

    # ── AWS Bedrock LLM ──
    BEDROCK_MODEL_ID = "us.anthropic.claude-sonnet-4-6"
    
    # ── Position Sizing (Conservative) ──
    MAX_POSITION_SIZE_INR = 20000   # Reduced from 90k to limit downside
    MIN_POSITION_SIZE_INR = 20000   

    TAKE_PROFIT_PCT = 1.0         # Ignored (exit by time instead)
    STOP_LOSS_PCT = 1.0           # Ignored (using EARLY_STOP_LOSS_PCT)
    MAX_POSITIONS = 1             

    # ── Entry Filters ──
    MIN_24H_DIP_PCT = -1.0        
    ENTRY_NEAR_LOW_PCT = 0.02     
    MOMENTUM_WINDOW_MINS = 5      
    MIN_MOMENTUM_PCT = 0.0005     

    # ── API ──
    REST_BASE_URL = "https://api.coindcx.com"

    # ── Asset Focus ──
    BLUE_CHIP_WHITELIST = ["BTCINR"]

config = Config()
