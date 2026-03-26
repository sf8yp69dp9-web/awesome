"""
Arbitrage Scanner — findet Dreiecks-Arbitrage Chancen auf Binance.

Dreiecks-Arbitrage Prinzip:
  USDT → BTC → ETH → USDT (oder andere Kombinationen)
  Wenn der Kreislauf mehr USDT zurückgibt als er kostet → Profit!

Beispiel:
  1000 USDT → kaufe BTC  → kaufe ETH mit BTC → verkaufe ETH für USDT
  Wenn am Ende 1003 USDT → 0.3% Profit (minus Fees)

Binance Fees: 0.1% pro Trade → 3 Trades = 0.3% Gesamtkosten
Mindest-Profit: > 0.35% (nach Fees noch 0.05% übrig)
"""
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# ── Dreiecks-Kombinationen zum Scannen ──────────────────────────────────────
# Format: (A/B, B/C, A/C) — Route: USDT→A→B→USDT
TRIANGLES = [
    ("BTC/USDT", "ETH/BTC",  "ETH/USDT"),
    ("BTC/USDT", "BNB/BTC",  "BNB/USDT"),
    ("ETH/USDT", "BNB/ETH",  "BNB/USDT"),
    ("BTC/USDT", "SOL/BTC",  "SOL/USDT"),
    ("BTC/USDT", "XRP/BTC",  "XRP/USDT"),
    ("ETH/USDT", "SOL/ETH",  "SOL/USDT"),
    ("BTC/USDT", "ADA/BTC",  "ADA/USDT"),
    ("BTC/USDT", "DOGE/BTC", "DOGE/USDT"),
]

FEE = 0.001          # 0.1% Binance Standard-Fee
MIN_PROFIT_PCT = 0.15  # Mindestprofit nach Fees (%)


@dataclass
class ArbitrageOpportunity:
    """Eine gefundene Arbitrage-Chance."""
    triangle: tuple[str, str, str]
    route: str                    # z.B. "USDT → BTC → ETH → USDT"
    profit_pct: float             # Profit nach Fees in %
    profit_usdt: float            # Absoluter Profit in USDT
    capital_usdt: float           # Eingesetztes Kapital
    prices: dict[str, float]      # Verwendete Preise
    found_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __str__(self) -> str:
        return (
            f"🔺 {self.route}\n"
            f"   Profit: {self.profit_pct:+.3f}% = {self.profit_usdt:+.4f} USDT\n"
            f"   Kapital: {self.capital_usdt:.2f} USDT"
        )


@dataclass
class ScanResult:
    """Ergebnis eines kompletten Scans."""
    opportunities: list[ArbitrageOpportunity]
    scanned: int
    duration_ms: float
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def best(self) -> Optional[ArbitrageOpportunity]:
        return max(self.opportunities, key=lambda o: o.profit_pct) if self.opportunities else None


