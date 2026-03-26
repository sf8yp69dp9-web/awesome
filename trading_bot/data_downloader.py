"""Historical data downloader for backtesting."""
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd

from .config import BotConfig, ExchangeConfig
from .exchange import ExchangeConnector

logger = logging.getLogger(__name__)


def download_ohlcv(
    exchange_config: ExchangeConfig,
    symbol: str,
    timeframe: str,
    start_date: str,
    end_date: Optional[str] = None,
    cache_dir: str = "trading_bot/data",
) -> pd.DataFrame:
    """
    Download historical OHLCV data from exchange.
    Caches to disk in Parquet format for fast reuse.
    """
    cache_path = _cache_path(cache_dir, symbol, timeframe, start_date, end_date)

    if cache_path.exists():
        logger.info(f"Loading cached data: {cache_path}")
        return pd.read_parquet(cache_path)

    logger.info(f"Downloading {symbol} {timeframe} from {start_date} ...")

    connector = ExchangeConnector(exchange_config)
    connector.load_markets()

    since_ms = int(datetime.strptime(start_date, "%Y-%m-%d").timestamp() * 1000)
    end_ms = (
        int(datetime.strptime(end_date, "%Y-%m-%d").timestamp() * 1000)
        if end_date
        else int(datetime.now().timestamp() * 1000)
    )

    tf_ms = _timeframe_to_ms(timeframe)
    all_candles = []
    current = since_ms

    while current < end_ms:
        try:
            candles = connector.exchange.fetch_ohlcv(symbol, timeframe, since=current, limit=1000)
        except Exception as e:
            logger.error(f"Error fetching candles: {e}")
            time.sleep(5)
            continue

        if not candles:
            break

        all_candles.extend(candles)
        current = candles[-1][0] + tf_ms

        logger.debug(f"Downloaded {len(all_candles)} candles up to {datetime.fromtimestamp(current/1000)}")
        time.sleep(0.5)  # Rate limiting

    if not all_candles:
        raise ValueError(f"No data returned for {symbol} {timeframe} from {start_date}")

    df = pd.DataFrame(all_candles, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    df.set_index("timestamp", inplace=True)
    df = df.astype(float)
    df = df[~df.index.duplicated(keep="first")]
    df.sort_index(inplace=True)

    # Filter to date range
    start_dt = pd.Timestamp(start_date, tz="UTC")
    end_dt = pd.Timestamp(end_date, tz="UTC") if end_date else df.index[-1]
    df = df[start_dt:end_dt]

    # Cache to disk
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(cache_path)
    logger.info(f"Saved {len(df)} candles to {cache_path}")

    return df


def _cache_path(cache_dir: str, symbol: str, timeframe: str, start: str, end: Optional[str]) -> Path:
    safe_symbol = symbol.replace("/", "")
    filename = f"{safe_symbol}_{timeframe}_{start}_{end or 'now'}.parquet"
    return Path(cache_dir) / filename


def _timeframe_to_ms(timeframe: str) -> int:
    mapping = {
        "1m": 60_000, "3m": 180_000, "5m": 300_000, "15m": 900_000,
        "30m": 1_800_000, "1h": 3_600_000, "2h": 7_200_000, "4h": 14_400_000,
        "6h": 21_600_000, "12h": 43_200_000, "1d": 86_400_000,
    }
    return mapping.get(timeframe, 3_600_000)
