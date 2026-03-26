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

📊 <b>Trading</b>
/status    — Portfolio-Übersicht
/portfolio — Alle Trades & Positionen
/pause     — Neue Käufe pausieren
/resume    — Käufe wieder aktivieren
/stop      — Bot stoppen

✍️ <b>Content Creator</b>
/post      — Post für alle Plattformen generieren
/post btc  — Post zu einem Thema generieren
/drafts    — Letzte 5 Entwürfe anzeigen

💬 <b>AI-Assistent</b>
/reset     — Gesprächsverlauf löschen
/hilfe     — Diese Hilfe

<i>Oder schreib einfach eine Frage — KI antwortet direkt!</i>"""


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

        # Lazy-init Module
        self._assistant = None
        self._creator = None

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

    def _get_assistant(self):
        if self._assistant is None:
            from .ai_assistant import AIAssistant
            self._assistant = AIAssistant(get_status_fn=self.on_status)
        return self._assistant

    def _get_creator(self):
        if self._creator is None:
            from .content_creator import ContentCreator
            self._creator = ContentCreator(
                telegram_token=self.token,
                telegram_channel_id=self.chat_id,
            )
        return self._creator

    def _handle(self, update: dict) -> None:
        msg = update.get("message", {})
        chat_id_int = msg.get("chat", {}).get("id")
        chat_id = str(chat_id_int or "")
        text = (msg.get("text") or "").strip()

        if chat_id != self.chat_id or not text:
            return

        cmd = text.lower()
        logger.info(f"Telegram Nachricht: {text[:60]}")

        if cmd in ("/hilfe", "/help", "/start"):
            self._send(HILFE_TEXT)

        elif cmd == "/status":
            reply = self.on_status() if self.on_status else "⚠️ Status nicht verfügbar."
            self._send(reply)

        elif cmd == "/portfolio":
            reply = self.on_portfolio() if self.on_portfolio else "⚠️ Portfolio nicht verfügbar."
            self._send(reply)

        elif cmd == "/pause":
            self._paused = True
            self._send("⏸ <b>Bot pausiert.</b>\nKeine neuen Käufe. Offene Positionen werden weiter überwacht.")

        elif cmd == "/resume":
            self._paused = False
            self._send("▶️ <b>Bot fortgesetzt.</b>\nNeue Käufe wieder aktiv.")

        elif cmd == "/stop":
            self._send("⏹ <b>Bot wird gestoppt...</b>\nOffene Positionen werden geschlossen.")
            if self.on_stop:
                self.on_stop()

        elif cmd == "/reset":
            self._get_assistant().clear_history(chat_id_int)
            self._send("🔄 Gesprächsverlauf gelöscht. Frischer Start!")

        elif cmd.startswith("/post"):
            topic = text[5:].strip() or ""
            self._send("✍️ <i>Generiere Posts für alle Plattformen...</i>")
            creator = self._get_creator()
            if not creator:
                self._send("❌ Content Creator nicht verfügbar. ANTHROPIC_API_KEY fehlt.")
                return
            context = self.on_status() if self.on_status else ""
            drafts = creator.generate_all_platforms(topic=topic, context=context)
            if not drafts:
                self._send("❌ Fehler beim Generieren. Bitte erneut versuchen.")
                return
            for platform, draft in drafts.items():
                icons = {"telegram": "📱", "twitter": "🐦", "instagram": "📸"}
                icon = icons.get(platform, "📝")
                self._send(
                    f"{icon} <b>{platform.capitalize()}</b> ({len(draft.full_text())} Zeichen)\n\n"
                    f"{draft.full_text()}\n\n"
                    f"🎨 <i>Bild-Prompt:</i>\n<code>{draft.image_prompt}</code>"
                )

        elif cmd == "/drafts":
            creator = self._get_creator()
            if not creator:
                self._send("❌ Content Creator nicht verfügbar.")
                return
            drafts = creator.get_drafts(5)
            if not drafts:
                self._send("📭 Noch keine Entwürfe. Schreibe /post um einen zu erstellen.")
                return
            for d in drafts:
                ts = d.created_at.strftime("%d.%m %H:%M")
                self._send(
                    f"📝 <b>{d.platform.capitalize()}</b> · {ts}\n"
                    f"Thema: {d.topic}\n\n"
                    f"{d.full_text()[:300]}{'...' if len(d.full_text())>300 else ''}"
                )

        else:
            # Freie Textnachricht → AI-Assistent
            self._send("💭 <i>Denke nach...</i>")
            reply = self._get_assistant().chat(chat_id_int, text)
            self._send(reply)

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
