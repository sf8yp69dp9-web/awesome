"""Configuration management - loads YAML config and environment overrides."""
import os
import yaml
from dataclasses import dataclass, field
from typing import List, Optional
from pathlib import Path


@dataclass
class ExchangeConfig:
    name: str = "binance"
    api_key: str = ""
    api_secret: str = ""
    testnet: bool = True
    rate_limit: bool = True


@dataclass
class TradingConfig:
    symbols: List[str] = field(default_factory=lambda: ["BTC/USDT", "ETH/USDT"])
    timeframe: str = "1h"
    strategy: str = "ema_crossover"
    dry_run: bool = True


@dataclass
class PortfolioConfig:
    initial_capital: float = 500.0
    base_currency: str = "USDT"


@dataclass
class RiskConfig:
    max_position_size_pct: float = 0.10
    stop_loss_pct: float = 0.02
    take_profit_pct: float = 0.04
    trailing_stop_pct: float = 0.015     # Trail stop at 1.5% below highest price
    trailing_stop_enabled: bool = True
    atr_period: int = 14                 # ATR lookback for dynamic stop placement
    atr_multiplier: float = 3.0          # Stop = entry - (atr_multiplier × ATR)
    atr_stop_enabled: bool = True        # Use ATR stops; falls back to fixed % if False
    max_open_positions: int = 3
    max_daily_loss_pct: float = 0.05
    max_drawdown_pct: float = 0.15


@dataclass
class AIConfig:
    enabled: bool = False
    api_key: str = ""                    # Set via ANTHROPIC_API_KEY env var
    model: str = "claude-haiku-4-5-20251001"   # Fast + cheap for signal validation
    confidence_threshold: float = 0.6   # Min AI confidence to pass signal through


@dataclass
class StrategyParams:
    # EMA Crossover
    fast_period: int = 9
    slow_period: int = 21
    signal_period: int = 5
    # RSI
    period: int = 14
    oversold: float = 30.0
    overbought: float = 70.0
    lookback: int = 2
    # MACD
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    # Ensemble filters
    adx_period: int = 14
    adx_threshold: float = 15.0
    volume_window: int = 20
    volume_multiplier: float = 0.0   # 0 = disabled; set >1.0 with real exchange data


@dataclass
class BacktestConfig:
    start_date: str = "2024-01-01"
    end_date: str = "2025-01-01"
    initial_capital: float = 500.0
    commission: float = 0.001


@dataclass
class LoggingConfig:
    level: str = "INFO"
    log_file: str = "logs/trading_bot.log"
    trade_log: str = "logs/trades.csv"
    report_dir: str = "reports/"


