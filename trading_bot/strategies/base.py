"""Base strategy class — all strategies inherit from this."""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Optional

import pandas as pd


class Signal(Enum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


@dataclass
class StrategyResult:
    signal: Signal
    confidence: float = 1.0         # 0.0 - 1.0
    reason: str = ""
    metadata: Optional[dict] = None


class BaseStrategy(ABC):
    """
    Abstract base for all trading strategies.
    Each strategy receives OHLCV data and returns a signal.
    """

    name: str = "base"

    def __init__(self, params: dict):
        self.params = params

    @abstractmethod
    def generate_signal(self, df: pd.DataFrame) -> StrategyResult:
        """
        Given a DataFrame of OHLCV data (most recent row = current candle),
        return a StrategyResult with BUY / SELL / HOLD.
        """

    def _validate_df(self, df: pd.DataFrame, min_rows: int) -> bool:
        if df is None or len(df) < min_rows:
            return False
        required = ["open", "high", "low", "close", "volume"]
        return all(c in df.columns for c in required)
