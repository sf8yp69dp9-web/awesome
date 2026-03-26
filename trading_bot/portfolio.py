"""Portfolio and position tracking."""
import csv
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class Position:
    symbol: str
    side: str               # "long" or "short"
    entry_price: float
    amount: float           # Base asset amount (e.g. BTC)
    entry_time: datetime
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    order_id: Optional[str] = None

    @property
    def cost(self) -> float:
        return self.entry_price * self.amount

    def unrealized_pnl(self, current_price: float) -> float:
        if self.side == "long":
            return (current_price - self.entry_price) * self.amount
        else:
            return (self.entry_price - current_price) * self.amount

    def unrealized_pnl_pct(self, current_price: float) -> float:
        if self.entry_price == 0:
            return 0.0
        return self.unrealized_pnl(current_price) / self.cost


@dataclass
class Trade:
    symbol: str
    side: str               # "buy" or "sell"
    entry_price: float
    exit_price: float
    amount: float
    entry_time: datetime
    exit_time: datetime
    pnl: float              # Net P&L in base currency
    pnl_pct: float
    reason: str             # "take_profit", "stop_loss", "signal", "manual"
    commission: float = 0.0

    @property
    def duration_hours(self) -> float:
        delta = self.exit_time - self.entry_time
        return delta.total_seconds() / 3600


class Portfolio:
    """Tracks capital, open positions, and closed trade history."""

    def __init__(self, initial_capital: float, base_currency: str = "USDT", trade_log_path: str = "logs/trades.csv"):
        self.initial_capital = initial_capital
        self.cash = initial_capital          # Available cash
        self.base_currency = base_currency
        self.positions: Dict[str, Position] = {}   # symbol -> Position
        self.trades: List[Trade] = []
        self.trade_log_path = Path(trade_log_path)
        self._daily_pnl: float = 0.0
        self._daily_reset_date: Optional[str] = None
        self._ensure_log_file()

    def _ensure_log_file(self) -> None:
        self.trade_log_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.trade_log_path.exists():
            with open(self.trade_log_path, "w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow([
                    "exit_time", "symbol", "side", "entry_price", "exit_price",
                    "amount", "pnl", "pnl_pct", "reason", "commission", "duration_hours"
                ])

    @property
    def total_value(self) -> float:
        """Current portfolio value: cash + open position costs (unrealized)."""
        positions_value = sum(p.cost for p in self.positions.values())
        return self.cash + positions_value

    @property
    def total_unrealized_pnl(self) -> float:
        return sum(p.unrealized_pnl(p.entry_price) for p in self.positions.values())

    @property
    def total_realized_pnl(self) -> float:
        return sum(t.pnl for t in self.trades)

    @property
    def drawdown(self) -> float:
        """Current drawdown from initial capital."""
        peak = max(self.initial_capital, self.total_value)
        if peak == 0:
            return 0.0
        return (peak - self.total_value) / peak

    @property
    def daily_pnl(self) -> float:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if self._daily_reset_date != today:
            self._daily_pnl = 0.0
            self._daily_reset_date = today
        return self._daily_pnl

    def open_position(
        self,
        symbol: str,
        side: str,
        price: float,
        amount: float,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        order_id: Optional[str] = None,
        commission_rate: float = 0.001,
    ) -> Position:
        cost = price * amount
        commission = cost * commission_rate
        total_cost = cost + commission

        if total_cost > self.cash:
            raise ValueError(f"Insufficient funds: need {total_cost:.4f}, have {self.cash:.4f}")

        self.cash -= total_cost
        position = Position(
            symbol=symbol,
            side=side,
            entry_price=price,
            amount=amount,
            entry_time=datetime.now(timezone.utc),
            stop_loss=stop_loss,
            take_profit=take_profit,
            order_id=order_id,
        )
        self.positions[symbol] = position
        logger.info(
            f"Opened {side.upper()} {symbol}: {amount:.6f} @ {price:.4f} "
            f"(cost={total_cost:.2f}, SL={stop_loss}, TP={take_profit})"
        )
        return position

    def close_position(
        self,
        symbol: str,
        exit_price: float,
        reason: str = "signal",
        commission_rate: float = 0.001,
    ) -> Optional[Trade]:
        if symbol not in self.positions:
            logger.warning(f"No open position for {symbol}")
            return None

        pos = self.positions.pop(symbol)
        proceeds = exit_price * pos.amount
        commission = proceeds * commission_rate
        net_proceeds = proceeds - commission

        entry_cost = pos.entry_price * pos.amount
        pnl = net_proceeds - entry_cost
        pnl_pct = pnl / entry_cost if entry_cost > 0 else 0.0

        self.cash += net_proceeds
        self._daily_pnl += pnl

        trade = Trade(
            symbol=symbol,
            side=pos.side,
            entry_price=pos.entry_price,
            exit_price=exit_price,
            amount=pos.amount,
            entry_time=pos.entry_time,
            exit_time=datetime.now(timezone.utc),
            pnl=pnl,
            pnl_pct=pnl_pct,
            reason=reason,
            commission=commission,
        )
        self.trades.append(trade)
        self._log_trade(trade)

        emoji = "+" if pnl >= 0 else ""
        logger.info(
            f"Closed {symbol} [{reason}]: {pos.amount:.6f} @ {exit_price:.4f} "
            f"PnL={emoji}{pnl:.2f} ({emoji}{pnl_pct*100:.2f}%)"
        )
        return trade

    def _log_trade(self, trade: Trade) -> None:
        with open(self.trade_log_path, "a", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                trade.exit_time.isoformat(),
                trade.symbol,
                trade.side,
                f"{trade.entry_price:.6f}",
                f"{trade.exit_price:.6f}",
                f"{trade.amount:.8f}",
                f"{trade.pnl:.4f}",
                f"{trade.pnl_pct*100:.4f}",
                trade.reason,
                f"{trade.commission:.4f}",
                f"{trade.duration_hours:.2f}",
            ])

    def has_position(self, symbol: str) -> bool:
        return symbol in self.positions

    def get_position(self, symbol: str) -> Optional[Position]:
        return self.positions.get(symbol)

    def summary(self) -> Dict:
        total_trades = len(self.trades)
        winning_trades = [t for t in self.trades if t.pnl > 0]
        win_rate = len(winning_trades) / total_trades if total_trades > 0 else 0.0
        avg_win = sum(t.pnl for t in winning_trades) / len(winning_trades) if winning_trades else 0.0
        losing_trades = [t for t in self.trades if t.pnl <= 0]
        avg_loss = sum(t.pnl for t in losing_trades) / len(losing_trades) if losing_trades else 0.0
        total_return = (self.total_value - self.initial_capital) / self.initial_capital

        return {
            "initial_capital": self.initial_capital,
            "current_value": self.total_value,
            "cash": self.cash,
            "open_positions": len(self.positions),
            "total_return_pct": total_return * 100,
            "total_realized_pnl": self.total_realized_pnl,
            "total_trades": total_trades,
            "win_rate_pct": win_rate * 100,
            "avg_win": avg_win,
            "avg_loss": avg_loss,
            "drawdown_pct": self.drawdown * 100,
            "daily_pnl": self._daily_pnl,
        }
