"""EMA Crossover strategy: buy when fast EMA crosses above slow EMA."""
import pandas as pd

from .base import BaseStrategy, Signal, StrategyResult


class EMACrossoverStrategy(BaseStrategy):
    """
    Classic EMA crossover:
    - BUY  when fast_ema crosses above slow_ema (golden cross)
    - SELL when fast_ema crosses below slow_ema (death cross)
    - HOLD otherwise

    Optional: signal_ema as a trend filter (only trade in direction of signal_ema slope)
    """

    name = "ema_crossover"

    def __init__(self, params: dict):
        super().__init__(params)
        self.fast = int(params.get("fast_period", 9))
        self.slow = int(params.get("slow_period", 21))
        self.signal = int(params.get("signal_period", 5))

    def generate_signal(self, df: pd.DataFrame) -> StrategyResult:
        min_rows = self.slow + 2
        if not self._validate_df(df, min_rows):
            return StrategyResult(Signal.HOLD, reason="Not enough data")

        close = df["close"]

        ema_fast = close.ewm(span=self.fast, adjust=False).mean()
        ema_slow = close.ewm(span=self.slow, adjust=False).mean()
        ema_signal = close.ewm(span=self.signal, adjust=False).mean()

        # Current and previous values
        fast_now = ema_fast.iloc[-1]
        fast_prev = ema_fast.iloc[-2]
        slow_now = ema_slow.iloc[-1]
        slow_prev = ema_slow.iloc[-2]
        signal_now = ema_signal.iloc[-1]
        price_now = close.iloc[-1]

        # Golden cross: fast crosses above slow
        golden_cross = fast_prev <= slow_prev and fast_now > slow_now
        # Death cross: fast crosses below slow
        death_cross = fast_prev >= slow_prev and fast_now < slow_now

        # Trend filter: price above signal EMA = bullish regime
        bullish_regime = price_now > signal_now

        metadata = {
            "ema_fast": round(fast_now, 4),
            "ema_slow": round(slow_now, 4),
            "ema_signal": round(signal_now, 4),
            "spread_pct": round((fast_now - slow_now) / slow_now * 100, 4),
        }

        if golden_cross and bullish_regime:
            return StrategyResult(
                signal=Signal.BUY,
                confidence=min(1.0, abs(fast_now - slow_now) / slow_now * 50),
                reason=f"Golden cross (EMA{self.fast} > EMA{self.slow})",
                metadata=metadata,
            )

        if death_cross:
            return StrategyResult(
                signal=Signal.SELL,
                confidence=min(1.0, abs(fast_now - slow_now) / slow_now * 50),
                reason=f"Death cross (EMA{self.fast} < EMA{self.slow})",
                metadata=metadata,
            )

        return StrategyResult(Signal.HOLD, reason="No crossover", metadata=metadata)
