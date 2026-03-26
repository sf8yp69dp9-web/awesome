"""
Crypto Sentiment Analyzer
Quellen: Reddit JSON API + CryptoPanic News + Claude KI
Score: -1.0 (sehr negativ) bis +1.0 (sehr positiv)
Cache: 1 Stunde
"""
import json
import logging
import re
import urllib.request
import urllib.parse
from datetime import datetime, timezone, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

# ── Cache ────────────────────────────────────────────────────────────────────
_CACHE: dict[str, dict] = {}   # symbol → {score, label, sources, fetched_at}
_CACHE_TTL = timedelta(hours=1)

# ── Mapping coin → Reddit-Subreddits ─────────────────────────────────────────
_SUBREDDITS: dict[str, list[str]] = {
    "BTC":  ["Bitcoin", "CryptoCurrency"],
    "ETH":  ["ethereum", "CryptoCurrency"],
    "BNB":  ["binance", "CryptoCurrency"],
    "SOL":  ["solana", "CryptoCurrency"],
    "ADA":  ["cardano", "CryptoCurrency"],
    "DEFAULT": ["CryptoCurrency", "CryptoMarkets"],
}

# ── Einfache Keyword-Gewichte (VADER-ähnlich, offline) ───────────────────────
_POS = {"bull", "bullish", "moon", "pump", "surge", "rally", "ath", "buy",
        "gain", "profit", "up", "rise", "green", "breakout", "adoption",
        "partnership", "launch", "milestone", "record", "strong", "🚀", "💎"}
_NEG = {"bear", "bearish", "crash", "dump", "sell", "loss", "down", "fall",
        "red", "scam", "hack", "fraud", "ban", "regulation", "sec", "lawsuit",
        "collapse", "fear", "panic", "rug", "dead", "rekt", "warn", "drop", "📉"}


def _keyword_score(text: str) -> float:
    """Schneller keyword-basierter Score ohne externe Libs."""
    words = set(re.findall(r"\w+|[🚀💎📉]", text.lower()))
    pos = len(words & _POS)
    neg = len(words & _NEG)
    total = pos + neg
    if total == 0:
        return 0.0
    return (pos - neg) / total


def _fetch_reddit(symbol: str, limit: int = 25) -> list[str]:
    """Holt Titel der Top-Posts aus Reddit (keine Auth nötig)."""
    coin = symbol.split("/")[0].upper()
    subreddits = _SUBREDDITS.get(coin, _SUBREDDITS["DEFAULT"])
    titles = []
    for sub in subreddits[:2]:
        try:
            url = f"https://www.reddit.com/r/{sub}/hot.json?limit={limit}"
            req = urllib.request.Request(url, headers={"User-Agent": "TradingBot/1.0"})
            with urllib.request.urlopen(req, timeout=6) as resp:
                data = json.loads(resp.read())
                for post in data["data"]["children"]:
                    titles.append(post["data"]["title"])
        except Exception as e:
            logger.debug(f"Reddit {sub} fetch error: {e}")
    return titles


def _fetch_cryptopanic(symbol: str) -> list[str]:
    """Holt aktuelle News von CryptoPanic (kostenlose API, kein Key nötig)."""
    coin = symbol.split("/")[0].upper()
    try:
        url = f"https://cryptopanic.com/api/v1/posts/?auth_token=anonymous&currencies={coin}&public=true"
        with urllib.request.urlopen(url, timeout=6) as resp:
            data = json.loads(resp.read())
            return [item["title"] for item in data.get("results", [])[:20]]
    except Exception as e:
        logger.debug(f"CryptoPanic fetch error: {e}")
        return []


