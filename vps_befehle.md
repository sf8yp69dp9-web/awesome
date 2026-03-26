# VPS Schnellreferenz — TradingMaschiene

## Bot steuern
```bash
sudo systemctl start tradingmaschiene    # Starten
sudo systemctl stop tradingmaschiene     # Stoppen
sudo systemctl restart tradingmaschiene  # Neu starten
sudo systemctl status tradingmaschiene   # Status anzeigen
```

## Logs anzeigen
```bash
sudo journalctl -u tradingmaschiene -f         # Live-Logs
sudo journalctl -u tradingmaschiene -n 100     # Letzte 100 Zeilen
```

## Bot updaten (neuer Code)
```bash
cd ~/tradingmaschiene
git pull origin claude/trading-bot-development-MvSCF
sudo systemctl restart tradingmaschiene
```

## API-Keys bearbeiten
```bash
nano ~/tradingmaschiene/.env
sudo systemctl restart tradingmaschiene
```

## Dashboard
```
http://DEINE-VPS-IP:8080
```
