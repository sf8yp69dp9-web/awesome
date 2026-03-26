"""Paper trading: real-time simulation using live market data, no real orders."""
import logging
import time
from datetime import datetime, timezone
from typing import Optional

from .config import BotConfig
from .exchange import ExchangeConnector, MockExchange
from .portfolio import Portfolio
from .risk import RiskManager
from .strategies import STRATEGY_REGISTRY
from .strategies.base import Signal
from .reporter import Reporter

logger = logging.getLogger(__name__)


class PaperTrader:
    """
    Paper trading engine — like TradingEngine but forces dry_run=True
    and adds a real-time performance display.
    """

    def __init__(self, config: BotConfig):
        self.cfg = config

        real_exchange = ExchangeConnector(config.exchange)
        self.exchange = MockExchange(real_exchange)

        self.portfolio = Portfolio(
            initial_capital=config.portfolio.initial_capital,
            base_currency=config.portfolio.base_currency,
            trade_log_path=config.logging.trade_log,
        )

        self.risk = RiskManager(config.risk)

        strategy_name = config.trading.strategy
        strategy_params = vars(config.strategy_params)
        self.strategy = STRATEGY_REGISTRY[strategy_name](strategy_params)

        self.reporter = Reporter(config)
        self._running = False
        self._tick_count = 0

        logger.info(f"PaperTrader initialized | Strategy: {strategy_name} | Capital: {config.portfolio.initial_capital}")

    def run(self, max_ticks: Optional[int] = None) -> None:
        self._running = True
        logger.info("=== PAPER TRADING STARTED ===")
        self.reporter.print_header()

        try:
            while self._running:
                self._tick()
                self._tick_count += 1

                # Print live status every 5 ticks
                if self._tick_count % 5 == 0:
                    self.reporter.print_portfolio_status(self.portfolio)

                if max_ticks and self._tick_count >= max_ticks:
                    logger.info(f"Paper trading complete after {max_ticks} ticks.")
                    break

                sleep_seconds = self._get_sleep_seconds()
                time.sleep(sleep_seconds)

        except KeyboardInterrupt:
            logger.info("Paper trading stopped by user.")
        finally:
            self._final_report()

    def stop(self) -> None:
        self._running = False

    def _tick(self) -> None:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        logger.info(f"[PAPER] Tick #{self._tick_count + 1} @ {now}")

        for symbol in self.cfg.trading.symbols:
            try:
                self._process_symbol(symbol)
            except Exception as e:
                logger.error(f"[PAPER] Error on {symbol}: {e}", exc_info=True)

    def _process_symbol(self, symbol: str) -> None:
        df = self.exchange.fetch_ohlcv(symbol, self.cfg.trading.timeframe, limit=200)
        if df is None or len(df) < 50:
            return

        current_price = float(df["close"].iloc[-1])

        # Check SL/TP
        if self.portfolio.has_position(symbol):
            should_exit, reason = self.risk.check_exit_conditions(symbol, current_price, self.portfolio)
            if should_exit:
                self._sell(symbol, current_price, reason)
                return

        # Get signal
        result = self.strategy.generate_signal(df)
        logger.info(f"[PAPER] {symbol} @ {current_price:.4f} | {result.signal.value.upper()} | {result.reason}")

        if result.signal == Signal.BUY and not self.portfolio.has_position(symbol):
            self._buy(symbol, current_price)
        elif result.signal == Signal.SELL and self.portfolio.has_position(symbol):
            self._sell(symbol, current_price, "signal")

    def _buy(self, symbol: str, price: float) -> None:
        min_amount = self.exchange.get_min_order_amount(symbol)
        decision = self.risk.evaluate_trade(self.portfolio, symbol, "long", price, min_amount)

        if not decision.allowed:
            logger.info(f"[PAPER] Trade blocked: {decision.reason}")
            return

        order = self.exchange.create_market_buy(symbol, decision.amount)
        fill_price = float(order.get("price") or price)

        self.portfolio.open_position(
            symbol=symbol,
            side="long",
            price=fill_price,
            amount=decision.amount,
            stop_loss=decision.stop_loss_price,
            take_profit=decision.take_profit_price,
            order_id=order.get("id"),
        )

    def _sell(self, symbol: str, price: float, reason: str) -> None:
        pos = self.portfolio.get_position(symbol)
        if not pos:
            return
        order = self.exchange.create_market_sell(symbol, pos.amount)
        fill_price = float(order.get("price") or price)
        self.portfolio.close_position(symbol, fill_price, reason=reason)

    def _get_sleep_seconds(self) -> int:
        tf_seconds = {
            "1m": 60, "3m": 180, "5m": 300, "15m": 900,
            "30m": 1800, "1h": 3600, "4h": 14400, "1d": 86400,
        }
        candle_s = tf_seconds.get(self.cfg.trading.timeframe, 3600)
        now_ts = int(time.time())
        next_candle = ((now_ts // candle_s) + 1) * candle_s
        return max(10, next_candle - now_ts - 5)

    def _final_report(self) -> None:
        self.reporter.print_portfolio_status(self.portfolio)
        self.reporter.save_report(self.portfolio)
        logger.info("=== PAPER TRADING ENDED ===")
