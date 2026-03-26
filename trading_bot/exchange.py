"""Exchange connector using ccxt. Supports Binance and Kraken."""
import logging
import time
from typing import List, Dict, Optional, Tuple
from datetime import datetime, timezone

import ccxt
import pandas as pd

from .config import ExchangeConfig

logger = logging.getLogger(__name__)


class ExchangeConnector:
    """Unified exchange interface wrapping ccxt."""

    SUPPORTED = {"binance", "kraken", "kucoin", "bybit"}

    def __init__(self, config: ExchangeConfig):
        self.config = config
        self.exchange = self._create_exchange()
        self._markets_loaded = False

    def _create_exchange(self) -> ccxt.Exchange:
        name = self.config.name.lower()
        if name not in self.SUPPORTED:
            raise ValueError(f"Unsupported exchange '{name}'. Choose from: {self.SUPPORTED}")

        exchange_class = getattr(ccxt, name)
        params = {
            "apiKey": self.config.api_key,
            "secret": self.config.api_secret,
            "enableRateLimit": self.config.rate_limit,
            "options": {"defaultType": "spot"},
        }

        if self.config.testnet and name == "binance":
            params["options"]["defaultType"] = "spot"
            params["urls"] = {
                "api": {
                    "public": "https://testnet.binance.vision/api",
                    "private": "https://testnet.binance.vision/api",
                }
            }

        exchange = exchange_class(params)
        logger.info(f"Connected to {name} (testnet={self.config.testnet})")
        return exchange

    def load_markets(self) -> None:
        if not self._markets_loaded:
            self.exchange.load_markets()
            self._markets_loaded = True

    def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str = "1h",
        limit: int = 500,
        since: Optional[int] = None,
    ) -> pd.DataFrame:
        """Fetch OHLCV candle data as a DataFrame."""
        self.load_markets()
        try:
            raw = self.exchange.fetch_ohlcv(symbol, timeframe, since=since, limit=limit)
        except ccxt.NetworkError as e:
            logger.error(f"Network error fetching OHLCV for {symbol}: {e}")
            raise
        except ccxt.ExchangeError as e:
            logger.error(f"Exchange error fetching OHLCV for {symbol}: {e}")
            raise

        df = pd.DataFrame(raw, columns=["timestamp", "open", "high", "low", "close", "volume"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        df.set_index("timestamp", inplace=True)
        df = df.astype(float)
        return df

    def fetch_ticker(self, symbol: str) -> Dict:
        """Get current ticker for a symbol."""
        self.load_markets()
        return self.exchange.fetch_ticker(symbol)

    def fetch_balance(self) -> Dict:
        """Fetch account balance."""
        return self.exchange.fetch_balance()

    def create_market_buy(self, symbol: str, amount: float) -> Dict:
        """Place a market buy order (amount in base currency)."""
        logger.info(f"Market BUY {amount} {symbol}")
        return self.exchange.create_market_buy_order(symbol, amount)

    def create_market_sell(self, symbol: str, amount: float) -> Dict:
        """Place a market sell order (amount in base currency)."""
        logger.info(f"Market SELL {amount} {symbol}")
        return self.exchange.create_market_sell_order(symbol, amount)

    def create_limit_buy(self, symbol: str, amount: float, price: float) -> Dict:
        logger.info(f"Limit BUY {amount} {symbol} @ {price}")
        return self.exchange.create_limit_buy_order(symbol, amount, price)

    def create_limit_sell(self, symbol: str, amount: float, price: float) -> Dict:
        logger.info(f"Limit SELL {amount} {symbol} @ {price}")
        return self.exchange.create_limit_sell_order(symbol, amount, price)

    def cancel_order(self, order_id: str, symbol: str) -> Dict:
        return self.exchange.cancel_order(order_id, symbol)

    def fetch_open_orders(self, symbol: Optional[str] = None) -> List[Dict]:
        return self.exchange.fetch_open_orders(symbol)

    def fetch_order(self, order_id: str, symbol: str) -> Dict:
        return self.exchange.fetch_order(order_id, symbol)

    def get_current_price(self, symbol: str) -> float:
        ticker = self.fetch_ticker(symbol)
        return float(ticker["last"])

    def get_min_order_amount(self, symbol: str) -> float:
        """Get minimum order amount for a symbol."""
        self.load_markets()
        market = self.exchange.markets.get(symbol, {})
        limits = market.get("limits", {})
        amount_min = limits.get("amount", {}).get("min", 0.0)
        return float(amount_min) if amount_min else 0.0

    def get_price_precision(self, symbol: str) -> int:
        """Get price decimal precision for a symbol."""
        self.load_markets()
        market = self.exchange.markets.get(symbol, {})
        return market.get("precision", {}).get("price", 8)

    def get_amount_precision(self, symbol: str) -> int:
        """Get amount decimal precision for a symbol."""
        self.load_markets()
        market = self.exchange.markets.get(symbol, {})
        return market.get("precision", {}).get("amount", 8)


class MockExchange:
    """Mock exchange for paper trading — uses live prices but simulates execution."""

    def __init__(self, real_exchange: ExchangeConnector):
        self.real = real_exchange
        self._order_counter = 0

    def fetch_ohlcv(self, symbol: str, timeframe: str = "1h", limit: int = 500, since=None) -> pd.DataFrame:
        return self.real.fetch_ohlcv(symbol, timeframe, limit, since)

    def fetch_ticker(self, symbol: str) -> Dict:
        return self.real.fetch_ticker(symbol)

    def get_current_price(self, symbol: str) -> float:
        return self.real.get_current_price(symbol)

    def create_market_buy(self, symbol: str, amount: float) -> Dict:
        price = self.get_current_price(symbol)
        self._order_counter += 1
        order = self._make_order("buy", "market", symbol, amount, price)
        logger.info(f"[PAPER] BUY {amount:.6f} {symbol} @ {price:.4f}")
        return order

    def create_market_sell(self, symbol: str, amount: float) -> Dict:
        price = self.get_current_price(symbol)
        self._order_counter += 1
        order = self._make_order("sell", "market", symbol, amount, price)
        logger.info(f"[PAPER] SELL {amount:.6f} {symbol} @ {price:.4f}")
        return order

    def create_limit_buy(self, symbol: str, amount: float, price: float) -> Dict:
        self._order_counter += 1
        order = self._make_order("buy", "limit", symbol, amount, price)
        logger.info(f"[PAPER] Limit BUY {amount:.6f} {symbol} @ {price:.4f}")
        return order

    def create_limit_sell(self, symbol: str, amount: float, price: float) -> Dict:
        self._order_counter += 1
        order = self._make_order("sell", "limit", symbol, amount, price)
        logger.info(f"[PAPER] Limit SELL {amount:.6f} {symbol} @ {price:.4f}")
        return order

    def _make_order(self, side: str, order_type: str, symbol: str, amount: float, price: float) -> Dict:
        return {
            "id": f"paper_{self._order_counter}",
            "symbol": symbol,
            "side": side,
            "type": order_type,
            "amount": amount,
            "price": price,
            "filled": amount,
            "cost": amount * price,
            "status": "closed",
            "timestamp": int(datetime.now(timezone.utc).timestamp() * 1000),
            "datetime": datetime.now(timezone.utc).isoformat(),
        }

    def fetch_balance(self) -> Dict:
        return {}  # Paper trading tracks balance internally in Portfolio

    def get_min_order_amount(self, symbol: str) -> float:
        return self.real.get_min_order_amount(symbol)

    def get_price_precision(self, symbol: str) -> int:
        return self.real.get_price_precision(symbol)

    def get_amount_precision(self, symbol: str) -> int:
        return self.real.get_amount_precision(symbol)

    def load_markets(self) -> None:
        self.real.load_markets()
