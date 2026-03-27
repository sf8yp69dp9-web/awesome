"""
Web Dashboard — Live Portfolio-Übersicht im Browser.
Startet einen Flask-Server auf http://localhost:8080
Auto-refresh alle 30 Sekunden.
"""
import json
import logging
import threading
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .portfolio import Portfolio

logger = logging.getLogger(__name__)

_HTML = """<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="30">
<title>TradingMaschiene</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js"></script>
<style>
  :root{--bg:#0d1117;--card:#161b22;--border:#30363d;--green:#3fb950;--red:#f85149;--yellow:#d29922;--text:#e6edf3;--muted:#8b949e;--accent:#58a6ff}
  *{margin:0;padding:0;box-sizing:border-box}
  body{background:var(--bg);color:var(--text);font-family:'Segoe UI',system-ui,sans-serif;min-height:100vh}
  header{background:var(--card);border-bottom:1px solid var(--border);padding:16px 24px;display:flex;align-items:center;gap:12px}
  header h1{font-size:1.2rem;font-weight:600}
  .badge{font-size:.75rem;padding:3px 8px;border-radius:12px;background:#238636;color:#fff}
  .badge.paper{background:#1f6feb}
  .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;padding:20px 24px}
  .card{background:var(--card);border:1px solid var(--border);border-radius:8px;padding:16px}
  .card .label{font-size:.75rem;color:var(--muted);text-transform:uppercase;letter-spacing:.05em;margin-bottom:6px}
  .card .value{font-size:1.5rem;font-weight:700}
  .card .sub{font-size:.8rem;color:var(--muted);margin-top:4px}
  .green{color:var(--green)}.red{color:var(--red)}.yellow{color:var(--yellow)}.accent{color:var(--accent)}
  .chart-wrap{margin:0 24px 20px;background:var(--card);border:1px solid var(--border);border-radius:8px;padding:16px}
  .chart-wrap h2{font-size:.9rem;color:var(--muted);margin-bottom:12px}
  canvas{max-height:200px}
  .trades{margin:0 24px 24px;background:var(--card);border:1px solid var(--border);border-radius:8px;overflow:hidden}
  .trades h2{font-size:.9rem;color:var(--muted);padding:12px 16px;border-bottom:1px solid var(--border)}
  table{width:100%;border-collapse:collapse;font-size:.85rem}
  th{text-align:left;padding:8px 16px;color:var(--muted);font-weight:500;font-size:.75rem;text-transform:uppercase}
  td{padding:8px 16px;border-top:1px solid var(--border)}
  tr:hover td{background:rgba(255,255,255,.03)}
  .pill{display:inline-block;padding:2px 8px;border-radius:10px;font-size:.75rem}
  .pill.win{background:rgba(63,185,80,.2);color:var(--green)}
  .pill.loss{background:rgba(248,81,73,.2);color:var(--red)}
  .pill.open{background:rgba(88,166,255,.2);color:var(--accent)}
  footer{text-align:center;color:var(--muted);font-size:.75rem;padding:16px;border-top:1px solid var(--border)}
  @keyframes pulse{0%,100%{opacity:1}50%{opacity:.4}}
  .dot{width:8px;height:8px;border-radius:50%;background:var(--green);display:inline-block;animation:pulse 2s infinite}
</style>
</head>
<body>
<header>
  <span class="dot"></span>
  <h1>TradingMaschiene</h1>
  <span class="badge paper" id="mode">PAPER</span>
  <span style="margin-left:auto;color:var(--muted);font-size:.8rem" id="updated"></span>
</header>

<div class="grid" id="metrics"></div>
<div class="grid" id="sentiment"></div>
<div class="chart-wrap"><h2>Equity Kurve</h2><canvas id="eq"></canvas></div>
<div class="trades"><h2>Letzte Trades</h2><table><thead><tr><th>Zeit</th><th>Symbol</th><th>Einstieg</th><th>Ausstieg</th><th>PnL</th><th>Dauer</th><th>Grund</th></tr></thead><tbody id="tbody"></tbody></table></div>
<footer>Auto-refresh alle 30s &nbsp;·&nbsp; TradingMaschiene &nbsp;·&nbsp; <span id="ts"></span></footer>

<script>
async function load(){
  const d = await fetch('/api/data').then(r=>r.json());
  const ret = d.total_return_pct;
  const retColor = ret>=0?'green':'red';
  const dpnl = d.daily_pnl;
  const dpColor = dpnl>=0?'green':'red';

  document.getElementById('mode').textContent = d.mode;
  document.getElementById('updated').textContent = 'Aktualisiert: '+new Date().toLocaleTimeString('de');
  document.getElementById('ts').textContent = new Date().toLocaleString('de');

  document.getElementById('metrics').innerHTML = [
    {label:'Portfolio', value: d.portfolio_value.toFixed(2)+' USDT', sub:'Startkapital: '+d.initial_capital.toFixed(2), cls:''},
    {label:'Gesamtrendite', value: (ret>=0?'+':'')+ret.toFixed(2)+'%', sub:'Realized PnL: '+(d.realized_pnl>=0?'+':'')+d.realized_pnl.toFixed(2), cls:retColor},
    {label:'Heute', value: (dpnl>=0?'+':'')+dpnl.toFixed(2)+' USDT', sub:'Daily P&L', cls:dpColor},
    {label:'Trades', value: d.total_trades, sub:'Win Rate: '+d.win_rate.toFixed(1)+'%', cls:''},
    {label:'Drawdown', value: d.drawdown.toFixed(2)+'%', sub:'Max erlaubt: 15%', cls: d.drawdown>10?'red':d.drawdown>5?'yellow':'green'},
    {label:'Offene Pos.', value: d.open_positions, sub:'Max: '+d.max_positions, cls:'accent'},
  ].map(m=>`<div class="card"><div class="label">${m.label}</div><div class="value ${m.cls}">${m.value}</div><div class="sub">${m.sub}</div></div>`).join('');

  // Sentiment cards
  if(d.sentiment && Object.keys(d.sentiment).length){
    const sc = Object.entries(d.sentiment).map(([sym,s])=>{
      const score = s.score;
      const cls = score>0.2?'green':score<-0.2?'red':'yellow';
      const bar = Math.round((score+1)/2*100);
      return `<div class="card"><div class="label">Sentiment ${sym}</div><div class="value ${cls}">${s.label}</div><div style="background:#21262d;border-radius:4px;height:6px;margin-top:8px"><div style="background:${score>0.2?'var(--green)':score<-0.2?'var(--red)':'var(--yellow)'};width:${bar}%;height:100%;border-radius:4px;transition:width .5s"></div></div><div class="sub">${score>=0?'+':''}${score.toFixed(2)} · ${s.sources} Quellen</div></div>`;
    }).join('');
    document.getElementById('sentiment').innerHTML = sc;
  }

  // Equity chart
  if(d.equity_curve && d.equity_curve.length>1){
    const ctx=document.getElementById('eq').getContext('2d');
    if(window._chart) window._chart.destroy();
    window._chart=new Chart(ctx,{type:'line',data:{labels:d.equity_labels,datasets:[{data:d.equity_curve,borderColor:'#58a6ff',backgroundColor:'rgba(88,166,255,.1)',fill:true,tension:.3,pointRadius:0,borderWidth:2}]},options:{plugins:{legend:{display:false}},scales:{x:{display:false},y:{grid:{color:'#21262d'},ticks:{color:'#8b949e'}}},animation:{duration:0}}});
  }

  // Trades table
  const rows = (d.trades||[]).slice(-20).reverse().map(t=>{
    const pnl = t.pnl>=0;
    const cls = t.exit_price?( pnl?'win':'loss'):'open';
    const lbl = t.exit_price?( pnl?'Gewinn':'Verlust'):'Offen';
    return `<tr>
      <td>${t.entry_time||'—'}</td>
      <td>${t.symbol}</td>
      <td>${(+t.entry_price).toFixed(2)}</td>
      <td>${t.exit_price?(+t.exit_price).toFixed(2):'—'}</td>
      <td class="${pnl?'green':'red'}">${t.pnl!=null?(t.pnl>=0?'+':'')+t.pnl.toFixed(2):'—'}</td>
      <td>${t.duration||'—'}</td>
      <td><span class="pill ${cls}">${t.reason||lbl}</span></td>
    </tr>`;
  }).join('');
  document.getElementById('tbody').innerHTML = rows || '<tr><td colspan="7" style="text-align:center;color:var(--muted);padding:24px">Noch keine Trades</td></tr>';
}
load();
</script>
</body>
</html>"""


