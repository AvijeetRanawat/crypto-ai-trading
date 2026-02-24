import requests
import asyncio
import time
from config import config
from logger import logger
import database

class CoinDCXClient:
    def __init__(self):
        self.base_url = config.REST_BASE_URL
        self.latest_prices = {}   # {symbol: price}
        self.ticker_meta = {}     # {symbol: {change_24h, volume, high, low}}
        self.monitored_channels = []
        self.headers = {
            'User-Agent': 'Mozilla/5.0',
            'Connection': 'close',
            'X-Auth-Apikey': config.API_KEY,
        }

    def _get_with_retry(self, url, retries=3, timeout=20):
        """GET request with exponential backoff."""
        for attempt in range(retries):
            try:
                response = requests.get(url, timeout=timeout, headers=self.headers)
                response.raise_for_status()
                return response.json()
            except (requests.exceptions.ConnectionError,
                    requests.exceptions.ReadTimeout) as e:
                wait = 2 ** attempt
                logger.warning(f"API retry {attempt+1}/{retries}: {type(e).__name__}. Wait {wait}s...")
                time.sleep(wait)
            except Exception as e:
                logger.error(f"API error: {e}")
                return None
        logger.error(f"All retries exhausted for {url}")
        return None

    def get_market_ticker(self):
        """Fetches ticker data for all markets."""
        result = self._get_with_retry(f"{self.base_url}/exchange/ticker")
        return result if result else []

    async def connect_ws(self, channels=None):
        """Polls ticker frequently to capture micro-momentum + 24h metadata."""
        if channels:
            self.monitored_channels = channels
        logger.info("Starting High-Frequency Price Feed (5s interval)...")
        while True:
            try:
                tickers = self.get_market_ticker()
                if tickers:
                    for t in tickers:
                        market = t.get('market')
                        if market in self.monitored_channels:
                            last_price = float(t.get('last_price', 0))
                            self.latest_prices[market] = last_price
                            database.save_price(market, last_price)
                            
                            # ── POPULATE TICKER META (was missing!) ──
                            self.ticker_meta[market] = {
                                'high': float(t.get('high', 0)),
                                'low': float(t.get('low', 0)),
                                'volume': float(t.get('volume', 0)),
                                'change_24h': float(t.get('change_24_hour', 0)),
                                'bid': float(t.get('bid', 0)),
                                'ask': float(t.get('ask', 0)),
                                'timestamp': t.get('timestamp', ''),
                            }
                await asyncio.sleep(config.POLL_INTERVAL_SECONDS)
            except Exception as e:
                logger.error(f"Price feed error: {e}. Retrying in 10s...")
                await asyncio.sleep(10)

    def place_order(self, pair, side, price, quantity):
        if config.TRADING_MODE == "SIMULATION":
            return {"status": "simulated"}
        return None

client = CoinDCXClient()
