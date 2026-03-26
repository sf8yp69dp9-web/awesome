"""Offline simulation mode: replays synthetic market data as if it were live."""
import logging
import time
from datetime import datetime, timezone
from typing import Optional

import pandas as pd

from .config import BotConfig
from .data_downloader import generate_demo_ohlcv
from .portfolio import Portfolio
from .risk import RiskManager
from .strategies import STRATEGY_REGISTRY
from .strategies.base import Signal
from .reporter import Reporter
from .ai_validator import AISignalValidator

logger = logging.getLogger(__name__)


class SimulatedExchange:
    """Feeds pre-generated OHLCV data candle-by-candle, simulating a live feed."""

    def __init__(self, data: pd.DataFrame, symbol: str):
        self._data = data
        self._symbol = symbol
        self._cursor = 50          # Start after warmup period
        self._order_counter = 0

    def next_tick(self) -> Optional[pd.DataFrame]:
        """Return window of candles up to current cursor, advance cursor."""
        if self._cursor >= len(self._data):
            return None
        window = self._data.iloc[:self._cursor + 1]
        self._cursor += 1
        return window

    @property
    def current_price(self) -> float:
        idx = min(self._cursor, len(self._data) - 1)
        return float(self._data["close"].iloc[idx])

    @property
    def current_time(self):
        idx = min(self._cursor, len(self._data) - 1)
        return self._data.index[idx]

    @property
    def total_candles(self) -> int:
        return len(self._data)

    def create_market_buy(self, symbol: str, amount: float) -> dict:
        price = self.current_price
        self._order_counter += 1
        logger.info(f"[SIM] BUY  {amount:.6f} {symbol} @ {price:.2f}")
        return {
            "id": f"sim_{self._order_counter}",
            "symbol": symbol,
            "side": "buy",
            "amount": amount,
            "price": price,
            "filled": amount,
            "status": "closed",
        }

    def create_market_sell(self, symbol: str, amount: float) -> dict:
        price = self.current_price
        self._order_counter += 1
        logger.info(f"[SIM] SELL {amount:.6f} {symbol} @ {price:.2f}")
        return {
            "id": f"sim_{self._order_counter}",
            "symbol": symbol,
            "side": "sell",
            "amount": amount,
            "price": price,
            "filled": amount,
            "status": "closed",
        }

    def get_min_order_amount(self, symbol: str) -> float:
        return 0.00001

    def get_amount_precision(self, symbol: str) -> int:
        return 6


class OfflinePaperTrader:
    """
    Full paper trading simulation without internet.
    Replays synthetic market data and executes the strategy in real time.
    """

    def __init__(self, config: BotConfig, speed: float = 0.0):
        """
        speed: seconds to wait between each candle (0.0 = as fast as possible for demo)
        """
        self.cfg = config
        self.speed = speed

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
        self.ai_validator = AISignalValidator(config.ai)
        self._symbol = config.trading.symbols[0]

    def run(self, candles: int = 8784, print_every: int = 100) -> None:
        """Run the full simulation."""
        logger.info(f"[SIM] Generating market data for {self._symbol}...")
        df = generate_demo_ohlcv(
            symbol=self._symbol,
            timeframe=self.cfg.trading.timeframe,
            start_date=self.cfg.backtesting.start_date,
            end_date=self.cfg.backtesting.end_date,
        )

        sim = SimulatedExchange(df, self._symbol)
        self.reporter.print_header()

        tick = 0
        last_status_tick = 0

        while True:
            window = sim.next_tick()
            if window is None:
                break

            tick += 1
            current_price = sim.current_price
            current_time = sim.current_time

            # Update trailing stop on open position
            if self.portfolio.has_position(self._symbol) and self.cfg.risk.trailing_stop_enabled:
                self.risk.update_trailing_stop(
                    self._symbol, current_price, self.portfolio,
                    trail_pct=self.cfg.risk.trailing_stop_pct,
                )

            # Check SL/TP on open position
            if self.portfolio.has_position(self._symbol):
                should_exit, reason = self.risk.check_exit_conditions(
                    self._symbol, current_price, self.portfolio
                )
                if should_exit:
                    self._sell(sim, self._symbol, current_price, reason)

            # Generate signal
            result = self.strategy.generate_signal(window)

            if result.signal == Signal.BUY and not self.portfolio.has_position(self._symbol):
                validation = self.ai_validator.validate(self._symbol, result, window, current_price)
                if validation.approved:
                    self._buy(sim, self._symbol, current_price)
                elif not validation.skipped:
                    logger.info(f"[AI] BUY blocked for {self._symbol}: {validation.reasoning}")
            elif result.signal == Signal.SELL and self.portfolio.has_position(self._symbol):
                self._sell(sim, self._symbol, current_price, "signal")

            # Print status every N ticks
            if tick - last_status_tick >= print_every:
                ts_str = current_time.strftime("%Y-%m-%d %H:%M") if hasattr(current_time, 'strftime') else str(current_time)
                print(f"\n[{ts_str}] Tick {tick}/{sim.total_candles-50} | {self._symbol} @ {current_price:.2f}")
                self.reporter.print_portfolio_status(self.portfolio)
                last_status_tick = tick

            if self.speed > 0:
                time.sleep(self.speed)

        # Force close any open position at end
        if self.portfolio.has_position(self._symbol):
            final_price = sim.current_price
            self._sell(sim, self._symbol, final_price, "end_of_simulation")

        # Final report
        print("\n" + "="*60)
        print("SIMULATION COMPLETE")
        print("="*60)
        self.reporter.print_portfolio_status(self.portfolio)
        report_path = self.reporter.save_report(self.portfolio)
        print(f"\nReport saved: {report_path}")

    def _buy(self, sim: SimulatedExchange, symbol: str, price: float) -> None:
        decision = self.risk.evaluate_trade(self.portfolio, symbol, "long", price, sim.get_min_order_amount(symbol))
        if not decision.allowed:
            return
        precision = sim.get_amount_precision(symbol)
        amount = round(decision.amount, precision)
        order = sim.create_market_buy(symbol, amount)
        fill_price = float(order.get("price") or price)
        self.portfolio.open_position(
            symbol=symbol, side="long", price=fill_price, amount=amount,
            stop_loss=decision.stop_loss_price, take_profit=decision.take_profit_price,
            order_id=order.get("id"),
        )

    def _sell(self, sim: SimulatedExchange, symbol: str, price: float, reason: str) -> None:
        pos = self.portfolio.get_position(symbol)
        if not pos:
            return
        order = sim.create_market_sell(symbol, pos.amount)
        fill_price = float(order.get("price") or price)
        self.portfolio.close_position(symbol, fill_price, reason=reason)
