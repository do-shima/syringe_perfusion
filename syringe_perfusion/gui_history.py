from __future__ import annotations

import json
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Any

from .run_history import export_runs, recent_runs


class RunHistoryFrame(ttk.Frame):
    def __init__(self, parent: tk.Widget, app: Any) -> None:
        super().__init__(parent, padding=8)
        self.app = app
        self.dish_filter_var = tk.StringVar(value="")
        self.condition_filter_var = tk.StringVar(value="")
        self.status_var = tk.StringVar(value=self.app.t("status.not_loaded"))
        self.runs: list[dict[str, Any]] = []
        self._build()

    def _build(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        self.toolbar = ttk.Frame(self)
        self.toolbar.grid(row=0, column=0, sticky="ew", pady=(0, 7))
        for column in (1, 3):
            self.toolbar.columnconfigure(column, weight=1)
        self.dish_label = ttk.Label(self.toolbar)
        self.dish_label.grid(row=0, column=0, sticky="w")
        ttk.Entry(self.toolbar, textvariable=self.dish_filter_var).grid(row=0, column=1, sticky="ew", padx=(4, 10))
        self.condition_label = ttk.Label(self.toolbar)
        self.condition_label.grid(row=0, column=2, sticky="w")
        ttk.Entry(self.toolbar, textvariable=self.condition_filter_var).grid(row=0, column=3, sticky="ew", padx=(4, 0))
        self.actions = ttk.Frame(self.toolbar)
        self.actions.grid(row=1, column=0, columnspan=4, sticky="ew", pady=(6, 0))
        self.action_buttons: dict[str, ttk.Button] = {}
        for column, (name, command) in enumerate((
            ("refresh", self.refresh_async),
            ("details", self.open_details),
            ("selected", lambda: self.export(False)),
            ("visible", lambda: self.export(True)),
        )):
            self.actions.columnconfigure(column, weight=1)
            button = ttk.Button(self.actions, command=command, style="Neutral.TButton")
            button.grid(row=0, column=column, sticky="ew", padx=(0 if column == 0 else 3, 0))
            self.action_buttons[name] = button

        table = ttk.Frame(self)
        table.grid(row=1, column=0, sticky="nsew")
        table.columnconfigure(0, weight=1)
        table.rowconfigure(0, weight=1)
        columns = ("timestamp", "dish_id", "condition", "run_id", "in_flow_ml_min", "out_flow_ml_min", "terminal_state")
        self.tree = ttk.Treeview(table, columns=columns, show="headings", height=14, selectmode="browse")
        self.tree.grid(row=0, column=0, sticky="nsew")
        self.vscroll = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        self.vscroll.grid(row=0, column=1, sticky="ns")
        self.hscroll = ttk.Scrollbar(table, orient="horizontal", command=self.tree.xview)
        self.hscroll.grid(row=1, column=0, sticky="ew")
        self.tree.configure(yscrollcommand=self.vscroll.set, xscrollcommand=self.hscroll.set)
        widths = {"timestamp": 175, "dish_id": 110, "condition": 150, "run_id": 210,
                  "in_flow_ml_min": 110, "out_flow_ml_min": 110, "terminal_state": 180}
        for column in columns:
            self.tree.column(column, width=widths[column], minwidth=75, stretch=column in {"condition", "run_id", "terminal_state"})
        self.tree.bind("<Double-1>", lambda _event: self.open_details(), add="+")
        ttk.Label(self, textvariable=self.status_var).grid(row=2, column=0, sticky="w", pady=(5, 0))
        self.refresh_language()

    def refresh_language(self) -> None:
        self.dish_label.configure(text=self.app.t("history.dish_id"))
        self.condition_label.configure(text=self.app.t("history.condition"))
        for name, key in {"refresh": "history.refresh", "details": "history.open_details",
                          "selected": "history.export_selected", "visible": "history.export_visible"}.items():
            self.action_buttons[name].configure(text=self.app.t(key))
        keys = ("history.timestamp", "history.dish_id", "history.condition", "history.run_id",
                "history.in_flow", "history.out_flow", "history.terminal_state")
        for column, key in zip(self.tree["columns"], keys):
            self.tree.heading(column, text=self.app.t(key))
        if self.runs:
            self._apply_runs(self.runs, None)
        elif self.status_var.get() != self.app.t("status.loading"):
            self.status_var.set(self.app.t("history.empty"))

    def refresh_async(self) -> None:
        dish = self.dish_filter_var.get()
        condition = self.condition_filter_var.get()
        self.status_var.set(self.app.t("status.loading"))

        def worker() -> None:
            try:
                runs = recent_runs(self.app.config_resolution, limit=20, dish_id=dish, condition=condition)
                self.app.post_ui(self._apply_runs, runs, None)
            except Exception as exc:
                self.app.post_ui(self._apply_runs, [], str(exc))
        threading.Thread(target=worker, daemon=True, name="a4-run-history").start()

    def _apply_runs(self, runs: list[dict[str, Any]], error: str | None) -> None:
        self.runs = runs
        self.tree.delete(*self.tree.get_children())
        for index, run in enumerate(runs):
            values = []
            for column in self.tree["columns"]:
                value = run.get(column, "")
                if column == "terminal_state":
                    value = self.app.localizer.state_label(str(value))
                values.append(value)
            self.tree.insert("", "end", iid=str(index), values=tuple(values))
        self.status_var.set(error or (self.app.t("status.recent_runs", count=len(runs)) if runs else self.app.t("history.empty")))

    def open_details(self) -> None:
        selected = self.tree.selection()
        if not selected:
            return
        run = self.runs[int(selected[0])]
        window = tk.Toplevel(self)
        window.title(self.app.t("history.evidence"))
        window.geometry("760x520")
        window.columnconfigure(0, weight=1)
        window.rowconfigure(1, weight=1)
        canonical = str(run.get("terminal_state", ""))
        ttk.Label(window, text=f"{self.app.t('history.terminal_state')}: {self.app.localizer.state_label(canonical)}",
                  style="SectionTitle.TLabel").grid(row=0, column=0, sticky="w", padx=12, pady=10)
        text = tk.Text(window, width=100, height=25, wrap="none", font=("Consolas", 9))
        text.grid(row=1, column=0, sticky="nsew", padx=(12, 0), pady=(0, 12))
        scrollbar = ttk.Scrollbar(window, orient="vertical", command=text.yview)
        scrollbar.grid(row=1, column=1, sticky="ns", pady=(0, 12))
        text.configure(yscrollcommand=scrollbar.set)
        text.insert("end", json.dumps(run, ensure_ascii=False, indent=2))
        text.configure(state="disabled")

    def export(self, visible: bool) -> None:
        selected = self.tree.selection()
        runs = self.runs if visible else ([self.runs[int(selected[0])]] if selected else [])
        if not runs:
            messagebox.showerror(self.app.t("history.evidence"), self.app.t("history.empty"), parent=self)
            return
        output = filedialog.asksaveasfilename(defaultextension=".csv",
                                               filetypes=[("CSV", "*.csv"), ("JSON", "*.json"), ("Markdown", "*.md")])
        if not output:
            return
        format_name = "json" if output.casefold().endswith(".json") else "markdown" if output.casefold().endswith(".md") else "csv"

        def worker() -> None:
            try:
                path = export_runs(runs, output, format=format_name)
                self.app.post_ui(self.status_var.set, str(path))
            except Exception as exc:
                self.app.post_ui(messagebox.showerror, self.app.t("history.evidence"), str(exc))
        threading.Thread(target=worker, daemon=True, name="a4-run-export").start()
