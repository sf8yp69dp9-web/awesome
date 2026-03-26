"""Reporting, live dashboard, and report generation."""
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

import pandas as pd
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.columns import Columns
from rich.text import Text
from rich.align import Align
from rich import box

from .config import BotConfig
from .portfolio import Portfolio

logger = logging.getLogger(__name__)
console = Console()


# ── Sparkline helpers ────────────────────────────────────────────────────────

_SPARK_BLOCKS = " ▁▂▃▄▅▆▇█"


def sparkline(values: List[float], width: int = 20) -> str:
    """Render a compact sparkline from a list of float values."""
    if not values or len(values) < 2:
        return "─" * width

    # Downsample to width
    if len(values) > width:
        step = len(values) / width
        values = [values[int(i * step)] for i in range(width)]

    mn, mx = min(values), max(values)
    rng = mx - mn or 1.0
    chars = [_SPARK_BLOCKS[int((v - mn) / rng * 8)] for v in values]
    return "".join(chars)


def price_trend_arrow(values: List[float]) -> str:
    if len(values) < 2:
        return "→"
    delta = values[-1] - values[-3] if len(values) >= 3 else values[-1] - values[0]
    if delta > 0:
        return "▲"
    if delta < 0:
        return "▼"
    return "→"


# ── Reporter ─────────────────────────────────────────────────────────────────

