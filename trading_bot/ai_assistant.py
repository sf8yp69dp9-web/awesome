"""
AI-Assistent — Claude-powered Chatbot via Telegram.
Antwortet auf freie Textnachrichten, kennt den Trading-Bot-Kontext.
Gesprächsverlauf pro Chat-ID (max. 20 Nachrichten).
"""
import logging
from collections import deque
from typing import Callable, Optional

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """Du bist ein persönlicher KI-Assistent und Crypto-Experte für einen Trading-Bot-Nutzer.

Deine Persönlichkeit:
- Freundlich, direkt, auf Augenhöhe — kein unnötiges "Natürlich!" oder "Gerne!"
- Antwortest auf Deutsch wenn der Nutzer Deutsch schreibt
- Kurze, präzise Antworten (max. 3-4 Sätze, außer der Nutzer fragt nach Details)
- Nutzt Emojis sparsam aber passend
- Bei Zahlen/Preisen immer aktuelle Kontext erwähnen

Dein Wissen:
- Vollständige Kenntnis des Trading-Bots: Ensemble-Strategie (EMA+RSI+MACD), ADX-Filter, ATR-Stops, Fear & Greed, Sentiment-Analyzer
- Crypto-Märkte: BTC, ETH, Altcoins, DeFi, NFTs, Regulierung
- Trading: Technische Analyse, Risikomanagement, Portfolio-Strategien
- Allgemeinwissen: alles was ein persönlicher Assistent wissen sollte

Befehle des Bots (zur Info):
/status — Portfolio-Status
/portfolio — Detaillierter Überblick
/pause — Bot pausieren
/resume — Bot fortsetzen
/stop — Bot beenden
/hilfe — Alle Befehle

Alles was kein Befehl ist → du beantwortest es als Assistent."""


class AIAssistant:
    """
    Claude-powered Chatbot-Assistent für Telegram.
    Wird von TelegramCommander für Nicht-Befehls-Nachrichten aufgerufen.
    """

    def __init__(self, get_status_fn: Optional[Callable[[], str]] = None):
        """
        get_status_fn: Callback um aktuellen Bot-Status als Text zu holen.
        Wird automatisch in den Kontext eingebunden wenn vorhanden.
        """
        self._history: dict[int, deque] = {}   # chat_id → deque of messages
        self._get_status = get_status_fn
        self._max_history = 20
        self._enabled = self._check_api()

    def _check_api(self) -> bool:
        try:
            import anthropic  # noqa: F401
            import os
            return bool(os.environ.get("ANTHROPIC_API_KEY"))
        except ImportError:
            logger.warning("anthropic nicht installiert — AI-Assistent deaktiviert")
            return False

    def chat(self, chat_id: int, user_message: str) -> str:
        """
        Verarbeitet eine Nutzernachricht und gibt die KI-Antwort zurück.
        Gibt leeren String zurück wenn KI nicht verfügbar.
        """
        if not self._enabled:
            return "❌ KI-Assistent nicht verfügbar. ANTHROPIC_API_KEY fehlt."

        if chat_id not in self._history:
            self._history[chat_id] = deque(maxlen=self._max_history)

        history = self._history[chat_id]

        # Aktuellen Bot-Status in System-Prompt einbinden
        system = _SYSTEM_PROMPT
        if self._get_status:
            try:
                status = self._get_status()
                # Strip HTML tags for plain text context
                import re
                status_plain = re.sub(r"<[^>]+>", "", status)
                system += f"\n\nAktueller Bot-Status:\n{status_plain}"
            except Exception:
                pass

        # Nachricht zu History hinzufügen
        history.append({"role": "user", "content": user_message})

        try:
            import anthropic
            client = anthropic.Anthropic()
            response = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=512,
                system=system,
                messages=list(history),
            )
            reply = response.content[0].text.strip()
            history.append({"role": "assistant", "content": reply})
            return reply

        except Exception as e:
            logger.error(f"AI-Assistent Fehler: {e}")
            history.pop()   # Fehlgeschlagene Nachricht aus History entfernen
            return f"⚠️ Fehler: {e}"

    def clear_history(self, chat_id: int) -> None:
        """Gesprächsverlauf für einen Chat löschen."""
        self._history.pop(chat_id, None)

    @property
    def enabled(self) -> bool:
        return self._enabled
