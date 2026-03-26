"""Main trading engine — orchestrates exchange, portfolio, risk, and strategies."""
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
from .ai_validator import AISignalValidator
from .reporter import Reporter
from .telegram_notifier import TelegramNotifier
from .telegram_commander import TelegramCommander
from .web_dashboard import WebDashboard
from .fear_greed import get_fear_greed, position_size_multiplier, emoji as fg_emoji
from .sentiment import get_sentiment, trade_allowed as sentiment_allowed, position_multiplier as sentiment_mult, emoji as sent_emoji

logger = logging.getLogger(__name__)


class TradingEngine:
    """
    Core trading loop.
    - Fetches OHLCV data on each tick
    - Runs the configured strategy
    - Checks risk rules
    - Executes trades (live or paper)
    - Monitors open positions for SL/TP
    """

    def __init__(self, config: BotConfig, dry_run: Optional[bool] = None):
        self.cfg = config
        self.is_dry_run = dry_run if dry_run is not None else config.trading.dry_run

        # Build exchange (real or mock)
        real_exchange = ExchangeConnector(config.exchange)
        if self.is_dry_run:
            self.exchange = MockExchange(real_exchange)
            logger.info("Running in PAPER TRADING mode")
        else:
            self.exchange = real_exchange
            logger.warning("Running in LIVE TRADING mode — real money at risk!")

        # Portfolio
        self.portfolio = Portfolio(
            initial_capital=config.portfolio.initial_capital,
            base_currency=config.portfolio.base_currency,
            trade_log_path=config.logging.trade_log,
        )

        # Risk manager
        self.risk = RiskManager(config.risk)

        # Strategy
        strategy_name = config.trading.strategy
        if strategy_name not in STRATEGY_REGISTRY:
            raise ValueError(f"Unknown strategy: '{strategy_name}'. Available: {list(STRATEGY_REGISTRY.keys())}")

        strategy_params = vars(config.strategy_params)
        self.strategy = STRATEGY_REGISTRY[strategy_name](strategy_params)
        logger.info(f"Strategy: {strategy_name}")

        self.ai_validator = AISignalValidator(config.ai)
        self.reporter = Reporter(config)
        self.telegram = TelegramNotifier(config.telegram.token, config.telegram.chat_id)
        self.commander = TelegramCommander(config.telegram.token, config.telegram.chat_id)
        self.dashboard = WebDashboard(port=8080)
        self._fear_greed_mult = 1.0
        self._sentiment: dict[str, dict] = {}   # symbol → sentiment result
        self._running = False
        self._tick_count = 0

    def run(self, max_ticks: Optional[int] = None) -> None:
        """Start the trading loop. Runs until stopped or max_ticks reached."""
        self._running = True
        logger.info(
            f"Starting TradingEngine | Symbols: {self.cfg.trading.symbols} | "
            f"Timeframe: {self.cfg.trading.timeframe} | "
            f"Strategy: {self.cfg.trading.strategy}"
        )
        mode = "PAPER" if self.is_dry_run else "LIVE"
        self.telegram.startup(
            strategy=self.cfg.trading.strategy,
            symbol=self.cfg.trading.symbols[0],
            capital=self.cfg.portfolio.initial_capital,
            mode=mode,
        )

        # Start dashboard and commander
        self.dashboard.set_portfolio(self.portfolio, mode)
        self.dashboard.start()

        self.commander.on_stop = self.stop
        self.commander.on_status = self._status_text
        self.commander.on_portfolio = self._portfolio_text
        self.commander.start()

        try:
            while self._running:
                self._tick()
                self._tick_count += 1

                if max_ticks and self._tick_count >= max_ticks:
                    logger.info(f"Reached max ticks ({max_ticks}), stopping.")
                    break

                sleep_seconds = self._get_sleep_seconds()
                logger.debug(f"Sleeping {sleep_seconds}s until next candle...")
                time.sleep(sleep_seconds)

        except KeyboardInterrupt:
            logger.info("Interrupted by user. Shutting down gracefully...")
        finally:
            self.commander.stop()
            self._shutdown()

    def stop(self) -> None:
        self._running = False

    def _tick(self) -> None:
        """One iteration of the trading loop."""
        now = datetime.now(timezone.utc).strftime("%H:%M:%S")
        logger.info(f"--- Tick #{self._tick_count + 1} @ {now} ---")

        # Refresh Fear & Greed multiplier (cached daily)
        fg = get_fear_greed()
        self._fear_greed_mult = position_size_multiplier(fg["value"])
        logger.debug(f"Fear & Greed: {fg['value']} ({fg['label']}) → size ×{self._fear_greed_mult}")

        for symbol in self.cfg.trading.symbols:
            try:
                self._process_symbol(symbol)
            except Exception as e:
                logger.error(f"Error processing {symbol}: {e}", exc_info=True)

        self.dashboard.record_equity(self.portfolio.total_value)
        self.dashboard.set_sentiment(self._sentiment)
        self.risk.log_risk_status(self.portfolio)
        self.telegram.check_and_send_daily_summary(
            self.portfolio,
            target_hour_utc=self.cfg.telegram.daily_summary_hour,
        )

    def _process_symbol(self, symbol: str) -> None:
        # 1. Fetch OHLCV
        df = self.exchange.fetch_ohlcv(symbol, self.cfg.trading.timeframe, limit=200)
        if df is None or len(df) < 50:
            logger.warning(f"Insufficient data for {symbol}")
            return

        current_price = float(df["close"].iloc[-1])

        # 2. Update trailing stop on open position
        if self.portfolio.has_position(symbol) and self.cfg.risk.trailing_stop_enabled:
            self.risk.update_trailing_stop(
                symbol, current_price, self.portfolio,
                trail_pct=self.cfg.risk.trailing_stop_pct,
            )

        # 3. Check exit conditions on open positions
        if self.portfolio.has_position(symbol):
            should_exit, exit_reason = self.risk.check_exit_conditions(symbol, current_price, self.portfolio)
            if should_exit:
                self._execute_sell(symbol, current_price, reason=exit_reason)
                return  # Don't re-enter on same tick

        # 4. Generate strategy signal
        result = self.strategy.generate_signal(df)
        logger.info(f"{symbol} @ {current_price:.4f} | Signal: {result.signal.value} | {result.reason}")

        # 5. Sentiment-Filter (cached 1h)
        sent = get_sentiment(symbol, use_ai=self.cfg.ai.enabled)
        self._sentiment[symbol] = sent

        # 6. Validate signal with AI (if enabled)
        if result.signal == Signal.BUY and not self.portfolio.has_position(symbol):
            if not sentiment_allowed(sent["score"]):
                logger.info(f"[SENTIMENT] BUY blockiert für {symbol}: {sent['label']} ({sent['score']:+.2f})")
                return
            validation = self.ai_validator.validate(symbol, result, df, current_price)
            if validation.approved:
                self._try_buy(symbol, current_price, df=df, signal_result=result, sentiment=sent)
            elif not validation.skipped:
                logger.info(f"[AI] BUY blocked for {symbol}: {validation.reasoning}")

        elif result.signal == Signal.SELL and self.portfolio.has_position(symbol):
            self._execute_sell(symbol, current_price, reason="signal")

    def _try_buy(self, symbol: str, current_price: float, df=None, signal_result=None, sentiment: dict | None = None) -> None:
        """Evaluate risk and place a buy order if approved."""
        if self.commander.is_paused:
            logger.info(f"Bot paused via Telegram — skipping BUY for {symbol}")
            return

        min_amount = self.exchange.get_min_order_amount(symbol)
        decision = self.risk.evaluate_trade(
            portfolio=self.portfolio,
            symbol=symbol,
            side="long",
            current_price=current_price,
            min_order_amount=min_amount,
            df=df,
        )

        if not decision.allowed:
            logger.info(f"Trade blocked for {symbol}: {decision.reason}")
            return

        # Apply Fear & Greed + Sentiment size multipliers
        combined_mult = self._fear_greed_mult
        if sentiment:
            combined_mult *= sentiment_mult(sentiment["score"])
        if combined_mult != 1.0:
            adjusted = min(decision.position_size_usd * combined_mult, self.portfolio.cash * 0.99)
            decision.position_size_usd = adjusted
            decision.amount = adjusted / current_price

        precision = self.exchange.get_amount_precision(symbol)
        amount = round(decision.amount, precision if isinstance(precision, int) else 8)

        try:
            order = self.exchange.create_market_buy(symbol, amount)
            fill_price = float(order.get("price") or current_price)

            self.portfolio.open_position(
                symbol=symbol, side="long", price=fill_price, amount=amount,
                stop_loss=decision.stop_loss_price, take_profit=decision.take_profit_price,
                order_id=order.get("id"),
            )

            # KI-Erklärung auf Deutsch + Telegram-Alert
            explanation = ""
            if signal_result and df is not None:
                explanation = self.ai_validator.explain_trade_de(
                    symbol, signal_result, df, fill_price,
                    stop_loss=decision.stop_loss_price,
                    take_profit=decision.take_profit_price,
                )
            self.telegram.trade_opened(
                symbol=symbol, price=fill_price, amount=amount,
                cost=decision.position_size_usd,
                stop_loss=decision.stop_loss_price,
                take_profit=decision.take_profit_price,
                strategy_reason=signal_result.reason if signal_result else "—",
                explanation=explanation,
            )
        except Exception as e:
            logger.error(f"Failed to place buy order for {symbol}: {e}")
            self.telegram.error(f"Kauf fehlgeschlagen {symbol}: {e}")

    def _execute_sell(self, symbol: str, current_price: float, reason: str = "signal") -> None:
        """Close an open position."""
        position = self.portfolio.get_position(symbol)
        if not position:
            return

        try:
            order = self.exchange.create_market_sell(symbol, position.amount)
            fill_price = float(order.get("price") or current_price)
            trade = self.portfolio.close_position(symbol, fill_price, reason=reason)

            # Telegram-Alert
            if trade:
                self.telegram.trade_closed(
                    symbol=symbol,
                    entry_price=trade.entry_price,
                    exit_price=trade.exit_price,
                    pnl=trade.pnl,
                    pnl_pct=trade.pnl_pct * 100,
                    reason=reason,
                    duration_hours=trade.duration_hours,
                )
        except Exception as e:
            logger.error(f"Failed to place sell order for {symbol}: {e}")
            self.telegram.error(f"Verkauf fehlgeschlagen {symbol}: {e}")

    def _get_sleep_seconds(self) -> int:
        """Return seconds until the next candle close."""
        tf_seconds = {
            "1m": 60, "3m": 180, "5m": 300, "15m": 900,
            "30m": 1800, "1h": 3600, "2h": 7200, "4h": 14400,
            "6h": 21600, "12h": 43200, "1d": 86400,
        }
        tf = self.cfg.trading.timeframe
        candle_seconds = tf_seconds.get(tf, 3600)
        now_ts = int(time.time())
        next_candle = ((now_ts // candle_seconds) + 1) * candle_seconds
        sleep = max(10, next_candle - now_ts - 5)  # 5s before candle close
        return sleep

    def _status_text(self) -> str:
        s = self.portfolio.summary()
        ret = s.get("total_return_pct", (s["current_value"] - s["initial_capital"]) / s["initial_capital"] * 100)
        fg = get_fear_greed()
        mode = "PAPER" if self.is_dry_run else "LIVE"
        lines = [
            f"📊 <b>Status — {mode}</b>",
            f"Wert: <b>{s['current_value']:.2f} USDT</b>",
            f"Rendite: {ret:+.2f}%  |  Drawdown: {s['drawdown_pct']:.2f}%",
            f"Trades: {s['total_trades']}  |  Win Rate: {s['win_rate_pct']:.1f}%",
            f"Fear & Greed: {fg_emoji(fg['value'])} {fg['value']} ({fg['label']})",
        ]
        for sym, sent in self._sentiment.items():
            lines.append(f"Sentiment {sym}: {sent_emoji(sent['score'])} {sent['label']} ({sent['score']:+.2f})")
        return "\n".join(lines)

    def _portfolio_text(self) -> str:
        s = self.portfolio.summary()
        lines = [
            f"📈 <b>Portfolio Detail</b>",
            f"Kapital: {s['initial_capital']:.2f} → {s['current_value']:.2f} USDT",
        ]
        for sym, pos in self.portfolio.positions.items():
            lines.append(f"• {sym}: {pos.amount:.6f} @ {pos.entry_price:.2f}")
        recent = self.portfolio.trade_history[-5:]
        if recent:
            lines.append("\n<b>Letzte Trades:</b>")
            for t in reversed(recent):
                lines.append(f"• {t.symbol}: {t.pnl:+.2f} USDT ({t.reason})")
        return "\n".join(lines)

    def _shutdown(self) -> None:
        summary = self.portfolio.summary()
        logger.info("=== Trading Session Summary ===")
        logger.info(f"Initial Capital:  {summary['initial_capital']:.2f}")
        logger.info(f"Final Value:      {summary['current_value']:.2f}")
        logger.info(f"Total Return:     {summary['total_return_pct']:.2f}%")
        logger.info(f"Total Trades:     {summary['total_trades']}")
        logger.info(f"Win Rate:         {summary['win_rate_pct']:.1f}%")
        logger.info(f"Max Drawdown:     {summary['drawdown_pct']:.2f}%")
