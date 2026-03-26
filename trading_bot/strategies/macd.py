"""MACD momentum strategy."""
import pandas as pd

from .base import BaseStrategy, Signal, StrategyResult


class MACDStrategy(BaseStrategy):
    """
    MACD momentum:
    - BUY  when MACD line crosses above Signal line (histogram turns positive)
    - SELL when MACD line crosses below Signal line (histogram turns negative)
    - Uses Zero-line filter: only BUY when MACD > 0 (uptrend), SELL when MACD < 0 (downtrend)
    """

    name = "macd"

    def __init__(self, params: dict):
        super().__init__(params)
        self.fast = int(params.get("macd_fast", params.get("fast_period", 12)))
        self.slow = int(params.get("macd_slow", params.get("slow_period", 26)))
        self.signal = int(params.get("macd_signal", params.get("signal_period", 9)))

    def _compute_macd(self, close: pd.Series):
        ema_fast = close.ewm(span=self.fast, adjust=False).mean()
        ema_slow = close.ewm(span=self.slow, adjust=False).mean()
        macd_line = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=self.signal, adjust=False).mean()
        histogram = macd_line - signal_line
        return macd_line, signal_line, histogram

    def generate_signal(self, df: pd.DataFrame) -> StrategyResult:
        min_rows = self.slow + self.signal + 2
        if not self._validate_df(df, min_rows):
            return StrategyResult(Signal.HOLD, reason="Not enough data")

        close = df["close"]
        macd_line, signal_line, histogram = self._compute_macd(close)

        macd_now = macd_line.iloc[-1]
        macd_prev = macd_line.iloc[-2]
        sig_now = signal_line.iloc[-1]
        sig_prev = signal_line.iloc[-2]
        hist_now = histogram.iloc[-1]
        hist_prev = histogram.iloc[-2]

        # Bullish crossover: MACD crosses above Signal
        bullish_cross = hist_prev < 0 and hist_now >= 0
        # Bearish crossover: MACD crosses below Signal
        bearish_cross = hist_prev > 0 and hist_now <= 0

        # Zero-line filter: only trade in direction of MACD relative to zero
        above_zero = macd_now > 0
        below_zero = macd_now < 0

        metadata = {
            "macd": round(macd_now, 6),
            "signal": round(sig_now, 6),
            "histogram": round(hist_now, 6),
            "above_zero": above_zero,
        }

        if bullish_cross and above_zero:
            confidence = min(1.0, abs(hist_now) / (abs(macd_now) + 1e-10))
            return StrategyResult(
                signal=Signal.BUY,
                confidence=max(0.3, confidence),
                reason=f"MACD bullish cross (hist={hist_now:.6f}, above zero)",
                metadata=metadata,
            )

        if bearish_cross and below_zero:
            confidence = min(1.0, abs(hist_now) / (abs(macd_now) + 1e-10))
            return StrategyResult(
                signal=Signal.SELL,
                confidence=max(0.3, confidence),
                reason=f"MACD bearish cross (hist={hist_now:.6f}, below zero)",
                metadata=metadata,
            )

        return StrategyResult(Signal.HOLD, reason=f"MACD no signal (hist={hist_now:.6f})", metadata=metadata)
