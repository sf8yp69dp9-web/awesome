# Crypto Trading Bot

Automated crypto trading bot with paper trading, backtesting, and live trading capabilities.

## Features

- **3 strategies**: EMA Crossover, RSI Mean-Reversion, MACD Momentum
- **Paper trading**: Simulate trades with real market data, zero risk
- **Backtesting**: Test strategies on historical data with Sharpe, Sortino, win rate, drawdown metrics
- **Risk management**: Position sizing, stop-loss, take-profit, daily loss limit, max drawdown guard
- **Supports**: Binance, Kraken, KuCoin, Bybit (via ccxt)
- **Live dashboard**: Rich terminal UI with live portfolio status
- **Reports**: JSON and CSV trade logs saved automatically

---

## Quick Start

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure

Edit `config.yaml` — the defaults use paper trading mode with 500 USDT.

For live trading, copy the example env file:
```bash
cp .env.example .env
# Edit .env with your exchange API keys
```

### 3. Backtest a strategy

```bash
# Backtest EMA crossover on BTC/USDT for 2024
python main.py backtest --symbol BTC/USDT --strategy ema_crossover --start 2024-01-01 --end 2025-01-01

# Compare all 3 strategies
python main.py backtest --symbol ETH/USDT --all-strategies
```

### 4. Paper trade

```bash
# Use settings from config.yaml
python main.py paper

# Override options
python main.py paper --symbol BTC/USDT --strategy rsi --capital 500
```

### 5. Live trade (real money — careful!)

```bash
# Requires API keys in .env or config.local.yaml
# Will ask for confirmation before starting
python main.py live --symbol BTC/USDT
```

---

## CLI Commands

| Command | Description |
|---|---|
| `python main.py paper` | Start paper trading |
| `python main.py live` | Start live trading |
| `python main.py backtest` | Backtest on historical data |
| `python main.py status` | Show trade log |
| `python main.py price BTC/USDT` | Get current price |
| `python main.py strategies` | List available strategies |

---

## Strategies

### EMA Crossover (`ema_crossover`)
- **Buy**: Fast EMA (9) crosses above Slow EMA (21) + price above signal EMA
- **Sell**: Fast EMA crosses below Slow EMA (death cross)
- **Best for**: Trending markets

### RSI Mean-Reversion (`rsi`)
- **Buy**: RSI exits oversold zone (below 30) after confirmation bars
- **Sell**: RSI exits overbought zone (above 70)
- **Best for**: Ranging/oscillating markets

### MACD Momentum (`macd`)
- **Buy**: MACD histogram crosses positive + MACD above zero line
- **Sell**: Histogram crosses negative + MACD below zero line
- **Best for**: Momentum breakouts

---

## Risk Management

All trades go through the risk manager before execution:

| Rule | Default | Config key |
|---|---|---|
| Max position size | 10% of portfolio | `risk.max_position_size_pct` |
| Stop-loss | 2% below entry | `risk.stop_loss_pct` |
| Take-profit | 4% above entry | `risk.take_profit_pct` |
| Max open positions | 3 | `risk.max_open_positions` |
| Daily loss limit | 5% of capital | `risk.max_daily_loss_pct` |
| Max drawdown | 15% | `risk.max_drawdown_pct` |

---

## Configuration

All settings are in `config.yaml`. Sensitive values (API keys) should be in `config.local.yaml` or `.env` (never committed to git).

```yaml
trading:
  symbols: ["BTC/USDT", "ETH/USDT"]
  timeframe: "1h"
  strategy: "ema_crossover"
  dry_run: true   # <- false for live trading
```

---

## File Structure

```
trading_bot/
├── config.py          — Configuration loader
├── exchange.py        — ccxt exchange connector + mock for paper trading
├── portfolio.py       — Position tracking, trade history
├── risk.py            — Risk management rules
├── engine.py          — Main live trading loop
├── backtester.py      — Historical backtesting engine
├── paper_trader.py    — Paper trading mode
├── reporter.py        — Rich dashboard + JSON/CSV reports
├── data_downloader.py — Historical OHLCV downloader with caching
├── cli.py             — Click CLI interface
├── logger.py          — Logging setup
└── strategies/
    ├── base.py         — Abstract base strategy
    ├── ema_crossover.py
    ├── rsi.py
    └── macd.py
```

---

## Safety Notes

- **Always start with paper trading** and run backtests before going live
- **Start small** — test with the minimum allowed amount first
- **API keys**: Use read + trade permissions only, never withdrawal permissions
- **Testnet first**: Set `exchange.testnet: true` and use Binance testnet
- The bot will automatically stop trading if:
  - Daily loss exceeds `max_daily_loss_pct`
  - Portfolio drawdown exceeds `max_drawdown_pct`
