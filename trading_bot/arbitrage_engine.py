"""
Arbitrage Engine — überwacht Märkte und führt profitable Trades aus.

Läuft in einer schnellen Schleife (alle 5 Sekunden) und sucht nach
Dreiecks-Arbitrage Chancen. Bei Fund: Telegram-Alert + optionale Ausführung.
"""
import logging
import time
from datetime import datetime, timezone
from typing import Optional

from .config import BotConfig
from .exchange import ExchangeConnector, MockExchange
from .portfolio import Portfolio
from .arbitrage_scanner import ArbitrageScanner, ArbitrageOpportunity
from .telegram_notifier import TelegramNotifier
from .web_dashboard import WebDashboard
from .telegram_commander import TelegramCommander

logger = logging.getLogger(__name__)

SCAN_INTERVAL = 5      # Sekunden zwischen Scans
MAX_TRADES_PER_HOUR = 10
MIN_CAPITAL = 20.0     # Mindestkapital in USDT


class ArbitrageEngine:
    """
    Hauptschleife für Arbitrage-Trading.
    - Scannt alle 5 Sekunden auf Chancen
    - Sendet Telegram-Alerts bei Fund
    - Führt Trades aus (wenn auto_execute=True)
    - Zeigt Live-Stats im Dashboard
    """

    def __init__(self, config: BotConfig, auto_execute: bool = False):
        """
        auto_execute: True = echte Trades ausführen, False = nur Alerts
        """
        self.cfg = config
        self.auto_execute = auto_execute

        # Exchange
        real_exchange = ExchangeConnector(config.exchange)
        self.exchange = MockExchange(real_exchange)  # Immer Paper für Sicherheit

        self.portfolio = Portfolio(
            initial_capital=config.portfolio.initial_capital,
            base_currency=config.portfolio.base_currency,
            trade_log_path=config.logging.trade_log,
        )

        capital = min(config.portfolio.initial_capital * 0.1, 100.0)
        self.scanner = ArbitrageScanner(
            exchange=self.exchange,
            capital_usdt=max(capital, MIN_CAPITAL),
        )

        self.telegram = TelegramNotifier(config.telegram.token, config.telegram.chat_id)
        self.dashboard = WebDashboard(port=8080)
        self.commander = TelegramCommander(config.telegram.token, config.telegram.chat_id)

        self._running = False
        self._scan_count = 0
        self._opportunities_found = 0
        self._trades_executed = 0
        self._trades_this_hour = 0
        self._hour_reset_time = time.time()
        self._total_profit = 0.0
        self._best_opportunity: Optional[ArbitrageOpportunity] = None

    def run(self) -> None:
        """Startet die Arbitrage-Schleife."""
        self._running = True
        mode = "AUTO" if self.auto_execute else "ALERT-ONLY"
        logger.info(f"Arbitrage Engine gestartet | Modus: {mode}")

        # Dashboard + Commander starten
        self.dashboard.set_portfolio(self.portfolio, f"ARB-{mode}")
        self.dashboard.start()
        self.commander.on_stop = self.stop
        self.commander.on_status = self._status_text
        self.commander.start()

        # Startup-Nachricht
        self.telegram.send(
            f"🔺 <b>Arbitrage Bot gestartet</b>\n"
            f"Modus: {mode}\n"
            f"Kapital pro Trade: {self.scanner.capital:.2f} USDT\n"
            f"Min. Profit: {self.scanner.fee*300:.2f}% nach Fees\n"
            f"Scanne {len(self.scanner._get_all_symbols())} Paare..."
        )

        try:
            while self._running:
                self._scan_cycle()
                time.sleep(SCAN_INTERVAL)
        except KeyboardInterrupt:
            logger.info("Arbitrage Bot gestoppt.")
        finally:
            self.commander.stop()
            self._shutdown()

    def stop(self) -> None:
        self._running = False

    # ── Scan-Zyklus ───────────────────────────────────────────────────────

    def _scan_cycle(self) -> None:
        self._scan_count += 1
        self._reset_hourly_counter()

        try:
            result = self.scanner.scan()
        except Exception as e:
            logger.error(f"Scan Fehler: {e}")
            return

        logger.info(
            f"Scan #{self._scan_count} | {result.scanned} Dreiecke | "
            f"{len(result.opportunities)} Chancen | {result.duration_ms:.0f}ms"
        )

        if result.best:
            self._opportunities_found += 1

            if self._best_opportunity is None or result.best.profit_pct > self._best_opportunity.profit_pct:
                self._best_opportunity = result.best

            logger.info(f"CHANCE GEFUNDEN: {result.best}")
            self._alert_opportunity(result.best)

            if self.auto_execute and self._trades_this_hour < MAX_TRADES_PER_HOUR:
                self._execute(result.best)

        self.dashboard.record_equity(self.portfolio.total_value)

    # ── Ausführung ────────────────────────────────────────────────────────

    def _execute(self, opp: ArbitrageOpportunity) -> bool:
        """
        Führt einen Arbitrage-Trade aus.
        Gibt True zurück wenn erfolgreich.
        """
        logger.info(f"[ARB] Führe aus: {opp.route} | Erwarteter Profit: {opp.profit_pct:+.3f}%")

        pair_ab, pair_bc, pair_ac = opp.triangle
        capital = opp.capital_usdt

        try:
            # Schritt 1: USDT → A
            a_sym = pair_ab.split("/")[0]
            price_ab = opp.prices[pair_ab]
            amount_a = (capital / price_ab) * (1 - self.scanner.fee)
            order1 = self.exchange.create_market_buy(pair_ab, amount_a)
            fill1 = float(order1.get("price") or price_ab)
            actual_a = capital / fill1 * (1 - self.scanner.fee)
            logger.info(f"[ARB] 1/3 {capital:.2f} USDT → {actual_a:.6f} {a_sym} @ {fill1:.4f}")

            # Schritt 2: A → B
            b_sym = pair_bc.split("/")[0]
            price_bc = opp.prices[pair_bc]
            amount_b = (actual_a / price_bc) * (1 - self.scanner.fee)
            order2 = self.exchange.create_market_buy(pair_bc, amount_b)
            fill2 = float(order2.get("price") or price_bc)
            actual_b = actual_a / fill2 * (1 - self.scanner.fee)
            logger.info(f"[ARB] 2/3 {actual_a:.6f} {a_sym} → {actual_b:.6f} {b_sym} @ {fill2:.8f}")

            # Schritt 3: B → USDT
            price_ac = opp.prices[pair_ac]
            order3 = self.exchange.create_market_sell(pair_ac, actual_b)
            fill3 = float(order3.get("price") or price_ac)
            usdt_end = actual_b * fill3 * (1 - self.scanner.fee)
            logger.info(f"[ARB] 3/3 {actual_b:.6f} {b_sym} → {usdt_end:.4f} USDT @ {fill3:.4f}")

            # Profit berechnen
            actual_profit = usdt_end - capital
            actual_pct = actual_profit / capital * 100

            self._trades_executed += 1
            self._trades_this_hour += 1
            self._total_profit += actual_profit
            self.portfolio.cash += actual_profit

            logger.info(
                f"[ARB] ✓ Trade abgeschlossen | "
                f"Profit: {actual_profit:+.4f} USDT ({actual_pct:+.3f}%)"
            )

            self.telegram.send(
                f"✅ <b>Arbitrage Trade ausgeführt</b>\n"
                f"Route: {opp.route}\n"
                f"Einsatz: {capital:.2f} USDT\n"
                f"Profit: <b>{actual_profit:+.4f} USDT ({actual_pct:+.3f}%)</b>\n"
                f"Gesamt-Profit: {self._total_profit:+.4f} USDT"
            )
            return True

        except Exception as e:
            logger.error(f"[ARB] Trade Fehler: {e}")
            self.telegram.error(f"Arbitrage Trade fehlgeschlagen: {e}")
            return False

    # ── Alerts & Status ───────────────────────────────────────────────────

    def _alert_opportunity(self, opp: ArbitrageOpportunity) -> None:
        """Sendet Telegram-Alert für gefundene Chance."""
        mode_hint = "💡 Nur Alert-Modus" if not self.auto_execute else "🤖 Wird ausgeführt..."
        self.telegram.send(
            f"🔺 <b>Arbitrage Chance!</b>\n\n"
            f"Route: <b>{opp.route}</b>\n"
            f"Profit: <b>{opp.profit_pct:+.3f}%</b>\n"
            f"= {opp.profit_usdt:+.4f} USDT auf {opp.capital_usdt:.0f} USDT\n\n"
            f"Preise:\n"
            + "\n".join(f"  {k}: {v:.8g}" for k, v in opp.prices.items()) +
            f"\n\n{mode_hint}"
        )

    def _status_text(self) -> str:
        uptime_scans = self._scan_count
        rate = self._opportunities_found / max(uptime_scans, 1) * 100
        return (
            f"🔺 <b>Arbitrage Bot Status</b>\n"
            f"Modus: {'AUTO' if self.auto_execute else 'ALERT'}\n"
            f"Scans: {uptime_scans}\n"
            f"Chancen gefunden: {self._opportunities_found} ({rate:.1f}%)\n"
            f"Trades: {self._trades_executed}\n"
            f"Gesamt-Profit: <b>{self._total_profit:+.4f} USDT</b>\n"
            + (f"Beste Chance: {self._best_opportunity.profit_pct:+.3f}%\n" if self._best_opportunity else "")
        )

    def _reset_hourly_counter(self) -> None:
        if time.time() - self._hour_reset_time > 3600:
            self._trades_this_hour = 0
            self._hour_reset_time = time.time()

    def _shutdown(self) -> None:
        logger.info(
            f"=== Arbitrage Session Ende ===\n"
            f"Scans: {self._scan_count}\n"
            f"Chancen: {self._opportunities_found}\n"
            f"Trades: {self._trades_executed}\n"
            f"Gesamt-Profit: {self._total_profit:+.4f} USDT"
        )
        self.telegram.send(
            f"⏹ <b>Arbitrage Bot gestoppt</b>\n"
            f"Scans: {self._scan_count} | Trades: {self._trades_executed}\n"
            f"Gesamt-Profit: <b>{self._total_profit:+.4f} USDT</b>"
        )