class Reporter:
    """Generates console dashboards and file reports."""

    def __init__(self, config: BotConfig):
        self.cfg = config
        self.report_dir = Path(config.logging.report_dir)
        self.report_dir.mkdir(parents=True, exist_ok=True)
        self._equity_history: List[float] = []
        self._price_history: List[float] = []

    def record_tick(self, portfolio_value: float, current_price: Optional[float] = None) -> None:
        """Call every tick to keep history for sparklines."""
        self._equity_history.append(portfolio_value)
        if current_price is not None:
            self._price_history.append(current_price)

    def print_header(self) -> None:
        mode = "[red]LIVE[/red]" if not self.cfg.trading.dry_run else "[green]PAPER[/green]"
        symbols = " · ".join(self.cfg.trading.symbols)
        console.print(Panel(
            Align.center(Text("CRYPTO TRADING BOT", style="bold cyan")),
            subtitle=(
                f"Strategy: [yellow]{self.cfg.trading.strategy}[/yellow]  │  "
                f"Mode: {mode}  │  "
                f"Capital: [white]{self.cfg.portfolio.initial_capital:.0f} "
                f"{self.cfg.portfolio.base_currency}[/white]  │  "
                f"Symbols: [dim]{symbols}[/dim]"
            ),
            border_style="bright_blue",
            padding=(0, 2),
        ))

    def print_portfolio_status(self, portfolio: Portfolio, current_prices: Optional[dict] = None) -> None:
        summary = portfolio.summary()
        self._equity_history.append(summary["current_value"])
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

        ret_pct = summary["total_return_pct"]
        ret_color = "green" if ret_pct >= 0 else "red"
        pnl_color = "green" if summary["total_realized_pnl"] >= 0 else "red"
        daily_color = "green" if summary["daily_pnl"] >= 0 else "red"

        eq_spark = sparkline(self._equity_history[-40:], width=25)
        eq_arrow = price_trend_arrow(self._equity_history[-5:])

        # ── Left panel: Portfolio stats ──────────────────────────────────
        stats = Table(box=box.SIMPLE, show_header=False, padding=(0, 1))
        stats.add_column("k", style="dim cyan", width=18)
        stats.add_column("v", justify="right", min_width=14)

        stats.add_row("Capital",
            f"[dim]{summary['initial_capital']:.2f}[/dim]")
        stats.add_row("Current Value",
            f"[bold]{summary['current_value']:.2f} {self.cfg.portfolio.base_currency}[/bold]")
        stats.add_row("Cash",
            f"{summary['cash']:.2f}")
        stats.add_row("Total Return",
            f"[{ret_color}]{ret_pct:+.2f}%[/{ret_color}]")
        stats.add_row("Realized PnL",
            f"[{pnl_color}]{summary['total_realized_pnl']:+.2f}[/{pnl_color}]")
        stats.add_row("Daily PnL",
            f"[{daily_color}]{summary['daily_pnl']:+.2f}[/{daily_color}]")
        stats.add_row("Drawdown",
            f"[red]{summary['drawdown_pct']:.2f}%[/red]")

        left = Panel(stats, title="[cyan]Portfolio[/cyan]", border_style="blue", padding=(0, 1))

        # ── Right panel: Trade stats + equity sparkline ──────────────────
        trade_t = Table(box=box.SIMPLE, show_header=False, padding=(0, 1))
        trade_t.add_column("k", style="dim cyan", width=18)
        trade_t.add_column("v", justify="right", min_width=14)

        trade_t.add_row("Total Trades",    str(summary["total_trades"]))
        trade_t.add_row("Open Positions",  str(summary["open_positions"]))
        trade_t.add_row("Win Rate",        f"{summary['win_rate_pct']:.1f}%")
        trade_t.add_row("Avg Win",         f"[green]{summary['avg_win']:+.2f}[/green]" if summary['avg_win'] else "[dim]—[/dim]")
        trade_t.add_row("Avg Loss",        f"[red]{summary['avg_loss']:+.2f}[/red]" if summary['avg_loss'] else "[dim]—[/dim]")
        spark_row = Text(f"{eq_arrow} ", style="bold")
        spark_row.append(eq_spark, style="cyan")
        trade_t.add_row("Equity Curve", spark_row)

        right = Panel(trade_t, title="[cyan]Trades[/cyan]", border_style="blue", padding=(0, 1))

        console.print(Columns([left, right], equal=True, expand=True))
        console.print(f"[dim]  ⏱  {now}[/dim]")

        # ── Open positions ────────────────────────────────────────────────
        if portfolio.positions:
            pos_table = Table(
                title="  Open Positions",
                box=box.SIMPLE_HEAD,
                border_style="yellow",
                header_style="bold yellow",
            )
            pos_table.add_column("Symbol", style="cyan")
            pos_table.add_column("Side")
            pos_table.add_column("Entry", justify="right")
            pos_table.add_column("Current", justify="right")
            pos_table.add_column("Amount", justify="right")
            pos_table.add_column("Unreal. PnL", justify="right")
            pos_table.add_column("Stop Loss", justify="right")
            pos_table.add_column("Take Profit", justify="right")

            for sym, pos in portfolio.positions.items():
                cur_price = (current_prices or {}).get(sym, pos.entry_price)
                upnl = pos.unrealized_pnl(cur_price)
                upnl_pct = pos.unrealized_pnl_pct(cur_price) * 100
                upnl_color = "green" if upnl >= 0 else "red"

                price_spark = ""
                if self._price_history:
                    price_spark = " " + sparkline(self._price_history[-15:], width=8)

                pos_table.add_row(
                    sym,
                    f"[green]{pos.side.upper()}[/green]",
                    f"{pos.entry_price:.4f}",
                    f"{cur_price:.4f}{price_spark}",
                    f"{pos.amount:.6f}",
                    f"[{upnl_color}]{upnl:+.2f} ({upnl_pct:+.2f}%)[/{upnl_color}]",
                    f"[red]{pos.stop_loss:.4f}[/red]" if pos.stop_loss else "[dim]—[/dim]",
                    f"[green]{pos.take_profit:.4f}[/green]" if pos.take_profit else "[dim]—[/dim]",
                )
            console.print(pos_table)

        # ── Recent trades ─────────────────────────────────────────────────
        if portfolio.trades:
            recent = portfolio.trades[-6:]
            t = Table(
                title="  Recent Trades",
                box=box.SIMPLE_HEAD,
                border_style="magenta",
                header_style="bold magenta",
            )
            t.add_column("Time", style="dim")
            t.add_column("Symbol")
            t.add_column("Entry", justify="right")
            t.add_column("Exit", justify="right")
            t.add_column("PnL", justify="right")
            t.add_column("Duration")
            t.add_column("Reason")

            for trade in reversed(recent):
                pnl_color = "green" if trade.pnl >= 0 else "red"
                icon = "✓" if trade.pnl >= 0 else "✗"
                t.add_row(
                    trade.exit_time.strftime("%m-%d %H:%M"),
                    trade.symbol,
                    f"{trade.entry_price:.4f}",
                    f"{trade.exit_price:.4f}",
                    f"[{pnl_color}]{icon} {trade.pnl:+.2f} ({trade.pnl_pct*100:+.2f}%)[/{pnl_color}]",
                    f"{trade.duration_hours:.1f}h",
                    _reason_label(trade.reason),
                )
            console.print(t)

    def print_backtest_results(self, metrics) -> None:
        ret_color = "green" if metrics.total_return_pct >= 0 else "red"
        sharpe_color = ("green" if metrics.sharpe_ratio >= 1.5
                        else "yellow" if metrics.sharpe_ratio >= 0.5
                        else "red")

        # Equity sparkline from trade history (approximated from metrics)
        table = Table(
            title=f"  Backtest: [yellow]{metrics.strategy.upper()}[/yellow] on [cyan]{metrics.symbol}[/cyan]",
            box=box.ROUNDED,
            border_style="cyan",
            header_style="bold",
        )
        table.add_column("Metric", style="cyan", width=22)
        table.add_column("Value", justify="right", min_width=20)

        table.add_row("Period",         f"{metrics.start_date} → {metrics.end_date}")
        table.add_row("Initial Capital",f"[dim]{metrics.initial_capital:.2f}[/dim]")
        table.add_row("Final Value",    f"[bold]{metrics.final_value:.2f}[/bold]")
        table.add_row("Total Return",   f"[{ret_color}][bold]{metrics.total_return_pct:+.2f}%[/bold][/{ret_color}]")
        table.add_row("", "")
        table.add_row("Total Trades",   str(metrics.total_trades))
        table.add_row("Win Rate",       _win_rate_bar(metrics.win_rate_pct))
        table.add_row("Profit Factor",  f"{metrics.profit_factor:.2f}")
        table.add_row("Avg Win",        f"[green]{metrics.avg_win_pct:+.2f}%[/green]")
        table.add_row("Avg Loss",       f"[red]{metrics.avg_loss_pct:+.2f}%[/red]")
        table.add_row("Best Trade",     f"[green]{metrics.best_trade_pct:+.2f}%[/green]")
        table.add_row("Worst Trade",    f"[red]{metrics.worst_trade_pct:+.2f}%[/red]")
        table.add_row("", "")
        table.add_row("Max Drawdown",   f"[red]{metrics.max_drawdown_pct:.2f}%[/red]")
        table.add_row("Sharpe Ratio",   f"[{sharpe_color}]{metrics.sharpe_ratio:.3f}[/{sharpe_color}]")
        table.add_row("Sortino Ratio",  f"{metrics.sortino_ratio:.3f}")
        table.add_row("Avg Duration",   f"{metrics.avg_trade_duration_hours:.1f}h")
        table.add_row("Commission",     f"[dim]{metrics.total_commission:.2f}[/dim]")

        console.print(table)

    def save_report(self, portfolio: Portfolio) -> str:
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
        path = self.report_dir / f"report_{ts}.json"
        with open(path, "w") as f:
            json.dump(report, f, indent=2)
        logger.info(f"Report saved: {path}")
        return str(path)

    def save_backtest_report(self, metrics) -> str:
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
        sym = metrics.symbol.replace("/", "")
        path = self.report_dir / f"backtest_{metrics.strategy}_{sym}_{ts}.json"
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
        logger.info(f"Backtest report saved: {path}")
        return str(path)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _win_rate_bar(pct: float) -> str:
    filled = int(pct / 10)
    bar = "█" * filled + "░" * (10 - filled)
    color = "green" if pct >= 50 else "yellow" if pct >= 35 else "red"
    return f"[{color}]{bar}[/{color}] {pct:.1f}%"


def _reason_label(reason: str) -> str:
    labels = {
        "stop_loss":          "[red]Stop Loss[/red]",
        "take_profit":        "[green]Take Profit[/green]",
        "signal":             "[cyan]Signal[/cyan]",
        "max_drawdown":       "[bold red]Drawdown[/bold red]",
        "end_of_simulation":  "[dim]End[/dim]",
        "end_of_data":        "[dim]End[/dim]",
    }
    return labels.get(reason, f"[dim]{reason}[/dim]")
