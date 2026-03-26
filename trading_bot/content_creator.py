"""
Content Creator — KI-generierte Crypto-Posts für Social Media.
Schreibt täglich automatisch Posts für Instagram, X (Twitter) und Telegram-Kanal.
Nutzt Claude Haiku für Text + generiert DALL-E Prompts für Bilder.
"""
import json
import logging
import os
import threading
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# ── Plattform-Formate ────────────────────────────────────────────────────────
PLATFORMS = {
    "telegram": {"max_chars": 4096, "hashtags": 5,  "emoji": True},
    "twitter":  {"max_chars": 280,  "hashtags": 3,  "emoji": True},
    "instagram":{"max_chars": 2200, "hashtags": 30, "emoji": True},
}

# ── Post-Themen (rotieren täglich) ──────────────────────────────────────────
TOPICS = [
    "Bitcoin Marktanalyse & Trend",
    "Ethereum & DeFi Update",
    "Fear & Greed Index Analyse",
    "Trading-Strategie Tipp des Tages",
    "Krypto News & Regulierung",
    "Portfolio-Management Lektion",
    "Altcoin-Spotlight",
    "Technische Analyse Grundlagen",
    "Risikomanagement im Krypto-Trading",
    "KI im Trading — Chancen & Grenzen",
]

_SYSTEM = """Du bist ein Krypto-Content-Creator mit 50.000 Followern.
Dein Stil: informativ aber unterhaltsam, professionell aber nicht arrogant.
Nutze aktuelle Crypto-Begriffe natürlich. Keine Finanzberatung!
Schreibe NUR den Post-Text, keine Erklärungen darum."""


class ContentDraft:
    """Ein generierter Post-Entwurf."""

    def __init__(self, platform: str, topic: str, text: str, image_prompt: str,
                 hashtags: list[str], created_at: datetime):
        self.platform = platform
        self.topic = topic
        self.text = text
        self.image_prompt = image_prompt
        self.hashtags = hashtags
        self.created_at = created_at

    def full_text(self) -> str:
        """Text + Hashtags kombiniert."""
        tags = " ".join(f"#{h}" for h in self.hashtags)
        if self.platform == "twitter":
            # Twitter: Hashtags im Text sparen
            combined = f"{self.text}\n\n{tags}"
            return combined[:280]
        return f"{self.text}\n\n{tags}"

    def to_dict(self) -> dict:
        return {
            "platform":     self.platform,
            "topic":        self.topic,
            "text":         self.text,
            "image_prompt": self.image_prompt,
            "hashtags":     self.hashtags,
            "full_text":    self.full_text(),
            "created_at":   self.created_at.isoformat(),
            "chars":        len(self.full_text()),
        }


