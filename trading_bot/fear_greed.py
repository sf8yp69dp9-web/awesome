"""Fear & Greed Index — holt täglichen Krypto-Sentiment von alternative.me."""
import json
import logging
import urllib.request
from datetime import datetime, timezone, date
from typing import Optional

logger = logging.getLogger(__name__)

_CACHE: dict = {"date": None, "value": None, "label": None}


def get_fear_greed() -> dict:
    """
    Gibt Fear & Greed Index zurück: {"value": 42, "label": "Fear"}.
    Cached für den Tag. Bei Netzwerkfehler: {"value": 50, "label": "Neutral"}.
    """
    today = datetime.now(timezone.utc).date()
    if _CACHE["date"] == today and _CACHE["value"] is not None:
        return {"value": _CACHE["value"], "label": _CACHE["label"]}

    try:
        url = "https://api.alternative.me/fng/?limit=1&format=json"
        with urllib.request.urlopen(url, timeout=5) as resp:
            data = json.loads(resp.read())["data"][0]
            value = int(data["value"])
            label = data["value_classification"]
            _CACHE.update(date=today, value=value, label=label)
            logger.info(f"Fear & Greed Index: {value} ({label})")
            return {"value": value, "label": label}
    except Exception as e:
        logger.warning(f"Fear & Greed fetch fehlgeschlagen: {e} — verwende Neutral (50)")
        return {"value": 50, "label": "Neutral"}


def position_size_multiplier(fear_greed_value: int) -> float:
    """
    Passt Positionsgröße basierend auf Sentiment an:
    - Extreme Fear  (<20) → 1.5× (mehr kaufen — Markt übertreibt)
    - Fear          (20-40) → 1.2×
    - Neutral       (40-60) → 1.0×
    - Greed         (60-80) → 0.8×
    - Extreme Greed (>80)   → 0.5× (vorsichtiger sein)
    """
    if fear_greed_value < 20:
        return 1.5
    elif fear_greed_value < 40:
        return 1.2
    elif fear_greed_value < 60:
        return 1.0
    elif fear_greed_value < 80:
        return 0.8
    else:
        return 0.5


def emoji(value: int) -> str:
    if value < 25:   return "😱"
    elif value < 45: return "😰"
    elif value < 55: return "😐"
    elif value < 75: return "😏"
    else:            return "🤑"
