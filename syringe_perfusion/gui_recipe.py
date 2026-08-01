from __future__ import annotations

import copy
import json
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any, Callable

from .blocks import default_block
from .recipe_engine import RecipeEngine
from .recipe_model import Recipe, block_id, validate_recipe
from .recipe_store import default_recipe_dir, load_recipe, save_recipe
from .ui_theme import ScrollableFrame, create_card, status_badge


BLOCK_TYPES = (
    "pump_start",
    "pump_stop",
    "manual_jog",
    "wait",
    "stop_all",
    "log_marker",
    "prompt_check",
)
START_ACTIONS = ("start_forward", "start_reverse")
DIRECTIONS = ("forward", "reverse")


class RecipeBuilderFrame(ttk.Frame):
    """Responsive recipe editor which preserves the schema and engine contract."""

    WIDE_BREAKPOINT = 900
    MIN_LIBRARY_WIDTH = 170
    MIN_STEPS_WIDTH = 400
    MIN_INSPECTOR_WIDTH = 300

    def __init__(self, parent: tk.Widget, app: Any) -> None:
        super().__init__(parent, padding=10)
        self.app = app
        self.current_path: Path | None = None
        self.blocks: list[dict[str, Any]] = []
        self.selected_block_index: int | None = None
        self._cancel_event: threading.Event | None = None
        self._layout_job: str | None = None
        self._loading_inspector = False
        self._tree_selection_guard = False
        self._modified = False
        self._validated = False
        self._log_expanded = False

        self.recipe_id_var = tk.StringVar(value="new_recipe_v1")
        self.display_name_var = tk.StringVar(value=self.app.t("recipe.new_name"))
        self.description_var = tk.StringVar(value="")
        self.file_status_var = tk.StringVar(value="")
        self.validation_status_var = tk.StringVar(value=self.app.t("recipe.status.not_validated"))
        self.recipe_status_var = tk.StringVar(value="")

        self.prop_type_var = tk.StringVar(value="")
        self.prop_type_display_var = tk.StringVar(value="")
        self.prop_id_var = tk.StringVar(value="")
        self.prop_pump_var = tk.StringVar(value="IN")
        self.prop_pump_display_var = tk.StringVar(value="")
        self.prop_action_var = tk.StringVar(value="start_forward")
        self.prop_action_display_var = tk.StringVar(value="")
        self.prop_direction_var = tk.StringVar(value="forward")
        self.prop_direction_display_var = tk.StringVar(value="")
        self.prop_profile_var = tk.StringVar(value="fast30_1ml")
        self.prop_profile_display_var = tk.StringVar(value="")
        self.prop_duration_var = tk.StringVar(value="1.0")
        self.prop_duration_ms_var = tk.StringVar(value="1000")
        self.prop_message_var = tk.StringVar(value="")
        self.prop_note_var = tk.StringVar(value="")
        self.inspector_dirty_var = tk.StringVar(value="")

        self._build()
        self._install_traces()
        self._reset_new_recipe(mark_modified=False)
        self.refresh_language()

    def _build(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        self.header = create_card(self)
        self.header.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        for column in range(8):
            self.header.columnconfigure(column, weight=1 if column in {1, 3} else 0)
        self.header_title = ttk.Label(self.header, style="SectionTitle.TLabel")
        self.header_title.grid(row=0, column=0, columnspan=6, sticky="w")
        self.validation_badge = status_badge(self.header, "", "disabled")
        self.validation_badge.grid(row=0, column=6, columnspan=2, sticky="e")
        self.recipe_id_label = ttk.Label(self.header, style="Card.TLabel")
        self.recipe_id_label.grid(row=1, column=0, sticky="w", padx=(0, 6), pady=(8, 3))
        self.recipe_id_entry = ttk.Entry(self.header, textvariable=self.recipe_id_var)
        self.recipe_id_entry.grid(row=1, column=1, sticky="ew", padx=(0, 12), pady=(8, 3))
        self.recipe_name_label = ttk.Label(self.header, style="Card.TLabel")
        self.recipe_name_label.grid(row=1, column=2, sticky="w", padx=(0, 6), pady=(8, 3))
        self.recipe_name_entry = ttk.Entry(self.header, textvariable=self.display_name_var)
        self.recipe_name_entry.grid(row=1, column=3, sticky="ew", padx=(0, 12), pady=(8, 3))
        self.file_status_label = ttk.Label(self.header, textvariable=self.file_status_var, style="Subtitle.TLabel")
        self.file_status_label.grid(
            row=1, column=4, columnspan=4, sticky="e", pady=(8, 3)
        )

        self.header_actions = ttk.Frame(self.header, style="Card.TFrame")
        self.header_actions.grid(row=2, column=0, columnspan=8, sticky="ew", pady=(8, 0))
        self.action_buttons: dict[str, ttk.Button] = {}
        action_specs = (
            ("new", self.new_recipe, "Neutral.TButton"),
            ("open", self.load_recipe_dialog, "Neutral.TButton"),
            ("save", self.save_current, "Success.TButton"),
            ("save_as", self.save_as, "Success.TButton"),
            ("validate_all", self.validate_current, "Primary.TButton"),
            ("dry_run", self.dry_run, "Primary.TButton"),
            ("live_run", self.run_recipe, "Warning.TButton"),
            ("stop_all", self.stop_all_now, "Danger.TButton"),
        )
        self._action_base_styles = {name: style for name, _command, style in action_specs}
        for column, (name, command, style) in enumerate(action_specs):
            self.header_actions.columnconfigure(column, weight=1)
            button = ttk.Button(self.header_actions, command=command, style=style)
            button.grid(row=0, column=column, sticky="ew", padx=(0 if column == 0 else 3, 0), pady=2)
            self.action_buttons[name] = button

        self.workspace = ttk.Frame(self, style="Page.TFrame")
        self.workspace.grid(row=1, column=0, sticky="nsew")
        self.workspace.bind("<Configure>", self._schedule_responsive_layout, add="+")
        self._narrow_view = "steps"
        self.narrow_switch = ttk.Frame(self.workspace, style="Toolbar.TFrame")
        self.narrow_steps_button = ttk.Button(
            self.narrow_switch,
            style="Primary.TButton",
            command=lambda: self.show_narrow_view("steps"),
        )
        self.narrow_steps_button.grid(row=0, column=0, sticky="ew", padx=(0, 3))
        self.narrow_inspector_button = ttk.Button(
            self.narrow_switch,
            style="Neutral.TButton",
            command=lambda: self.show_narrow_view("inspector"),
        )
        self.narrow_inspector_button.grid(row=0, column=1, sticky="ew", padx=(3, 0))
        self.narrow_switch.columnconfigure(0, weight=1)
        self.narrow_switch.columnconfigure(1, weight=1)

        self.library_frame = create_card(self.workspace)
        self.library_frame.columnconfigure(0, weight=1)
        self.library_frame.rowconfigure(2, weight=1)
        self.library_title = ttk.Label(self.library_frame, style="SectionTitle.TLabel")
        self.library_title.grid(row=0, column=0, sticky="ew")
        self.library_help = ttk.Label(self.library_frame, style="Subtitle.TLabel", justify="left")
        self.library_help._responsive_wrap_margin = 12  # type: ignore[attr-defined]
        self.library_help.grid(row=1, column=0, sticky="ew", pady=(3, 8))
        self.library_scroll = ScrollableFrame(self.library_frame, height=180)
        self.library_scroll.grid(row=2, column=0, sticky="nsew")
        self.library_scroll.inner.columnconfigure(0, weight=1)
        self.library_buttons: dict[str, ttk.Button] = {}
        for row, block_type in enumerate(BLOCK_TYPES):
            button = ttk.Button(
                self.library_scroll.inner,
                style="NeutralCompact.TButton",
                command=lambda value=block_type: self.add_block(value),
            )
            button.grid(row=row, column=0, sticky="ew", pady=3)
            self.library_buttons[block_type] = button

        self.steps_frame = create_card(self.workspace)
        self.steps_frame.columnconfigure(0, weight=1)
        self.steps_frame.rowconfigure(2, weight=1)
        self.steps_title = ttk.Label(self.steps_frame, style="SectionTitle.TLabel")
        self.steps_title.grid(row=0, column=0, sticky="ew")
        self.steps_help = ttk.Label(self.steps_frame, style="Subtitle.TLabel", justify="left")
        self.steps_help._responsive_wrap_margin = 12  # type: ignore[attr-defined]
        self.steps_help.grid(row=1, column=0, sticky="ew", pady=(3, 8))
        tree_area = ttk.Frame(self.steps_frame, style="Card.TFrame")
        tree_area.grid(row=2, column=0, sticky="nsew")
        tree_area.columnconfigure(0, weight=1)
        tree_area.rowconfigure(0, weight=1)
        columns = ("number", "type", "target", "summary", "duration")
        self.steps_tree = ttk.Treeview(tree_area, columns=columns, show="headings", selectmode="browse", height=11)
        self.steps_tree.grid(row=0, column=0, sticky="nsew")
        self.steps_vscroll = ttk.Scrollbar(tree_area, orient="vertical", command=self.steps_tree.yview)
        self.steps_vscroll.grid(row=0, column=1, sticky="ns")
        self.steps_hscroll = ttk.Scrollbar(tree_area, orient="horizontal", command=self.steps_tree.xview)
        self.steps_hscroll.grid(row=1, column=0, sticky="ew")
        self.steps_tree.configure(yscrollcommand=self.steps_vscroll.set, xscrollcommand=self.steps_hscroll.set)
        self.steps_tree.column("number", width=42, minwidth=38, stretch=False, anchor="center")
        self.steps_tree.column("type", width=120, minwidth=90, stretch=False)
        self.steps_tree.column("target", width=80, minwidth=65, stretch=False)
        self.steps_tree.column("summary", width=260, minwidth=160, stretch=True)
        self.steps_tree.column("duration", width=120, minwidth=95, stretch=False)
        self.steps_tree.bind("<<TreeviewSelect>>", self._on_tree_select, add="+")
        self.steps_tree.bind("<Double-1>", self._open_selected_inspector, add="+")
        self.steps_tree.bind("<Delete>", lambda _event: self.delete_selected(confirm=True), add="+")
        self.steps_tree.bind("<Control-d>", lambda _event: self.duplicate_selected(), add="+")
        self.steps_tree.bind("<Control-D>", lambda _event: self.duplicate_selected(), add="+")

        self.move_bar = ttk.Frame(self.steps_frame, style="Card.TFrame")
        self.move_bar.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        self.move_buttons: dict[str, ttk.Button] = {}
        for column, (name, command) in enumerate((
            ("up", self.move_up),
            ("down", self.move_down),
            ("duplicate", self.duplicate_selected),
            ("delete", lambda: self.delete_selected(confirm=True)),
        )):
            self.move_bar.columnconfigure(column, weight=1)
            style = "DangerSecondary.TButton" if name == "delete" else "NeutralCompact.TButton"
            button = ttk.Button(self.move_bar, command=command, style=style)
            button.grid(row=0, column=column, sticky="ew", padx=(0 if column == 0 else 3, 0))
            self.move_buttons[name] = button

        self.inspector_frame = create_card(self.workspace)
        self.inspector_frame.columnconfigure(0, weight=1)
        self.inspector_frame.rowconfigure(2, weight=1)
        self.inspector_title = ttk.Label(self.inspector_frame, style="SectionTitle.TLabel")
        self.inspector_title.grid(row=0, column=0, sticky="ew")
        self.inspector_help = ttk.Label(self.inspector_frame, style="Subtitle.TLabel", justify="left")
        self.inspector_help._responsive_wrap_margin = 12  # type: ignore[attr-defined]
        self.inspector_help.grid(row=1, column=0, sticky="ew", pady=(3, 8))
        self.inspector_scroll = ScrollableFrame(self.inspector_frame, height=280)
        self.inspector_scroll.grid(row=2, column=0, sticky="nsew")
        inspector = self.inspector_scroll.inner
        inspector.columnconfigure(0, weight=1)
        self.inspector_fields: dict[str, ttk.Frame] = {}
        self.inspector_widgets: dict[str, tk.Widget] = {}
        self.inspector_section_labels: dict[str, ttk.Label] = {}
        row = 0
        row = self._inspector_section(inspector, row, "basic")
        row = self._inspector_field(inspector, row, "type", lambda frame: ttk.Label(frame, textvariable=self.prop_type_display_var, style="Card.TLabel"))
        row = self._inspector_field(inspector, row, "id", lambda frame: ttk.Entry(frame, textvariable=self.prop_id_var))
        row = self._inspector_section(inspector, row, "pump")
        row = self._inspector_field(inspector, row, "pump", lambda frame: ttk.Combobox(frame, textvariable=self.prop_pump_display_var, state="readonly"))
        self.prop_pump_combo = self.inspector_widgets["pump"]
        row = self._inspector_field(inspector, row, "action", lambda frame: ttk.Combobox(frame, textvariable=self.prop_action_display_var, state="readonly"))
        self.prop_action_combo = self.inspector_widgets["action"]
        row = self._inspector_field(inspector, row, "direction", lambda frame: ttk.Combobox(frame, textvariable=self.prop_direction_display_var, state="readonly"))
        self.prop_direction_combo = self.inspector_widgets["direction"]
        row = self._inspector_field(inspector, row, "profile", lambda frame: ttk.Combobox(frame, textvariable=self.prop_profile_display_var, state="readonly"))
        self.prop_profile_combo = self.inspector_widgets["profile"]
        row = self._inspector_section(inspector, row, "timing")
        row = self._inspector_field(inspector, row, "duration_s", lambda frame: ttk.Entry(frame, textvariable=self.prop_duration_var), unit="s")
        row = self._inspector_field(inspector, row, "duration_ms", lambda frame: ttk.Entry(frame, textvariable=self.prop_duration_ms_var), unit="ms")
        row = self._inspector_section(inspector, row, "message")
        row = self._inspector_field(inspector, row, "message", lambda frame: ttk.Entry(frame, textvariable=self.prop_message_var))
        row = self._inspector_section(inspector, row, "advanced")
        row = self._inspector_field(inspector, row, "note", lambda frame: ttk.Entry(frame, textvariable=self.prop_note_var))
        self.inspector_dirty_label = ttk.Label(inspector, textvariable=self.inspector_dirty_var, style="Subtitle.TLabel")
        self.inspector_dirty_label.grid(row=row, column=0, sticky="w", pady=(8, 3))
        row += 1
        self.apply_button = ttk.Button(inspector, command=self.apply_properties, style="Primary.TButton")
        self.apply_button.grid(row=row, column=0, sticky="ew", pady=(3, 4))

        self.secondary = ttk.Frame(self, style="Toolbar.TFrame", padding=(10, 6))
        self.secondary.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        self.secondary.columnconfigure(0, weight=1)
        ttk.Label(self.secondary, textvariable=self.recipe_status_var, style="Card.TLabel").grid(row=0, column=0, sticky="w")
        self.log_toggle_button = ttk.Button(self.secondary, style="NeutralCompact.TButton", command=self.toggle_log)
        self.log_toggle_button.grid(row=0, column=1, sticky="e", padx=(8, 0))
        self.copy_log_button = ttk.Button(self.secondary, style="NeutralCompact.TButton", command=self.copy_log)
        self.copy_log_button.grid(row=0, column=2, sticky="e", padx=(4, 0))
        self.clear_log_button = ttk.Button(self.secondary, style="NeutralCompact.TButton", command=self.clear_log_display)
        self.clear_log_button.grid(row=0, column=3, sticky="e", padx=(4, 0))
        self.log = tk.Text(self, height=5, wrap="word", font=("Consolas", 9), background="#FFFFFF",
                           foreground="#111827", relief="solid", borderwidth=1, padx=8, pady=6)

        for sequence, callback in (
            ("<Control-s>", self.save_current),
            ("<Control-S>", self.save_current),
            ("<Control-Shift-s>", self.save_as),
            ("<Control-Shift-S>", self.save_as),
            ("<Control-o>", self.load_recipe_dialog),
            ("<Control-O>", self.load_recipe_dialog),
            ("<Control-n>", self.new_recipe),
            ("<Control-N>", self.new_recipe),
        ):
            self.app.bind(sequence, lambda _event, fn=callback: (fn(), "break")[1], add="+")

    def _inspector_section(self, parent: ttk.Frame, row: int, name: str) -> int:
        label = ttk.Label(parent, style="SectionTitle.TLabel")
        label.grid(row=row, column=0, sticky="ew", pady=(8 if row else 0, 4))
        self.inspector_section_labels[name] = label
        return row + 1

    def _inspector_field(
        self,
        parent: ttk.Frame,
        row: int,
        name: str,
        widget_factory: Callable[[ttk.Frame], tk.Widget],
        *,
        unit: str = "",
    ) -> int:
        frame = ttk.Frame(parent, style="Card.TFrame")
        frame.grid(row=row, column=0, sticky="ew", pady=3)
        frame.columnconfigure(1, weight=1)
        label = ttk.Label(frame, style="Card.TLabel")
        label.grid(row=0, column=0, sticky="w", padx=(0, 8))
        widget = widget_factory(frame)
        widget.grid(row=0, column=1, sticky="ew")
        if unit:
            ttk.Label(frame, text=unit, style="Card.TLabel").grid(row=0, column=2, sticky="w", padx=(6, 0))
        frame._field_label = label  # type: ignore[attr-defined]
        self.inspector_fields[name] = frame
        self.inspector_widgets[name] = widget
        return row + 1

    def _install_traces(self) -> None:
        self.recipe_id_var.trace_add("write", self._metadata_changed)
        self.display_name_var.trace_add("write", self._metadata_changed)
        for variable in (
            self.prop_id_var, self.prop_pump_display_var, self.prop_action_display_var,
            self.prop_direction_display_var, self.prop_profile_display_var, self.prop_duration_var,
            self.prop_duration_ms_var, self.prop_message_var, self.prop_note_var,
        ):
            variable.trace_add("write", self._inspector_changed)

    def _metadata_changed(self, *_args: Any) -> None:
        if not self._loading_inspector:
            self._set_modified(True)

    def _inspector_changed(self, *_args: Any) -> None:
        if self._loading_inspector or self.selected_block_index is None:
            return
        self.inspector_dirty_var.set(self.app.t("recipe.status.inspector_modified"))
        self.apply_button.configure(style="Warning.TButton")

    @property
    def inspector_dirty(self) -> bool:
        return bool(self.inspector_dirty_var.get())

    @property
    def modified(self) -> bool:
        return self._modified

    def _set_modified(self, value: bool) -> None:
        self._modified = value
        self._validated = False if value else self._validated
        self._update_header_status()

    def _update_header_status(self) -> None:
        if self._modified:
            state = "modified" if self.current_path else "unsaved"
        else:
            state = "saved" if self.current_path else "unsaved"
        self.file_status_var.set(self.app.t(f"recipe.status.{state}"))
        self.validation_status_var.set(
            self.app.t("recipe.status.validated" if self._validated else "recipe.status.not_validated")
        )
        self.validation_badge.configure(
            text=self.validation_status_var.get(),
            style="BadgeEnabled.TLabel" if self._validated else "BadgeDisabled.TLabel",
        )
        self.update_status_line()

    def _schedule_responsive_layout(self, _event: tk.Event | None = None) -> None:
        if self._layout_job is not None:
            try:
                self.after_cancel(self._layout_job)
            except tk.TclError:
                pass
        self._layout_job = self.after(60, self._apply_responsive_layout)

    def _apply_responsive_layout(self) -> None:
        self._layout_job = None
        width = max(1, self.workspace.winfo_width())
        for widget in (self.library_frame, self.steps_frame, self.inspector_frame):
            widget.grid_forget()
        if width >= self.WIDE_BREAKPOINT:
            self.recipe_layout_mode = "wide"
            self.header.configure(padding=16)
            self.library_title.grid()
            self.library_help.grid()
            self.steps_title.grid()
            self.steps_help.grid()
            self.inspector_title.grid()
            self.inspector_help.grid()
            self.narrow_switch.grid_forget()
            self.workspace.columnconfigure(0, weight=2, minsize=self.MIN_LIBRARY_WIDTH)
            self.workspace.columnconfigure(1, weight=5, minsize=self.MIN_STEPS_WIDTH)
            self.workspace.columnconfigure(2, weight=3, minsize=self.MIN_INSPECTOR_WIDTH)
            self.workspace.rowconfigure(0, weight=1)
            self.workspace.rowconfigure(1, weight=0)
            self.library_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
            self.steps_frame.grid(row=0, column=1, sticky="nsew", padx=6)
            self.inspector_frame.grid(row=0, column=2, sticky="nsew", padx=(6, 0))
            self.recipe_id_label.grid_configure(row=1, column=0, columnspan=1)
            self.recipe_id_entry.grid_configure(row=1, column=1, columnspan=1)
            self.recipe_name_label.grid_configure(row=1, column=2, columnspan=1)
            self.recipe_name_entry.grid_configure(row=1, column=3, columnspan=1)
            self.file_status_label.grid_configure(row=1, column=4, columnspan=4)
            self.header_actions.grid_configure(row=2)
            for column, (name, button) in enumerate(self.action_buttons.items()):
                button.configure(style=self._action_base_styles[name])
                button.grid_forget()
                button.grid(row=0, column=column, sticky="ew", padx=(0 if column == 0 else 3, 0), pady=2)
        else:
            self.recipe_layout_mode = "narrow"
            self.header.configure(padding=(12, 8))
            self.library_title.grid()
            self.library_help.grid_remove()
            self.steps_title.grid()
            self.steps_help.grid_remove()
            self.inspector_title.grid_remove()
            self.inspector_help.grid_remove()
            self.workspace.columnconfigure(0, weight=0, minsize=self.MIN_LIBRARY_WIDTH)
            self.workspace.columnconfigure(1, weight=1, minsize=320)
            self.workspace.columnconfigure(2, weight=0, minsize=0)
            self.workspace.rowconfigure(0, weight=0)
            self.workspace.rowconfigure(1, weight=1)
            self.narrow_switch.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 5))
            self.show_narrow_view(self._narrow_view)
            self.recipe_id_label.grid_configure(row=1, column=0, columnspan=1)
            self.recipe_id_entry.grid_configure(row=1, column=1, columnspan=3)
            self.recipe_name_label.grid_configure(row=1, column=2, columnspan=1)
            self.recipe_name_entry.grid_configure(row=1, column=3, columnspan=1)
            self.file_status_label.grid_configure(row=1, column=4, columnspan=4)
            self.header_actions.grid_configure(row=2)
            compact_styles = {
                "Neutral.TButton": "NeutralCompact.TButton",
                "Primary.TButton": "PrimaryCompact.TButton",
                "Success.TButton": "SuccessCompact.TButton",
                "Warning.TButton": "WarningCompact.TButton",
                "Danger.TButton": "DangerCompact.TButton",
            }
            for index, (name, button) in enumerate(self.action_buttons.items()):
                button.configure(style=compact_styles[self._action_base_styles[name]])
                button.grid_forget()
                button.grid(row=index // 4, column=index % 4, sticky="ew",
                            padx=(0 if index % 4 == 0 else 3, 0), pady=2)

    def show_narrow_view(self, view: str) -> None:
        if view not in {"steps", "inspector"}:
            return
        self._narrow_view = view
        if getattr(self, "recipe_layout_mode", "narrow") != "narrow":
            return
        self.library_frame.grid_forget()
        self.steps_frame.grid_forget()
        self.inspector_frame.grid_forget()
        if view == "steps":
            self.library_frame.grid(row=1, column=0, sticky="nsew", padx=(0, 6))
            self.steps_frame.grid(row=1, column=1, sticky="nsew", padx=(6, 0))
            self.narrow_steps_button.configure(style="Primary.TButton")
            self.narrow_inspector_button.configure(style="Neutral.TButton")
        else:
            self.inspector_frame.grid(row=1, column=0, columnspan=2, sticky="nsew")
            self.narrow_steps_button.configure(style="Neutral.TButton")
            self.narrow_inspector_button.configure(style="Primary.TButton")

    def _reset_new_recipe(self, *, mark_modified: bool = True) -> None:
        self._loading_inspector = True
        try:
            self.current_path = None
            self.blocks = []
            self.recipe_id_var.set("new_recipe_v1")
            self.display_name_var.set(self.app.t("recipe.new_name"))
            self.description_var.set("")
            block = default_block("pump_start")
            block["id"] = block_id(self.blocks)
            self.blocks.append(block)
        finally:
            self._loading_inspector = False
        self._modified = mark_modified
        self._validated = False
        self.refresh_timeline(select=0)
        self.append_log(self.app.t("recipe.log.new"))

    def can_discard_recipe(self) -> bool:
        if not self._modified:
            return True
        return messagebox.askyesno(
            self.app.t("recipe.dialog.unsaved_title"),
            self.app.t("recipe.dialog.unsaved_message"),
            parent=self,
        )

    def new_recipe(self) -> None:
        if self.can_discard_recipe():
            self._reset_new_recipe()

    def validate_current(self) -> bool:
        try:
            recipe = self.make_recipe()
            self._validated = True
            self.validation_badge.configure(style="BadgeEnabled.TLabel")
            self.append_log(self.app.t("recipe.log.validation_ok"))
            self._update_header_status()
            return True
        except Exception as exc:
            self._validated = False
            self.validation_status_var.set(self.app.t("recipe.status.validation_error"))
            self.validation_badge.configure(text=self.validation_status_var.get(), style="BadgeDanger.TLabel")
            self.append_log(self.app.t("recipe.log.validation_failed", error=exc))
            return False

    def add_block(self, block_type: str) -> None:
        block = default_block(block_type)
        if "pump" in block and block["pump"] not in self.app.available_pumps():
            block["pump"] = "IN"
        block["id"] = block_id(self.blocks)
        self.blocks.append(block)
        self._set_modified(True)
        self.refresh_timeline(select=len(self.blocks) - 1)

    def update_available_pumps(self) -> None:
        self._refresh_display_mappings()
        if self.prop_pump_var.get() not in self.app.available_pumps():
            self.prop_pump_var.set("IN")
            self.prop_pump_display_var.set(self.app.localizer.display_value("IN"))

    def refresh_timeline(self, select: int | None = None) -> None:
        preserved_id = None
        if select is None and self.selected_block_index is not None and self.selected_block_index < len(self.blocks):
            preserved_id = str(self.blocks[self.selected_block_index].get("id", ""))
        self._tree_selection_guard = True
        try:
            self.steps_tree.delete(*self.steps_tree.get_children())
            for index, block in enumerate(self.blocks):
                self.steps_tree.insert("", "end", iid=str(index), values=self._step_values(index, block))
            if select is None and preserved_id:
                select = next((i for i, block in enumerate(self.blocks) if str(block.get("id", "")) == preserved_id), None)
            if select is not None and self.blocks:
                select = max(0, min(select, len(self.blocks) - 1))
                self.selected_block_index = select
                self.steps_tree.selection_set(str(select))
                self.steps_tree.focus(str(select))
                self.steps_tree.see(str(select))
                self.load_selected_properties()
            elif not self.blocks:
                self.selected_block_index = None
                self._clear_inspector()
        finally:
            self._tree_selection_guard = False
        self.update_status_line()

    def _step_values(self, index: int, block: dict[str, Any]) -> tuple[str, str, str, str, str]:
        block_type = str(block.get("type", ""))
        target = self.app.localizer.display_value(str(block.get("pump", ""))) if block.get("pump") else "—"
        summary = self._step_summary(block)
        duration = ""
        if "duration_ms" in block:
            duration = f"{block.get('duration_ms')} ms"
        elif "duration_s" in block:
            duration = f"{block.get('duration_s')} s"
        return (str(index + 1), self.app.localizer.display_value(block_type), target, summary, duration or "—")

    def _step_summary(self, block: dict[str, Any]) -> str:
        block_type = str(block.get("type", ""))
        if block_type == "pump_start":
            return self.app.t("recipe.summary.pump_start", action=self.app.localizer.display_value(str(block.get("action", ""))), profile=block.get("profile", ""))
        if block_type == "pump_stop":
            return self.app.t("recipe.summary.pump_stop")
        if block_type == "manual_jog":
            return self.app.t("recipe.summary.manual_jog", direction=self.app.localizer.display_value(str(block.get("direction", ""))))
        if block_type == "wait":
            return self.app.t("recipe.summary.wait", seconds=block.get("duration_s", ""))
        if block_type == "stop_all":
            return self.app.t("recipe.summary.stop_all")
        return str(block.get("message") or block.get("note") or self.app.localizer.display_value(block_type))

    def _on_tree_select(self, _event: tk.Event | None = None) -> None:
        if self._tree_selection_guard:
            return
        selection = self.steps_tree.selection()
        if not selection:
            return
        self.select_step(int(selection[0]))

    def _open_selected_inspector(self, event: tk.Event | None = None) -> None:
        self._on_tree_select(event)
        if getattr(self, "recipe_layout_mode", "wide") == "narrow":
            self.show_narrow_view("inspector")

    def select_step(self, index: int) -> bool:
        if index == self.selected_block_index:
            return True
        if self.inspector_dirty and not messagebox.askyesno(
            self.app.t("recipe.dialog.inspector_title"),
            self.app.t("recipe.dialog.inspector_message"),
            parent=self,
        ):
            self._tree_selection_guard = True
            try:
                if self.selected_block_index is not None:
                    self.steps_tree.selection_set(str(self.selected_block_index))
                    self.steps_tree.focus(str(self.selected_block_index))
            finally:
                self._tree_selection_guard = False
            return False
        self.selected_block_index = index
        self.load_selected_properties()
        return True

    def selected_index(self) -> int | None:
        return self.selected_block_index

    def _clear_inspector(self) -> None:
        self._loading_inspector = True
        try:
            self.prop_type_var.set("")
            self.prop_type_display_var.set(self.app.t("recipe.empty.select_step"))
            self.inspector_dirty_var.set("")
        finally:
            self._loading_inspector = False
        self.apply_button.configure(style="Primary.TButton", state="disabled")
        self.update_inspector_state("")

    def load_selected_properties(self) -> None:
        index = self.selected_index()
        if index is None or index >= len(self.blocks):
            self._clear_inspector()
            return
        block = self.blocks[index]
        self._loading_inspector = True
        try:
            self.prop_type_var.set(str(block.get("type", "")))
            self.prop_type_display_var.set(self.app.localizer.display_value(self.prop_type_var.get()))
            self.prop_id_var.set(str(block.get("id", "")))
            self.prop_pump_var.set(str(block.get("pump", "IN")))
            self.prop_pump_display_var.set(self.app.localizer.display_value(self.prop_pump_var.get()))
            self.prop_action_var.set(str(block.get("action", "start_forward")))
            self.prop_action_display_var.set(self.app.localizer.display_value(self.prop_action_var.get()))
            self.prop_direction_var.set(str(block.get("direction", "forward")))
            self.prop_direction_display_var.set(self.app.localizer.display_value(self.prop_direction_var.get()))
            self.prop_profile_var.set(str(block.get("profile", "fast30_1ml")))
            self.prop_profile_display_var.set(self._profile_display(self.prop_profile_var.get()))
            self.prop_duration_var.set(str(block.get("duration_s", "")))
            self.prop_duration_ms_var.set(str(block.get("duration_ms", "1000")))
            self.prop_message_var.set(str(block.get("message", "")))
            self.prop_note_var.set(str(block.get("note", "")))
            self.inspector_dirty_var.set("")
        finally:
            self._loading_inspector = False
        self.apply_button.configure(style="Primary.TButton", state="normal")
        self.update_inspector_state(self.prop_type_var.get())

    def update_inspector_state(self, block_type: str) -> None:
        visible = {"type", "id", "note"}
        if block_type in {"pump_start", "pump_stop", "manual_jog"}:
            visible.add("pump")
        if block_type == "pump_start":
            visible.update({"action", "profile"})
        if block_type == "manual_jog":
            visible.update({"direction", "duration_ms"})
        if block_type == "wait":
            visible.add("duration_s")
        if block_type in {"log_marker", "prompt_check"}:
            visible.add("message")
        for name, frame in self.inspector_fields.items():
            if name in visible:
                frame.grid()
            else:
                frame.grid_remove()
        section_fields = {
            "basic": {"type", "id"}, "pump": {"pump", "action", "direction", "profile"},
            "timing": {"duration_s", "duration_ms"}, "message": {"message"}, "advanced": {"note"},
        }
        for section, fields in section_fields.items():
            label = self.inspector_section_labels[section]
            (label.grid if visible & fields else label.grid_remove)()

    def apply_properties(self) -> None:
        index = self.selected_index()
        if index is None:
            return
        block_type = self.prop_type_var.get()
        block: dict[str, Any] = {"id": self.prop_id_var.get().strip(), "type": block_type}
        pump = self.app.localizer.canonical_value(self.prop_pump_display_var.get(), self.app.available_pumps()) or self.prop_pump_var.get()
        action = self.app.localizer.canonical_value(self.prop_action_display_var.get(), START_ACTIONS) or self.prop_action_var.get()
        direction = self.app.localizer.canonical_value(self.prop_direction_display_var.get(), DIRECTIONS) or self.prop_direction_var.get()
        profile = self._profile_canonical(self.prop_profile_display_var.get()) or self.prop_profile_var.get()
        if block_type in {"pump_start", "pump_stop"}:
            block["pump"] = pump
            block["action"] = "stop" if block_type == "pump_stop" else action
        if block_type == "pump_start":
            block["profile"] = profile
        if block_type == "manual_jog":
            block.update(pump=pump, direction=direction, duration_ms=int(self.prop_duration_ms_var.get()))
        if block_type == "wait":
            block["duration_s"] = float(self.prop_duration_var.get())
        if block_type in {"log_marker", "prompt_check"}:
            block["message"] = self.prop_message_var.get()
        if self.prop_note_var.get():
            block["note"] = self.prop_note_var.get()
        previous = self.blocks[index]
        self.blocks[index] = block
        try:
            validate_recipe(self.make_recipe(), self.app.data)
        except Exception as exc:
            self.blocks[index] = previous
            messagebox.showerror(self.app.t("recipe.dialog.invalid_block"), str(exc), parent=self)
            return
        self._set_modified(True)
        self.refresh_timeline(select=index)

    def move_up(self, index: int | None = None) -> None:
        index = self.selected_index() if index is None else index
        if index is None or index == 0:
            return
        self.blocks[index - 1], self.blocks[index] = self.blocks[index], self.blocks[index - 1]
        self._set_modified(True)
        self.refresh_timeline(select=index - 1)

    def move_down(self, index: int | None = None) -> None:
        index = self.selected_index() if index is None else index
        if index is None or index >= len(self.blocks) - 1:
            return
        self.blocks[index + 1], self.blocks[index] = self.blocks[index], self.blocks[index + 1]
        self._set_modified(True)
        self.refresh_timeline(select=index + 1)

    def duplicate_selected(self, index: int | None = None) -> None:
        index = self.selected_index() if index is None else index
        if index is None:
            return
        copied = copy.deepcopy(self.blocks[index])
        copied["id"] = block_id(self.blocks)
        self.blocks.insert(index + 1, copied)
        self._set_modified(True)
        self.refresh_timeline(select=index + 1)

    def delete_selected(self, index: int | None = None, *, confirm: bool = False) -> None:
        index = self.selected_index() if index is None else index
        if index is None:
            return
        if confirm and not messagebox.askyesno(
            self.app.t("recipe.dialog.delete_title"), self.app.t("recipe.dialog.delete_message"), parent=self
        ):
            return
        del self.blocks[index]
        self._set_modified(True)
        self.refresh_timeline(select=min(index, len(self.blocks) - 1) if self.blocks else None)

    def make_recipe(self) -> Recipe:
        recipe = Recipe(schema_version=2, recipe_id=self.recipe_id_var.get().strip(),
                        display_name=self.display_name_var.get().strip(), description=self.description_var.get().strip(),
                        blocks=copy.deepcopy(self.blocks))
        validate_recipe(recipe, self.app.data)
        return recipe

    def load_recipe_dialog(self) -> None:
        if not self.can_discard_recipe():
            return
        path = filedialog.askopenfilename(initialdir=str(default_recipe_dir()), title=self.app.t("recipe.dialog.open_title"),
                                          filetypes=[(self.app.t("recipe.filetype"), "*.json"), (self.app.t("dialog.all_files"), "*.*")])
        if not path:
            return
        try:
            recipe = load_recipe(path)
            validate_recipe(recipe, self.app.data)
            self._loading_inspector = True
            try:
                self.current_path = Path(path)
                self.recipe_id_var.set(recipe.recipe_id)
                self.display_name_var.set(recipe.display_name)
                self.description_var.set(recipe.description)
                self.blocks = copy.deepcopy(recipe.blocks)
            finally:
                self._loading_inspector = False
            self._modified = False
            self._validated = True
            self.refresh_timeline(select=0)
            self.append_log(self.app.t("recipe.log.loaded", path=path))
            self._update_header_status()
        except Exception as exc:
            messagebox.showerror(self.app.t("recipe.dialog.load_failed"), str(exc), parent=self)

    def save_current(self) -> None:
        if self.current_path is None:
            self.save_as()
            return
        self._save_to(self.current_path)

    def save_as(self) -> None:
        path = filedialog.asksaveasfilename(initialdir=str(default_recipe_dir()), initialfile=f"{self.recipe_id_var.get()}.json",
                                             title=self.app.t("recipe.dialog.save_title"), defaultextension=".json",
                                             filetypes=[(self.app.t("recipe.filetype"), "*.json"), (self.app.t("dialog.all_files"), "*.*")])
        if path:
            self.current_path = Path(path)
            self._save_to(self.current_path)

    def _save_to(self, path: Path) -> None:
        try:
            saved = save_recipe(self.make_recipe(), path)
            self._modified = False
            self._validated = True
            self._update_header_status()
            self.append_log(self.app.t("recipe.log.saved", path=saved))
        except Exception as exc:
            messagebox.showerror(self.app.t("recipe.dialog.save_failed"), str(exc), parent=self)

    def dry_run(self) -> None:
        self._start_execution(dry_run=True)

    def run_recipe(self) -> None:
        if self.app.dry_run_var.get():
            messagebox.showwarning(self.app.t("recipe.dialog.live_disabled_title"), self.app.t("recipe.dialog.live_disabled"), parent=self)
            return
        self._start_execution(dry_run=False)

    def _start_execution(self, *, dry_run: bool) -> None:
        try:
            recipe = self.make_recipe()
        except Exception as exc:
            messagebox.showerror(self.app.t("recipe.dialog.invalid_recipe"), str(exc), parent=self)
            return
        if not self.show_preview(recipe):
            return
        if not dry_run:
            pumps = ", ".join(sorted({str(block.get("pump")) for block in recipe.blocks if block.get("pump")})) or "—"
            if not messagebox.askokcancel(
                self.app.t("recipe.dialog.live_title"),
                self.app.t("recipe.dialog.live_message", pumps=pumps), parent=self,
            ):
                return
            if not self.show_checklist(recipe):
                return
        try:
            self.app.apply_gui_pump_settings()
            data = json.loads(json.dumps(self.app.data))
            context = {"dish_id": self.app.dish_id_var.get(), "condition": self.app.condition_var.get(),
                       "trigger_source": self.app.trigger_var.get(), "assume_yes": dry_run}
            config_resolution = self.app.config_resolution
        except Exception as exc:
            messagebox.showerror(self.app.t("recipe.dialog.start_failed"), str(exc), parent=self)
            return
        if not self.app.begin_gui_operation("recipe"):
            return
        self._cancel_event = threading.Event()
        context["cancel_event"] = self._cancel_event
        context["prompt_callback"] = self.prompt_callback
        self.run_thread(self._execute_worker, recipe, dry_run, data, config_resolution, context)

    def _execute_worker(self, recipe: Recipe, dry_run: bool, data: dict[str, Any], config_resolution: Any,
                        context: dict[str, Any]) -> None:
        engine = RecipeEngine(data, config_resolution)
        events = engine.execute(recipe, dry_run=dry_run, context=context)
        self.append_log(json.dumps(events, ensure_ascii=False))

    def stop_all_now(self) -> None:
        if self._cancel_event is not None:
            self._cancel_event.set()
        self.app.gui_stop_all_now()
        self.append_log(self.app.t("recipe.log.stop_requested"))

    def cancel_execution(self) -> None:
        if self._cancel_event is not None:
            self._cancel_event.set()

    def show_preview(self, recipe: Recipe) -> bool:
        lines = [f"{recipe.display_name} ({recipe.recipe_id})", ""]
        for index, block in enumerate(recipe.blocks, start=1):
            lines.append(f"{index:02d}. {self.app.localizer.display_value(str(block.get('type', '')))} — {self._step_summary(block)}")
        return messagebox.askokcancel(self.app.t("recipe.dialog.preview_title"), "\n".join(lines), parent=self)

    def show_checklist(self, recipe: Recipe) -> bool:
        dialog = tk.Toplevel(self)
        dialog.title(self.app.t("recipe.dialog.checklist_title"))
        dialog.transient(self.winfo_toplevel())
        dialog.grab_set()
        variables = []
        keys = ["line_primed", "r1_fl", "needle", "profile"]
        if self.uses_reverse(recipe):
            keys.append("waste")
        for row, key in enumerate(keys):
            variable = tk.BooleanVar(value=False)
            ttk.Checkbutton(dialog, text=self.app.t(f"recipe.checklist.{key}"), variable=variable).grid(row=row, column=0, sticky="w", padx=16, pady=5)
            variables.append(variable)
        result = {"ok": False}

        def accept() -> None:
            if not all(variable.get() for variable in variables):
                messagebox.showerror(self.app.t("recipe.dialog.checklist_incomplete"), self.app.t("recipe.dialog.checklist_required"), parent=dialog)
                return
            result["ok"] = True
            dialog.destroy()

        ttk.Button(dialog, text=self.app.t("recipe.action.live_run"), command=accept, style="Warning.TButton").grid(row=len(keys), column=0, sticky="ew", padx=16, pady=(12, 6))
        ttk.Button(dialog, text=self.app.t("action.cancel"), command=dialog.destroy, style="Neutral.TButton").grid(row=len(keys) + 1, column=0, sticky="ew", padx=16, pady=(0, 12))
        self.wait_window(dialog)
        return result["ok"]

    def prompt_callback(self, message: str) -> bool:
        result = {"ok": False}
        event = threading.Event()

        def ask() -> None:
            result["ok"] = messagebox.askokcancel(self.app.t("recipe.dialog.prompt_title"), message)
            event.set()

        self.app.post_ui(ask)
        event.wait()
        return result["ok"]

    @staticmethod
    def uses_reverse(recipe: Recipe) -> bool:
        return any(block.get("action") == "start_reverse" or block.get("direction") == "reverse" for block in recipe.blocks)

    def run_thread(self, func: Callable[..., None], *args: Any) -> None:
        def worker() -> None:
            try:
                func(*args)
            except Exception as exc:
                self.app.post_ui(self._recipe_failed, str(exc))
            else:
                self.app.post_ui(self._recipe_finished)
        threading.Thread(target=worker, daemon=True).start()

    def _recipe_finished(self) -> None:
        self._cancel_event = None
        self.app.finish_gui_operation("recipe")

    def _recipe_failed(self, message: str) -> None:
        self._cancel_event = None
        self.app.finish_gui_operation("recipe")
        messagebox.showerror(self.app.t("recipe.dialog.operation_failed"), message, parent=self)

    def toggle_log(self) -> None:
        self._log_expanded = not self._log_expanded
        if self._log_expanded:
            self.log.grid(row=3, column=0, sticky="ew", pady=(5, 0))
        else:
            self.log.grid_remove()
        self._update_log_buttons()

    def copy_log(self) -> None:
        self.app._copy_text(self.log.get("1.0", "end-1c"), self.app.t("recipe.log.label"))

    def clear_log_display(self) -> None:
        self.log.delete("1.0", "end")

    def append_log(self, text: str) -> None:
        def update() -> None:
            self.log.insert("end", text + "\n")
            self.log.see("end")
        if threading.current_thread() is threading.main_thread():
            update()
        else:
            self.app.post_ui(update)

    def _profile_display(self, key: str) -> str:
        profile = self.app.data.get("profiles", {}).get(key, {})
        name = str(profile.get("display_name", key))
        return f"{name} [{key}]" if name != key else key

    def _profile_canonical(self, display: str) -> str | None:
        return next((key for key in self.app.data.get("profiles", {}) if self._profile_display(key) == display), None)

    def _refresh_display_mappings(self) -> None:
        pumps = self.app.available_pumps()
        self.prop_pump_combo.configure(values=tuple(self.app.localizer.display_value(value) for value in pumps))
        self.prop_action_combo.configure(values=tuple(self.app.localizer.display_value(value) for value in START_ACTIONS))
        self.prop_direction_combo.configure(values=tuple(self.app.localizer.display_value(value) for value in DIRECTIONS))
        self.prop_profile_combo.configure(values=tuple(self._profile_display(key) for key in self.app.data.get("profiles", {})))

    def update_execution_mode(self) -> None:
        self.action_buttons["live_run"].configure(state="disabled" if self.app.dry_run_var.get() else "normal")
        self.action_buttons["dry_run"].configure(state="normal")

    def update_status_line(self, recipe: Recipe | None = None) -> None:
        pumps = sorted({str(block.get("pump")) for block in self.blocks if block.get("pump")})
        self.recipe_status_var.set(self.app.t("recipe.status.summary", count=len(self.blocks), pumps=", ".join(pumps) or self.app.t("status.no_pumps")))

    def _update_log_buttons(self) -> None:
        self.log_toggle_button.configure(text=self.app.t("recipe.action.hide_log" if self._log_expanded else "recipe.action.show_log"))
        self.copy_log_button.configure(text=self.app.t("recipe.action.copy_log"))
        self.clear_log_button.configure(text=self.app.t("recipe.action.clear_log"))

    def refresh_language(self) -> None:
        t = self.app.t
        self.header_title.configure(text=t("recipe.builder"))
        self.recipe_id_label.configure(text=t("recipe.id"))
        self.recipe_name_label.configure(text=t("recipe.name"))
        action_keys = {"new": "action.new", "open": "action.open", "save": "action.save", "save_as": "action.save_as",
                       "validate_all": "recipe.action.validate_all", "dry_run": "recipe.action.dry_run",
                       "live_run": "recipe.action.live_run", "stop_all": "action.stop_all_title"}
        for name, key in action_keys.items():
            self.action_buttons[name].configure(text=t(key))
        self.library_title.configure(text=t("recipe.library"))
        self.library_help.configure(text=t("recipe.library_help"))
        self.steps_title.configure(text=t("recipe.steps"))
        self.steps_help.configure(text=t("recipe.steps_help"))
        self.inspector_title.configure(text=t("recipe.inspector"))
        self.inspector_help.configure(text=t("recipe.inspector_help"))
        self.narrow_steps_button.configure(text=t("recipe.action.edit_steps"))
        self.narrow_inspector_button.configure(text=t("recipe.action.open_inspector"))
        for block_type, button in self.library_buttons.items():
            button.configure(text=self.app.localizer.display_value(block_type))
        for name, key in (("up", "action.up"), ("down", "action.down"), ("duplicate", "action.duplicate"), ("delete", "action.delete")):
            self.move_buttons[name].configure(text=t(key))
        headings = ("recipe.column.number", "recipe.column.type", "recipe.column.target", "recipe.column.summary", "recipe.column.duration")
        for column, key in zip(self.steps_tree["columns"], headings):
            self.steps_tree.heading(column, text=t(key))
        section_keys = {"basic": "recipe.section.basic", "pump": "recipe.section.pump", "timing": "recipe.section.timing",
                        "message": "recipe.section.message", "advanced": "recipe.section.advanced"}
        for name, key in section_keys.items():
            self.inspector_section_labels[name].configure(text=t(key))
        field_keys = {"type": "label.type", "id": "label.id", "pump": "label.pump", "action": "label.action",
                      "direction": "label.direction", "profile": "label.profile", "duration_s": "label.duration_s",
                      "duration_ms": "label.duration_ms", "message": "label.message", "note": "label.note"}
        for name, key in field_keys.items():
            getattr(self.inspector_fields[name], "_field_label").configure(text=t(key))
        self.apply_button.configure(text=t("recipe.apply"))
        self._update_log_buttons()
        self._refresh_display_mappings()
        if self.selected_block_index is not None:
            self.load_selected_properties()
        self.update_execution_mode()
        self.refresh_timeline(select=self.selected_block_index)
        self._update_header_status()
        self._schedule_responsive_layout()
