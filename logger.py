import logging
import sys


logger = logging.getLogger("CoinDCXAgent")
logger.setLevel(logging.DEBUG)

formatter = logging.Formatter(
    '%(asctime)s | %(levelname)s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

# Console Handler
stdout_handler = logging.StreamHandler(sys.stdout)
stdout_handler.setFormatter(formatter)
logger.addHandler(stdout_handler)

# File Handler (Consolidated)
file_handler = logging.FileHandler("trading.log")
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)

def log_trade(action, symbol, price, amount, reason, trade_id=None):
    trade_info = f"{action} | {symbol} | Price: {price} | Amt: {amount} | Reason: {reason}"
    if trade_id:
        trade_info += f" | ID: {trade_id}"
    logger.info(f"TRADE_LOG: {trade_info}")
