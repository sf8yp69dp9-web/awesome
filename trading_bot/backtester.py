"""Backtesting engine — simulates strategy on historical data."""
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Dict, Optional

import numpy as np
import pandas as pd

from .config import BotConfig
from .portfolio import Portfolio, Trade
from .risk import RiskManager
from .strategies import STRATEGY_REGISTRY
from .strategies.base import Signal

logger = logging.getLogger(__name__)


@dataclass
class BacktestMetrics:
    symbol: str
    strategy: str
    start_date: str
    end_date: str
    initial_capital: float
    final_value: float
    total_return_pct: float
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate_pct: float
    avg_win_pct: float
    avg_loss_pct: float
    profit_factor: float
    max_drawdown_pct: float
    sharpe_ratio: float
    sortino_ratio: float
    best_trade_pct: float
    worst_trade_pct: float
    avg_trade_duration_hours: float
    total_commission: float

    def __str__(self) -> str:
        lines = [
            f"\n{'='*50}",
            f"BACKTEST RESULTS: {self.strategy.upper()} on {self.symbol}",
            f"{'='*50}",
            f"Period:           {self.start_date} → {self.end_date}",
            f"Initial Capital:  {self.initial_capital:.2f}",
            f"Final Value:      {self.final_value:.2f}",
            f"Total Return:     {self.total_return_pct:+.2f}%",
            f"{'─'*50}",
            f"Total Trades:     {self.total_trades}",
            f"Win Rate:         {self.win_rate_pct:.1f}%",
            f"Winning / Losing: {self.winning_trades} / {self.losing_trades}",
            f"Avg Win:          {self.avg_win_pct:+.2f}%",
            f"Avg Loss:         {self.avg_loss_pct:+.2f}%",
            f"Best Trade:       {self.best_trade_pct:+.2f}%",
            f"Worst Trade:      {self.worst_trade_pct:+.2f}%",
            f"Profit Factor:    {self.profit_factor:.2f}",
            f"{'─'*50}",
            f"Max Drawdown:     {self.max_drawdown_pct:.2f}%",
            f"Sharpe Ratio:     {self.sharpe_ratio:.3f}",
            f"Sortino Ratio:    {self.sortino_ratio:.3f}",
            f"Avg Duration:     {self.avg_trade_duration_hours:.1f}h",
            f"Total Commission: {self.total_commission:.2f}",
            f"{'='*50}",
        ]
        return "\n".join(lines)


