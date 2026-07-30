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
        self.status_var = tk.StringVar(value="Not loaded")
        self.runs: list[dict[str, Any]] = []
        self._build()

    def _build(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        filters = ttk.Frame(self)
        filters.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        filters.columnconfigure(1, weight=1)
        filters.columnconfigure(3, weight=1)
        ttk.Label(filters, text="Dish ID").grid(row=0, column=0)
        ttk.Entry(filters, textvariable=self.dish_filter_var).grid(row=0, column=1, sticky="ew", padx=4)
        ttk.Label(filters, text="Condition").grid(row=0, column=2)
        ttk.Entry(filters, textvariable=self.condition_filter_var).grid(row=0, column=3, sticky="ew", padx=4)
        ttk.Button(filters, text="Refresh", command=self.refresh_async).grid(row=0, column=4, padx=2)
        ttk.Button(filters, text="Open details", command=self.open_details).grid(row=0, column=5, padx=2)
        ttk.Button(filters, text="Export selected", command=lambda: self.export(False)).grid(row=0, column=6, padx=2)
        ttk.Button(filters, text="Export visible", command=lambda: self.export(True)).grid(row=0, column=7, padx=2)
        columns = ("timestamp", "dish_id", "condition", "run_id", "in_flow_ml_min", "out_flow_ml_min", "terminal_state")
        self.tree = ttk.Treeview(self, columns=columns, show="headings", height=14)
        for column in columns:
            self.tree.heading(column, text=column.replace("_", " ").title())
            self.tree.column(column, width=120 if column not in {"run_id", "timestamp"} else 190)
        self.tree.grid(row=1, column=0, sticky="nsew")
        ttk.Label(self, textvariable=self.status_var).grid(row=2, column=0, sticky="w", pady=(4, 0))

    def refresh_async(self) -> None:
        dish = self.dish_filter_var.get()
        condition = self.condition_filter_var.get()
        self.status_var.set("Loading…")

        def worker() -> None:
            try:
                runs = recent_runs(
                    self.app.config_resolution,
                    limit=20,
                    dish_id=dish,
                    condition=condition,
                )
                self.app.post_ui(self._apply_runs, runs, None)
            except Exception as exc:
                self.app.post_ui(self._apply_runs, [], str(exc))

        threading.Thread(target=worker, daemon=True, name="a4-run-history").start()

    def _apply_runs(self, runs: list[dict[str, Any]], error: str | None) -> None:
        self.runs = runs
        for item in self.tree.get_children():
            self.tree.delete(item)
        for index, run in enumerate(runs):
            self.tree.insert(
                "",
                "end",
                iid=str(index),
                values=tuple(run.get(column, "") for column in self.tree["columns"]),
            )
        self.status_var.set(error or f"{len(runs)} recent run(s)")

    def open_details(self) -> None:
        selected = self.tree.selection()
        if not selected:
            return
        run = self.runs[int(selected[0])]
        window = tk.Toplevel(self)
        window.title("Run evidence")
        text = tk.Text(window, width=100, height=30, wrap="word")
        text.pack(fill="both", expand=True)
        text.insert("end", json.dumps(run, ensure_ascii=False, indent=2))
        text.configure(state="disabled")

    def export(self, visible: bool) -> None:
        selected = self.tree.selection()
        runs = self.runs if visible else ([self.runs[int(selected[0])]] if selected else [])
        if not runs:
            messagebox.showerror("Nothing to export", "Select a run or refresh the visible list.")
            return
        output = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv"), ("JSON", "*.json"), ("Markdown", "*.md")],
        )
        if not output:
            return
        format = "json" if output.casefold().endswith(".json") else "markdown" if output.casefold().endswith(".md") else "csv"

        def worker() -> None:
            try:
                path = export_runs(runs, output, format=format)
                self.app.post_ui(self.status_var.set, f"Exported: {path}")
            except Exception as exc:
                self.app.post_ui(messagebox.showerror, "Run export failed", str(exc))

        threading.Thread(target=worker, daemon=True, name="a4-run-export").start()
