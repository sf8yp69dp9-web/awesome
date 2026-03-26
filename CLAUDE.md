# CLAUDE.md — Projekt-Gedächtnis & Arbeitsregeln

Dieses File wird bei jeder Session gelesen. Hier stehen Fehler die ich gemacht habe,
Architektur-Entscheidungen und Kontext damit nichts verloren geht.

---

## Projekt-Übersicht

**TradingMaschiene** — Automatischer Crypto-Trading-Bot mit KI-Integration.

- **Nutzer:** Deutschsprachig, Anfänger-freundlich, arbeitet mobil (Handy)
- **Ziel:** 500 EUR auf Binance Testnet → später Live-Trading
- **Branch:** `claude/trading-bot-development-MvSCF`
- **Einstiegspunkt:** `python main.py paper` (oder `live` / `backtest`)

---

## Architektur

```
trading_bot/
├── engine.py           # Live/Paper Trading Engine (Hauptschleife)
├── offline_sim.py      # Offline-Simulation (kein Internet nötig)
├── cli.py              # Click CLI + Startup-Animation
├── config.py           # Dataclasses: BotConfig, RiskConfig, etc.
├── portfolio.py        # Positionen, Trade-History, PnL
├── risk.py             # RiskManager: ATR-Stops, Trailing Stop, Drawdown
├── exchange.py         # ccxt-Wrapper + MockExchange für Paper Trading
├── backtester.py       # Historischer Backtest
├── reporter.py         # Rich Terminal-Dashboard
├── data_downloader.py  # OHLCV holen + GBM-Fallback
├── strategies/
│   ├── ensemble.py     # 2/3 Voting: EMA + RSI + MACD + ADX-Filter
│   ├── ema_crossover.py
│   ├── rsi.py
│   └── macd.py
├── ai_validator.py     # Claude Haiku validiert BUY/SELL + Erklärungen DE
├── ai_assistant.py     # Claude Haiku Chatbot via Telegram (freie Fragen)
├── sentiment.py        # Reddit + CryptoPanic + KI → Score -1.0…+1.0
├── fear_greed.py       # alternative.me API → Positionsgröße anpassen
├── telegram_notifier.py # Trade-Alerts + Daily Summary
├── telegram_commander.py # Bot-Steuerung via Telegram-Befehle + AI-Chat
└── web_dashboard.py    # Flask :8080 Dark-Theme Dashboard + Chart.js
```

### Schlüssel-Parameter (config.yaml)
- Strategie: `ensemble` (Standard)
- ADX-Threshold: `15` (war 25 → zu aggressiv, 0 Trades)
- ATR-Multiplier: `3.0` (war 2.0 → Stops zu eng)
- Volume-Filter: `0` (deaktiviert — funktioniert nicht auf GBM-Daten)
- Kapital: `500 EUR`

---

## Fehler die ich gemacht habe (nie wieder!)

### KRITISCH
1. **Fehlender `return` in `_call_claude()`** (`ai_validator.py`)
   - `AIValidation` wurde gebaut aber NIE zurückgegeben → immer `None`
   - Symptom: Alle AI-Validierungen schlugen lautlos fehl
   - Fix: `return AIValidation(...)` am Ende der Methode

2. **Falsches OHLCV-Column** (`ai_validator.py`)
   - `O:{row['close']}` statt `O:{row['open']}` → Claude bekam falsche Daten
   - Fix: `O:{row['open']}`

### HOCH
3. **UTC-Timezone Mismatch** (`telegram_notifier.py`)
   - `date.today()` (lokal) vs `datetime.now(timezone.utc).date()` (UTC)
   - Symptom: Daily Summary konnte doppelt gesendet werden um Mitternacht
   - Fix: Immer UTC verwenden

4. **ATR auf vollem Window** (`risk.py`)
   - `_compute_atr()` rechnete EWM über alle 8784 Zeilen bei jedem Tick
   - Fix: `df = df.iloc[-tail:]` (tail = period × 3)

5. **Static Method via Instance** (`backtester.py`)
   - `self.risk_mgr._compute_atr()` → `RiskManager._compute_atr()`

### LOGIK
6. **ADX-Filter zu aggressiv** → 0 Trades
   - Threshold 25 auf GBM-Daten → alles gefiltert
   - Fix: Threshold auf 15 gesenkt

7. **Volume-Filter blockierte alle Trades**
   - 1.5× Multiplier passte nicht zu synthetischen Daten
   - Fix: `volume_multiplier=0` (deaktiviert)

8. **`EXPLAIN_PROMPT_DE` zwischen Methoden definiert**
   - Sollte als Klassen-Attribut oben stehen
   - Fix: Ans Class-Top verschoben (neben `SYSTEM_PROMPT`)

---

## Umgebung & Einschränkungen

- **Kein Internet** in dieser Umgebung → alle Network-Calls schlagen fehl
- **Fallback-Mechanismen** überall eingebaut:
  - Exchange → GBM Offline-Sim
  - Fear & Greed → Neutral (50) bei Fehler
  - Sentiment → Score 0.0 bei Fehler
  - AI Validator → `skipped=True` wenn kein API-Key
  - Telegram → silent fail, nur geloggt
- **API Keys** in `.env` (bereits konfiguriert):
  - Binance Testnet Keys ✅
  - Telegram Bot: `@Moremoney4life_bot` ✅
  - Chat ID: `7488167784` ✅

---

## Gebaut (chronologisch)

| Feature | Status | Datei |
|---------|--------|-------|
| Basis Trading Bot | ✅ | engine.py |
| Ensemble Strategie | ✅ | strategies/ensemble.py |
| AI Signal Validator | ✅ | ai_validator.py |
| Trailing Stop + ATR | ✅ | risk.py |
| Telegram Alerts | ✅ | telegram_notifier.py |
| Rich Terminal Dashboard | ✅ | reporter.py |
| Offline Simulation | ✅ | offline_sim.py |
| Backtester | ✅ | backtester.py |
| **Fear & Greed Index** | ✅ | fear_greed.py |
| **Telegram Commander** | ✅ | telegram_commander.py |
| **Web Dashboard** | ✅ | web_dashboard.py (:8080) |
| **Startup Animation** | ✅ | cli.py |
| **Sentiment Analyzer** | ✅ | sentiment.py |
| **AI-Assistent** | ✅ | ai_assistant.py |
| **Content Creator** | ✅ | content_creator.py |

---

## Nächste Schritte

1. **VPS Setup** — Bot 24/7 laufen lassen (Hetzner ~4€/Monat empfohlen)
2. **Live Trading** — Wenn Testnet stabil läuft, auf echte Keys umstellen
3. **Mehr Coins** — ETH/USDT, SOL/USDT hinzufügen

## Wichtige Erkenntnis (Session 2026-03-26)
- Bot muss auf PC laufen damit Telegram-Befehle funktionieren
- Nutzer ist oft nur am Handy → VPS wird wichtig für 24/7-Betrieb

---

## Arbeitsregeln für mich

- **Vor jeder Änderung:** Datei lesen, Kontext verstehen
- **Neue Features:** Erst planen, dann schrittweise bauen, dann testen
- **Fehler sofort dokumentieren** hier in CLAUDE.md
- **Commit-Nachrichten:** Klar beschreiben WAS und WARUM
- **Graceful Degradation:** Jedes Feature muss ohne Internet funktionieren
- **Kein Over-Engineering:** Nur bauen was der Nutzer braucht
- **Deutsch kommunizieren** mit dem Nutzer (Code bleibt Englisch)
