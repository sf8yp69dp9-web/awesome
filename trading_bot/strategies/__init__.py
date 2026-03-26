from .base import BaseStrategy
from .ema_crossover import EMACrossoverStrategy
from .rsi import RSIStrategy
from .macd import MACDStrategy
from .ensemble import EnsembleStrategy

STRATEGY_REGISTRY = {
    "ema_crossover": EMACrossoverStrategy,
    "rsi": RSIStrategy,
    "macd": MACDStrategy,
    "ensemble": EnsembleStrategy,
}

__all__ = [
    "BaseStrategy", "EMACrossoverStrategy", "RSIStrategy",
    "MACDStrategy", "EnsembleStrategy", "STRATEGY_REGISTRY",
]