class WebDashboard:
    """Live Web-Dashboard auf http://localhost:8080"""

    def __init__(self, port: int = 8080):
        self.port = port
        self._thread: threading.Thread = None
        self._portfolio = None
        self._mode = "PAPER"
        self._equity: list = []
        self._eq_labels: list = []
        self._sentiment: dict = {}

    def set_portfolio(self, portfolio, mode: str = "PAPER") -> None:
        self._portfolio = portfolio
        self._mode = mode

    def set_sentiment(self, sentiment: dict) -> None:
        """Update sentiment data (symbol → sentiment dict)."""
        self._sentiment = sentiment

    def record_equity(self, value: float) -> None:
        ts = datetime.now(timezone.utc).strftime("%H:%M")
        self._equity.append(round(value, 2))
        self._eq_labels.append(ts)
        if len(self._equity) > 500:
            self._equity.pop(0)
            self._eq_labels.pop(0)

    def start(self) -> None:
        self._thread = threading.Thread(target=self._serve, daemon=True, name="WebDashboard")
        self._thread.start()
        logger.info(f"Web Dashboard: http://localhost:{self.port}")

    def _api_data(self) -> dict:
        if not self._portfolio:
            return {"error": "No portfolio"}
        s = self._portfolio.summary()
        trades = []
        for t in self._portfolio.trades[-50:]:
            trades.append({
                "symbol":      t.symbol,
                "entry_price": t.entry_price,
                "exit_price":  t.exit_price,
                "pnl":         round(t.pnl, 4),
                "duration":    f"{t.duration_hours:.1f}h",
                "reason":      t.reason,
                "entry_time":  t.entry_time.strftime("%d.%m %H:%M") if hasattr(t.entry_time, "strftime") else str(t.entry_time),
            })
        return {
            "mode":           self._mode,
            "portfolio_value": round(s["current_value"], 2),
            "initial_capital": round(s["initial_capital"], 2),
            "total_return_pct": round(s["total_return_pct"], 2) if "total_return_pct" in s else round((s["current_value"]-s["initial_capital"])/s["initial_capital"]*100, 2),
            "realized_pnl":   round(s.get("total_realized_pnl", s.get("realized_pnl", 0)), 2),
            "daily_pnl":      round(s["daily_pnl"], 2),
            "total_trades":   s["total_trades"],
            "win_rate":       round(s["win_rate_pct"], 1),
            "drawdown":       round(s["drawdown_pct"], 2),
            "open_positions": s["open_positions"],
            "max_positions":  3,
            "equity_curve":   self._equity,
            "equity_labels":  self._eq_labels,
            "trades":         trades,
            "sentiment":      self._sentiment,
        }

    def _serve(self) -> None:
        try:
            from flask import Flask, jsonify, Response
            app = Flask(__name__, static_folder=None)
            app.logger.disabled = True
            import logging as _log
            _log.getLogger("werkzeug").setLevel(_log.ERROR)

            @app.route("/")
            def index():
                return Response(_HTML, mimetype="text/html")

            @app.route("/api/data")
            def api_data():
                return jsonify(self._api_data())

            app.run(host="0.0.0.0", port=self.port, debug=False, use_reloader=False)
        except ImportError:
            logger.warning("Flask nicht installiert — Web Dashboard deaktiviert. pip install flask")
        except Exception as e:
            logger.warning(f"Web Dashboard Fehler: {e}")
