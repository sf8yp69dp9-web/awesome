"""Reporting, dashboard display, and HTML/CSV report generation."""
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich import box

from .config import BotConfig
from .portfolio import Portfolio

logger = logging.getLogger(__name__)
console = Console()


class Reporter:
    """Generates console dashboards and file reports."""

    def __init__(self, config: BotConfig):
        self.cfg = config
        self.report_dir = Path(config.logging.report_dir)
        self.report_dir.mkdir(parents=True, exist_ok=True)

    def print_header(self) -> None:
        console.print(Panel(
            Text("CRYPTO TRADING BOT", justify="center", style="bold cyan") ,
            subtitle=f"Strategy: [yellow]{self.cfg.trading.strategy}[/yellow] | "
                     f"Mode: [green]PAPER[/green] | "
                     f"Capital: [white]{self.cfg.portfolio.initial_capital:.0f} {self.cfg.portfolio.base_currency}[/white]",
            border_style="cyan",
        ))

    def print_portfolio_status(self, portfolio: Portfolio) -> None:
        summary = portfolio.summary()
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

        pnl_color = "green" if summary["total_realized_pnl"] >= 0 else "red"
        ret_color = "green" if summary["total_return_pct"] >= 0 else "red"

        # Main stats table
        table = Table(title=f"Portfolio Status — {now}", box=box.ROUNDED, border_style="blue")
        table.add_column("Metric", style="cyan", width=24)
        table.add_column("Value", style="white", justify="right")

        table.add_row("Initial Capital",    f"{summary['initial_capital']:.2f} {self.cfg.portfolio.base_currency}")
        table.add_row("Current Value",      f"{summary['current_value']:.2f} {self.cfg.portfolio.base_currency}")
        table.add_row("Cash Available",     f"{summary['cash']:.2f} {self.cfg.portfolio.base_currency}")
        table.add_row("Total Return",       f"[{ret_color}]{summary['total_return_pct']:+.2f}%[/{ret_color}]")
        table.add_row("Realized PnL",       f"[{pnl_color}]{summary['total_realized_pnl']:+.2f}[/{pnl_color}]")
        table.add_row("Daily PnL",          f"{summary['daily_pnl']:+.2f}")
        table.add_row("Open Positions",     str(summary["open_positions"]))
        table.add_row("Total Trades",       str(summary["total_trades"]))
        table.add_row("Win Rate",           f"{summary['win_rate_pct']:.1f}%")
        table.add_row("Max Drawdown",       f"[red]{summary['drawdown_pct']:.2f}%[/red]")

        console.print(table)

        # Open positions table
        if portfolio.positions:
            pos_table = Table(title="Open Positions", box=box.SIMPLE, border_style="yellow")
            pos_table.add_column("Symbol")
            pos_table.add_column("Side")
            pos_table.add_column("Entry Price", justify="right")
            pos_table.add_column("Amount", justify="right")
            pos_table.add_column("Cost", justify="right")
            pos_table.add_column("Stop Loss", justify="right")
            pos_table.add_column("Take Profit", justify="right")

            for sym, pos in portfolio.positions.items():
                pos_table.add_row(
                    sym,
                    f"[green]{pos.side.upper()}[/green]",
                    f"{pos.entry_price:.4f}",
                    f"{pos.amount:.6f}",
                    f"{pos.cost:.2f}",
                    f"[red]{pos.stop_loss:.4f}[/red]" if pos.stop_loss else "—",
                    f"[green]{pos.take_profit:.4f}[/green]" if pos.take_profit else "—",
                )
            console.print(pos_table)

        # Recent trades
        if portfolio.trades:
            recent = portfolio.trades[-5:]
            trade_table = Table(title="Recent Trades (last 5)", box=box.SIMPLE, border_style="magenta")
            trade_table.add_column("Time")
            trade_table.add_column("Symbol")
            trade_table.add_column("Side")
            trade_table.add_column("Entry", justify="right")
            trade_table.add_column("Exit", justify="right")
            trade_table.add_column("PnL", justify="right")
            trade_table.add_column("Reason")

            for t in reversed(recent):
                pnl_style = "green" if t.pnl >= 0 else "red"
                trade_table.add_row(
                    t.exit_time.strftime("%m-%d %H:%M"),
                    t.symbol,
                    t.side,
                    f"{t.entry_price:.4f}",
                    f"{t.exit_price:.4f}",
                    f"[{pnl_style}]{t.pnl:+.2f} ({t.pnl_pct*100:+.2f}%)[/{pnl_style}]",
                    t.reason,
                )
            console.print(trade_table)

    def print_backtest_results(self, metrics) -> None:
        """Pretty-print BacktestMetrics to console."""
        ret_color = "green" if metrics.total_return_pct >= 0 else "red"
        sharpe_color = "green" if metrics.sharpe_ratio >= 1 else ("yellow" if metrics.sharpe_ratio >= 0 else "red")

        table = Table(
            title=f"Backtest: {metrics.strategy.upper()} on {metrics.symbol}",
            box=box.ROUNDED,
            border_style="cyan",
        )
        table.add_column("Metric", style="cyan", width=24)
        table.add_column("Value", justify="right")

        table.add_row("Period",             f"{metrics.start_date} → {metrics.end_date}")
        table.add_row("Initial Capital",    f"{metrics.initial_capital:.2f}")
        table.add_row("Final Value",        f"{metrics.final_value:.2f}")
        table.add_row("Total Return",       f"[{ret_color}]{metrics.total_return_pct:+.2f}%[/{ret_color}]")
        table.add_row("Total Trades",       str(metrics.total_trades))
        table.add_row("Win Rate",           f"{metrics.win_rate_pct:.1f}%")
        table.add_row("Profit Factor",      f"{metrics.profit_factor:.2f}")
        table.add_row("Avg Win",            f"[green]{metrics.avg_win_pct:+.2f}%[/green]")
        table.add_row("Avg Loss",           f"[red]{metrics.avg_loss_pct:+.2f}%[/red]")
        table.add_row("Best Trade",         f"[green]{metrics.best_trade_pct:+.2f}%[/green]")
        table.add_row("Worst Trade",        f"[red]{metrics.worst_trade_pct:+.2f}%[/red]")
        table.add_row("Max Drawdown",       f"[red]{metrics.max_drawdown_pct:.2f}%[/red]")
        table.add_row("Sharpe Ratio",       f"[{sharpe_color}]{metrics.sharpe_ratio:.3f}[/{sharpe_color}]")
        table.add_row("Sortino Ratio",      f"{metrics.sortino_ratio:.3f}")
        table.add_row("Avg Duration",       f"{metrics.avg_trade_duration_hours:.1f}h")
        table.add_row("Total Commission",   f"{metrics.total_commission:.2f}")

        console.print(table)

    def save_report(self, portfolio: Portfolio) -> str:
        """Save a JSON report to the reports directory."""
        summary = portfolio.summary()
        report = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "config": {
                "strategy": self.cfg.trading.strategy,
                "symbols": self.cfg.trading.symbols,
                "timeframe": self.cfg.trading.timeframe,
            },
            "portfolio": summary,
            "trades": [
                {
                    "symbol": t.symbol,
                    "side": t.side,
                    "entry_price": t.entry_price,
                    "exit_price": t.exit_price,
                    "amount": t.amount,
                    "entry_time": t.entry_time.isoformat(),
                    "exit_time": t.exit_time.isoformat(),
                    "pnl": t.pnl,
                    "pnl_pct": t.pnl_pct,
                    "reason": t.reason,
                    "duration_hours": t.duration_hours,
                }
                for t in portfolio.trades
            ],
        }

        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        report_path = self.report_dir / f"report_{ts}.json"
        with open(report_path, "w") as f:
            json.dump(report, f, indent=2)

        logger.info(f"Report saved: {report_path}")
        return str(report_path)

    def save_backtest_report(self, metrics) -> str:
        """Save backtest results as JSON."""
        data = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "symbol": metrics.symbol,
            "strategy": metrics.strategy,
            "start_date": metrics.start_date,
            "end_date": metrics.end_date,
            "initial_capital": metrics.initial_capital,
            "final_value": metrics.final_value,
            "total_return_pct": metrics.total_return_pct,
            "total_trades": metrics.total_trades,
            "win_rate_pct": metrics.win_rate_pct,
            "profit_factor": metrics.profit_factor,
            "max_drawdown_pct": metrics.max_drawdown_pct,
            "sharpe_ratio": metrics.sharpe_ratio,
            "sortino_ratio": metrics.sortino_ratio,
        }

        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        path = self.report_dir / f"backtest_{metrics.strategy}_{metrics.symbol.replace('/', '')}_{ts}.json"
        with open(path, "w") as f:
            json.dump(data, f, indent=2)

        logger.info(f"Backtest report saved: {path}")
        return str(path)
