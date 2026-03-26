"""Historical data downloader for backtesting, with offline demo mode."""
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from .config import ExchangeConfig

logger = logging.getLogger(__name__)

# Realistic reference prices per symbol for demo mode
DEMO_PRICES = {
    "BTC/USDT": 42000.0,
    "ETH/USDT": 2200.0,
    "SOL/USDT": 95.0,
    "BNB/USDT": 310.0,
    "BTC/EUR":  38000.0,
    "ETH/EUR":  2000.0,
}


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
    Falls back to realistic simulated data if network is unavailable.
    Caches to disk in Parquet format for fast reuse.
    """
    cache_path = _cache_path(cache_dir, symbol, timeframe, start_date, end_date)

    if cache_path.exists():
        logger.info(f"Loading cached data: {cache_path}")
        return pd.read_parquet(cache_path)

    # Try real download first
    try:
        df = _download_from_exchange(symbol, timeframe, start_date, end_date)
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(cache_path)
        logger.info(f"Saved {len(df)} candles to {cache_path}")
        return df
    except Exception as e:
        logger.warning(f"Network download failed ({e}). Using simulated data for demo.")
        df = generate_demo_ohlcv(symbol, timeframe, start_date, end_date)
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(cache_path)
        logger.info(f"Generated {len(df)} simulated candles for {symbol} → cached at {cache_path}")
        return df


def _download_from_exchange(
    symbol: str,
    timeframe: str,
    start_date: str,
    end_date: Optional[str],
) -> pd.DataFrame:
    import ccxt
    exchange = ccxt.binance({"enableRateLimit": True})
    exchange.load_markets()

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
        candles = exchange.fetch_ohlcv(symbol, timeframe, since=current, limit=1000)
        if not candles:
            break
        all_candles.extend(candles)
        current = candles[-1][0] + tf_ms
        logger.debug(f"Downloaded {len(all_candles)} candles")
        time.sleep(0.3)

    if not all_candles:
        raise ValueError(f"No data returned for {symbol}")

    df = pd.DataFrame(all_candles, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    df.set_index("timestamp", inplace=True)
    df = df.astype(float)
    df = df[~df.index.duplicated(keep="first")]
    df.sort_index(inplace=True)

    start_dt = pd.Timestamp(start_date, tz="UTC")
    end_dt = pd.Timestamp(end_date, tz="UTC") if end_date else df.index[-1]
    return df[start_dt:end_dt]


def generate_demo_ohlcv(
    symbol: str,
    timeframe: str = "1h",
    start_date: str = "2024-01-01",
    end_date: Optional[str] = "2025-01-01",
    seed: Optional[int] = None,
) -> pd.DataFrame:
    """
    Generate realistic OHLCV data using Geometric Brownian Motion.

    Parameters are calibrated to match crypto market characteristics:
    - Annual volatility ~65% (BTC historical average)
    - Slight positive drift (long-term bull trend)
    - Realistic volume with intraday patterns
    - Proper OHLC relationships (no lookahead)
    """
    if seed is None:
        # Deterministic seed per symbol so results are reproducible
        seed = abs(hash(symbol + start_date)) % (2**31)

    rng = np.random.default_rng(seed)

    tf_hours = _timeframe_to_hours(timeframe)
    start_dt = pd.Timestamp(start_date, tz="UTC")
    end_dt = pd.Timestamp(end_date or "2025-01-01", tz="UTC")

    freq_map = {
        "1m": "1min", "3m": "3min", "5m": "5min", "15m": "15min",
        "30m": "30min", "1h": "1h", "2h": "2h", "4h": "4h",
        "6h": "6h", "12h": "12h", "1d": "1D",
    }
    freq = freq_map.get(timeframe, "1h")
    timestamps = pd.date_range(start_dt, end_dt, freq=freq, tz="UTC")[:-1]
    n = len(timestamps)

    # GBM parameters — annualized, scaled to timeframe
    hours_per_year = 8760.0
    annual_vol = 0.65      # 65% annual volatility (crypto)
    annual_drift = 0.40    # 40% annual drift (mild bull market)

    dt = tf_hours / hours_per_year
    vol = annual_vol * np.sqrt(dt)
    drift = (annual_drift - 0.5 * annual_vol**2) * dt

    # Simulate close prices via GBM
    log_returns = drift + vol * rng.standard_normal(n)

    # Add occasional regime changes (bull/bear phases)
    regime = np.ones(n)
    phase_len = int(n * 0.15)  # ~15% phases
    for _ in range(rng.integers(3, 7)):
        start_idx = rng.integers(0, n - phase_len)
        regime[start_idx:start_idx + phase_len] *= rng.choice([-2.0, 0.3])
    log_returns *= (1 + regime * 0.3)

    base_price = DEMO_PRICES.get(symbol, 1000.0)
    closes = base_price * np.exp(np.cumsum(log_returns))

    # Generate OHLC from close using intrabar volatility
    intrabar_vol = vol * 0.5
    highs = closes * np.exp(np.abs(rng.normal(0, intrabar_vol, n)))
    lows = closes * np.exp(-np.abs(rng.normal(0, intrabar_vol, n)))
    opens = np.roll(closes, 1)
    opens[0] = base_price

    # Ensure OHLC consistency
    highs = np.maximum(highs, np.maximum(opens, closes))
    lows = np.minimum(lows, np.minimum(opens, closes))

    # Volume: log-normal with daily cycle pattern
    hour_of_day = timestamps.hour
    volume_cycle = 1.0 + 0.5 * np.sin(2 * np.pi * (hour_of_day - 14) / 24)  # Peak at 14:00 UTC
    base_volume = DEMO_PRICES.get(symbol, 1000.0) * 50  # Scale volume to price
    volumes = base_volume * volume_cycle * np.exp(rng.normal(0, 0.5, n))
    volumes = np.maximum(volumes, 1.0)

    df = pd.DataFrame({
        "open":   opens,
        "high":   highs,
        "low":    lows,
        "close":  closes,
        "volume": volumes,
    }, index=timestamps)

    logger.info(
        f"[DEMO] Generated {len(df)} {timeframe} candles for {symbol} "
        f"({start_date} → {end_date}) | "
        f"Price range: {closes.min():.0f} – {closes.max():.0f}"
    )
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


def _timeframe_to_hours(timeframe: str) -> float:
    mapping = {
        "1m": 1/60, "3m": 3/60, "5m": 5/60, "15m": 15/60,
        "30m": 0.5, "1h": 1.0, "2h": 2.0, "4h": 4.0,
        "6h": 6.0, "12h": 12.0, "1d": 24.0,
    }
    return mapping.get(timeframe, 1.0)
