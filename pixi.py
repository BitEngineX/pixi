#!/usr/bin/env python3
"""
Pixi — Command Line Interface for the Eisenhower Matrix Task Manager.

Pixi is a keyboard-driven task manager built around the Eisenhower Matrix
(Important/Urgent quadrants) with a gamified daily scoring system.

Usage:
    pixi add <task> [--folder <folder>]     Add task to folder
    pixi list [--inbox]                      List all tasks
    pixi complete <task-id> [--value <num>]  Complete a task (with score)
    pixi move <task-id> <quadrant>           Move task to Q1/Q2/Q3/Q4
    pixi delete <task-id>                    Delete task permanently
    pixi report [--date <YYYY-MM-DD>]        Show daily scores
    pixi log [--limit <num>]                 Show activity logs
    pixi gui                                 Launch interactive TUI (main.py)
    pixi stats                               Show matrix statistics
"""

import argparse
import json
import os
import subprocess
import sys
import uuid
from datetime import date, datetime

# ========== Configuration ==========
# Data files live next to the source by default (works for git clones and
# editable installs). Override with the PIXI_DATA_DIR environment variable
# to store your data anywhere you like.
DATA_DIR = os.environ.get("PIXI_DATA_DIR") or os.path.dirname(os.path.abspath(__file__))
SAVE_FILE = os.path.join(DATA_DIR, "tasks.json")
STATE_FILE = os.path.join(DATA_DIR, "daily_state.json")
LOGS_FILE = os.path.join(DATA_DIR, "logs.json")
SCORES_FILE = os.path.join(DATA_DIR, "daily_scores.log")

# Base scores for the gamification system (see README for the full formula).
NQ1_BASE = 600.0   # Important & Urgent
NQ2_BASE = 350.0   # Important & Not Urgent
NQ4_BASE = -150.0  # Not Important & Not Urgent
# ===================================


def load_tasks():
    """Load tasks from the JSON save file."""
    if not os.path.exists(SAVE_FILE):
        return []
    with open(SAVE_FILE, "r") as f:
        return json.load(f)


def save_tasks(tasks):
    """Persist tasks to the JSON save file."""
    with open(SAVE_FILE, "w") as f:
        json.dump(tasks, f, indent=2)


def load_daily_state():
    """Load the daily score state."""
    if not os.path.exists(STATE_FILE):
        return {"day_score": 0.0, "last_date": None}
    with open(STATE_FILE, "r") as f:
        return json.load(f)


def save_daily_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def add_log(message):
    """Append a timestamped entry to the activity log (capped at 500)."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_entry = f"[{timestamp}] {message}"

    logs = []
    if os.path.exists(LOGS_FILE):
        with open(LOGS_FILE, "r") as f:
            logs = json.load(f)

    logs.append(log_entry)
    if len(logs) > 500:
        logs = logs[-500:]

    with open(LOGS_FILE, "w") as f:
        json.dump(logs, f, indent=2)


def find_task_by_id(tasks, task_id, parent=None):
    """Depth-first search for a task/folder by its UID."""
    for i, task in enumerate(tasks):
        if task.get("uid") == task_id:
            return task, tasks, i, parent
        if "children" in task:
            result = find_task_by_id(task["children"], task_id, task)
            if result[0]:
                return result
    return None, None, None, None


def flatten_tasks(tasks):
    """Convert the nested task tree into a flat list of dicts."""
    result = []
    for task in tasks:
        uid = task.get("uid", "no-uid")
        label = task.get("label", "Unknown")
        task_type = task.get("type", "task")
        quadrant = task.get("quadrant", "-")
        if quadrant is None:
            quadrant = "-"
        completed = task.get("completed", False)
        status = "✓" if completed else " "
        result.append({
            "uid": uid,
            "label": label,
            "type": task_type,
            "quadrant": quadrant,
            "completed": completed,
            "status": status
        })
        if "children" in task:
            result.extend(flatten_tasks(task["children"]))
    return result


def rollover_day(state):
    """Archive yesterday's score and reset the counter when the date changed."""
    today = date.today()
    last_date = state.get("last_date")
    if last_date:
        try:
            last_date_obj = datetime.fromisoformat(last_date).date()
            if last_date_obj < today:
                with open(SCORES_FILE, "a") as f:
                    f.write(f"{last_date}: {state['day_score']:.2f}\n")
                state["day_score"] = 0.0
        except (ValueError, KeyError):
            pass
    return state


