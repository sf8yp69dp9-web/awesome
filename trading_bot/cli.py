"""Command-line interface for the trading bot."""
import logging
import sys
from pathlib import Path

import click
from rich.console import Console

from .config import load_config
from .logger import setup_logging

console = Console()


@click.group()
@click.option("--config", "-c", default="config.yaml", help="Path to config file", show_default=True)
@click.option("--verbose", "-v", is_flag=True, help="Enable debug logging")
@click.pass_context
def cli(ctx, config, verbose):
    """Crypto Trading Bot — automated strategy trading with risk management."""
    ctx.ensure_object(dict)
    cfg = load_config(config)
    if verbose:
        cfg.logging.level = "DEBUG"
    setup_logging(cfg.logging)
    ctx.obj["config"] = cfg
    ctx.obj["config_path"] = config


@cli.command()
@click.option("--symbol", "-s", multiple=True, help="Override trading symbol(s), e.g. BTC/USDT")
@click.option("--strategy", help="Override strategy (ema_crossover | rsi | macd)")
@click.option("--capital", type=float, help="Override initial capital")
@click.pass_context
def paper(ctx, symbol, strategy, capital):
    """Start paper trading (real market data, no real money)."""
    from .paper_trader import PaperTrader

    cfg = ctx.obj["config"]
    cfg.trading.dry_run = True

    if symbol:
        cfg.trading.symbols = list(symbol)
    if strategy:
        cfg.trading.strategy = strategy
    if capital:
        cfg.portfolio.initial_capital = capital

    console.print(f"[green]Starting paper trading[/green] | Strategy: [yellow]{cfg.trading.strategy}[/yellow]")
    trader = PaperTrader(cfg)
    trader.run()


@cli.command()
@click.option("--symbol", "-s", multiple=True, help="Override symbol(s)")
@click.option("--strategy", help="Override strategy")
@click.pass_context
def live(ctx, symbol, strategy):
    """Start LIVE trading (real money — use with extreme caution!)."""
    from .engine import TradingEngine

    cfg = ctx.obj["config"]

    if not cfg.exchange.api_key or not cfg.exchange.api_secret:
        console.print("[red]ERROR: No API keys configured. Set EXCHANGE_API_KEY and EXCHANGE_API_SECRET.[/red]")
        sys.exit(1)

    if symbol:
        cfg.trading.symbols = list(symbol)
    if strategy:
        cfg.trading.strategy = strategy

    console.print(
        "[bold red]WARNING: LIVE TRADING MODE[/bold red] — real money will be used!\n"
        f"Exchange: [yellow]{cfg.exchange.name}[/yellow] | "
        f"Testnet: [yellow]{cfg.exchange.testnet}[/yellow]\n"
        f"Capital: [white]{cfg.portfolio.initial_capital} {cfg.portfolio.base_currency}[/white]"
    )
    if not click.confirm("Are you sure you want to start live trading?"):
        console.print("Aborted.")
        return

    cfg.trading.dry_run = False
    engine = TradingEngine(cfg, dry_run=False)
    engine.run()


@cli.command()
@click.option("--symbol", "-s", default=None, help="Symbol to backtest (overrides config)")
@click.option("--strategy", default=None, help="Strategy to test (overrides config)")
@click.option("--start", default=None, help="Start date YYYY-MM-DD")
@click.option("--end", default=None, help="End date YYYY-MM-DD")
@click.option("--capital", type=float, default=None, help="Initial capital")
@click.option("--all-strategies", is_flag=True, help="Run backtest for all strategies")
@click.pass_context
def backtest(ctx, symbol, strategy, start, end, capital, all_strategies):
    """Backtest strategy on historical data."""
    from .backtester import Backtester
    from .data_downloader import download_ohlcv
    from .reporter import Reporter
    from .strategies import STRATEGY_REGISTRY

    cfg = ctx.obj["config"]

    if symbol:
        cfg.trading.symbols = [symbol]
    if start:
        cfg.backtesting.start_date = start
    if end:
        cfg.backtesting.end_date = end
    if capital:
        cfg.backtesting.initial_capital = capital

    reporter = Reporter(cfg)
    strategies_to_test = list(STRATEGY_REGISTRY.keys()) if all_strategies else [strategy or cfg.trading.strategy]

    for sym in cfg.trading.symbols:
        console.print(f"\n[cyan]Downloading historical data for {sym}...[/cyan]")
        try:
            df = download_ohlcv(
                exchange_config=cfg.exchange,
                symbol=sym,
                timeframe=cfg.trading.timeframe,
                start_date=cfg.backtesting.start_date,
                end_date=cfg.backtesting.end_date,
            )
            console.print(f"[green]Loaded {len(df)} candles ({cfg.backtesting.start_date} → {cfg.backtesting.end_date})[/green]")
        except Exception as e:
            console.print(f"[red]Failed to load data for {sym}: {e}[/red]")
            continue

        for strat in strategies_to_test:
            cfg.trading.strategy = strat
            try:
                backtester = Backtester(cfg)
                metrics = backtester.run(df.copy(), sym)
                reporter.print_backtest_results(metrics)
                report_path = reporter.save_backtest_report(metrics)
                console.print(f"[dim]Saved: {report_path}[/dim]")
            except Exception as e:
                console.print(f"[red]Backtest failed for {strat} on {sym}: {e}[/red]")
                logging.getLogger(__name__).exception("Backtest error")


@cli.command()
@click.pass_context
def status(ctx):
    """Show current portfolio status and recent trades from the trade log."""
    import csv
    from rich.table import Table
    from rich import box

    cfg = ctx.obj["config"]
    trade_log = Path(cfg.logging.trade_log)

    if not trade_log.exists():
        console.print("[yellow]No trade log found yet. Start paper or live trading first.[/yellow]")
        return

    with open(trade_log) as f:
        rows = list(csv.DictReader(f))

    if not rows:
        console.print("[yellow]Trade log is empty.[/yellow]")
        return

    table = Table(title=f"Trade Log ({trade_log})", box=box.ROUNDED)
    for col in rows[0].keys():
        table.add_column(col, overflow="fold")

    for row in rows[-20:]:  # Last 20 trades
        pnl = float(row.get("pnl", 0))
        style = "green" if pnl >= 0 else "red"
        table.add_row(*row.values(), style=style)

    console.print(table)
    console.print(f"\n[dim]Total trades: {len(rows)} | Showing last 20[/dim]")


@cli.command()
@click.argument("symbol")
@click.pass_context
def price(ctx, symbol):
    """Get current price for a symbol."""
    from .exchange import ExchangeConnector

    cfg = ctx.obj["config"]
    try:
        ex = ExchangeConnector(cfg.exchange)
        p = ex.get_current_price(symbol)
        console.print(f"[cyan]{symbol}[/cyan]: [bold white]{p:.4f}[/bold white] {cfg.portfolio.base_currency}")
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")


@cli.command()
@click.pass_context
def strategies(ctx):
    """List available trading strategies."""
    from .strategies import STRATEGY_REGISTRY

    table = __import__("rich.table", fromlist=["Table"]).Table(title="Available Strategies")
    table.add_column("Name", style="cyan")
    table.add_column("Description")

    descriptions = {
        "ema_crossover": "EMA crossover — golden/death cross signals",
        "rsi":           "RSI mean-reversion — oversold/overbought entries",
        "macd":          "MACD momentum — histogram crossover signals",
    }

    for name in STRATEGY_REGISTRY:
        table.add_row(name, descriptions.get(name, "—"))

    console.print(table)


def main():
    cli(obj={})
