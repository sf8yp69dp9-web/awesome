#!/usr/bin/env python3
"""
process_tasks.py — Hourly worker: process highest-priority active tasks.

Run via cron:  0 * * * * /usr/bin/python3 /home/user/awesome/process_tasks.py >> /home/user/awesome/tasks.log 2>&1

Logic:
  1. Load tasks.json
  2. If no active tasks → log and exit
  3. Sort active tasks: high → medium → low, then by creation date
  4. Work through ALL active tasks in priority order this run:
       - Log what was done
       - Mark as complete
       - Save after each task
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent.resolve()
TASKS_FILE = SCRIPT_DIR / "tasks.json"
LOG_FILE   = SCRIPT_DIR / "tasks.log"

PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2}


def log(msg: str):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    line = f"[{ts}] {msg}"
    print(line)
    with LOG_FILE.open("a") as f:
        f.write(line + "\n")


def load_tasks():
    if not TASKS_FILE.exists():
        return []
    try:
        return json.loads(TASKS_FILE.read_text())
    except json.JSONDecodeError:
        return []


def save_tasks(tasks):
    TASKS_FILE.write_text(json.dumps(tasks, indent=2))


def main():
    log("WORKER START  Hourly task processor running")

    tasks = load_tasks()
    active = [t for t in tasks if t.get("status") == "active"]

    if not active:
        log("WORKER IDLE   Task list is empty — nothing to process")
        log("WORKER DONE")
        return

    # Sort: priority order, then creation date ascending
    active.sort(key=lambda t: (
        PRIORITY_ORDER.get(t.get("priority", "low"), 99),
        t.get("created", "")
    ))

    log(f"WORKER FOUND  {len(active)} active task(s) to process")

    completed_count = 0
    for task in active:
        tid   = task["id"]
        title = task["title"]
        prio  = task.get("priority", "medium").upper()
        desc  = task.get("description", "").strip()

        log(f"WORKER PROC   [{prio:6}] {title!r}" + (f" — {desc}" if desc else ""))

        # Mark complete
        now = datetime.now(timezone.utc).isoformat()
        for t in tasks:
            if t["id"] == tid:
                t["status"]    = "complete"
                t["completed"] = now
                break

        save_tasks(tasks)
        log(f"WORKER DONE   [{prio:6}] {title!r} marked complete")
        completed_count += 1

    log(f"WORKER FINISH Processed {completed_count} task(s) this run")


if __name__ == "__main__":
    main()
