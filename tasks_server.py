#!/usr/bin/env python3
"""
tasks_server.py — Local to-do dashboard web server.
Usage: python3 tasks_server.py [--port 8080]
"""

import argparse
import json
import os
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
import re

SCRIPT_DIR = Path(__file__).parent.resolve()
TASKS_FILE = SCRIPT_DIR / "tasks.json"
LOG_FILE   = SCRIPT_DIR / "tasks.log"

PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2}

# ── persistence ──────────────────────────────────────────────────────────────

def load_tasks():
    if not TASKS_FILE.exists():
        return []
    try:
        return json.loads(TASKS_FILE.read_text())
    except json.JSONDecodeError:
        return []

def save_tasks(tasks):
    TASKS_FILE.write_text(json.dumps(tasks, indent=2))

def log(msg: str):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    line = f"[{ts}] {msg}\n"
    with LOG_FILE.open("a") as f:
        f.write(line)
    print(line, end="")

# ── HTML ─────────────────────────────────────────────────────────────────────

HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>To-Do Dashboard</title>
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

  :root {
    --bg:        #0f1117;
    --surface:   #1a1d27;
    --border:    #2a2d3e;
    --text:      #e2e8f0;
    --muted:     #8892a4;
    --accent:    #6366f1;
    --high:      #ef4444;
    --medium:    #f59e0b;
    --low:       #22c55e;
    --complete:  #3b3f52;
    --radius:    10px;
  }

  body {
    background: var(--bg);
    color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    min-height: 100vh;
    padding: 2rem 1rem;
  }

  header {
    max-width: 780px;
    margin: 0 auto 2rem;
    display: flex;
    align-items: center;
    justify-content: space-between;
  }

  header h1 {
    font-size: 1.6rem;
    font-weight: 700;
    letter-spacing: -0.5px;
  }

  header h1 span { color: var(--accent); }

  .stats {
    display: flex;
    gap: 1.2rem;
    font-size: .82rem;
    color: var(--muted);
  }

  .stats b { color: var(--text); }

  /* ── Add / Edit form ── */
  .card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 1.4rem;
    max-width: 780px;
    margin: 0 auto 1.6rem;
  }

  .card h2 {
    font-size: .95rem;
    font-weight: 600;
    margin-bottom: 1rem;
    color: var(--muted);
    text-transform: uppercase;
    letter-spacing: .06em;
  }

  .form-row {
    display: flex;
    gap: .75rem;
    flex-wrap: wrap;
    align-items: flex-end;
  }

  .form-group { display: flex; flex-direction: column; gap: .35rem; }
  .form-group label { font-size: .78rem; color: var(--muted); }

  input[type="text"], textarea, select {
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: 6px;
    color: var(--text);
    padding: .5rem .75rem;
    font-size: .9rem;
    outline: none;
    transition: border-color .15s;
  }
  input[type="text"]:focus, textarea:focus, select:focus {
    border-color: var(--accent);
  }

  .form-group.title   { flex: 2; min-width: 200px; }
  .form-group.title input { width: 100%; }
  .form-group.desc    { flex: 3; min-width: 220px; }
  .form-group.desc textarea { width: 100%; resize: vertical; min-height: 38px; }
  .form-group.prio    { flex: 0 0 110px; }
  .form-group.prio select { width: 100%; }

  .btn {
    border: none;
    border-radius: 6px;
    cursor: pointer;
    font-size: .88rem;
    font-weight: 600;
    padding: .5rem 1.1rem;
    transition: opacity .15s, transform .1s;
  }
  .btn:active { transform: scale(.97); }
  .btn-primary  { background: var(--accent); color: #fff; }
  .btn-primary:hover { opacity: .88; }
  .btn-ghost    { background: transparent; color: var(--muted); border: 1px solid var(--border); }
  .btn-ghost:hover { color: var(--text); border-color: var(--text); }
  .btn-danger   { background: transparent; color: #ef4444; border: 1px solid #ef444433; }
  .btn-danger:hover { background: #ef444422; }

  /* ── Task list ── */
  .task-list {
    max-width: 780px;
    margin: 0 auto;
    display: flex;
    flex-direction: column;
    gap: .75rem;
  }

  .empty {
    text-align: center;
    padding: 3rem;
    color: var(--muted);
    font-size: .95rem;
  }

  .task {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 1rem 1.2rem;
    display: flex;
    align-items: flex-start;
    gap: 1rem;
    transition: border-color .15s;
  }
  .task:hover { border-color: #3a3f5c; }
  .task.done  { opacity: .45; }

  .prio-dot {
    width: 10px;
    height: 10px;
    border-radius: 50%;
    margin-top: .45rem;
    flex-shrink: 0;
  }
  .prio-dot.high   { background: var(--high); box-shadow: 0 0 6px var(--high); }
  .prio-dot.medium { background: var(--medium); box-shadow: 0 0 6px var(--medium); }
  .prio-dot.low    { background: var(--low); box-shadow: 0 0 6px var(--low); }

  .task-body { flex: 1; min-width: 0; }

  .task-title {
    font-size: .97rem;
    font-weight: 600;
    display: flex;
    align-items: center;
    gap: .6rem;
  }
  .task-title.done-text { text-decoration: line-through; color: var(--muted); }

  .badge {
    font-size: .68rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: .05em;
    padding: .15rem .5rem;
    border-radius: 4px;
  }
  .badge.high   { background: #ef444422; color: var(--high); }
  .badge.medium { background: #f59e0b22; color: var(--medium); }
  .badge.low    { background: #22c55e22; color: var(--low); }
  .badge.complete { background: #ffffff11; color: var(--muted); }

  .task-desc {
    font-size: .84rem;
    color: var(--muted);
    margin-top: .3rem;
    white-space: pre-wrap;
    word-break: break-word;
  }

  .task-meta {
    font-size: .72rem;
    color: #555d73;
    margin-top: .4rem;
  }

  .task-actions {
    display: flex;
    gap: .5rem;
    flex-shrink: 0;
  }

  .btn-icon {
    background: transparent;
    border: 1px solid var(--border);
    border-radius: 6px;
    color: var(--muted);
    cursor: pointer;
    font-size: .8rem;
    padding: .28rem .6rem;
    transition: all .15s;
  }
  .btn-icon:hover { color: var(--text); border-color: var(--text); }
  .btn-icon.del:hover { color: var(--high); border-color: var(--high); }

  /* inline edit mode */
  .task.editing { border-color: var(--accent); }
  .edit-fields { display: none; flex-direction: column; gap: .5rem; margin-top: .6rem; }
  .task.editing .edit-fields { display: flex; }
  .task.editing .view-fields { display: none; }
  .edit-fields input, .edit-fields textarea, .edit-fields select { width: 100%; }
  .edit-actions { display: flex; gap: .5rem; margin-top: .2rem; }

  /* filter bar */
  .filter-bar {
    max-width: 780px;
    margin: 0 auto 1rem;
    display: flex;
    gap: .5rem;
    flex-wrap: wrap;
    align-items: center;
  }
  .filter-bar span { font-size: .8rem; color: var(--muted); margin-right: .3rem; }

  .pill {
    background: transparent;
    border: 1px solid var(--border);
    border-radius: 20px;
    color: var(--muted);
    cursor: pointer;
    font-size: .78rem;
    padding: .25rem .8rem;
    transition: all .15s;
  }
  .pill:hover, .pill.active { background: var(--accent); border-color: var(--accent); color: #fff; }

  .section-label {
    max-width: 780px;
    margin: 1.4rem auto .6rem;
    font-size: .75rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: .08em;
    color: var(--muted);
  }
</style>
</head>
<body>

<header>
  <h1>To-Do <span>Dashboard</span></h1>
  <div class="stats">
    <span>Active: <b id="stat-active">0</b></span>
    <span>Done: <b id="stat-done">0</b></span>
    <span>High priority: <b id="stat-high">0</b></span>
  </div>
</header>

<div class="card">
  <h2>Add Task</h2>
  <div class="form-row">
    <div class="form-group title">
      <label>Title *</label>
      <input type="text" id="new-title" placeholder="What needs doing?" />
    </div>
    <div class="form-group desc">
      <label>Description</label>
      <textarea id="new-desc" placeholder="Optional details…" rows="1"></textarea>
    </div>
    <div class="form-group prio">
      <label>Priority</label>
      <select id="new-prio">
        <option value="high">🔴 High</option>
        <option value="medium" selected>🟡 Medium</option>
        <option value="low">🟢 Low</option>
      </select>
    </div>
    <button class="btn btn-primary" onclick="addTask()">Add</button>
  </div>
</div>

<div class="filter-bar">
  <span>Show:</span>
  <button class="pill active" data-filter="active" onclick="setFilter('active', this)">Active</button>
  <button class="pill" data-filter="all"    onclick="setFilter('all', this)">All</button>
  <button class="pill" data-filter="done"   onclick="setFilter('done', this)">Completed</button>
</div>

<div class="task-list" id="task-list"></div>

<script>
let tasks = [];
let currentFilter = 'active';

async function fetchTasks() {
  const r = await fetch('/api/tasks');
  tasks = await r.json();
  render();
}

function setFilter(f, el) {
  currentFilter = f;
  document.querySelectorAll('.pill').forEach(p => p.classList.remove('active'));
  el.classList.add('active');
  render();
}

function priorityLabel(p) {
  return { high: '🔴 High', medium: '🟡 Medium', low: '🟢 Low' }[p] || p;
}

function fmtDate(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}

function render() {
  const list = document.getElementById('task-list');
  const PRIO = { high: 0, medium: 1, low: 2 };

  let filtered = tasks.filter(t => {
    if (currentFilter === 'active') return t.status === 'active';
    if (currentFilter === 'done')   return t.status === 'complete';
    return true;
  });

  filtered.sort((a, b) => {
    if (a.status !== b.status) return a.status === 'active' ? -1 : 1;
    if (PRIO[a.priority] !== PRIO[b.priority]) return PRIO[a.priority] - PRIO[b.priority];
    return new Date(a.created) - new Date(b.created);
  });

  // stats
  const active = tasks.filter(t => t.status === 'active');
  document.getElementById('stat-active').textContent = active.length;
  document.getElementById('stat-done').textContent   = tasks.filter(t => t.status === 'complete').length;
  document.getElementById('stat-high').textContent   = active.filter(t => t.priority === 'high').length;

  if (filtered.length === 0) {
    list.innerHTML = `<div class="empty">No tasks here. ${currentFilter === 'active' ? 'Add one above ↑' : ''}</div>`;
    return;
  }

  list.innerHTML = filtered.map(t => {
    const done = t.status === 'complete';
    return `
    <div class="task${done ? ' done' : ''}" id="task-${t.id}">
      <div class="prio-dot ${t.priority}"></div>
      <div class="task-body">

        <div class="view-fields">
          <div class="task-title${done ? ' done-text' : ''}">
            ${escHtml(t.title)}
            <span class="badge ${done ? 'complete' : t.priority}">${done ? 'Done' : priorityLabel(t.priority)}</span>
          </div>
          ${t.description ? `<div class="task-desc">${escHtml(t.description)}</div>` : ''}
          <div class="task-meta">
            Created ${fmtDate(t.created)}${t.completed ? ' · Completed ' + fmtDate(t.completed) : ''}
          </div>
        </div>

        <div class="edit-fields">
          <input  type="text"  id="edit-title-${t.id}"  value="${escAttr(t.title)}"       placeholder="Title" />
          <textarea            id="edit-desc-${t.id}"   rows="2"                          placeholder="Description">${escHtml(t.description || '')}</textarea>
          <select              id="edit-prio-${t.id}">
            <option value="high"   ${t.priority==='high'   ? 'selected' : ''}>🔴 High</option>
            <option value="medium" ${t.priority==='medium' ? 'selected' : ''}>🟡 Medium</option>
            <option value="low"    ${t.priority==='low'    ? 'selected' : ''}>🟢 Low</option>
          </select>
          <div class="edit-actions">
            <button class="btn btn-primary" onclick="saveEdit('${t.id}')">Save</button>
            <button class="btn btn-ghost"   onclick="cancelEdit('${t.id}')">Cancel</button>
          </div>
        </div>

      </div>
      <div class="task-actions">
        ${!done ? `<button class="btn-icon" title="Mark complete" onclick="completeTask('${t.id}')">✓</button>` : ''}
        <button class="btn-icon" title="Edit" onclick="startEdit('${t.id}')">✎</button>
        <button class="btn-icon del" title="Delete" onclick="deleteTask('${t.id}')">✕</button>
      </div>
    </div>`;
  }).join('');
}

function escHtml(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
function escAttr(s) {
  return String(s).replace(/"/g,'&quot;').replace(/'/g,'&#39;');
}

async function addTask() {
  const title = document.getElementById('new-title').value.trim();
  if (!title) { document.getElementById('new-title').focus(); return; }
  const body = {
    title,
    description: document.getElementById('new-desc').value.trim(),
    priority:    document.getElementById('new-prio').value,
  };
  await fetch('/api/tasks', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(body) });
  document.getElementById('new-title').value = '';
  document.getElementById('new-desc').value  = '';
  document.getElementById('new-prio').value  = 'medium';
  fetchTasks();
}

async function deleteTask(id) {
  if (!confirm('Delete this task?')) return;
  await fetch(`/api/tasks/${id}`, { method: 'DELETE' });
  fetchTasks();
}

async function completeTask(id) {
  await fetch(`/api/tasks/${id}`, {
    method: 'PUT',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({ status: 'complete' })
  });
  fetchTasks();
}

function startEdit(id) {
  document.getElementById(`task-${id}`).classList.add('editing');
}
function cancelEdit(id) {
  document.getElementById(`task-${id}`).classList.remove('editing');
}
async function saveEdit(id) {
  const body = {
    title:       document.getElementById(`edit-title-${id}`).value.trim(),
    description: document.getElementById(`edit-desc-${id}`).value.trim(),
    priority:    document.getElementById(`edit-prio-${id}`).value,
  };
  if (!body.title) return;
  await fetch(`/api/tasks/${id}`, { method: 'PUT', headers: {'Content-Type':'application/json'}, body: JSON.stringify(body) });
  fetchTasks();
}

// Enter key on title input triggers add
document.addEventListener('DOMContentLoaded', () => {
  document.getElementById('new-title').addEventListener('keydown', e => {
    if (e.key === 'Enter') addTask();
  });
  fetchTasks();
});
</script>
</body>
</html>
"""

# ── HTTP handler ──────────────────────────────────────────────────────────────

class Handler(BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):
        pass  # suppress default access log spam

    def _send(self, code, body, content_type="application/json"):
        data = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _read_body(self):
        length = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(length)) if length else {}

    def do_GET(self):
        if self.path == "/":
            self._send(200, HTML, "text/html; charset=utf-8")
        elif self.path == "/api/tasks":
            self._send(200, json.dumps(load_tasks()))
        else:
            self._send(404, '{"error":"not found"}')

    def do_POST(self):
        if self.path != "/api/tasks":
            self._send(404, '{"error":"not found"}')
            return
        data = self._read_body()
        title = (data.get("title") or "").strip()
        if not title:
            self._send(400, '{"error":"title required"}')
            return
        tasks = load_tasks()
        task = {
            "id":          str(uuid.uuid4()),
            "title":       title,
            "description": (data.get("description") or "").strip(),
            "priority":    data.get("priority", "medium"),
            "status":      "active",
            "created":     datetime.now(timezone.utc).isoformat(),
            "completed":   None,
        }
        tasks.append(task)
        save_tasks(tasks)
        log(f"TASK ADDED    [{task['priority'].upper():6}] {task['title']!r}")
        self._send(201, json.dumps(task))

    def do_PUT(self):
        m = re.match(r"^/api/tasks/([^/]+)$", self.path)
        if not m:
            self._send(404, '{"error":"not found"}')
            return
        task_id = m.group(1)
        data = self._read_body()
        tasks = load_tasks()
        for i, t in enumerate(tasks):
            if t["id"] == task_id:
                if "title" in data:
                    tasks[i]["title"] = data["title"].strip()
                if "description" in data:
                    tasks[i]["description"] = data["description"].strip()
                if "priority" in data:
                    tasks[i]["priority"] = data["priority"]
                if data.get("status") == "complete" and t["status"] != "complete":
                    tasks[i]["status"]    = "complete"
                    tasks[i]["completed"] = datetime.now(timezone.utc).isoformat()
                    log(f"TASK COMPLETE [{t['priority'].upper():6}] {t['title']!r}")
                elif "status" in data:
                    tasks[i]["status"] = data["status"]
                if "title" in data or "description" in data or "priority" in data:
                    if data.get("status") != "complete":
                        log(f"TASK EDITED   [{tasks[i]['priority'].upper():6}] {tasks[i]['title']!r}")
                save_tasks(tasks)
                self._send(200, json.dumps(tasks[i]))
                return
        self._send(404, '{"error":"task not found"}')

    def do_DELETE(self):
        m = re.match(r"^/api/tasks/([^/]+)$", self.path)
        if not m:
            self._send(404, '{"error":"not found"}')
            return
        task_id = m.group(1)
        tasks = load_tasks()
        for i, t in enumerate(tasks):
            if t["id"] == task_id:
                tasks.pop(i)
                save_tasks(tasks)
                log(f"TASK DELETED  [{t['priority'].upper():6}] {t['title']!r}")
                self._send(200, '{"ok":true}')
                return
        self._send(404, '{"error":"task not found"}')

# ── main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="To-Do Dashboard")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()

    server = HTTPServer(("127.0.0.1", args.port), Handler)
    log(f"SERVER START  Listening on http://127.0.0.1:{args.port}")
    print(f"  Open http://127.0.0.1:{args.port} in your browser")
    print(f"  Ctrl-C to stop\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log("SERVER STOP   Keyboard interrupt")

if __name__ == "__main__":
    main()
