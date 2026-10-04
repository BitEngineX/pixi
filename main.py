#!/usr/bin/env python3
"""
Pixi — Interactive Terminal UI (TUI) for the Eisenhower Matrix Task Manager.

A keyboard-driven Textual app with a task tree, the four-quadrant Eisenhower
Matrix, a prioritized todo list, and a gamified daily scoring system.

Run with:  pixi gui   (or: python main.py)
"""

from textual.app import App, ComposeResult
from textual.widgets import Tree, Header, Footer, Label, Input, ListView, ListItem, Button, Digits, TabbedContent, TabPane
from textual.containers import Vertical, Horizontal
from textual.screen import ModalScreen
import json
import os
import uuid
from datetime import datetime, date

# Data files live next to the source by default. Override with the
# PIXI_DATA_DIR environment variable to store your data anywhere you like.
DATA_DIR = os.environ.get("PIXI_DATA_DIR") or os.path.dirname(os.path.abspath(__file__))
SAVE_FILE = os.path.join(DATA_DIR, "tasks.json")
STATE_FILE = os.path.join(DATA_DIR, "daily_state.json")
LOGS_FILE = os.path.join(DATA_DIR, "logs.json")
SCORES_FILE = os.path.join(DATA_DIR, "daily_scores.log")

# ========== تنظیمات پایه امتیازدهی ==========
NQ1_BASE = 600.0
NQ2_BASE = 350.0
NQ4_BASE = -150.0
# ===========================================