class Backtester:
    """
    Runs a strategy on historical OHLCV data and computes performance metrics.
    Simulates realistic execution with commission and slippage.
    """

    def __init__(self, config: BotConfig):
        self.cfg = config
        self.commission = config.backtesting.commission

        strategy_name = config.trading.strategy
        if strategy_name not in STRATEGY_REGISTRY:
            raise ValueError(f"Unknown strategy: {strategy_name}")
        strategy_params = vars(config.strategy_params)
        self.strategy = STRATEGY_REGISTRY[strategy_name](strategy_params)
        self.risk_cfg = config.risk

    def run(self, df: pd.DataFrame, symbol: str) -> BacktestMetrics:
        """
        Run backtest on a DataFrame of OHLCV data.
        df must have columns: open, high, low, close, volume (DatetimeIndex)
        """
        logger.info(f"Starting backtest: {symbol} | {len(df)} candles | {self.cfg.trading.strategy}")

        initial_capital = self.cfg.backtesting.initial_capital
        cash = initial_capital
        peak_value = initial_capital
        max_drawdown = 0.0

        position = None         # Currently open position dict
        trades: List[Trade] = []
        equity_curve: List[float] = []
        daily_returns: List[float] = []

        for i in range(50, len(df)):
            window = df.iloc[:i + 1]
            current_bar = df.iloc[i]
            current_price = float(current_bar["close"])
            current_time = window.index[-1]

            portfolio_value = cash + (position["amount"] * current_price if position else 0)
            equity_curve.append(portfolio_value)

            # Track drawdown
            if portfolio_value > peak_value:
                peak_value = portfolio_value
            drawdown = (peak_value - portfolio_value) / peak_value
            if drawdown > max_drawdown:
                max_drawdown = drawdown

            # Check stop-loss / take-profit on open position
            if position:
                sl = position.get("stop_loss")
                tp = position.get("take_profit")
                exit_reason = None

                if sl and current_price <= sl:
                    exit_reason = "stop_loss"
                elif tp and current_price >= tp:
                    exit_reason = "take_profit"

                if exit_reason:
                    trade = self._close_position(position, current_price, current_time, exit_reason, cash)
                    trades.append(trade)
                    cash += trade.exit_price * trade.amount * (1 - self.commission)
                    position = None
                    continue

            # Generate strategy signal
            result = self.strategy.generate_signal(window)

            # Execute signals
            if result.signal == Signal.BUY and position is None:
                max_allocation = cash * self.risk_cfg.max_position_size_pct
                allocation = min(max_allocation, cash * 0.99)
                amount = allocation / current_price
                cost = amount * current_price * (1 + self.commission)

                if cost <= cash and amount > 0:
                    cash -= cost
                    position = {
                        "symbol": symbol,
                        "entry_price": current_price,
                        "amount": amount,
                        "entry_time": current_time,
                        "stop_loss": current_price * (1 - self.risk_cfg.stop_loss_pct),
                        "take_profit": current_price * (1 + self.risk_cfg.take_profit_pct),
                    }

            elif result.signal == Signal.SELL and position is not None:
                trade = self._close_position(position, current_price, current_time, "signal", cash)
                trades.append(trade)
                cash += trade.exit_price * trade.amount * (1 - self.commission)
                position = None

        # Force-close any open position at end
        if position:
            last_price = float(df["close"].iloc[-1])
            last_time = df.index[-1]
            trade = self._close_position(position, last_price, last_time, "end_of_data", cash)
            trades.append(trade)
            cash += trade.exit_price * trade.amount * (1 - self.commission)

        final_value = cash
        return self._compute_metrics(
            symbol=symbol,
            trades=trades,
            equity_curve=equity_curve,
            initial_capital=initial_capital,
            final_value=final_value,
            max_drawdown=max_drawdown,
        )

    def _close_position(self, position: dict, exit_price: float, exit_time, reason: str, cash: float) -> Trade:
        entry_cost = position["entry_price"] * position["amount"]
        exit_proceeds = exit_price * position["amount"] * (1 - self.commission)
        pnl = exit_proceeds - entry_cost
        pnl_pct = pnl / entry_cost if entry_cost > 0 else 0.0

        return Trade(
            symbol=position["symbol"],
            side="long",
            entry_price=position["entry_price"],
            exit_price=exit_price,
            amount=position["amount"],
            entry_time=position["entry_time"] if isinstance(position["entry_time"], datetime) else position["entry_time"].to_pydatetime(),
            exit_time=exit_time if isinstance(exit_time, datetime) else exit_time.to_pydatetime(),
            pnl=pnl,
            pnl_pct=pnl_pct,
            reason=reason,
            commission=exit_price * position["amount"] * self.commission,
        )

    def _compute_metrics(
        self,
        symbol: str,
        trades: List[Trade],
        equity_curve: List[float],
        initial_capital: float,
        final_value: float,
        max_drawdown: float,
    ) -> BacktestMetrics:
        total_trades = len(trades)
        winning = [t for t in trades if t.pnl > 0]
        losing = [t for t in trades if t.pnl <= 0]

        win_rate = len(winning) / total_trades * 100 if total_trades > 0 else 0.0
        avg_win_pct = sum(t.pnl_pct for t in winning) / len(winning) * 100 if winning else 0.0
        avg_loss_pct = sum(t.pnl_pct for t in losing) / len(losing) * 100 if losing else 0.0
        best = max((t.pnl_pct for t in trades), default=0.0) * 100
        worst = min((t.pnl_pct for t in trades), default=0.0) * 100
        avg_duration = sum(t.duration_hours for t in trades) / total_trades if total_trades > 0 else 0.0
        total_commission = sum(t.commission for t in trades)

        gross_profit = sum(t.pnl for t in winning)
        gross_loss = abs(sum(t.pnl for t in losing))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

        total_return_pct = (final_value - initial_capital) / initial_capital * 100

        # Sharpe & Sortino (annualized, assuming 1h candles)
        sharpe = self._compute_sharpe(equity_curve)
        sortino = self._compute_sortino(equity_curve)

        return BacktestMetrics(
            symbol=symbol,
            strategy=self.cfg.trading.strategy,
            start_date=self.cfg.backtesting.start_date,
            end_date=self.cfg.backtesting.end_date,
            initial_capital=initial_capital,
            final_value=final_value,
            total_return_pct=total_return_pct,
            total_trades=total_trades,
            winning_trades=len(winning),
            losing_trades=len(losing),
            win_rate_pct=win_rate,
            avg_win_pct=avg_win_pct,
            avg_loss_pct=avg_loss_pct,
            profit_factor=profit_factor,
            max_drawdown_pct=max_drawdown * 100,
            sharpe_ratio=sharpe,
            sortino_ratio=sortino,
            best_trade_pct=best,
            worst_trade_pct=worst,
            avg_trade_duration_hours=avg_duration,
            total_commission=total_commission,
        )

    def _compute_sharpe(self, equity_curve: List[float], risk_free_rate: float = 0.0) -> float:
        if len(equity_curve) < 2:
            return 0.0
        returns = np.diff(equity_curve) / np.array(equity_curve[:-1])
        if returns.std() == 0:
            return 0.0
        # Annualize based on timeframe
        tf_map = {"1m": 525600, "5m": 105120, "15m": 35040, "1h": 8760, "4h": 2190, "1d": 365}
        periods_per_year = tf_map.get(self.cfg.trading.timeframe, 8760)
        sharpe = (returns.mean() - risk_free_rate / periods_per_year) / returns.std() * np.sqrt(periods_per_year)
        return float(sharpe)

    def _compute_sortino(self, equity_curve: List[float], risk_free_rate: float = 0.0) -> float:
        if len(equity_curve) < 2:
            return 0.0
        returns = np.diff(equity_curve) / np.array(equity_curve[:-1])
        downside = returns[returns < 0]
        if len(downside) == 0 or downside.std() == 0:
            return float("inf") if returns.mean() > 0 else 0.0
        tf_map = {"1m": 525600, "5m": 105120, "15m": 35040, "1h": 8760, "4h": 2190, "1d": 365}
        periods_per_year = tf_map.get(self.cfg.trading.timeframe, 8760)
        sortino = (returns.mean() - risk_free_rate / periods_per_year) / downside.std() * np.sqrt(periods_per_year)
        return float(sortino)