@dataclass
class BotConfig:
    exchange: ExchangeConfig = field(default_factory=ExchangeConfig)
    trading: TradingConfig = field(default_factory=TradingConfig)
    portfolio: PortfolioConfig = field(default_factory=PortfolioConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    ai: AIConfig = field(default_factory=AIConfig)
    strategy_params: StrategyParams = field(default_factory=StrategyParams)
    backtesting: BacktestConfig = field(default_factory=BacktestConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)


def load_config(config_path: str = "config.yaml") -> BotConfig:
    """Load configuration from YAML file, with environment variable overrides."""
    cfg = BotConfig()

    # Load from YAML
    path = Path(config_path)
    if path.exists():
        with open(path) as f:
            raw = yaml.safe_load(f)
    else:
        raw = {}

    # Also try local override file
    local_path = Path("config.local.yaml")
    if local_path.exists():
        with open(local_path) as f:
            local = yaml.safe_load(f) or {}
        raw = _deep_merge(raw, local)

    # Exchange
    if "exchange" in raw:
        ex = raw["exchange"]
        cfg.exchange.name = ex.get("name", cfg.exchange.name)
        cfg.exchange.api_key = ex.get("api_key", cfg.exchange.api_key)
        cfg.exchange.api_secret = ex.get("api_secret", cfg.exchange.api_secret)
        cfg.exchange.testnet = ex.get("testnet", cfg.exchange.testnet)
        cfg.exchange.rate_limit = ex.get("rate_limit", cfg.exchange.rate_limit)

    # Trading
    if "trading" in raw:
        tr = raw["trading"]
        cfg.trading.symbols = tr.get("symbols", cfg.trading.symbols)
        cfg.trading.timeframe = tr.get("timeframe", cfg.trading.timeframe)
        cfg.trading.strategy = tr.get("strategy", cfg.trading.strategy)
        cfg.trading.dry_run = tr.get("dry_run", cfg.trading.dry_run)

    # Portfolio
    if "portfolio" in raw:
        p = raw["portfolio"]
        cfg.portfolio.initial_capital = p.get("initial_capital", cfg.portfolio.initial_capital)
        cfg.portfolio.base_currency = p.get("base_currency", cfg.portfolio.base_currency)

    # Risk
    if "risk" in raw:
        r = raw["risk"]
        cfg.risk.max_position_size_pct = r.get("max_position_size_pct", cfg.risk.max_position_size_pct)
        cfg.risk.stop_loss_pct = r.get("stop_loss_pct", cfg.risk.stop_loss_pct)
        cfg.risk.take_profit_pct = r.get("take_profit_pct", cfg.risk.take_profit_pct)
        cfg.risk.max_open_positions = r.get("max_open_positions", cfg.risk.max_open_positions)
        cfg.risk.max_daily_loss_pct = r.get("max_daily_loss_pct", cfg.risk.max_daily_loss_pct)
        cfg.risk.max_drawdown_pct = r.get("max_drawdown_pct", cfg.risk.max_drawdown_pct)
        cfg.risk.trailing_stop_pct = r.get("trailing_stop_pct", cfg.risk.trailing_stop_pct)
        cfg.risk.trailing_stop_enabled = r.get("trailing_stop_enabled", cfg.risk.trailing_stop_enabled)
        cfg.risk.atr_period = r.get("atr_period", cfg.risk.atr_period)
        cfg.risk.atr_multiplier = r.get("atr_multiplier", cfg.risk.atr_multiplier)
        cfg.risk.atr_stop_enabled = r.get("atr_stop_enabled", cfg.risk.atr_stop_enabled)

    # AI
    if "ai" in raw:
        a = raw["ai"]
        cfg.ai.enabled = a.get("enabled", cfg.ai.enabled)
        cfg.ai.model = a.get("model", cfg.ai.model)
        cfg.ai.confidence_threshold = a.get("confidence_threshold", cfg.ai.confidence_threshold)

    # Strategy params
    if "strategies" in raw:
        s = raw["strategies"]
        ema = s.get("ema_crossover", {})
        cfg.strategy_params.fast_period = ema.get("fast_period", cfg.strategy_params.fast_period)
        cfg.strategy_params.slow_period = ema.get("slow_period", cfg.strategy_params.slow_period)
        cfg.strategy_params.signal_period = ema.get("signal_period", cfg.strategy_params.signal_period)

        rsi = s.get("rsi", {})
        cfg.strategy_params.period = rsi.get("period", cfg.strategy_params.period)
        cfg.strategy_params.oversold = rsi.get("oversold", cfg.strategy_params.oversold)
        cfg.strategy_params.overbought = rsi.get("overbought", cfg.strategy_params.overbought)
        cfg.strategy_params.lookback = rsi.get("lookback", cfg.strategy_params.lookback)

        macd = s.get("macd", {})
        cfg.strategy_params.macd_fast = macd.get("fast_period", cfg.strategy_params.macd_fast)
        cfg.strategy_params.macd_slow = macd.get("slow_period", cfg.strategy_params.macd_slow)
        cfg.strategy_params.macd_signal = macd.get("signal_period", cfg.strategy_params.macd_signal)

        ens = s.get("ensemble", {})
        cfg.strategy_params.adx_period = ens.get("adx_period", cfg.strategy_params.adx_period)
        cfg.strategy_params.adx_threshold = ens.get("adx_threshold", cfg.strategy_params.adx_threshold)
        cfg.strategy_params.volume_window = ens.get("volume_window", cfg.strategy_params.volume_window)
        cfg.strategy_params.volume_multiplier = ens.get("volume_multiplier", cfg.strategy_params.volume_multiplier)

    # Backtesting
    if "backtesting" in raw:
        b = raw["backtesting"]
        cfg.backtesting.start_date = b.get("start_date", cfg.backtesting.start_date)
        cfg.backtesting.end_date = b.get("end_date", cfg.backtesting.end_date)
        cfg.backtesting.initial_capital = b.get("initial_capital", cfg.backtesting.initial_capital)
        cfg.backtesting.commission = b.get("commission", cfg.backtesting.commission)

    # Logging
    if "logging" in raw:
        lg = raw["logging"]
        cfg.logging.level = lg.get("level", cfg.logging.level)
        cfg.logging.log_file = lg.get("log_file", cfg.logging.log_file)
        cfg.logging.trade_log = lg.get("trade_log", cfg.logging.trade_log)
        cfg.logging.report_dir = lg.get("report_dir", cfg.logging.report_dir)

    # Environment overrides (highest priority)
    if os.environ.get("EXCHANGE_API_KEY"):
        cfg.exchange.api_key = os.environ["EXCHANGE_API_KEY"]
    if os.environ.get("EXCHANGE_API_SECRET"):
        cfg.exchange.api_secret = os.environ["EXCHANGE_API_SECRET"]
    if os.environ.get("EXCHANGE_NAME"):
        cfg.exchange.name = os.environ["EXCHANGE_NAME"]
    if os.environ.get("DRY_RUN", "").lower() == "false":
        cfg.trading.dry_run = False
    if os.environ.get("ANTHROPIC_API_KEY"):
        cfg.ai.api_key = os.environ["ANTHROPIC_API_KEY"]
        cfg.ai.enabled = True

    return cfg


def _deep_merge(base: dict, override: dict) -> dict:
    result = base.copy()
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result