class ContentCreator:
    """
    Generiert automatisch Crypto-Posts mit Claude KI.
    Kann manuell oder automatisch täglich getriggert werden.
    """

    def __init__(self, post_hour_utc: int = 9, auto_send_telegram: bool = False,
                 telegram_token: str = "", telegram_channel_id: str = ""):
        """
        post_hour_utc: Stunde (UTC) für täglichen Auto-Post (Standard: 9 Uhr)
        auto_send_telegram: Postet automatisch in Telegram-Kanal wenn True
        telegram_token/channel_id: Für Auto-Post in Kanal (nicht Chat)
        """
        self.post_hour_utc = post_hour_utc
        self.auto_send_telegram = auto_send_telegram
        self.telegram_token = telegram_token
        self.telegram_channel_id = telegram_channel_id

        self._enabled = self._check_api()
        self._last_post_date = None
        self._drafts: list[ContentDraft] = []
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    def _check_api(self) -> bool:
        try:
            import anthropic  # noqa: F401
            return bool(os.environ.get("ANTHROPIC_API_KEY"))
        except ImportError:
            logger.warning("anthropic nicht installiert — Content Creator deaktiviert")
            return False

    # ── Post generieren ──────────────────────────────────────────────────────

    def generate(self, platform: str = "telegram", topic: str = "",
                 context: str = "") -> Optional[ContentDraft]:
        """
        Generiert einen Post-Entwurf.

        platform: "telegram" | "twitter" | "instagram"
        topic: Thema (leer = automatisch wählen)
        context: Zusatz-Info (z.B. aktueller Bot-Status, Preis)
        """
        if not self._enabled:
            logger.warning("Content Creator: ANTHROPIC_API_KEY fehlt")
            return None

        if not topic:
            topic = self._pick_topic()

        cfg = PLATFORMS.get(platform, PLATFORMS["telegram"])
        max_chars = cfg["max_chars"] - 200  # Puffer für Hashtags

        prompt = self._build_prompt(platform, topic, max_chars, context)

        try:
            import anthropic
            client = anthropic.Anthropic()

            # Post-Text generieren
            response = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=600,
                system=_SYSTEM,
                messages=[{"role": "user", "content": prompt}],
            )
            text = response.content[0].text.strip()

            # Hashtags generieren
            hashtags = self._generate_hashtags(topic, platform, cfg["hashtags"])

            # DALL-E Prompt generieren
            image_prompt = self._generate_image_prompt(topic, text)

            draft = ContentDraft(
                platform=platform,
                topic=topic,
                text=text,
                image_prompt=image_prompt,
                hashtags=hashtags,
                created_at=datetime.now(timezone.utc),
            )

            with self._lock:
                self._drafts.append(draft)
                if len(self._drafts) > 50:
                    self._drafts.pop(0)

            logger.info(f"Content erstellt: {platform} | {topic[:40]} | {len(draft.full_text())} Zeichen")
            return draft

        except Exception as e:
            logger.error(f"Content Creator Fehler: {e}")
            return None

    def generate_all_platforms(self, topic: str = "", context: str = "") -> dict[str, ContentDraft]:
        """Generiert Posts für alle 3 Plattformen gleichzeitig."""
        results = {}
        for platform in PLATFORMS:
            draft = self.generate(platform=platform, topic=topic, context=context)
            if draft:
                results[platform] = draft
        return results

    def get_drafts(self, limit: int = 10) -> list[ContentDraft]:
        """Letzte N Entwürfe zurückgeben."""
        with self._lock:
            return list(reversed(self._drafts[-limit:]))

    # ── Auto-Scheduler ───────────────────────────────────────────────────────

    def start_scheduler(self) -> None:
        """Startet Background-Thread für tägliche Auto-Posts."""
        if not self._enabled:
            return
        self._thread = threading.Thread(
            target=self._scheduler_loop, daemon=True, name="ContentCreator"
        )
        self._thread.start()
        logger.info(f"Content Creator Scheduler gestartet (täglich {self.post_hour_utc}:00 UTC)")

    def _scheduler_loop(self) -> None:
        import time
        while True:
            now = datetime.now(timezone.utc)
            today = now.date()
            if (now.hour == self.post_hour_utc and
                    self._last_post_date != today):
                self._daily_post(now)
                self._last_post_date = today
            time.sleep(60)

    def _daily_post(self, now: datetime) -> None:
        topic = self._pick_topic_by_weekday(now.weekday())
        logger.info(f"[ContentCreator] Täglicher Post: {topic}")

        # Telegram-Post (immer generieren)
        draft = self.generate(platform="telegram", topic=topic)
        if draft and self.auto_send_telegram and self.telegram_token:
            self._send_telegram(draft.full_text())

    # ── Hilfsmethoden ────────────────────────────────────────────────────────

    def _pick_topic(self) -> str:
        day_of_year = datetime.now(timezone.utc).timetuple().tm_yday
        return TOPICS[day_of_year % len(TOPICS)]

    def _pick_topic_by_weekday(self, weekday: int) -> str:
        topic_map = {
            0: "Bitcoin Marktanalyse & Trend",        # Montag
            1: "Trading-Strategie Tipp des Tages",    # Dienstag
            2: "Fear & Greed Index Analyse",           # Mittwoch
            3: "Altcoin-Spotlight",                    # Donnerstag
            4: "Krypto News & Regulierung",            # Freitag
            5: "Portfolio-Management Lektion",         # Samstag
            6: "KI im Trading — Chancen & Grenzen",   # Sonntag
        }
        return topic_map.get(weekday, TOPICS[0])

    def _build_prompt(self, platform: str, topic: str, max_chars: int, context: str) -> str:
        ctx_block = f"\n\nAktueller Kontext:\n{context}" if context else ""
        style = {
            "telegram": "Ausführlicher, informativer Post mit Struktur. Nutze Emojis sparsam.",
            "twitter":  f"Kurz, prägnant, maximal {max_chars} Zeichen. Ein starker Hook-Satz am Anfang.",
            "instagram": "Storytelling-Stil. Persönlich, inspirierend. Mit Call-to-Action am Ende.",
        }.get(platform, "")

        return (
            f"Schreibe einen {platform.capitalize()}-Post zum Thema: <b>{topic}</b>\n\n"
            f"Stil: {style}\n"
            f"Sprache: Deutsch\n"
            f"Max. Zeichen: {max_chars}{ctx_block}\n\n"
            f"Wichtig: Kein 'Als KI...' oder 'Ich bin...' — schreibe direkt als Creator."
        )

    def _generate_hashtags(self, topic: str, platform: str, count: int) -> list[str]:
        """Generiert passende Hashtags basierend auf Thema."""
        base = ["Krypto", "Bitcoin", "Crypto", "Trading", "BTC"]
        topic_tags = {
            "Bitcoin": ["BTC", "Bitcoin", "BitcoinTrading"],
            "Ethereum": ["ETH", "Ethereum", "DeFi"],
            "Fear": ["FearAndGreed", "CryptoSentiment", "MarketPsychology"],
            "Strategie": ["TradingStrategy", "TechnicalAnalysis", "TA"],
            "KI": ["AITrading", "KITrading", "AlgoTrading"],
            "Altcoin": ["Altcoins", "Altseason", "CryptoGems"],
            "Portfolio": ["Portfolio", "Risikomanagement", "HODL"],
            "News": ["CryptoNews", "Blockchain", "Web3"],
        }
        extra = []
        for key, tags in topic_tags.items():
            if key.lower() in topic.lower():
                extra = tags
                break
        all_tags = (extra + base)[:count]
        return all_tags

    def _generate_image_prompt(self, topic: str, post_text: str) -> str:
        """Generiert einen DALL-E Prompt für ein passendes Bild."""
        try:
            import anthropic
            client = anthropic.Anthropic()
            resp = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=100,
                messages=[{"role": "user", "content":
                    f"Schreibe einen kurzen DALL-E Bildprompt (Englisch, max. 50 Wörter) "
                    f"für einen Social-Media-Post über: {topic}. "
                    f"Stil: cinematic, futuristic crypto aesthetic, dark blue/gold color scheme. "
                    f"Nur den Prompt, keine Erklärung."
                }],
            )
            return resp.content[0].text.strip()
        except Exception:
            return f"Futuristic crypto trading visualization, {topic}, dark blue gold aesthetic, 4k cinematic"

    def _send_telegram(self, text: str) -> None:
        """Sendet Post an Telegram-Kanal."""
        import urllib.request
        try:
            url = f"https://api.telegram.org/bot{self.telegram_token}/sendMessage"
            payload = json.dumps({
                "chat_id": self.telegram_channel_id,
                "text": text,
                "parse_mode": "HTML",
            }).encode()
            req = urllib.request.Request(
                url, data=payload,
                headers={"Content-Type": "application/json"}
            )
            urllib.request.urlopen(req, timeout=10)
            logger.info("Content Creator: Telegram-Post gesendet")
        except Exception as e:
            logger.error(f"Content Creator Telegram-Fehler: {e}")
