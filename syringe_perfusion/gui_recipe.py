from __future__ import annotations

import copy
import json
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any, Callable

from .blocks import block_summary, default_block
from .recipe_engine import RecipeEngine
from .recipe_model import Recipe, block_id, validate_recipe
from .recipe_store import default_recipe_dir, load_recipe, save_recipe
from .ui_theme import create_card, status_badge


PALETTE = [
    ("Pump Start", "pump_start"),
    ("Pump Stop", "pump_stop"),
    ("Manual Jog", "manual_jog"),
    ("Wait", "wait"),
    ("Stop All", "stop_all"),
    ("Log Marker", "log_marker"),
    ("Prompt Check", "prompt_check"),
]


class RecipeBuilderFrame(ttk.Frame):
    def __init__(self, parent: tk.Widget, app: Any) -> None:
        super().__init__(parent, padding=12)
        self.app = app
        self.current_path: Path | None = None
        self.blocks: list[dict[str, Any]] = []
        self.recipe_id_var = tk.StringVar(value="new_recipe_v1")
        self.display_name_var = tk.StringVar(value="New recipe")
        self.description_var = tk.StringVar(value="")

        self.prop_type_var = tk.StringVar(value="")
        self.prop_id_var = tk.StringVar(value="")
        self.prop_pump_var = tk.StringVar(value="IN")
        self.prop_action_var = tk.StringVar(value="start_forward")
        self.prop_direction_var = tk.StringVar(value="forward")
        self.prop_profile_var = tk.StringVar(value="fast30_1ml")
        self.prop_duration_var = tk.StringVar(value="1.0")
        self.prop_duration_ms_var = tk.StringVar(value="1000")
        self.prop_message_var = tk.StringVar(value="")
        self.prop_note_var = tk.StringVar(value="")
        self.validation_status_var = tk.StringVar(value="Validation: not checked")
        self.recipe_status_var = tk.StringVar(value="0 blocks")

        self._build()
        self.add_block("pump_start")

    def _build(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        toolbar = create_card(self, "Recipe Builder", "Build repeatable pump procedures from blocks.")
        toolbar.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        for col in range(10):
            toolbar.columnconfigure(col, weight=1 if col in {1, 3} else 0)
        ttk.Label(toolbar, text="Recipe ID", style="Card.TLabel").grid(row=2, column=0, sticky="w", padx=(0, 6), pady=4)
        ttk.Entry(toolbar, textvariable=self.recipe_id_var).grid(row=2, column=1, sticky="ew", padx=(0, 12), pady=4)
        ttk.Label(toolbar, text="Name", style="Card.TLabel").grid(row=2, column=2, sticky="w", padx=(0, 6), pady=4)
        ttk.Entry(toolbar, textvariable=self.display_name_var).grid(row=2, column=3, sticky="ew", padx=(0, 12), pady=4)
        status_badge(toolbar, "READY", "enabled").grid(row=2, column=4, sticky="w", padx=(0, 8))
        actions = [
            ("[New] New", self.new_recipe, "Secondary.TButton"),
            ("[Open] Open", self.load_recipe_dialog, "Secondary.TButton"),
            ("[Save] Save", self.save_current, "Success.TButton"),
            ("[Save] Save As", self.save_as, "Success.TButton"),
            ("[Check] Validate", self.validate_current, "Secondary.TButton"),
            ("[Run] Dry-run", self.dry_run, "Accent.TButton"),
            ("[Run] Run", self.run_recipe, "Accent.TButton"),
            ("[Stop] Stop all", self.stop_all_now, "Danger.TButton"),
        ]
        for index, (label, command, style) in enumerate(actions):
            ttk.Button(toolbar, text=label, command=command, style=style).grid(
                row=3 + index // 4, column=index % 4, sticky="ew", padx=3, pady=3
            )

        panes = ttk.Frame(self, style="Page.TFrame")
        panes.grid(row=1, column=0, sticky="nsew")
        panes.columnconfigure(1, weight=1)
        panes.rowconfigure(0, weight=1)

        self.library_frame = create_card(panes, "Block Library", "Add a step to the recipe.")
        self.library_frame.grid(row=0, column=0, sticky="ns", padx=(0, 10))
        for row, (label, block_type) in enumerate(PALETTE, start=2):
            ttk.Button(
                self.library_frame,
                text=f"[Add] {label}",
                style="Secondary.TButton",
                command=lambda bt=block_type: self.add_block(bt),
            ).grid(row=row, column=0, sticky="ew", pady=4)

        timeline = create_card(panes, "Recipe Steps", "Select a step, then edit it in the inspector.")
        timeline.grid(row=0, column=1, sticky="nsew", padx=(0, 10))
        timeline.rowconfigure(0, weight=1)
        timeline.columnconfigure(0, weight=1)
        self.timeline = tk.Listbox(timeline, activestyle="dotbox", exportselection=False)
        self.timeline.grid(row=2, column=0, sticky="nsew", pady=(8, 0))
        self.timeline.bind("<<ListboxSelect>>", lambda _e: self.load_selected_properties())
        scrollbar = ttk.Scrollbar(timeline, orient="vertical", command=self.timeline.yview)
        scrollbar.grid(row=2, column=1, sticky="ns", pady=(8, 0))
        self.timeline.configure(yscrollcommand=scrollbar.set)

        move_bar = ttk.Frame(timeline)
        move_bar.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        for label, command in [
            ("[Up] Up", self.move_up),
            ("[Down] Down", self.move_down),
            ("[Copy] Duplicate", self.duplicate_selected),
            ("[Delete] Delete", self.delete_selected),
        ]:
            ttk.Button(move_bar, text=label, command=command, style="Secondary.TButton").pack(side="left", padx=(0, 6))

        props = create_card(panes, "Inspector", "Edit the selected block.")
        props.grid(row=0, column=2, sticky="nsew")
        props.columnconfigure(1, weight=1)
        self._prop_row(props, 2, "Type", ttk.Label(props, textvariable=self.prop_type_var, style="Card.TLabel"))
        self._prop_row(props, 3, "ID", ttk.Entry(props, textvariable=self.prop_id_var))
        self.prop_pump_combo = ttk.Combobox(
            props,
            textvariable=self.prop_pump_var,
            values=self.app.available_pumps(),
            state="readonly",
        )
        self._prop_row(props, 4, "Pump", self.prop_pump_combo)
        self._prop_row(
            props,
            5,
            "Action",
            ttk.Combobox(
                props,
                textvariable=self.prop_action_var,
                values=["start_forward", "start_reverse", "stop"],
                state="readonly",
            ),
        )
        self._prop_row(
            props,
            6,
            "Direction",
            ttk.Combobox(
                props,
                textvariable=self.prop_direction_var,
                values=["forward", "reverse"],
                state="readonly",
            ),
        )
        self._prop_row(
            props,
            7,
            "Profile",
            ttk.Combobox(
                props,
                textvariable=self.prop_profile_var,
                values=list(self.app.data["profiles"]),
                state="readonly",
            ),
        )
        self._prop_row(props, 8, "Duration s", ttk.Entry(props, textvariable=self.prop_duration_var))
        self._prop_row(props, 9, "Duration ms", ttk.Entry(props, textvariable=self.prop_duration_ms_var))
        self._prop_row(props, 10, "Message", ttk.Entry(props, textvariable=self.prop_message_var))
        self._prop_row(props, 11, "Note", ttk.Entry(props, textvariable=self.prop_note_var))
        ttk.Button(props, text="[Apply] Apply changes", command=self.apply_properties, style="Accent.TButton").grid(
            row=12, column=0, columnspan=2, sticky="ew", pady=(12, 0)
        )
        ttk.Label(props, textvariable=self.validation_status_var, style="Subtitle.TLabel").grid(
            row=13, column=0, columnspan=2, sticky="w", pady=(10, 0)
        )

        status = ttk.Frame(self, style="Toolbar.TFrame", padding=(10, 6))
        status.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        status.columnconfigure(0, weight=1)
        ttk.Label(status, textvariable=self.recipe_status_var, style="Card.TLabel").grid(row=0, column=0, sticky="w")

        self.log = tk.Text(self, height=6, wrap="word")
        self.log.grid(row=3, column=0, sticky="ew", pady=(8, 0))

        self.app.bind("<Escape>", lambda _e: self.stop_all_now())

    def _prop_row(self, parent: ttk.Frame, row: int, label: str, widget: tk.Widget) -> None:
        ttk.Label(parent, text=label, style="Card.TLabel").grid(row=row, column=0, sticky="w", pady=4, padx=(0, 8))
        widget.grid(row=row, column=1, sticky="ew", pady=4)

    def new_recipe(self) -> None:
        self.current_path = None
        self.blocks = []
        self.recipe_id_var.set("new_recipe_v1")
        self.display_name_var.set("New recipe")
        self.description_var.set("")
        self.add_block("pump_start")
        self.append_log("New recipe")

    def validate_current(self) -> bool:
        try:
            recipe = self.make_recipe()
            self.validation_status_var.set("Validation: OK")
            self.update_status_line(recipe)
            self.append_log("Validation: OK")
            return True
        except Exception as exc:
            self.validation_status_var.set(f"Validation: {exc}")
            self.append_log(f"Validation failed: {exc}")
            return False

    def add_block(self, block_type: str) -> None:
        block = default_block(block_type)
        if "pump" in block and block["pump"] not in self.app.available_pumps():
            block["pump"] = "IN"
        block["id"] = block_id(self.blocks)
        self.blocks.append(block)
        self.refresh_timeline(select=len(self.blocks) - 1)

    def update_available_pumps(self) -> None:
        pumps = self.app.available_pumps()
        self.prop_pump_combo.configure(values=pumps)
        if self.prop_pump_var.get() not in pumps:
            self.prop_pump_var.set("IN")

    def refresh_timeline(self, select: int | None = None) -> None:
        self.timeline.delete(0, "end")
        for index, block in enumerate(self.blocks):
            text = f"{index + 1:02d}. {block_summary(block)}"
            self.timeline.insert("end", text)
        self.update_status_line()
        if select is not None and self.blocks:
            select = max(0, min(select, len(self.blocks) - 1))
            self.timeline.selection_clear(0, "end")
            self.timeline.selection_set(select)
            self.timeline.activate(select)
            self.load_selected_properties()

    def update_status_line(self, recipe: Recipe | None = None) -> None:
        pumps = sorted({str(block.get("pump")) for block in self.blocks if block.get("pump")})
        pump_text = ", ".join(pumps) if pumps else "none"
        validation = "OK" if recipe is not None else "not checked"
        self.recipe_status_var.set(f"{len(self.blocks)} blocks   Validation: {validation}   Uses pumps: {pump_text}")

    def selected_index(self) -> int | None:
        selected = self.timeline.curselection()
        return int(selected[0]) if selected else None

    def load_selected_properties(self) -> None:
        index = self.selected_index()
        if index is None:
            return
        block = self.blocks[index]
        self.prop_type_var.set(block.get("type", ""))
        self.prop_id_var.set(block.get("id", ""))
        self.prop_pump_var.set(block.get("pump", "IN"))
        self.prop_action_var.set(block.get("action", "start_forward"))
        self.prop_direction_var.set(block.get("direction", "forward"))
        self.prop_profile_var.set(block.get("profile", "fast30_1ml"))
        self.prop_duration_var.set(str(block.get("duration_s", "")))
        self.prop_duration_ms_var.set(str(block.get("duration_ms", "1000")))
        self.prop_message_var.set(block.get("message", ""))
        self.prop_note_var.set(block.get("note", ""))

    def apply_properties(self) -> None:
        index = self.selected_index()
        if index is None:
            return
        block_type = self.prop_type_var.get()
        block: dict[str, Any] = {"id": self.prop_id_var.get().strip(), "type": block_type}
        if block_type in {"pump_start", "pump_stop"}:
            block["pump"] = self.prop_pump_var.get()
            block["action"] = "stop" if block_type == "pump_stop" else self.prop_action_var.get()
        if block_type == "pump_start":
            block["profile"] = self.prop_profile_var.get()
        if block_type == "manual_jog":
            block["pump"] = self.prop_pump_var.get()
            block["direction"] = self.prop_direction_var.get()
            block["duration_ms"] = int(self.prop_duration_ms_var.get())
        if block_type == "wait":
            block["duration_s"] = float(self.prop_duration_var.get())
        if block_type in {"log_marker", "prompt_check"}:
            block["message"] = self.prop_message_var.get()
        note = self.prop_note_var.get()
        if note:
            block["note"] = note
        previous = self.blocks[index]
        self.blocks[index] = block
        try:
            validate_recipe(self.make_recipe(), self.app.data)
        except Exception as exc:
            self.blocks[index] = previous
            self.refresh_timeline(select=index)
            messagebox.showerror("Invalid block", str(exc))
            return
        self.refresh_timeline(select=index)

    def move_up(self) -> None:
        index = self.selected_index()
        if index is None or index == 0:
            return
        self.blocks[index - 1], self.blocks[index] = self.blocks[index], self.blocks[index - 1]
        self.refresh_timeline(select=index - 1)

    def move_down(self) -> None:
        index = self.selected_index()
        if index is None or index >= len(self.blocks) - 1:
            return
        self.blocks[index + 1], self.blocks[index] = self.blocks[index], self.blocks[index + 1]
        self.refresh_timeline(select=index + 1)

    def duplicate_selected(self) -> None:
        index = self.selected_index()
        if index is None:
            return
        copied = copy.deepcopy(self.blocks[index])
        copied["id"] = block_id(self.blocks)
        self.blocks.insert(index + 1, copied)
        self.refresh_timeline(select=index + 1)

    def delete_selected(self) -> None:
        index = self.selected_index()
        if index is None:
            return
        del self.blocks[index]
        self.refresh_timeline(select=min(index, len(self.blocks) - 1) if self.blocks else None)

    def make_recipe(self) -> Recipe:
        recipe = Recipe(
            schema_version=2,
            recipe_id=self.recipe_id_var.get().strip(),
            display_name=self.display_name_var.get().strip(),
            description=self.description_var.get().strip(),
            blocks=copy.deepcopy(self.blocks),
        )
        validate_recipe(recipe, self.app.data)
        return recipe

    def load_recipe_dialog(self) -> None:
        path = filedialog.askopenfilename(
            initialdir=str(default_recipe_dir()),
            title="Load recipe",
            filetypes=[("Recipe JSON", "*.json"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            recipe = load_recipe(path)
            validate_recipe(recipe, self.app.data)
            self.current_path = Path(path)
            self.recipe_id_var.set(recipe.recipe_id)
            self.display_name_var.set(recipe.display_name)
            self.description_var.set(recipe.description)
            self.blocks = copy.deepcopy(recipe.blocks)
            self.refresh_timeline(select=0)
            self.append_log(f"Loaded {path}")
        except Exception as exc:
            messagebox.showerror("Load failed", str(exc))

    def save_current(self) -> None:
        if self.current_path is None:
            self.save_as()
            return
        self._save_to(self.current_path)

    def save_as(self) -> None:
        path = filedialog.asksaveasfilename(
            initialdir=str(default_recipe_dir()),
            initialfile=f"{self.recipe_id_var.get()}.json",
            title="Save recipe",
            defaultextension=".json",
            filetypes=[("Recipe JSON", "*.json"), ("All files", "*.*")],
        )
        if not path:
            return
        self.current_path = Path(path)
        self._save_to(self.current_path)

    def _save_to(self, path: Path) -> None:
        try:
            saved = save_recipe(self.make_recipe(), path)
            self.append_log(f"Saved {saved}")
        except Exception as exc:
            messagebox.showerror("Save failed", str(exc))

    def dry_run(self) -> None:
        self._start_execution(dry_run=True)

    def run_recipe(self) -> None:
        self._start_execution(dry_run=False)

    def _start_execution(self, *, dry_run: bool) -> None:
        try:
            recipe = self.make_recipe()
        except Exception as exc:
            messagebox.showerror("Invalid recipe", str(exc))
            return
        if not self.show_preview(recipe):
            return
        if not dry_run:
            if self.uses_reverse(recipe):
                messagebox.showwarning("Reverse warning", "OUT reverse / start_reverse must be physically validated.")
            if not self.show_checklist(recipe):
                return
        self.app.apply_gui_pump_settings()
        self.run_thread(self._execute_worker, recipe, dry_run)

    def _execute_worker(self, recipe: Recipe, dry_run: bool) -> None:
        engine = RecipeEngine(self.app.data)
        events = engine.execute(
            recipe,
            dry_run=dry_run,
            context={
                "dish_id": self.app.dish_id_var.get(),
                "condition": self.app.condition_var.get(),
                "trigger_source": self.app.trigger_var.get(),
                "assume_yes": dry_run,
                "prompt_callback": self.prompt_callback,
            },
        )
        self.append_log(json.dumps(events, ensure_ascii=False))

    def stop_all_now(self) -> None:
        self.app.gui_stop_all_now()
        self.append_log("STOP ALL requested")

    def show_preview(self, recipe: Recipe) -> bool:
        lines = [f"{recipe.display_name} ({recipe.recipe_id})", ""]
        for index, block in enumerate(recipe.blocks, start=1):
            lines.append(f"{index:02d}. {block_summary(block)}")
        return messagebox.askokcancel("Recipe preview", "\n".join(lines))

    def show_checklist(self, recipe: Recipe) -> bool:
        dialog = tk.Toplevel(self)
        dialog.title("Run checklist")
        dialog.transient(self.winfo_toplevel())
        dialog.grab_set()
        vars_ = []
        items = [
            "line primed",
            "R1-FL checked",
            "needle position checked",
            "A4 saved profile checked",
        ]
        if self.uses_reverse(recipe):
            items.append("waste line checked when OUT reverse is used")
        for row, item in enumerate(items):
            var = tk.BooleanVar(value=False)
            ttk.Checkbutton(dialog, text=item, variable=var).grid(row=row, column=0, sticky="w", padx=16, pady=5)
            vars_.append(var)
        result = {"ok": False}

        def ok() -> None:
            if not all(var.get() for var in vars_):
                messagebox.showerror("Checklist incomplete", "All checklist items must be checked.", parent=dialog)
                return
            result["ok"] = True
            dialog.destroy()

        ttk.Button(dialog, text="Run", command=ok).grid(row=len(items), column=0, sticky="ew", padx=16, pady=(12, 6))
        ttk.Button(dialog, text="Cancel", command=dialog.destroy).grid(
            row=len(items) + 1, column=0, sticky="ew", padx=16, pady=(0, 12)
        )
        self.wait_window(dialog)
        return result["ok"]

    def prompt_callback(self, message: str) -> bool:
        result = {"ok": False}
        event = threading.Event()

        def ask() -> None:
            result["ok"] = messagebox.askokcancel("Prompt check", message)
            event.set()

        self.after(0, ask)
        event.wait()
        return result["ok"]

    @staticmethod
    def uses_reverse(recipe: Recipe) -> bool:
        return any(
            block.get("action") == "start_reverse" or block.get("direction") == "reverse"
            for block in recipe.blocks
        )

    def run_thread(self, func: Callable[..., None], *args: Any) -> None:
        def worker() -> None:
            try:
                func(*args)
            except Exception as exc:
                message = str(exc)
                self.after(0, lambda: messagebox.showerror("Recipe operation failed", message))

        threading.Thread(target=worker, daemon=True).start()

    def append_log(self, text: str) -> None:
        def update() -> None:
            self.log.insert("end", text + "\n")
            self.log.see("end")

        self.after(0, update)
