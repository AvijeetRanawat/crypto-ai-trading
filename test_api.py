from api_client import client
from logger import logger
import json

def test_ticker():
    logger.info("Testing get_market_ticker...")
    tickers = client.get_market_ticker()
    if tickers:
        logger.info(f"Successfully fetched {len(tickers)} markets.")
        # Print a sample
        logger.info(f"Sample Ticker (BTCINR): {next((t for t in tickers if t.get('market') == 'BTCINR'), 'Not Found')}")
    else:
        logger.error("Failed to fetch tickers.")

if __name__ == "__main__":
    test_ticker()
