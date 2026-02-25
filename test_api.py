from api_client import client
from logger import logger


def test_ticker():
    logger.info("Testing get_market_ticker...")
    tickers = client.get_market_ticker()
    if tickers:
        logger.info(f"Successfully fetched {len(tickers)} markets.")
        # Print a sample
        logger.info(f"Sample Ticker (BTCUSDT): {next((t for t in tickers if t.get('market') == 'BTCUSDT'), 'Not Found')}")
    else:
        logger.error("Failed to fetch tickers.")

if __name__ == "__main__":
    test_ticker()