class ArbitrageScanner:
    """
    Scannt Binance auf Dreiecks-Arbitrage Chancen.
    Nutzt den bestehenden ExchangeConnector.
    """

    def __init__(self, exchange, capital_usdt: float = 100.0, fee: float = FEE):
        """
        exchange: ExchangeConnector oder MockExchange
        capital_usdt: Kapital pro Trade-Simulation
        fee: Trading-Fee pro Trade (Standard: 0.1% = 0.001)
        """
        self.exchange = exchange
        self.capital = capital_usdt
        self.fee = fee
        self._prices: dict[str, float] = {}
        self._last_fetch = 0.0

    # ── Haupt-Scanner ─────────────────────────────────────────────────────

    def scan(self) -> ScanResult:
        """
        Scannt alle Dreiecke und gibt Chancen zurück.
        Holt Preise einmalig und berechnet alle Routen.
        """
        start = time.time()
        symbols = self._get_all_symbols()

        # Preise holen (gecacht für 5 Sekunden)
        now = time.time()
        if now - self._last_fetch > 5:
            self._prices = self._fetch_prices(symbols)
            self._last_fetch = now

        opportunities = []
        for triangle in TRIANGLES:
            opp = self._check_triangle(*triangle)
            if opp:
                opportunities.append(opp)

        duration_ms = (time.time() - start) * 1000
        return ScanResult(
            opportunities=sorted(opportunities, key=lambda o: o.profit_pct, reverse=True),
            scanned=len(TRIANGLES),
            duration_ms=duration_ms,
        )

    # ── Dreieck prüfen ────────────────────────────────────────────────────

    def _check_triangle(self, pair_ab: str, pair_bc: str, pair_ac: str) -> Optional[ArbitrageOpportunity]:
        """
        Prüft Route: USDT → A → B → USDT
        pair_ab = A/USDT (z.B. BTC/USDT)
        pair_bc = B/A    (z.B. ETH/BTC)
        pair_ac = B/USDT (z.B. ETH/USDT)
        """
        try:
            price_ab = self._prices.get(pair_ab)
            price_bc = self._prices.get(pair_bc)
            price_ac = self._prices.get(pair_ac)

            if not all([price_ab, price_bc, price_ac]):
                return None

            # Route Forward: USDT → A → B → USDT
            profit_fwd = self._calc_profit_forward(price_ab, price_bc, price_ac)

            # Route Reverse: USDT → B → A → USDT
            profit_rev = self._calc_profit_reverse(price_ab, price_bc, price_ac)

            best_profit = max(profit_fwd, profit_rev)
            if best_profit < MIN_PROFIT_PCT / 100:
                return None

            a = pair_ab.split("/")[0]
            b = pair_bc.split("/")[0]

            if profit_fwd >= profit_rev:
                route = f"USDT → {a} → {b} → USDT"
            else:
                route = f"USDT → {b} → {a} → USDT"

            return ArbitrageOpportunity(
                triangle=(pair_ab, pair_bc, pair_ac),
                route=route,
                profit_pct=round(best_profit * 100, 4),
                profit_usdt=round(self.capital * best_profit, 4),
                capital_usdt=self.capital,
                prices={pair_ab: price_ab, pair_bc: price_bc, pair_ac: price_ac},
            )

        except Exception as e:
            logger.debug(f"Triangle check error {pair_ab}/{pair_bc}/{pair_ac}: {e}")
            return None

    def _calc_profit_forward(self, price_ab, price_bc, price_ac) -> float:
        """USDT → A (buy AB) → B (buy BC) → USDT (sell AC)"""
        usdt = self.capital
        a = usdt / price_ab * (1 - self.fee)        # USDT → A
        b = a / price_bc * (1 - self.fee)            # A → B
        usdt_end = b * price_ac * (1 - self.fee)     # B → USDT
        return (usdt_end - usdt) / usdt

    def _calc_profit_reverse(self, price_ab, price_bc, price_ac) -> float:
        """USDT → B (buy AC) → A (sell BC) → USDT (sell AB)"""
        usdt = self.capital
        b = usdt / price_ac * (1 - self.fee)         # USDT → B
        a = b * price_bc * (1 - self.fee)             # B → A
        usdt_end = a * price_ab * (1 - self.fee)      # A → USDT
        return (usdt_end - usdt) / usdt

    # ── Preise holen ─────────────────────────────────────────────────────

    def _get_all_symbols(self) -> list[str]:
        symbols = set()
        for t in TRIANGLES:
            symbols.update(t)
        return list(symbols)

    def _fetch_prices(self, symbols: list[str]) -> dict[str, float]:
        """Holt aktuelle Preise für alle Symbole."""
        prices = {}
        for symbol in symbols:
            try:
                df = self.exchange.fetch_ohlcv(symbol, "1m", limit=2)
                if df is not None and len(df) > 0:
                    prices[symbol] = float(df["close"].iloc[-1])
            except Exception as e:
                logger.debug(f"Preis-Fetch Fehler {symbol}: {e}")
        return prices

    def get_price_summary(self) -> dict:
        """Gibt gecachte Preise zurück."""
        return dict(self._prices)