class MainApp(App):
    TITLE = "Pixi — Eisenhower Matrix"
    SUB_TITLE = "Manage tasks. Score your day."

    CSS = """
    Screen {
        layout: vertical;
    }
    TabbedContent {
        height: 1fr;
    }
    #tree-panel {
        border: solid $primary;
        margin: 1;
        padding: 1;
    }
    #matrix-panel {
        border: solid $secondary;
        margin: 1;
        padding: 1;
    }
    #todo-panel {
        border: solid $success;
        margin: 1;
        padding: 1;
    }
    Tree {
        height: 1fr;
        border: none;
    }
    #search-box {
        margin: 0 1 1 1;
    }
    #status {
        height: 1;
        dock: bottom;
        background: $surface;
        padding: 0 1;
    }
    .quadrant {
        height: 1fr;
        border: solid $panel;
        margin: 1;
        padding: 1;
    }
    .q1 { border: solid $error; }
    .q2 { border: solid $warning; }
    .q3 { border: solid $success; }
    .q4 { border: solid $primary; }
    .task-list {
        height: 1fr;
        margin-top: 1;
    }
    ListItem {
        padding: 0 1;
    }
    ListItem:focus {
        background: $primary 30%;
    }
    Digits {
        width: auto;
        text-align: center;
        margin-top: 1;
        color: $text;
    }
    """

    BINDINGS = [
        ("n", "add_task", "New Task"),
        ("f", "add_folder", "New Folder"),
        ("r", "rename", "Rename"),
        ("d", "delete", "Delete"),
        ("c", "complete_task", "Complete Task"),
        ("q", "quit", "Quit"),
        ("e", "expand_all", "Expand All"),
        ("w", "collapse_all", "Collapse All"),
        ("left", "move_left", "Move Left (Up Priority)"),
        ("right", "move_right", "Move Right (Down Priority)"),
        ("s", "change_quadrant", "Change Quadrant"),
    ]

    def __init__(self):
        super().__init__()
        self.selected_node = None
        self.day_score = 0.0
        self.last_date = None
        self.log_entries = []

    def compose(self) -> ComposeResult:
        yield Header()
        with TabbedContent():
            with TabPane("Dashboard", id="dashboard"):
                with Horizontal():
                    # پنل درخت (چپ)
                    with Vertical(id="tree-panel"):
                        self.search_input = Input(placeholder="Search tasks...", id="search-box")
                        yield self.search_input
                        self.main_tree = Tree("My Tasks")
                        yield self.main_tree
                        self.score_digits = Digits("0.00")
                        yield self.score_digits

                    # پنل ماتریس (وسط)
                    with Vertical(id="matrix-panel"):
                        yield Label("Eisenhower Matrix (← → to reorder, s to change quadrant)")
                        with Vertical(classes="quadrant q1"):
                            yield Label("Q1: Important & Urgent")
                            self.q1_list = ListView(classes="task-list")
                            yield self.q1_list
                        with Vertical(classes="quadrant q2"):
                            yield Label("Q2: Important & Not Urgent")
                            self.q2_list = ListView(classes="task-list")
                            yield self.q2_list
                        with Vertical(classes="quadrant q3"):
                            yield Label("Q3: Not Important & Urgent")
                            self.q3_list = ListView(classes="task-list")
                            yield self.q3_list
                        with Vertical(classes="quadrant q4"):
                            yield Label("Q4: Not Important & Not Urgent")
                            self.q4_list = ListView(classes="task-list")
                            yield self.q4_list

                    # پنل Todo (راست)
                    with Vertical(id="todo-panel"):
                        yield Label("Todo List (c to complete)")
                        self.todo_list = ListView(classes="task-list")
                        yield self.todo_list
                        self.clock_digits = Digits("")
                        yield self.clock_digits

            with TabPane("Reports", id="reports"):
                self.report_list = ListView()
                yield self.report_list

            with TabPane("Logs", id="logs"):
                self.log_list = ListView()
                yield self.log_list

        yield Label("Status: Ready", id="status")
        yield Footer()

    # ---------- توابع کمکی ----------
    def get_quadrant_from_listview(self, listview):
        if listview == self.q1_list:
            return "Q1"
        if listview == self.q2_list:
            return "Q2"
        if listview == self.q3_list:
            return "Q3"
        if listview == self.q4_list:
            return "Q4"
        return "unknown"

    # ---------- حرکت با چپ/راست ----------
    def action_move_left(self):
        listview = self.get_focused_listview()
        if listview and listview.index is not None and listview.index > 0:
            quadrant = self.get_quadrant_from_listview(listview)
            self._swap_items(listview, quadrant, listview.index, listview.index - 1)
        else:
            if self.main_tree.has_focus and self.selected_node:
                if self.selected_node.data and self.selected_node.data.get("type") == "folder":
                    if self.selected_node.is_expanded:
                        self.selected_node.collapse()

    def action_move_right(self):
        listview = self.get_focused_listview()
        if listview and listview.index is not None and listview.index < len(listview.children) - 1:
            quadrant = self.get_quadrant_from_listview(listview)
            self._swap_items(listview, quadrant, listview.index, listview.index + 1)
        else:
            if self.main_tree.has_focus and self.selected_node:
                if self.selected_node.data and self.selected_node.data.get("type") == "folder":
                    if not self.selected_node.is_expanded:
                        self.selected_node.expand()

    def _swap_items(self, listview, quadrant, idx_a, idx_b):
        if listview == self.todo_list:
            return
        items = list(listview.children)
        if idx_a < 0 or idx_b < 0 or idx_a >= len(items) or idx_b >= len(items):
            return
        items[idx_a], items[idx_b] = items[idx_b], items[idx_a]
        nodes = [getattr(it, "task_node", None) for it in items]
        listview.clear()
        for it in items:
            listview.append(it)
        listview.index = idx_b
        for i, node in enumerate(nodes):
            if node and node.data.get("quadrant"):
                node.data["priority"] = i + 1
        self.save_tasks()
        self.refresh_matrix()
        self.refresh_todo_list()
        listview.focus()
        listview.index = idx_b
        self.update_status("Priority updated")
        self.add_log(f"Reordered tasks in {quadrant}")

    # ---------- بقیه متدها (بدون تغییر) ----------
    def on_mount(self):
        self.load_daily_state()
        self.check_and_reset_day()
        if os.path.exists(SAVE_FILE):
            self.load_tasks()
        else:
            self.create_default_tasks()
        self.selected_node = self.main_tree.root
        self.main_tree.focus()
        self.refresh_matrix()
        self.refresh_todo_list()
        self.update_score_display()
        self.update_status(f"Daily score: {self.day_score:.2f}")
        self.update_clock()
        self.set_interval(1, self.update_clock)
        self.refresh_log_panel()
        self.refresh_report_panel()
        self.add_log("Application started")

    def update_clock(self):
        now = datetime.now().time()
        if hasattr(self, 'clock_digits'):
            self.clock_digits.update(f"{now:%T}")

    # ---------- مدیریت امتیاز و لاگ ----------
    def load_daily_state(self):
        if os.path.exists(STATE_FILE):
            try:
                with open(STATE_FILE, "r") as f:
                    data = json.load(f)
                    self.day_score = data.get("day_score", 0.0)
                    last_date_str = data.get("last_date")
                    if last_date_str:
                        self.last_date = datetime.fromisoformat(last_date_str).date()
            except:
                self.day_score = 0.0
                self.last_date = None
        else:
            self.day_score = 0.0
            self.last_date = None
        self.update_score_display()

    def save_daily_state(self):
        state = {
            "day_score": self.day_score,
            "last_date": date.today().isoformat()
        }
        with open(STATE_FILE, "w") as f:
            json.dump(state, f, indent=2)

    def log_daily_score(self, score, day_date):
        with open(SCORES_FILE, "a") as f:
            f.write(f"{day_date.isoformat()}: {score:.2f}\n")
        self.refresh_report_panel()

    def check_and_reset_day(self):
        today = date.today()
        if self.last_date is None:
            self.last_date = today
            self.save_daily_state()
            self.add_log("Daily state initialized.")
            return
        if self.last_date < today:
            self.log_daily_score(self.day_score, self.last_date)
            self.add_log(f"Day ended. Final score: {self.day_score:.2f}. Reset to 0.")
            self.day_score = 0.0
            self.last_date = today
            self.save_daily_state()
            self.update_score_display()
            self.update_status("New day! Daily score reset to 0.00")
            self.refresh_todo_list()
        else:
            self.save_daily_state()
            self.update_score_display()

    def update_score_display(self):
        if hasattr(self, 'score_digits'):
            self.score_digits.update(f"{self.day_score:.2f}")

    def add_log(self, message):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_entry = f"[{timestamp}] {message}"
        self.log_entries.append(log_entry)
        if len(self.log_entries) > 500:
            self.log_entries = self.log_entries[-500:]
        with open(LOGS_FILE, "w") as f:
            json.dump(self.log_entries, f, indent=2)
        if hasattr(self, 'log_list'):
            self.refresh_log_panel()

    def refresh_log_panel(self):
        if hasattr(self, 'log_list'):
            self.log_list.clear()
            if os.path.exists(LOGS_FILE):
                try:
                    with open(LOGS_FILE, "r") as f:
                        data = json.load(f)
                        self.log_entries = data
                except:
                    self.log_entries = []
            for entry in self.log_entries[-100:]:
                self.log_list.append(ListItem(Label(entry)))
            if not self.log_entries:
                self.log_list.append(ListItem(Label("No logs yet.")))

    def refresh_report_panel(self):
        if hasattr(self, 'report_list'):
            self.report_list.clear()
            if os.path.exists(SCORES_FILE):
                with open(SCORES_FILE, "r") as f:
                    lines = f.readlines()
                for line in lines:
                    self.report_list.append(ListItem(Label(line.strip())))
            else:
                self.report_list.append(ListItem(Label("No reports yet.")))

    def update_status(self, msg):
        self.query_one("#status", Label).update(msg)

    def get_node_text(self, node):
        text = str(node.label)
        for prefix in ["[F] ", "[T] "]:
            if text.startswith(prefix):
                text = text[len(prefix):]
        return text

    def collect_all_task_nodes(self):
        tasks = []
        def collect(node):
            for child in node.children:
                if child.data and child.data.get("type") == "task":
                    tasks.append(child)
                collect(child)
        collect(self.main_tree.root)
        return tasks

    def count_pending_by_quadrant(self):
        counts = {"Q1": 0, "Q2": 0, "Q3": 0, "Q4": 0}
        for node in self.collect_all_task_nodes():
            if not node.data.get("completed"):
                q = node.data.get("quadrant")
                if q in counts:
                    counts[q] += 1
        return counts

    def refresh_matrix(self):
        self.q1_list.clear()
        self.q2_list.clear()
        self.q3_list.clear()
        self.q4_list.clear()
        groups = {"Q1": [], "Q2": [], "Q3": [], "Q4": []}
        for node in self.collect_all_task_nodes():
            if node.data.get("completed"):
                continue
            q = node.data.get("quadrant")
            if q and q in groups:
                groups[q].append(node)
        for q in groups:
            groups[q].sort(key=lambda n: n.data.get("priority", 0))
        def add_items(lst, nodes):
            for node in nodes:
                name = self.get_node_text(node)
                item = ListItem(Label(name))
                item.task_node = node
                lst.append(item)
        add_items(self.q1_list, groups["Q1"])
        add_items(self.q2_list, groups["Q2"])
        add_items(self.q3_list, groups["Q3"])
        add_items(self.q4_list, groups["Q4"])

    def refresh_todo_list(self):
        self.todo_list.clear()
        tasks = [node for node in self.collect_all_task_nodes()
                 if not node.data.get("completed") and node.data.get("quadrant") in ("Q1", "Q2", "Q3", "Q4")]
        quadrant_order = {"Q1": 1, "Q2": 2, "Q3": 3, "Q4": 4}
        tasks.sort(key=lambda n: (quadrant_order.get(n.data.get("quadrant"), 5), n.data.get("priority", 0)))
        for node in tasks:
            quadrant = node.data.get("quadrant")
            priority = node.data.get("priority", 0)
            name = self.get_node_text(node)
            item = ListItem(Label(f"[{quadrant}-{priority}] {name}"))
            item.task_node = node
            self.todo_list.append(item)

    def get_focused_listview(self):
        if self.q1_list.has_focus:
            return self.q1_list
        if self.q2_list.has_focus:
            return self.q2_list
        if self.q3_list.has_focus:
            return self.q3_list
        if self.q4_list.has_focus:
            return self.q4_list
        if self.todo_list.has_focus:
            return self.todo_list
        return None

    def get_selected_task(self):
        listview = self.get_focused_listview()
        if listview and listview.index is not None:
            if listview.index < len(listview.children):
                item = listview.children[listview.index]
                if hasattr(item, "task_node"):
                    return listview, item.task_node, listview.index
        if self.selected_node and self.selected_node.data and self.selected_node.data.get("type") == "task":
            return None, self.selected_node, None
        return None, None, None

    # ---------- جستجو ----------
    def on_input_changed(self, event: Input.Changed):
        if event.input.id == "search-box":
            self.apply_search(event.value.strip())

    def apply_search(self, query):
        if not query:
            return
        query_lower = query.lower()
        for node in self.collect_all_task_nodes():
            if query_lower in self.get_node_text(node).lower():
                p = node.parent
                while p:
                    p.expand()
                    p = p.parent
                node.expand()

    # ---------- تغییر ربع (کلید s) ----------
    def action_change_quadrant(self):
        _, task_node, _ = self.get_selected_task()
        if not task_node:
            self.update_status("No task selected. Select a task in tree, matrix or todo list.")
            return
        task_name = self.get_node_text(task_node)
        current_quadrant = task_node.data.get("quadrant")
        is_completed = task_node.data.get("completed", False)

        class QuadrantDialog(ModalScreen):
            CSS = """
            QuadrantDialog {
                background: $surface;
                border: solid $primary;
                width: 40;
                height: 20;
                padding: 1;
            }
            Button { margin: 1; width: 1fr; }
            """
            def compose(self):
                yield Label(f"Task: {task_name}")
                if is_completed:
                    yield Label("Task is completed. Select a quadrant to reactivate it.")
                else:
                    yield Label(f"Current quadrant: {current_quadrant if current_quadrant else 'None'}")
                yield Label("Select quadrant (1-4) or remove (0):")
                yield Button("1. Q1: Important & Urgent", id="q1", variant="primary")
                yield Button("2. Q2: Important & Not Urgent", id="q2", variant="primary")
                yield Button("3. Q3: Not Important & Urgent", id="q3", variant="primary")
                yield Button("4. Q4: Not Important & Not Urgent", id="q4", variant="primary")
                if not is_completed and current_quadrant:
                    yield Button("0. Remove from matrix", id="remove", variant="default")
                yield Button("Cancel", id="cancel", variant="default")
            def on_key(self, e):
                if e.key == "1":
                    self.dismiss("Q1")
                elif e.key == "2":
                    self.dismiss("Q2")
                elif e.key == "3":
                    self.dismiss("Q3")
                elif e.key == "4":
                    self.dismiss("Q4")
                elif e.key == "0" and not is_completed and current_quadrant:
                    self.dismiss(None)
                elif e.key == "escape":
                    self.dismiss("cancel")
            def on_button_pressed(self, e):
                if e.button.id == "q1":
                    self.dismiss("Q1")
                elif e.button.id == "q2":
                    self.dismiss("Q2")
                elif e.button.id == "q3":
                    self.dismiss("Q3")
                elif e.button.id == "q4":
                    self.dismiss("Q4")
                elif e.button.id == "remove":
                    self.dismiss(None)
                elif e.button.id == "cancel":
                    self.dismiss("cancel")

        def set_quadrant(choice):
            if choice == "cancel":
                self.update_status("Cancelled")
                return
            if choice is None:
                task_node.data["quadrant"] = None
                task_node.data["priority"] = 0
                self.save_tasks()
                self.refresh_matrix()
                self.refresh_todo_list()
                self.update_status(f"Task '{task_name}' removed from matrix")
                self.add_log(f"Removed task '{task_name}' from matrix")
            elif choice in ("Q1", "Q2", "Q3", "Q4"):
                task_node.data["quadrant"] = choice
                task_node.data["completed"] = False
                existing = [n for n in self.collect_all_task_nodes() if n.data.get("quadrant") == choice and not n.data.get("completed")]
                max_prio = max((n.data.get("priority", 0) for n in existing), default=0)
                task_node.data["priority"] = max_prio + 1
                self.save_tasks()
                self.refresh_matrix()
                self.refresh_todo_list()
                self.update_status(f"Task '{task_name}' moved to {choice}")
                self.add_log(f"Task '{task_name}' moved to {choice}")

        self.push_screen(QuadrantDialog(), set_quadrant)

    # ---------- تکمیل تسک (کلید c) ----------
    def action_complete_task(self):
        self.check_and_reset_day()
        listview, task_node, idx = self.get_selected_task()
        if not task_node:
            self.update_status("No task selected. Select a task in matrix or todo list.")
            return
        if task_node.data.get("completed"):
            self.update_status("Task already completed.")
            return
        task_name = self.get_node_text(task_node)
        quadrant = task_node.data.get("quadrant")
        if quadrant not in ("Q1", "Q2", "Q3", "Q4"):
            self.update_status("Task is not in any quadrant. Please assign a quadrant first (using 's').")
            return

        pending_counts = self.count_pending_by_quadrant()
        def get_effective_nq(quad):
            if quad == "Q1":
                return NQ1_BASE
            elif quad == "Q2":
                if pending_counts.get("Q1", 0) > 0:
                    return NQ2_BASE / 2.0
                else:
                    return NQ2_BASE
            elif quad == "Q3":
                return 0.0
            elif quad == "Q4":
                if (pending_counts.get("Q1", 0) > 0 or
                    pending_counts.get("Q2", 0) > 0 or
                    pending_counts.get("Q3", 0) > 0):
                    return NQ4_BASE * 2.0
                else:
                    return NQ4_BASE
            else:
                return 0.0
        effective_nq = get_effective_nq(quadrant)

        def complete_and_add_score(added_score):
            self.day_score += added_score
            self.save_daily_state()
            self.update_score_display()
            task_node.data["completed"] = True
            task_node.data["quadrant"] = None
            task_node.data["priority"] = 0
            self.save_tasks()
            self.refresh_matrix()
            self.refresh_todo_list()
            self.update_status(f"Task '{task_name}' completed. Added {added_score:.2f} to daily score. New score: {self.day_score:.2f}")
            self.add_log(f"Completed task '{task_name}' in {quadrant}, added {added_score:.2f} to score. Total: {self.day_score:.2f}")
            self.check_and_reset_day()

        class ValueDialog(ModalScreen):
            CSS = """
            ValueDialog {
                background: $surface;
                border: solid $primary;
                width: 40;
                height: 8;
                padding: 1;
            }
            Input { margin: 1 0; }
            """
            def __init__(self, prompt, callback):
                super().__init__()
                self.prompt = prompt
                self.callback = callback
            def compose(self):
                yield Label(self.prompt)
                yield Input(placeholder="Enter a number (decimal allowed)", id="value")
                yield Label("Press Enter to confirm, Esc to cancel")
            def on_mount(self):
                self.query_one(Input).focus()
            def on_input_submitted(self, e):
                if e.value.strip():
                    try:
                        val = float(e.value.strip())
                        self.dismiss(val)
                    except:
                        self.dismiss(None)
                else:
                    self.dismiss(None)
            def on_key(self, e):
                if e.key == "escape":
                    self.dismiss(None)

        if quadrant == "Q1":
            def cb(val):
                if val is not None and val != 0:
                    complete_and_add_score(effective_nq / val)
                elif val == 0:
                    self.update_status("Zero not allowed. Task not completed.")
                else:
                    self.update_status("Cancelled. Task not completed.")
            self.push_screen(ValueDialog(f"Enter value for Q1 task '{task_name}' (Score = {effective_nq:.2f} / value):", cb), cb)
        elif quadrant == "Q2":
            def cb(val):
                if val is not None:
                    complete_and_add_score(val * effective_nq)
                else:
                    self.update_status("Cancelled. Task not completed.")
            self.push_screen(ValueDialog(f"Enter value for Q2 task '{task_name}' (Score = value × {effective_nq:.2f}):", cb), cb)
        elif quadrant == "Q3":
            complete_and_add_score(0.0)
        elif quadrant == "Q4":
            def cb(val):
                if val is not None:
                    complete_and_add_score(val * effective_nq)
                else:
                    self.update_status("Cancelled. Task not completed.")
            self.push_screen(ValueDialog(f"Enter value for Q4 task '{task_name}' (Score = value × {effective_nq:.2f}):", cb), cb)

    # ---------- عملیات اصلی درخت ----------
    def create_default_tasks(self):
        work = self.main_tree.root.add("[F] Work")
        work.data = {"type": "folder", "uid": str(uuid.uuid4())}
        personal = self.main_tree.root.add("[F] Personal")
        personal.data = {"type": "folder", "uid": str(uuid.uuid4())}
        t1 = work.add("[T] Complete report")
        t1.data = {"type": "task", "quadrant": "Q1", "priority": 1, "uid": str(uuid.uuid4()), "completed": False}
        t2 = work.add("[T] Team meeting")
        t2.data = {"type": "task", "quadrant": "Q1", "priority": 2, "uid": str(uuid.uuid4()), "completed": False}
        t3 = personal.add("[T] Buy groceries")
        t3.data = {"type": "task", "quadrant": "Q2", "priority": 1, "uid": str(uuid.uuid4()), "completed": False}
        self.main_tree.root.expand()
        work.expand()
        personal.expand()

    def action_add_task(self):
        if not self.selected_node:
            self.update_status("No item selected. Select a folder first.")
            return
        if self.selected_node != self.main_tree.root and (not self.selected_node.data or self.selected_node.data.get("type") != "folder"):
            self.update_status("Select a folder first (cannot add task to a task).")
            return

        class Dialog(ModalScreen):
            def compose(self):
                yield Label("Task name:")
                yield Input(placeholder="Enter name...", id="name")
                yield Label("Press Enter to confirm, Esc to cancel")
            def on_mount(self):
                self.query_one(Input).focus()
            def on_input_submitted(self, e):
                if e.value.strip():
                    self.dismiss(e.value.strip())
            def on_key(self, e):
                if e.key == "escape":
                    self.dismiss(None)

        def callback(name):
            if name:
                new = self.selected_node.add(f"[T] {name}")
                all_tasks = self.collect_all_task_nodes()
                max_prio = max((t.data.get("priority", 0) for t in all_tasks), default=0)
                new.data = {"type": "task", "quadrant": None, "priority": max_prio + 1, "uid": str(uuid.uuid4()), "completed": False}
                self.selected_node.expand()
                self.save_tasks()
                self.refresh_matrix()
                self.refresh_todo_list()
                self.update_status(f"Task '{name}' added")
                self.add_log(f"Added task '{name}' under '{self.get_node_text(self.selected_node)}'")

        self.push_screen(Dialog(), callback)

    def action_add_folder(self):
        if not self.selected_node:
            self.update_status("No item selected. Select a folder first.")
            return
        if self.selected_node != self.main_tree.root and (not self.selected_node.data or self.selected_node.data.get("type") != "folder"):
            self.update_status("Select a folder first (cannot add folder to a task).")
            return

        class Dialog(ModalScreen):
            def compose(self):
                yield Label("Folder name:")
                yield Input(placeholder="Enter name...", id="name")
                yield Label("Press Enter to confirm, Esc to cancel")
            def on_mount(self):
                self.query_one(Input).focus()
            def on_input_submitted(self, e):
                if e.value.strip():
                    self.dismiss(e.value.strip())
            def on_key(self, e):
                if e.key == "escape":
                    self.dismiss(None)

        def callback(name):
            if name:
                new = self.selected_node.add(f"[F] {name}")
                new.data = {"type": "folder", "uid": str(uuid.uuid4())}
                new.allow_expand = True
                self.selected_node.expand()
                self.save_tasks()
                self.update_status(f"Folder '{name}' added")
                self.add_log(f"Added folder '{name}' under '{self.get_node_text(self.selected_node)}'")

        self.push_screen(Dialog(), callback)

    def action_rename(self):
        if not self.selected_node or self.selected_node == self.main_tree.root:
            self.update_status("Select an item to rename")
            return
        old_name = self.get_node_text(self.selected_node)
        current = old_name
        prefix = "[F]" if self.selected_node.data.get("type") == "folder" else "[T]"

        class Dialog(ModalScreen):
            def compose(self):
                yield Label("New name:")
                yield Input(current, id="name")
                yield Label("Press Enter to save, Esc to cancel")
            def on_mount(self):
                self.query_one(Input).focus()
            def on_input_submitted(self, e):
                if e.value.strip():
                    self.dismiss(e.value.strip())
            def on_key(self, e):
                if e.key == "escape":
                    self.dismiss(None)

        def callback(new_name):
            if new_name and new_name != current:
                self.selected_node.label = f"{prefix} {new_name}"
                self.save_tasks()
                self.refresh_matrix()
                self.refresh_todo_list()
                self.update_status(f"Renamed to '{new_name}'")
                self.add_log(f"Renamed '{old_name}' to '{new_name}'")

        self.push_screen(Dialog(), callback)

    def action_delete(self):
        if not self.selected_node or self.selected_node == self.main_tree.root:
            self.update_status("Cannot delete root")
            return
        node = self.selected_node
        name = self.get_node_text(node)

        class Confirm(ModalScreen):
            def compose(self):
                yield Label(f"Delete '{name}'?")
                yield Label("Press y to confirm, n to cancel")
            def on_key(self, e):
                self.dismiss(e.key == "y")

        def callback(confirmed):
            if confirmed:
                node.remove()
                self.selected_node = self.main_tree.root
                self.save_tasks()
                self.refresh_matrix()
                self.refresh_todo_list()
                self.update_status(f"Deleted '{name}'")
                self.add_log(f"Deleted '{name}'")

        self.push_screen(Confirm(), callback)

    def action_expand_all(self):
        def expand(node):
            node.expand()
            for child in node.children:
                expand(child)
        expand(self.main_tree.root)
        self.update_status("Expanded all")
        self.add_log("Expanded all nodes")

    def action_collapse_all(self):
        def collapse(node):
            if node != self.main_tree.root:
                node.collapse()
            for child in node.children:
                collapse(child)
        collapse(self.main_tree.root)
        self.update_status("Collapsed all")
        self.add_log("Collapsed all nodes")

    def save_tasks(self):
        def serialize(node):
            return [{
                "label": str(child.label),
                "type": child.data.get("type"),
                "quadrant": child.data.get("quadrant"),
                "priority": child.data.get("priority", 0),
                "uid": child.data.get("uid"),
                "completed": child.data.get("completed", False),
                "children": serialize(child)
            } for child in node.children]
        with open(SAVE_FILE, "w") as f:
            json.dump(serialize(self.main_tree.root), f, indent=2)

    def load_tasks(self):
        def deserialize(node, items):
            for item in items:
                new = node.add(item["label"])
                data = {k: v for k, v in item.items() if k != "children"}
                new.data = data
                if new.data.get("type") == "folder":
                    new.allow_expand = True
                deserialize(new, item.get("children", []))
        with open(SAVE_FILE, "r") as f:
            deserialize(self.main_tree.root, json.load(f))

    def on_tree_node_selected(self, event):
        self.selected_node = event.node
        node_type = "folder" if event.node.data and event.node.data.get("type") == "folder" else "task"
        self.update_status(f"Selected: {self.get_node_text(event.node)} ({node_type})")
        if event.node.data and event.node.data.get("type") == "task" and not event.node.data.get("quadrant") and not event.node.data.get("completed"):
            self.prompt_quadrant(event.node)

    def prompt_quadrant(self, node):
        task_name = self.get_node_text(node)

        class QuadrantDialog(ModalScreen):
            CSS = """
            QuadrantDialog {
                background: $surface;
                border: solid $primary;
                width: 40;
                height: 18;
                padding: 1;
            }
            Button { margin: 1; width: 1fr; }
            """
            def compose(self):
                yield Label(f"Task: {task_name}")
                yield Label("Select Quadrant (1-4):")
                yield Button("1. Q1: Important & Urgent", id="q1", variant="primary")
                yield Button("2. Q2: Important & Not Urgent", id="q2", variant="primary")
                yield Button("3. Q3: Not Important & Urgent", id="q3", variant="primary")
                yield Button("4. Q4: Not Important & Not Urgent", id="q4", variant="primary")
                yield Button("Cancel", id="cancel", variant="default")
            def on_key(self, e):
                if e.key == "1":
                    self.dismiss("Q1")
                elif e.key == "2":
                    self.dismiss("Q2")
                elif e.key == "3":
                    self.dismiss("Q3")
                elif e.key == "4":
                    self.dismiss("Q4")
                elif e.key == "escape":
                    self.dismiss(None)
            def on_button_pressed(self, e):
                if e.button.id == "q1":
                    self.dismiss("Q1")
                elif e.button.id == "q2":
                    self.dismiss("Q2")
                elif e.button.id == "q3":
                    self.dismiss("Q3")
                elif e.button.id == "q4":
                    self.dismiss("Q4")
                else:
                    self.dismiss(None)

        def set_quadrant(quadrant):
            if quadrant:
                node.data["quadrant"] = quadrant
                existing = [n for n in self.collect_all_task_nodes() if n.data.get("quadrant") == quadrant and not n.data.get("completed")]
                max_prio = max((n.data.get("priority", 0) for n in existing), default=0)
                node.data["priority"] = max_prio + 1
                self.refresh_matrix()
                self.refresh_todo_list()
                self.save_tasks()
                self.update_status(f"Task '{task_name}' added to {quadrant}")
                self.add_log(f"Task '{task_name}' assigned to {quadrant}")

        self.push_screen(QuadrantDialog(), set_quadrant)

    def action_quit(self):
        self.save_tasks()
        self.save_daily_state()
        self.add_log("Application closed")
        self.exit()


if __name__ == "__main__":
    MainApp().run()