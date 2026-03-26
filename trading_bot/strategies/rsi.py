"""RSI mean-reversion strategy."""
import pandas as pd
import numpy as np

from .base import BaseStrategy, Signal, StrategyResult


class RSIStrategy(BaseStrategy):
    """
    RSI mean-reversion:
    - BUY  when RSI crosses up from oversold zone (< oversold threshold)
    - SELL when RSI crosses down from overbought zone (> overbought threshold)
    - Uses 'lookback' confirmation bars to reduce false signals
    """

    name = "rsi"

    def __init__(self, params: dict):
        super().__init__(params)
        self.period = int(params.get("period", 14))
        self.oversold = float(params.get("oversold", 30.0))
        self.overbought = float(params.get("overbought", 70.0))
        self.lookback = int(params.get("lookback", 2))

    def _compute_rsi(self, close: pd.Series) -> pd.Series:
        delta = close.diff()
        gain = delta.where(delta > 0, 0.0)
        loss = -delta.where(delta < 0, 0.0)
        avg_gain = gain.ewm(com=self.period - 1, adjust=False).mean()
        avg_loss = loss.ewm(com=self.period - 1, adjust=False).mean()
        rs = avg_gain / avg_loss.replace(0, np.nan)
        rsi = 100 - (100 / (1 + rs))
        return rsi.fillna(50)

    def generate_signal(self, df: pd.DataFrame) -> StrategyResult:
        min_rows = self.period + self.lookback + 2
        if not self._validate_df(df, min_rows):
            return StrategyResult(Signal.HOLD, reason="Not enough data")

        close = df["close"]
        rsi = self._compute_rsi(close)

        rsi_now = rsi.iloc[-1]
        rsi_prev = rsi.iloc[-2]

        # Check if we were in oversold zone for lookback bars and now rising
        recent_rsi = rsi.iloc[-(self.lookback + 1):-1]
        was_oversold = (recent_rsi < self.oversold).all()
        was_overbought = (recent_rsi > self.overbought).all()

        # Confirmation: now moving back inside normal range
        exiting_oversold = was_oversold and rsi_now > self.oversold
        exiting_overbought = was_overbought and rsi_now < self.overbought

        metadata = {
            "rsi": round(rsi_now, 2),
            "rsi_prev": round(rsi_prev, 2),
            "oversold_threshold": self.oversold,
            "overbought_threshold": self.overbought,
        }

        if exiting_oversold:
            confidence = min(1.0, (self.oversold - rsi.iloc[-(self.lookback + 1)]) / 30)
            return StrategyResult(
                signal=Signal.BUY,
                confidence=max(0.3, confidence),
                reason=f"RSI exiting oversold ({rsi_now:.1f} > {self.oversold})",
                metadata=metadata,
            )

        if exiting_overbought:
            confidence = min(1.0, (rsi.iloc[-(self.lookback + 1)] - self.overbought) / 30)
            return StrategyResult(
                signal=Signal.SELL,
                confidence=max(0.3, confidence),
                reason=f"RSI exiting overbought ({rsi_now:.1f} < {self.overbought})",
                metadata=metadata,
            )

        return StrategyResult(Signal.HOLD, reason=f"RSI neutral ({rsi_now:.1f})", metadata=metadata)
