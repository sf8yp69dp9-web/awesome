"""Ensemble strategy: all 3 strategies vote, majority wins.
Filters: ADX regime gate + volume confirmation before any vote is counted.
"""
import logging
import numpy as np
import pandas as pd

from .base import BaseStrategy, Signal, StrategyResult
from .ema_crossover import EMACrossoverStrategy
from .rsi import RSIStrategy
from .macd import MACDStrategy

logger = logging.getLogger(__name__)


class EnsembleStrategy(BaseStrategy):
    """
    Combines EMA Crossover, RSI, and MACD via majority voting with pre-filters.

    Pipeline:
    1. ADX regime filter  — skip if market is ranging (ADX < threshold)
    2. Volume filter      — skip if current volume < multiplier × avg volume
    3. Strategy votes     — BUY if 2/3 agree, SELL if 2/3 agree, else HOLD

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

    # ------------------------------------------------------------------
    # Filters
    # ------------------------------------------------------------------

    def _compute_adx(self, df: pd.DataFrame, period: int = 14) -> float:
        """Compute ADX from the last (3×period + 10) bars only — fast path for live use."""
        # Use only the tail we need for a stable Wilder-smoothed ADX
        lookback = period * 3 + 10
        df = df.iloc[-lookback:] if len(df) > lookback else df

        high = df["high"].values
        low  = df["low"].values
        close = df["close"].values

        n = len(high)
        tr_arr = np.empty(n)
        pdm_arr = np.empty(n)
        mdm_arr = np.empty(n)
        tr_arr[0] = pdm_arr[0] = mdm_arr[0] = 0.0

        for i in range(1, n):
            tr_arr[i] = max(
                high[i] - low[i],
                abs(high[i] - close[i - 1]),
                abs(low[i]  - close[i - 1]),
            )
            up   = high[i] - high[i - 1]
            down = low[i - 1] - low[i]
            pdm_arr[i] = up   if (up > down and up > 0)   else 0.0
            mdm_arr[i] = down if (down > up and down > 0) else 0.0

        alpha = 1.0 / period
        tr_s  = pd.Series(tr_arr).ewm(alpha=alpha, adjust=False).mean().values
        pdi   = 100 * pd.Series(pdm_arr).ewm(alpha=alpha, adjust=False).mean().values / np.where(tr_s == 0, np.nan, tr_s)
        mdi   = 100 * pd.Series(mdm_arr).ewm(alpha=alpha, adjust=False).mean().values / np.where(tr_s == 0, np.nan, tr_s)
        with np.errstate(invalid="ignore", divide="ignore"):
            dx = 100 * np.abs(pdi - mdi) / np.where((pdi + mdi) == 0, np.nan, pdi + mdi)
        adx = pd.Series(np.nan_to_num(dx)).ewm(alpha=alpha, adjust=False).mean()
        return float(adx.iloc[-1])

    def _volume_confirmed(self, df: pd.DataFrame, window: int = 20) -> bool:
        """Return True if current bar volume exceeds multiplier × recent average."""
        if "volume" not in df.columns or len(df) < window + 2:
            return True  # can't check → pass through
        vol = df["volume"]
        avg = vol.iloc[-(window + 1):-1].mean()
        if avg == 0:
            return True
        multiplier = self.params.get("volume_multiplier", 1.5)
        return float(vol.iloc[-1]) >= avg * multiplier

    # ------------------------------------------------------------------
    # Signal generation
    # ------------------------------------------------------------------

    def generate_signal(self, df: pd.DataFrame) -> StrategyResult:
        if not self._validate_df(df, 50):
            return StrategyResult(Signal.HOLD, reason="Not enough data")

        adx_period    = int(self.params.get("adx_period", 14))
        adx_threshold = float(self.params.get("adx_threshold", 25.0))
        vol_window    = int(self.params.get("volume_window", 20))

        # --- Filter 1: ADX regime gate ---
        try:
            adx_value = self._compute_adx(df, adx_period)
        except Exception:
            adx_value = 99.0  # if calculation fails, don't filter

        if adx_value < adx_threshold:
            return StrategyResult(
                Signal.HOLD,
                reason=f"ADX={adx_value:.1f} < {adx_threshold} — ranging market, no entry",
                metadata={"adx": round(adx_value, 2)},
            )

        # --- Filter 2: Volume confirmation (disabled when multiplier <= 0) ---
        vol_multiplier = float(self.params.get("volume_multiplier", 0.0))
        if vol_multiplier > 0 and not self._volume_confirmed(df, vol_window):
            return StrategyResult(
                Signal.HOLD,
                reason=f"Volume below {vol_multiplier}x average — low conviction",
                metadata={"adx": round(adx_value, 2)},
            )

        # --- Strategy votes ---
        results = [s.generate_signal(df) for s in self.strategies]
        names   = ["EMA", "RSI", "MACD"]

        buys  = [r for r in results if r.signal == Signal.BUY]
        sells = [r for r in results if r.signal == Signal.SELL]

        vote_log = " | ".join(
            f"{names[i]}:{results[i].signal.value.upper()}"
            for i in range(len(self.strategies))
        )
        logger.debug(f"Ensemble votes: {vote_log} | ADX={adx_value:.1f}")

        if len(buys) >= 2:
            reasons = [r.reason for r in buys]
            return StrategyResult(
                signal=Signal.BUY,
                confidence=len(buys) / len(self.strategies),
                reason=f"Ensemble BUY ({len(buys)}/3) ADX={adx_value:.1f}: {'; '.join(reasons)}",
                metadata={"votes": vote_log, "buy_count": len(buys), "adx": round(adx_value, 2)},
            )

        if len(sells) >= 2:
            reasons = [r.reason for r in sells]
            return StrategyResult(
                signal=Signal.SELL,
                confidence=len(sells) / len(self.strategies),
                reason=f"Ensemble SELL ({len(sells)}/3) ADX={adx_value:.1f}: {'; '.join(reasons)}",
                metadata={"votes": vote_log, "sell_count": len(sells), "adx": round(adx_value, 2)},
            )

        return StrategyResult(
            Signal.HOLD,
            reason=f"Split vote — no majority ({vote_log})",
            metadata={"votes": vote_log, "adx": round(adx_value, 2)},
        )