def _ai_score(texts: list[str], symbol: str) -> Optional[float]:
    """
    Nutzt Claude Haiku für tiefere Sentiment-Analyse.
    Gibt Score -1.0…+1.0 zurück, oder None wenn KI nicht verfügbar.
    """
    try:
        import anthropic
        client = anthropic.Anthropic()
        sample = "\n".join(f"- {t}" for t in texts[:15])
        prompt = (
            f"Analysiere das Krypto-Sentiment für {symbol} anhand dieser Schlagzeilen:\n\n"
            f"{sample}\n\n"
            "Antworte NUR mit einer Zahl zwischen -1.0 (sehr negativ) und +1.0 (sehr positiv). "
            "Beispiel: 0.3"
        )
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=10,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = msg.content[0].text.strip()
        score = float(re.search(r"-?\d+\.?\d*", raw).group())
        return max(-1.0, min(1.0, score))
    except Exception as e:
        logger.debug(f"AI sentiment error: {e}")
        return None


def _label(score: float) -> str:
    if score <= -0.6:  return "Sehr Negativ"
    elif score <= -0.2: return "Negativ"
    elif score < 0.2:   return "Neutral"
    elif score < 0.6:   return "Positiv"
    else:               return "Sehr Positiv"


def emoji(score: float) -> str:
    if score <= -0.6:  return "😱"
    elif score <= -0.2: return "😟"
    elif score < 0.2:   return "😐"
    elif score < 0.6:   return "😊"
    else:               return "🚀"


def get_sentiment(symbol: str, use_ai: bool = True) -> dict:
    """
    Hauptfunktion — gibt Sentiment für ein Symbol zurück.

    Returns:
        {
          "score":   float,   # -1.0 … +1.0
          "label":  str,      # "Positiv" etc.
          "sources": int,     # Anzahl ausgewerteter Texte
          "reddit":  float,   # Roh-Score Reddit
          "news":    float,   # Roh-Score News
          "ai":      float|None,
        }
    """
    now = datetime.now(timezone.utc)
    cached = _CACHE.get(symbol)
    if cached and now - cached["fetched_at"] < _CACHE_TTL:
        return cached["data"]

    # 1. Daten holen
    reddit_titles = _fetch_reddit(symbol)
    news_titles   = _fetch_cryptopanic(symbol)
    all_texts     = reddit_titles + news_titles

    # 2. Keyword-Score
    if all_texts:
        reddit_score = sum(_keyword_score(t) for t in reddit_titles) / max(len(reddit_titles), 1)
        news_score   = sum(_keyword_score(t) for t in news_titles)   / max(len(news_titles), 1)
        kw_score = (reddit_score * 0.5 + news_score * 0.5)
    else:
        reddit_score = news_score = kw_score = 0.0

    # 3. KI-Score (optional)
    ai_score = None
    if use_ai and all_texts:
        ai_score = _ai_score(all_texts, symbol)

    # 4. Finaler Score: KI 60% + Keywords 40% (wenn KI verfügbar)
    if ai_score is not None:
        final = ai_score * 0.6 + kw_score * 0.4
    else:
        final = kw_score

    final = round(max(-1.0, min(1.0, final)), 3)

    result = {
        "score":   final,
        "label":   _label(final),
        "sources": len(all_texts),
        "reddit":  round(reddit_score, 3),
        "news":    round(news_score, 3),
        "ai":      ai_score,
    }

    _CACHE[symbol] = {"data": result, "fetched_at": now}
    logger.info(
        f"Sentiment {symbol}: {final:+.2f} ({result['label']}) "
        f"| Reddit:{reddit_score:+.2f} News:{news_score:+.2f} AI:{ai_score} "
        f"| {len(all_texts)} Quellen"
    )
    return result


def trade_allowed(score: float, threshold: float = -0.4) -> bool:
    """Blockiert Käufe bei sehr negativem Sentiment."""
    return score >= threshold


def position_multiplier(score: float) -> float:
    """
    Passt Positionsgröße basierend auf Sentiment an:
    -1.0…-0.4 → 0.0× (kein Kauf)
    -0.4…-0.2 → 0.7×
    -0.2…+0.2 → 1.0×
     0.2…+0.6 → 1.2×
     0.6…+1.0 → 1.4×
    """
    if score < -0.4:   return 0.0
    elif score < -0.2: return 0.7
    elif score < 0.2:  return 1.0
    elif score < 0.6:  return 1.2
    else:              return 1.4