def cmd_add(args):
    tasks = load_tasks()
    task_name = args.task
    folder_name = args.folder if args.folder else None
    target = None

    if folder_name:
        def find_folder(node):
            for item in node:
                if item.get("type") == "folder" and folder_name in item.get("label", ""):
                    return item
                if "children" in item:
                    result = find_folder(item["children"])
                    if result:
                        return result
            return None
        target = find_folder(tasks)
        if not target:
            print(f"❌ Folder '{folder_name}' not found")
            return
    else:
        for item in tasks:
            if item.get("type") == "folder":
                target = item
                break
        if not target:
            print("❌ No folder found — create one first in the GUI (press 'f')")
            return

    new_task = {
        "label": f"[T] {task_name}",
        "type": "task",
        "quadrant": None,
        "priority": 0,
        "uid": str(uuid.uuid4()),
        "completed": False,
        "children": []
    }

    target.setdefault("children", []).append(new_task)
    save_tasks(tasks)
    add_log(f"Added task '{task_name}' under '{target.get('label', 'folder')}'")
    print(f"✅ Task '{task_name}' added")
    print(f"   UID: {new_task['uid']}")


def cmd_list(args):
    tasks = load_tasks()
    flat = flatten_tasks(tasks)

    if args.inbox:
        flat = [t for t in flat if t["type"] == "task" and t["quadrant"] in ("-", None)]

    if not flat:
        print("📭 No tasks found")
        return

    print("\n" + "=" * 80)
    print(f"{'Status':<8} {'UID':<36} {'Task':<35} {'Quadrant':<10}")
    print("=" * 80)

    for task in flat:
        uid_display = task['uid'][:34] if len(task['uid']) > 34 else task['uid']
        if task["type"] == "folder":
            print(f"{'📁':<8} {uid_display:<36} {task['label'][:33]:<35} {task['quadrant']:<10}")
        else:
            print(f"[{task['status']}] {uid_display:<36} {task['label'][:33]:<35} {task['quadrant']:<10}")

    print("=" * 80)


def cmd_complete(args):
    tasks = load_tasks()
    task_id = args.task_id

    task, parent_list, idx, parent = find_task_by_id(tasks, task_id)
    if not task:
        print("❌ Task not found")
        return

    if task.get("completed"):
        print("⚠️ Task already completed")
        return

    quadrant = task.get("quadrant")
    if not quadrant or quadrant not in ["Q1", "Q2", "Q3", "Q4"]:
        print(f"❌ Task has no quadrant. Use 'pixi move {task_id} Q1' first")
        return

    value = args.value if args.value else 1.0
    state = load_daily_state()
    state = rollover_day(state)

    # Effective NQ depends on what is still pending in the matrix.
    pending_counts = {"Q1": 0, "Q2": 0, "Q3": 0, "Q4": 0}
    for t in flatten_tasks(tasks):
        if not t["completed"] and t["quadrant"] != "-":
            pending_counts[t["quadrant"]] += 1

    if quadrant == "Q1":
        added_score = NQ1_BASE / value if value != 0 else 0
    elif quadrant == "Q2":
        if pending_counts.get("Q1", 0) > 0:
            added_score = value * (NQ2_BASE / 2.0)
        else:
            added_score = value * NQ2_BASE
    elif quadrant == "Q3":
        added_score = 0.0
    elif quadrant == "Q4":
        if pending_counts.get("Q1", 0) > 0 or pending_counts.get("Q2", 0) > 0 or pending_counts.get("Q3", 0) > 0:
            added_score = value * (NQ4_BASE * 2.0)
        else:
            added_score = value * NQ4_BASE
    else:
        added_score = 0.0

    state["day_score"] += added_score
    state["last_date"] = date.today().isoformat()
    save_daily_state(state)

    task["completed"] = True
    task["quadrant"] = None
    task["priority"] = 0

    save_tasks(tasks)
    add_log(f"Completed task '{task.get('label')}' in {quadrant}, added {added_score:.2f} to score")

    print("✅ Task completed!")
    print(f"   Added score: {added_score:.2f}")
    print(f"   Daily score: {state['day_score']:.2f}")


def cmd_move(args):
    tasks = load_tasks()
    task_id = args.task_id
    quadrant = args.quadrant.upper()

    if quadrant not in ["Q1", "Q2", "Q3", "Q4"]:
        print("❌ Invalid quadrant. Use Q1, Q2, Q3, or Q4")
        return

    task, parent_list, idx, parent = find_task_by_id(tasks, task_id)
    if not task:
        print(f"❌ Task with ID '{task_id}' not found")
        return

    old_quadrant = task.get("quadrant")
    task["quadrant"] = quadrant
    task["completed"] = False

    # Place the task last (lowest priority) within the new quadrant.
    flat = flatten_tasks(tasks)
    max_priority = 0
    for t in flat:
        if t["quadrant"] == quadrant and not t["completed"]:
            orig_task, _, _, _ = find_task_by_id(tasks, t["uid"])
            if orig_task and orig_task.get("priority", 0) > max_priority:
                max_priority = orig_task.get("priority", 0)
    task["priority"] = max_priority + 1

    save_tasks(tasks)
    add_log(f"Moved task '{task.get('label')}' from {old_quadrant or 'None'} to {quadrant}")
    print(f"✅ Task moved to {quadrant}")


def cmd_delete(args):
    tasks = load_tasks()
    task_id = args.task_id

    task, parent_list, idx, parent = find_task_by_id(tasks, task_id)
    if not task:
        print(f"❌ Task with ID '{task_id}' not found")
        return

    task_name = task.get("label")
    parent_list.pop(idx)

    save_tasks(tasks)
    add_log(f"Deleted task '{task_name}'")
    print(f"✅ Task '{task_name}' deleted")


