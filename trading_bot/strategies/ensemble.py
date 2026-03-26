"""Ensemble strategy: all 3 strategies vote, majority wins."""
import logging
import pandas as pd

from .base import BaseStrategy, Signal, StrategyResult
from .ema_crossover import EMACrossoverStrategy
from .rsi import RSIStrategy
from .macd import MACDStrategy

logger = logging.getLogger(__name__)


class EnsembleStrategy(BaseStrategy):
    """
    Combines EMA Crossover, RSI, and MACD via majority voting.

    Rules:
    - BUY  if 2 or 3 strategies say BUY
    - SELL if 2 or 3 strategies say SELL
    - HOLD otherwise (split vote)

    Confidence = fraction of strategies agreeing (0.67 or 1.0).
    """

    name = "ensemble"

    def __init__(self, params: dict):
        super().__init__(params)
        self.strategies = [
            EMACrossoverStrategy(params),
            RSIStrategy(params),
            MACDStrategy(params),
        ]

    def generate_signal(self, df: pd.DataFrame) -> StrategyResult:
        if not self._validate_df(df, 50):
            return StrategyResult(Signal.HOLD, reason="Not enough data")

        results = [s.generate_signal(df) for s in self.strategies]
        names = ["EMA", "RSI", "MACD"]

        buys  = [r for r in results if r.signal == Signal.BUY]
        sells = [r for r in results if r.signal == Signal.SELL]

        vote_log = " | ".join(
            f"{names[i]}:{results[i].signal.value.upper()}"
            for i in range(len(self.strategies))
        )
        logger.debug(f"Ensemble votes: {vote_log}")

        if len(buys) >= 2:
            reasons = [r.reason for r in buys]
            return StrategyResult(
                signal=Signal.BUY,
                confidence=len(buys) / len(self.strategies),
                reason=f"Ensemble BUY ({len(buys)}/3): {'; '.join(reasons)}",
                metadata={"votes": vote_log, "buy_count": len(buys)},
            )

        if len(sells) >= 2:
            reasons = [r.reason for r in sells]
            return StrategyResult(
                signal=Signal.SELL,
                confidence=len(sells) / len(self.strategies),
                reason=f"Ensemble SELL ({len(sells)}/3): {'; '.join(reasons)}",
                metadata={"votes": vote_log, "sell_count": len(sells)},
            )

        return StrategyResult(
            Signal.HOLD,
            reason=f"Split vote — no majority ({vote_log})",
            metadata={"votes": vote_log},
        )
