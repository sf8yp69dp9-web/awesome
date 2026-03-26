"""
Telegram Commander — empfängt Befehle von deinem Handy und steuert den Bot.

Befehle:
  /status     → Portfolio-Übersicht
  /portfolio  → Detaillierter Report
  /pause      → Kein Kauf mehr (läuft weiter, schützt offene Positionen)
  /resume     → Kaufen wieder aktiviert
  /stop       → Bot sauber beenden
  /hilfe      → Alle Befehle anzeigen
"""
import json
import logging
import threading
import urllib.request
from typing import Callable, Optional

logger = logging.getLogger(__name__)

HILFE_TEXT = """🤖 <b>TradingMaschiene — Befehle</b>

/status    — Portfolio-Übersicht
/portfolio — Alle Trades & Positionen
/pause     — Neue Käufe pausieren
/resume    — Käufe wieder aktivieren
/stop      — Bot stoppen
/hilfe     — Diese Hilfe"""


class TelegramCommander:
    """
    Läuft im Hintergrund-Thread und pollt Telegram auf neue Befehle.
    Kommuniziert mit der TradingEngine über einfache Callback-Funktionen.
    """

    def __init__(self, token: str, chat_id: str):
        self.token = token.strip()
        self.chat_id = chat_id.strip()
        self._enabled = bool(token and chat_id)
        self._offset = 0
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._paused = False

        # Callbacks — von Engine gesetzt
        self.on_stop: Optional[Callable] = None
        self.on_status: Optional[Callable[[], str]] = None
        self.on_portfolio: Optional[Callable[[], str]] = None

        if self._enabled:
            logger.info("Telegram Commander bereit — empfange Befehle")

    @property
    def is_paused(self) -> bool:
        return self._paused

    def start(self) -> None:
        if not self._enabled:
            return
        self._running = True
        self._thread = threading.Thread(target=self._poll_loop, daemon=True, name="TelegramCommander")
        self._thread.start()

    def stop(self) -> None:
        self._running = False

    # ------------------------------------------------------------------
    # Intern
    # ------------------------------------------------------------------

    def _poll_loop(self) -> None:
        import time
        while self._running:
            try:
                updates = self._get_updates()
                for update in updates:
                    self._handle(update)
                    self._offset = update["update_id"] + 1
            except Exception as e:
                logger.debug(f"Commander poll: {e}")
            time.sleep(2)

    def _get_updates(self) -> list:
        url = (
            f"https://api.telegram.org/bot{self.token}/getUpdates"
            f"?offset={self._offset}&timeout=1&limit=10"
        )
        with urllib.request.urlopen(url, timeout=5) as resp:
            data = json.loads(resp.read())
        return data.get("result", [])

    def _handle(self, update: dict) -> None:
        msg = update.get("message", {})
        chat_id = str(msg.get("chat", {}).get("id", ""))
        text = (msg.get("text") or "").strip().lower()

        if chat_id != self.chat_id or not text:
            return

        logger.info(f"Telegram Befehl: {text}")

        if text in ("/hilfe", "/help", "/start"):
            self._send(HILFE_TEXT)

        elif text == "/status":
            reply = self.on_status() if self.on_status else "⚠️ Status nicht verfügbar."
            self._send(reply)

        elif text == "/portfolio":
            reply = self.on_portfolio() if self.on_portfolio else "⚠️ Portfolio nicht verfügbar."
            self._send(reply)

        elif text == "/pause":
            self._paused = True
            self._send("⏸ <b>Bot pausiert.</b>\nKeine neuen Käufe. Offene Positionen werden weiter überwacht.")

        elif text == "/resume":
            self._paused = False
            self._send("▶️ <b>Bot fortgesetzt.</b>\nNeue Käufe wieder aktiv.")

        elif text == "/stop":
            self._send("⏹ <b>Bot wird gestoppt...</b>\nOffene Positionen werden geschlossen.")
            if self.on_stop:
                self.on_stop()

        else:
            self._send(f"❓ Unbekannter Befehl: <code>{text}</code>\n\n/hilfe für alle Befehle.")

    def _send(self, text: str) -> None:
        try:
            url = f"https://api.telegram.org/bot{self.token}/sendMessage"
            payload = json.dumps({
                "chat_id": self.chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            }).encode()
            req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=10)
        except Exception as e:
            logger.debug(f"Commander send fehlgeschlagen: {e}")
