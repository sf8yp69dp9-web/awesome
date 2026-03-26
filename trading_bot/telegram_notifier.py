"""
Telegram Notifier
-----------------
Sendet Trade-Alerts und tägliche Reports direkt an dein Handy.

Setup:
1. Öffne Telegram → suche @BotFather
2. /newbot → Name vergeben → Token kopieren
3. Schreibe dem Bot eine Nachricht, dann:
   https://api.telegram.org/bot<TOKEN>/getUpdates
   → "chat":{"id": DEINE_ID}
4. In .env setzen:
   TELEGRAM_BOT_TOKEN=...
   TELEGRAM_CHAT_ID=...
"""
import json
import logging
import urllib.request
from datetime import datetime, date, timezone
from typing import Optional

logger = logging.getLogger(__name__)


class TelegramNotifier:
    """Sendet formatierte Trade-Nachrichten via Telegram Bot API."""

    def __init__(self, token: str, chat_id: str):
        self.token = token.strip()
        self.chat_id = chat_id.strip()
        self._enabled = bool(self.token and self.chat_id)
        self._last_summary_date: Optional[date] = None

        if self._enabled:
            logger.info(f"Telegram aktiviert (chat_id={self.chat_id[:6]}...)")
        else:
            logger.info("Telegram deaktiviert — TELEGRAM_BOT_TOKEN/CHAT_ID nicht gesetzt.")

    @property
    def is_enabled(self) -> bool:
        return self._enabled

    # ------------------------------------------------------------------
    # Öffentliche Nachrichten
    # ------------------------------------------------------------------

    def startup(self, strategy: str, symbol: str, capital: float, mode: str = "PAPER") -> None:
        mode_emoji = "📄" if mode == "PAPER" else "💸"
        self._send(
            f"🚀 <b>Trading Bot gestartet</b>\n\n"
            f"{mode_emoji} Modus: <b>{mode}</b>\n"
            f"📊 Symbol: <b>{symbol}</b>\n"
            f"⚡ Strategie: <b>{strategy.upper()}</b>\n"
            f"💰 Kapital: <b>{capital:,.2f} USDT</b>\n\n"
            f"<i>Du wirst bei jedem Trade benachrichtigt.</i>"
        )

    def trade_opened(
        self,
        symbol: str,
        price: float,
        amount: float,
        cost: float,
        stop_loss: Optional[float],
        take_profit: Optional[float],
        strategy_reason: str,
        explanation: str = "",
    ) -> None:
        sl_pct = (price - stop_loss) / price * 100 if stop_loss else 0
        tp_pct = (take_profit - price) / price * 100 if take_profit else 0

        lines = [
            "🟢 <b>KAUF ausgeführt</b>",
            "",
            f"📊 <b>{symbol}</b>",
            f"💰 Preis: <b>{price:,.2f} USDT</b>",
            f"📦 Menge: {amount:.6f}  ({cost:.2f} USDT)",
        ]
        if take_profit:
            lines.append(f"🎯 Take-Profit: {take_profit:,.2f}  (<b>+{tp_pct:.1f}%</b>)")
        if stop_loss:
            lines.append(f"🛡 Stop-Loss: {stop_loss:,.2f}  (<b>-{sl_pct:.1f}%</b>)")

        if explanation:
            lines += ["", "🤖 <i>KI-Analyse:</i>", f"<i>{explanation}</i>"]
        else:
            short_reason = strategy_reason[:120]
            lines += ["", f"⚡ <i>{short_reason}</i>"]

        self._send("\n".join(lines))

    def trade_closed(
        self,
        symbol: str,
        entry_price: float,
        exit_price: float,
        pnl: float,
        pnl_pct: float,
        reason: str,
        duration_hours: float,
    ) -> None:
        reasons_de = {
            "take_profit":        "🎯 Take-Profit erreicht",
            "stop_loss":          "🛡 Stop-Loss ausgelöst",
            "signal":             "📊 Verkaufssignal",
            "trailing_stop":      "📉 Trailing Stop",
            "end_of_simulation":  "⏹ Simulation beendet",
            "end_of_data":        "⏹ Datensatz-Ende",
            "max_drawdown":       "⚠️ Max Drawdown",
        }
        reason_str = reasons_de.get(reason, f"📋 {reason}")
        result_emoji = "✅" if pnl >= 0 else "❌"
        header_emoji = "🟡" if pnl >= 0 else "🔴"

        pnl_str = f"{pnl:+.2f} USDT  ({pnl_pct:+.2f}%)"

        lines = [
            f"{header_emoji} <b>VERKAUF ausgeführt</b>",
            "",
            f"📊 <b>{symbol}</b>",
            f"💰 Ausstieg: <b>{exit_price:,.2f} USDT</b>",
            f"📥 Einstieg: {entry_price:,.2f} USDT",
            f"{result_emoji} Ergebnis: <b>{pnl_str}</b>",
            f"⏱ Dauer: {duration_hours:.1f}h",
            f"📋 Grund: {reason_str}",
        ]
        self._send("\n".join(lines))

    def daily_summary(
        self,
        portfolio_value: float,
        initial_capital: float,
        daily_pnl: float,
        total_trades: int,
        win_rate: float,
        drawdown_pct: float,
        explanation: str = "",
    ) -> None:
        total_return = (portfolio_value - initial_capital) / initial_capital * 100
        pnl_emoji = "📈" if daily_pnl >= 0 else "📉"

        lines = [
            f"📊 <b>Tages-Report</b>  —  {datetime.now(timezone.utc).strftime('%d.%m.%Y')}",
            "",
            f"💼 Portfolio: <b>{portfolio_value:,.2f} USDT</b>  ({total_return:+.2f}%)",
            f"{pnl_emoji} Heute: <b>{daily_pnl:+.2f} USDT</b>",
            f"🔄 Trades gesamt: {total_trades}",
            f"🎯 Win Rate: {win_rate:.1f}%",
            f"📉 Drawdown: {drawdown_pct:.2f}%",
        ]
        if explanation:
            lines += ["", "🤖 <i>KI-Zusammenfassung:</i>", f"<i>{explanation}</i>"]

        self._send("\n".join(lines))
        self._last_summary_date = datetime.now(timezone.utc).date()

    def check_and_send_daily_summary(
        self,
        portfolio,
        target_hour_utc: int = 20,
        explanation: str = "",
    ) -> None:
        """Sendet automatisch um target_hour_utc Uhr UTC — einmal pro Tag."""
        now = datetime.now(timezone.utc)
        today = now.date()

        if now.hour != target_hour_utc:
            return
        if self._last_summary_date == today:
            return  # Heute schon gesendet

        summary = portfolio.summary()
        self.daily_summary(
            portfolio_value=summary["current_value"],
            initial_capital=summary["initial_capital"],
            daily_pnl=summary["daily_pnl"],
            total_trades=summary["total_trades"],
            win_rate=summary["win_rate_pct"],
            drawdown_pct=summary["drawdown_pct"],
            explanation=explanation,
        )

    def error(self, message: str) -> None:
        self._send(f"⚠️ <b>Bot-Fehler</b>\n\n<code>{message[:400]}</code>")

    def shutdown(self, portfolio) -> None:
        summary = portfolio.summary()
        total_return = (summary["current_value"] - summary["initial_capital"]) / summary["initial_capital"] * 100
        self._send(
            f"⏹ <b>Bot gestoppt</b>\n\n"
            f"💼 Endwert: <b>{summary['current_value']:,.2f} USDT</b>  ({total_return:+.2f}%)\n"
            f"🔄 Trades: {summary['total_trades']}  |  Win Rate: {summary['win_rate_pct']:.1f}%"
        )

    # ------------------------------------------------------------------
    # Intern
    # ------------------------------------------------------------------

    def _send(self, text: str) -> bool:
        if not self._enabled:
            return False
        try:
            url = f"https://api.telegram.org/bot{self.token}/sendMessage"
            payload = json.dumps({
                "chat_id": self.chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            }).encode("utf-8")
            req = urllib.request.Request(
                url, data=payload,
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                ok = resp.status == 200
                if not ok:
                    logger.warning(f"Telegram HTTP {resp.status}")
                return ok
        except Exception as e:
            logger.warning(f"Telegram send fehlgeschlagen: {e}")
            return False
