import requests
import asyncio
import time
from config import config
from logger import logger
import database


def _safe_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


class CoinDCXClient:
    def __init__(self):
        self.exchange = config.EXCHANGE
        self.base_url = config.REST_BASE_URL
        self.latest_prices = {}   # {symbol: price}
        self.ticker_meta = {}     # {symbol: {change_24h, volume, high, low}}
        self.allowed_symbols = set(config.BLUE_CHIP_WHITELIST)
        self.monitored_channels = list(self.allowed_symbols)
        self.headers = {
            'User-Agent': 'curl/8.6.0',
            'Connection': 'close',
        }
        if config.API_KEY:
            if self.exchange == "BINANCE":
                self.headers['X-MBX-APIKEY'] = config.API_KEY
            else:
                self.headers['X-Auth-Apikey'] = config.API_KEY
        self._drift_alerted = set()
        self._binance_us_fallback_applied = False

    def _is_http_451(self, err) -> bool:
        resp = getattr(err, "response", None)
        return bool(resp is not None and int(getattr(resp, "status_code", 0) or 0) == 451)

    def _try_binance_us_fallback(self) -> bool:
        if self.exchange != "BINANCE" or self._binance_us_fallback_applied:
            return False
        old = str(self.base_url or "").rstrip("/")
        if old == "https://api.binance.us":
            self._binance_us_fallback_applied = True
            return False
        self.base_url = "https://api.binance.us"
        self._binance_us_fallback_applied = True
        logger.warning(
            "Received HTTP 451 from Binance endpoint. "
            f"Switching REST base URL from {old} to {self.base_url}."
        )
        return True

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
            except requests.exceptions.HTTPError as e:
                if self._is_http_451(e) and self._try_binance_us_fallback():
                    failed_url = str(getattr(getattr(e, "response", None), "url", "") or "")
                    failed_base = failed_url.split("/api/")[0].rstrip("/") if "/api/" in failed_url else ""
                    if failed_base:
                        url = url.replace(failed_base, self.base_url.rstrip("/"))
                    continue
                logger.error(f"API error: {e}")
                return None
            except Exception as e:
                logger.error(f"API error: {e}")
                return None
        logger.error(f"All retries exhausted for {url}")
        return None

    def get_market_ticker(self):
        """Fetches ticker data for all markets."""
        if self.exchange == "BINANCE":
            result = self._get_with_retry(f"{self.base_url}/api/v3/ticker/24hr")
            return self._normalize_binance_tickers(result)
        result = self._get_with_retry(f"{self.base_url}/exchange/ticker")
        return result if result else []

    def _normalize_binance_tickers(self, tickers):
        if not isinstance(tickers, list):
            return []
        normalized = []
        for t in tickers:
            symbol = str(t.get("symbol", "")).upper()
            if not symbol:
                continue
            normalized.append({
                "market": symbol,
                "last_price": _safe_float(t.get("lastPrice")),
                "high": _safe_float(t.get("highPrice")),
                "low": _safe_float(t.get("lowPrice")),
                "volume": _safe_float(t.get("volume")),
                "change_24_hour": _safe_float(t.get("priceChangePercent")),
                "bid": _safe_float(t.get("bidPrice")),
                "ask": _safe_float(t.get("askPrice")),
                "timestamp": t.get("closeTime"),
            })
        return normalized

    def get_historical_klines(self, symbol, interval='1m', limit=60):
        """Fetches historical k-lines (candles) for immediate warmup."""
        if self.exchange == "BINANCE":
            url = f"{self.base_url}/api/v3/klines?symbol={str(symbol).upper()}&interval={interval}&limit={limit}"
            try:
                resp = requests.get(url, timeout=10, headers=self.headers)
                resp.raise_for_status()
                data = resp.json()
                if data and isinstance(data, list):
                    closes = [
                        _safe_float(k[4])
                        for k in data[-limit:]
                        if isinstance(k, (list, tuple)) and len(k) > 4
                    ]
                    return closes
                return []
            except requests.exceptions.HTTPError as e:
                if self._is_http_451(e) and self._try_binance_us_fallback():
                    return self.get_historical_klines(symbol, interval=interval, limit=limit)
                logger.warning(f"Failed to fetch historical klines for {symbol}: {e}")
                return []
            except Exception as e:
                logger.warning(f"Failed to fetch historical klines for {symbol}: {e}")
                return []

        # CoinDCX pair format example: B-BTC_USDT
        public_url = "https://public.coindcx.com"
        symbol = str(symbol).upper()
        if symbol.endswith("USDT"):
            base = symbol[:-4]
            quote = "USDT"
            market_prefix = "B"
        else:
            base = symbol[:-3]
            quote = symbol[-3:]
            market_prefix = "I"
        fmt_symbol = f"{market_prefix}-{base}_{quote}"
        url = f"{public_url}/market_data/candles?pair={fmt_symbol}&interval={interval}"
        
        # We need raw requests as it's a different base URL
        try:
            resp = requests.get(url, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            if data and isinstance(data, list):
                # Data comes newest first usually, we want chronological order for warmup
                data.sort(key=lambda x: x.get('time', 0))
                # Take only the 'limit' most recent closes
                closes = [float(k.get('close', 0)) for k in data[-limit:]]
                return closes
            return []
        except Exception as e:
            logger.warning(f"Failed to fetch historical klines for {symbol}: {e}")
            return []

    async def connect_ws(self, channels=None):
        """Polls ticker frequently to capture micro-momentum + 24h metadata."""
        if channels:
            requested = {str(s).upper() for s in channels}
            self.monitored_channels = [s for s in requested if s in self.allowed_symbols]
            dropped = sorted(requested - set(self.monitored_channels))
            if dropped:
                logger.warning(f"Dropped non-allowlisted channels: {dropped}")
        logger.info(f"Starting {self.exchange} Price Feed ({config.POLL_INTERVAL_SECONDS}s interval)...")
        while True:
            try:
                tickers = self.get_market_ticker()
                if tickers:
                    # Keep only allowlisted symbols in in-memory state.
                    self.latest_prices = {s: p for s, p in self.latest_prices.items() if s in self.allowed_symbols}
                    self.ticker_meta = {s: m for s, m in self.ticker_meta.items() if s in self.allowed_symbols}
                    for t in tickers:
                        market = str(t.get('market', '')).upper()
                        if market in self._drift_alerted:
                            pass
                        elif market and market not in self.allowed_symbols and market in set(self.monitored_channels):
                            self._drift_alerted.add(market)
                            logger.error(f"Symbol drift detected in feed: {market} not in allowlist {sorted(self.allowed_symbols)}")

                        if market in self.monitored_channels:
                            last_price = float(t.get('last_price', 0))
                            if last_price <= 0:
                                continue
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
