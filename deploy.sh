#!/bin/bash
# ============================================================
# TradingMaschiene — VPS Setup Script
# Führe dieses Script auf deinem VPS aus:
#   curl -sSL <deine-url>/deploy.sh | bash
# Oder: bash deploy.sh
# ============================================================
set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

info()    { echo -e "${GREEN}[✓]${NC} $1"; }
warn()    { echo -e "${YELLOW}[!]${NC} $1"; }
error()   { echo -e "${RED}[✗]${NC} $1"; exit 1; }
section() { echo -e "\n${GREEN}══════════════════════════════${NC}"; echo -e "  $1"; echo -e "${GREEN}══════════════════════════════${NC}"; }

section "TradingMaschiene VPS Setup"

# ── 1. System Update ─────────────────────────────────────────
section "1/6 System aktualisieren"
sudo apt-get update -qq && sudo apt-get upgrade -y -qq
info "System aktualisiert"

# ── 2. Python & Tools ────────────────────────────────────────
section "2/6 Python & Tools installieren"
sudo apt-get install -y -qq python3 python3-pip python3-venv git screen ufw
info "Python $(python3 --version) installiert"

# ── 3. Repo klonen oder updaten ──────────────────────────────
section "3/6 Bot-Code einrichten"
BOT_DIR="$HOME/tradingmaschiene"

if [ -d "$BOT_DIR" ]; then
    warn "Verzeichnis existiert — update..."
    cd "$BOT_DIR"
    git pull origin claude/trading-bot-development-MvSCF
else
    git clone -b claude/trading-bot-development-MvSCF \
        https://github.com/sf8yp69dp9-web/awesome.git "$BOT_DIR"
    cd "$BOT_DIR"
fi
info "Code eingerichtet in $BOT_DIR"

# ── 4. Python Environment ────────────────────────────────────
section "4/6 Python-Umgebung einrichten"
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip -q
pip install -r requirements.txt -q
info "Abhängigkeiten installiert"

# ── 5. .env Datei ────────────────────────────────────────────
section "5/6 API-Keys konfigurieren"

if [ ! -f .env ]; then
    cat > .env << 'ENVEOF'
EXCHANGE_NAME=binance
EXCHANGE_API_KEY=
EXCHANGE_API_SECRET=
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
ANTHROPIC_API_KEY=
ENVEOF
    warn ".env erstellt — trage deine API-Keys ein!"
    warn "  nano $BOT_DIR/.env"
else
    info ".env bereits vorhanden"
fi

# ── 6. Systemd Service ───────────────────────────────────────
section "6/6 Auto-Start Service einrichten"

sudo tee /etc/systemd/system/tradingmaschiene.service > /dev/null << SERVICEEOF
[Unit]
Description=TradingMaschiene Crypto Trading Bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$BOT_DIR
ExecStart=$BOT_DIR/venv/bin/python main.py paper
Restart=always
RestartSec=30
StandardOutput=journal
StandardError=journal
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
SERVICEEOF

sudo systemctl daemon-reload
sudo systemctl enable tradingmaschiene
info "Service eingerichtet (startet automatisch nach Neustart)"

# ── Firewall ─────────────────────────────────────────────────
sudo ufw allow 8080/tcp comment "TradingMaschiene Dashboard" 2>/dev/null || true
sudo ufw allow OpenSSH 2>/dev/null || true

# ── Fertig ───────────────────────────────────────────────────
section "Setup abgeschlossen!"
echo ""
echo "  Nächste Schritte:"
echo ""
echo "  1. API-Keys eintragen:"
echo "     nano $BOT_DIR/.env"
echo ""
echo "  2. Bot starten:"
echo "     sudo systemctl start tradingmaschiene"
echo ""
echo "  3. Status prüfen:"
echo "     sudo systemctl status tradingmaschiene"
echo "     sudo journalctl -u tradingmaschiene -f"
echo ""
echo "  4. Dashboard öffnen:"
echo "     http://DEINE-VPS-IP:8080"
echo ""
echo "  Bot startet automatisch nach jedem Neustart!"