def cmd_report(args):
    if not os.path.exists(SCORES_FILE):
        print("📭 No reports found")
        return

    with open(SCORES_FILE, "r") as f:
        lines = f.readlines()

    if args.date:
        lines = [l for l in lines if args.date in l]

    print("\n" + "=" * 40)
    print("Daily Scores Report")
    print("=" * 40)
    for line in lines[-30:]:
        print(line.strip())
    print("=" * 40)


def cmd_log(args):
    if not os.path.exists(LOGS_FILE):
        print("📭 No logs found")
        return

    with open(LOGS_FILE, "r") as f:
        logs = json.load(f)

    limit = args.limit if args.limit else 30
    print("\n" + "=" * 80)
    print(f"Activity Logs (last {limit})")
    print("=" * 80)
    for log in logs[-limit:]:
        print(log)
    print("=" * 80)


def cmd_stats(args):
    tasks = load_tasks()
    flat = flatten_tasks(tasks)

    stats = {"Q1": 0, "Q2": 0, "Q3": 0, "Q4": 0, "inbox": 0, "completed": 0}

    for task in flat:
        if task["type"] != "task":
            continue
        if task["completed"]:
            stats["completed"] += 1
        elif task["quadrant"] in ("-", None):
            stats["inbox"] += 1
        elif task["quadrant"] in stats:
            stats[task["quadrant"]] += 1

    state = load_daily_state()

    print("\n" + "=" * 50)
    print("📊 Eisenhower Matrix Statistics")
    print("=" * 50)
    print(f"🔴 Q1 (Important & Urgent):         {stats['Q1']} tasks")
    print(f"🟡 Q2 (Important & Not Urgent):     {stats['Q2']} tasks")
    print(f"🟠 Q3 (Not Important & Urgent):     {stats['Q3']} tasks")
    print(f"⚪ Q4 (Not Important & Not Urgent): {stats['Q4']} tasks")
    print(f"📥 Inbox (No quadrant):             {stats['inbox']} tasks")
    print(f"✅ Completed:                       {stats['completed']} tasks")
    print("-" * 50)
    print(f"⭐ Today's Score: {state['day_score']:.2f}")
    print("=" * 50)


def cmd_gui(args):
    """Launch the interactive TUI (main.py) with the current interpreter."""
    print("🚀 Launching Pixi GUI...")
    main_script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "main.py")
    try:
        subprocess.run([sys.executable, main_script])
    except FileNotFoundError:
        print("❌ main.py not found next to pixi.py")
    except KeyboardInterrupt:
        print("\n👋 GUI closed")


def main():
    parser = argparse.ArgumentParser(
        prog="pixi",
        description="Pixi — Eisenhower Matrix CLI & TUI Task Manager",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    pixi add "Write report" --folder Work
    pixi list --inbox
    pixi move abc123 Q1
    pixi complete abc123 --value 2.5
    pixi delete abc123
    pixi stats
    pixi report
    pixi log --limit 20
    pixi gui
        """
    )

    subparsers = parser.add_subparsers(dest="command", help="Commands")

    add_parser = subparsers.add_parser("add", help="Add a new task")
    add_parser.add_argument("task", help="Task name")
    add_parser.add_argument("--folder", "-f", help="Target folder name")

    list_parser = subparsers.add_parser("list", help="List all tasks")
    list_parser.add_argument("--inbox", "-i", action="store_true", help="Show only inbox tasks (no quadrant)")

    complete_parser = subparsers.add_parser("complete", help="Complete a task")
    complete_parser.add_argument("task_id", help="Task UID")
    complete_parser.add_argument("--value", "-v", type=float, default=1.0, help="Value for score calculation")

    move_parser = subparsers.add_parser("move", help="Move task to quadrant")
    move_parser.add_argument("task_id", help="Task UID")
    move_parser.add_argument("quadrant", help="Target quadrant (Q1, Q2, Q3, Q4)")

    delete_parser = subparsers.add_parser("delete", help="Delete a task")
    delete_parser.add_argument("task_id", help="Task UID")

    report_parser = subparsers.add_parser("report", help="Show daily scores report")
    report_parser.add_argument("--date", "-d", help="Filter by date (YYYY-MM-DD)")

    log_parser = subparsers.add_parser("log", help="Show activity logs")
    log_parser.add_argument("--limit", "-n", type=int, default=30, help="Number of log entries to show")

    subparsers.add_parser("stats", help="Show matrix statistics")
    subparsers.add_parser("gui", help="Launch graphical interface (main.py)")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    commands = {
        "add": cmd_add,
        "list": cmd_list,
        "complete": cmd_complete,
        "move": cmd_move,
        "delete": cmd_delete,
        "report": cmd_report,
        "log": cmd_log,
        "stats": cmd_stats,
        "gui": cmd_gui,
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()
