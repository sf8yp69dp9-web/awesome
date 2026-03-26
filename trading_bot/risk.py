"""Risk management: position sizing, stop/take, trailing stop, daily loss limits, drawdown guard."""
import logging
import numpy as np
import pandas as pd
from dataclasses import dataclass
from typing import Optional, Tuple

from .config import RiskConfig
from .portfolio import Portfolio

logger = logging.getLogger(__name__)


@dataclass
class TradeDecision:
    allowed: bool
    reason: str
    position_size_usd: float = 0.0
    amount: float = 0.0
    stop_loss_price: Optional[float] = None
    take_profit_price: Optional[float] = None


class RiskManager:
    """
    Enforces all risk rules before a trade is placed:
    - Max position size (% of portfolio)
    - Max open positions
    - Daily loss limit
    - Max drawdown
    - Minimum order size
    """

    def __init__(self, config: RiskConfig):
        self.cfg = config

    @staticmethod
    def _compute_atr(df: pd.DataFrame, period: int = 14) -> float:
        """Average True Range — measures recent volatility."""
        high = df["high"]
        low  = df["low"]
        prev_close = df["close"].shift(1)
        tr = pd.concat([
            high - low,
            (high - prev_close).abs(),
            (low  - prev_close).abs(),
        ], axis=1).max(axis=1)
        atr = tr.ewm(alpha=1.0 / period, adjust=False).mean()
        return float(atr.iloc[-1])

    def evaluate_trade(
        self,
        portfolio: Portfolio,
        symbol: str,
        side: str,
        current_price: float,
        min_order_amount: float = 0.0,
        df: Optional[pd.DataFrame] = None,
    ) -> TradeDecision:
        """
        Check if a trade is allowed and calculate position size.
        Returns a TradeDecision with all relevant parameters.
        """
        # 1. Max drawdown check
        if portfolio.drawdown >= self.cfg.max_drawdown_pct:
            return TradeDecision(
                allowed=False,
                reason=f"Max drawdown reached: {portfolio.drawdown*100:.1f}% >= {self.cfg.max_drawdown_pct*100:.1f}%",
            )

        # 2. Daily loss limit check
        daily_loss_pct = abs(portfolio.daily_pnl) / portfolio.initial_capital
        if portfolio.daily_pnl < 0 and daily_loss_pct >= self.cfg.max_daily_loss_pct:
            return TradeDecision(
                allowed=False,
                reason=f"Daily loss limit hit: {daily_loss_pct*100:.1f}% >= {self.cfg.max_daily_loss_pct*100:.1f}%",
            )

        # 3. Max open positions check
        if len(portfolio.positions) >= self.cfg.max_open_positions:
            return TradeDecision(
                allowed=False,
                reason=f"Max open positions reached: {len(portfolio.positions)} >= {self.cfg.max_open_positions}",
            )

        # 4. Already in this position
        if portfolio.has_position(symbol):
            return TradeDecision(
                allowed=False,
                reason=f"Already have open position for {symbol}",
            )

        # 5. Calculate position size
        portfolio_value = portfolio.total_value
        max_allocation = portfolio_value * self.cfg.max_position_size_pct

        # Don't allocate more than available cash
        allocation = min(max_allocation, portfolio.cash * 0.99)  # 1% buffer for fees

        if allocation <= 0:
            return TradeDecision(
                allowed=False,
                reason="Insufficient cash for a trade",
            )

        amount = allocation / current_price

        # 6. Minimum order size check
        if min_order_amount > 0 and amount < min_order_amount:
            return TradeDecision(
                allowed=False,
                reason=f"Order amount {amount:.8f} below minimum {min_order_amount:.8f}",
            )

        # 7. Compute stop-loss and take-profit prices (ATR-based when possible)
        use_atr = (
            self.cfg.atr_stop_enabled
            and df is not None
            and len(df) >= self.cfg.atr_period + 2
        )

        if use_atr:
            atr = self._compute_atr(df, self.cfg.atr_period)
            atr_dist = self.cfg.atr_multiplier * atr
            # Safety bounds: never wider than 3× fixed %, never tighter than 0.5× fixed %
            min_dist = current_price * self.cfg.stop_loss_pct * 0.5
            max_dist = current_price * self.cfg.stop_loss_pct * 3.0
            atr_dist = max(min_dist, min(atr_dist, max_dist))
        else:
            atr = None
            atr_dist = current_price * self.cfg.stop_loss_pct

        if side == "long":
            stop_loss_price  = current_price - atr_dist
            take_profit_price = current_price * (1 + self.cfg.take_profit_pct)
        else:
            stop_loss_price  = current_price + atr_dist
            take_profit_price = current_price * (1 - self.cfg.take_profit_pct)

        sl_mode = f"ATR×{self.cfg.atr_multiplier}={atr:.2f}" if atr else "fixed%"
        logger.debug(
            f"Trade approved: {symbol} {side} {amount:.6f} @ {current_price:.4f} "
            f"SL={stop_loss_price:.4f} TP={take_profit_price:.4f} ({sl_mode})"
        )

        return TradeDecision(
            allowed=True,
            reason="OK",
            position_size_usd=allocation,
            amount=amount,
            stop_loss_price=stop_loss_price,
            take_profit_price=take_profit_price,
        )

    def check_exit_conditions(
        self,
        symbol: str,
        current_price: float,
        portfolio: Portfolio,
    ) -> Tuple[bool, str]:
        """
        Check if an open position should be force-closed due to risk rules.
        Returns (should_close, reason).
        """
        position = portfolio.get_position(symbol)
        if not position:
            return False, ""

        # Stop-loss hit
        if position.stop_loss is not None:
            if position.side == "long" and current_price <= position.stop_loss:
                return True, "stop_loss"
            if position.side == "short" and current_price >= position.stop_loss:
                return True, "stop_loss"

        # Take-profit hit
        if position.take_profit is not None:
            if position.side == "long" and current_price >= position.take_profit:
                return True, "take_profit"
            if position.side == "short" and current_price <= position.take_profit:
                return True, "take_profit"

        # Emergency: max drawdown while in position
        if portfolio.drawdown >= self.cfg.max_drawdown_pct:
            return True, "max_drawdown"

        return False, ""

    def update_trailing_stop(
        self,
        symbol: str,
        current_price: float,
        portfolio: Portfolio,
        trail_pct: Optional[float] = None,
    ) -> None:
        """
        Trailing stop-loss: moves the stop-loss UP as the price rises.
        Once moved up, the stop never moves back down.
        trail_pct defaults to stop_loss_pct from config.
        """
        position = portfolio.get_position(symbol)
        if not position or position.side != "long":
            return

        trail = trail_pct or self.cfg.stop_loss_pct
        new_stop = current_price * (1 - trail)

        if position.stop_loss is None or new_stop > position.stop_loss:
            old_stop = position.stop_loss
            position.stop_loss = new_stop
            if old_stop is not None:
                logger.debug(
                    f"Trailing SL updated {symbol}: {old_stop:.4f} → {new_stop:.4f} "
                    f"(price={current_price:.4f})"
                )

    def log_risk_status(self, portfolio: Portfolio) -> None:
        summary = portfolio.summary()
        logger.info(
            f"Risk Status | Value: {summary['current_value']:.2f} | "
            f"Cash: {summary['cash']:.2f} | "
            f"Drawdown: {summary['drawdown_pct']:.2f}% | "
            f"Daily PnL: {summary['daily_pnl']:.2f} | "
            f"Open Positions: {summary['open_positions']}"
        )
