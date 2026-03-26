from .base import BaseStrategy
from .ema_crossover import EMACrossoverStrategy
from .rsi import RSIStrategy
from .macd import MACDStrategy

STRATEGY_REGISTRY = {
    "ema_crossover": EMACrossoverStrategy,
    "rsi": RSIStrategy,
    "macd": MACDStrategy,
}

__all__ = ["BaseStrategy", "EMACrossoverStrategy", "RSIStrategy", "MACDStrategy", "STRATEGY_REGISTRY"]
