from __future__ import annotations

import json
import os
import queue
import re
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk
from typing import Any, Callable

from .a4 import DEFAULT_COMMANDS, format_settings_commands, list_serial_ports
from .app_info import APP_NAME, APP_SHORT_NAME, APP_VERSION
from .assets import find_asset, load_tk_image, set_window_icon
from .flow_control import PerfusionSetpoint, build_perfusion_setpoint
from .operations import (
    get_arm_status,
    program_pair,
    pushpull,
    run_profile,
    send_action,
    start_armed_pair,
    stop_all,
    stop_all_safe,
    write_profile,
    write_settings,
)
from .perfusion_state import config_fingerprint, invalidate_armed, read_state
from .port_scan import merge_port_devices, scan_serial_ports
from .protocol_runner import schedule_armed
from .config import (
    ConfigResolution,
    load_config,
    load_user_settings,
    persist_active_config_dir,
    persist_ui_preferences,
    resolve_config,
    save_pump_settings,
    validate_config_directory,
    validate_pump_settings,
)
from .coordinator import OperationCoordinator, RunToken
from .gui_commissioning import CommissioningFrame
from .gui_history import RunHistoryFrame
from .gui_recipe import RecipeBuilderFrame
from .preflight import assess_preflight
from .profiles import calculate, calculate_profile, result_to_dict, ul_per_mm_from_inner_diameter
from .ui_theme import ScrollableFrame, apply_theme, create_card, status_badge
from .validation_store import ValidationStore


TRIGGER_SOURCES = ["Manual", "Foot pedal comparable", "NIS", "TTL"]
RUN_MODES = ["IN only", "OUT only", "Push-pull", "Two forward"]


def merge_port_candidates(*groups: list[str] | tuple[str, ...]) -> list[str]:
    values = {str(value).strip() for group in groups for value in group if str(value).strip()}

    def natural_key(value: str) -> tuple[Any, ...]:
        return tuple(int(part) if part.isdigit() else part.casefold() for part in re.split(r"(\d+)", value))

    return sorted(values, key=natural_key)


class A4PumpApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_NAME)
        self.geometry("1180x760")
        self.minsize(860, 560)
        self.style = apply_theme(self)
        set_window_icon(self)
        self.config_resolution = resolve_config()
        self.data = load_config(self.config_resolution)
        self.ensure_gui_pump_defaults()
        self._loading_settings = True
        self._pump_settings_dirty = False
        self._active_operation: str | None = None
        self._stop_in_flight = False
        self._closing = False
        self._preview_after_id: str | None = None
        self._state_poll_after_id: str | None = None
        self._ui_queue_after_id: str | None = None
        self._ui_queue: queue.Queue[tuple[Callable[..., Any], tuple[Any, ...]]] = queue.Queue()
        self.detected_ports: list[dict[str, Any]] = []
        self.current_perfusion_setpoint: PerfusionSetpoint | None = None

        self.port_vars = {
            "IN": tk.StringVar(value=self.data["pumps"]["IN"]["port"]),
            "OUT": tk.StringVar(value=self.data["pumps"].get("OUT", {}).get("port", "")),
        }
        self.terminator_var = tk.StringVar(value=self.data["pumps"]["IN"].get("terminator", "\\r\\n"))
        self.baudrate_var = tk.StringVar(value=str(self.data["pumps"]["IN"].get("baudrate", 9600)))
        self.timeout_var = tk.StringVar(value=str(self.data["pumps"]["IN"].get("timeout", 1.0)))
        self.dry_run_var = tk.BooleanVar(value=True)
        self.out_enabled_var = tk.BooleanVar(value=self.data["pumps"].get("OUT", {}).get("enabled", False))
        self.manual_pump_var = tk.StringVar(value="IN")
        self.jog_duration_var = tk.StringVar(value="1000")
        self.hold_auto_stop_ms_var = tk.StringVar(value="4000")
        self._manual_active = False
        self._manual_token: RunToken | None = None
        self._manual_coordinator: OperationCoordinator | None = None
        self._manual_stop_after_id: str | None = None
        self._jog_active = False
        self._jog_stop_after_id: str | None = None
        self._jog_buttons: list[tk.Widget] = []

        self.syringe_var = tk.StringVar(value="terumo_ss05lz_5ml")
        self.calc_mode_var = tk.StringVar(value="volume_duration")
        self.volume_var = tk.StringVar(value="1000")
        self.duration_var = tk.StringVar(value="30")
        self.flow_var = tk.StringVar(value="2.0")
        self.speed_var = tk.StringVar(value="15.37")
        self.calc_result_var = tk.StringVar(value="")
        self.calc_write_pump_var = tk.StringVar(value="IN")
        self.calc_save_after_write_var = tk.BooleanVar(value=True)
        self.last_calc_result: dict[str, Any] | None = None

        self.profile_var = tk.StringVar(value="fast30_1ml")
        self.profile_result_var = tk.StringVar(value="")
        self.profile_write_pump_var = tk.StringVar(value="IN")
        self.profile_save_after_write_var = tk.BooleanVar(value=True)
        self.profile_start_after_write_var = tk.BooleanVar(value=False)

        self.dish_id_var = tk.StringVar(value="")
        self.condition_var = tk.StringVar(value="")
        self.trigger_var = tk.StringVar(value="Manual")
        self.run_mode_var = tk.StringVar(value="IN only")
        self.profile_in_var = tk.StringVar(value="fast30_1ml")
        self.profile_out_var = tk.StringVar(value="drain30_1ml")
        self.out_delay_var = tk.StringVar(value="0.5")
        ui = load_user_settings().get("ui_preferences", {})
        if not isinstance(ui, dict):
            ui = {}
        self.flow_slider_min = float(ui.get("flow_slider_min", 0.1))
        self.flow_slider_max = float(ui.get("flow_slider_max", 3.0))
        self.flow_slider_step = float(ui.get("flow_slider_step", 0.1))
        self.require_current_commissioning_var = tk.BooleanVar(
            value=bool(ui.get("require_current_commissioning", False))
        )
        self._commissioning_acknowledged = False
        self.validation_store = ValidationStore(self.config_resolution)
        self.perfusion_mode_var = tk.StringVar(value="fixed_volume")
        self.in_flow_var = tk.StringVar(value="2.0")
        self.flow_slider_var = tk.DoubleVar(value=2.0)
        self.target_volume_ml_var = tk.StringVar(value="1.0")
        self.fixed_duration_s_var = tk.StringVar(value="60")
        self.maximum_duration_s_var = tk.StringVar(value="300")
        self.in_syringe_var = tk.StringVar(value="terumo_ss05lz_5ml")
        self.out_syringe_var = tk.StringVar(value="terumo_ss05lz_5ml")
        self.same_out_syringe_var = tk.BooleanVar(value=True)
        self.out_ratio_locked_var = tk.BooleanVar(value=True)
        self.out_ratio_var = tk.StringVar(value="1.0")
        self.independent_out_flow_var = tk.StringVar(value="2.0")
        self.in_to_out_delay_var = tk.StringVar(value="0.5")
        self.requested_start_delay_var = tk.StringVar(value="0")
        self.perfusion_preview_var = tk.StringVar(value="Enter a valid setpoint.")
        self.perfusion_state_var = tk.StringVar(value="DIRTY")
        self.programmed_message_var = tk.StringVar(value="")
        self.runtime_detail_var = tk.StringVar(value="")
        self.port_scan_status_var = tk.StringVar(value="Ports not scanned")
        self.in_port_metadata_var = tk.StringVar(value="")
        self.out_port_metadata_var = tk.StringVar(value="")
        self.page_title_var = tk.StringVar(value="Dashboard")
        self.page_subtitle_var = tk.StringVar(value="Ready")
        self.status_var = tk.StringVar(value="Ready")
        self.nav_buttons: dict[str, ttk.Button] = {}
        self.pages: dict[str, tk.Widget] = {}
        self._logo_image: tk.PhotoImage | None = None

        self._build()
        for variable in (
            self.port_vars["IN"],
            self.port_vars["OUT"],
            self.out_enabled_var,
            self.baudrate_var,
            self.terminator_var,
            self.timeout_var,
        ):
            variable.trace_add("write", self._mark_pump_settings_dirty)
        for variable in (
            self.perfusion_mode_var,
            self.in_flow_var,
            self.target_volume_ml_var,
            self.fixed_duration_s_var,
            self.maximum_duration_s_var,
            self.in_syringe_var,
            self.out_syringe_var,
            self.same_out_syringe_var,
            self.out_ratio_locked_var,
            self.out_ratio_var,
            self.independent_out_flow_var,
            self.in_to_out_delay_var,
            self.requested_start_delay_var,
        ):
            variable.trace_add("write", self._on_perfusion_input_changed)
        self._loading_settings = False
        self.bind_all("<Escape>", self.on_escape_stop)
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.update_out_widgets_state()
        self.update_run_mode_options()
        self.update_manual_pump_options()
        self.update_syringe_info()
        self.update_profile_info()
        self.refresh_config_display()
        self.schedule_perfusion_preview()
        self._ui_queue_after_id = self.after(25, self._drain_ui_queue)
        self.after(50, self.scan_ports_async)
        self._state_poll_after_id = self.after(400, self.poll_runtime_state)

    def ensure_gui_pump_defaults(self) -> None:
        if "IN" not in self.data["pumps"]:
            raise KeyError("IN pump is required")
        self.data["pumps"]["IN"]["enabled"] = True
        self.data["pumps"]["IN"].setdefault("terminator", "\\r\\n")
        self.data["pumps"]["IN"].setdefault("timeout", 1.0)
        self.data["pumps"]["IN"].setdefault("commands", DEFAULT_COMMANDS.copy())
        if "OUT" not in self.data["pumps"]:
            self.data["pumps"]["OUT"] = {
                "enabled": False,
                "name": "Pump OUT",
                "role": "waste_or_wash",
                "port": "",
                "baudrate": 9600,
                "terminator": "\\r\\n",
                "timeout": 1.0,
                "commands": DEFAULT_COMMANDS.copy(),
            }
        self.data["pumps"]["OUT"].setdefault("enabled", False)
        self.data["pumps"]["OUT"].setdefault("port", "")
        self.data["pumps"]["OUT"].setdefault("baudrate", 9600)
        self.data["pumps"]["OUT"].setdefault("terminator", "\\r\\n")
        self.data["pumps"]["OUT"].setdefault("timeout", 1.0)
        self.data["pumps"]["OUT"].setdefault("commands", DEFAULT_COMMANDS.copy())

    def _build(self) -> None:
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)

        self.sidebar = ttk.Frame(self, style="Sidebar.TFrame", padding=16)
        self.sidebar.grid(row=0, column=0, sticky="ns")
        self._build_sidebar(self.sidebar)

        content = ttk.Frame(self, style="Page.TFrame", padding=16)
        content.grid(row=0, column=1, sticky="nsew")
        content.columnconfigure(0, weight=1)
        content.rowconfigure(1, weight=1)

        header = ttk.Frame(content, style="Page.TFrame")
        header.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        header.columnconfigure(0, weight=1)
        ttk.Label(header, textvariable=self.page_title_var, style="PageTitle.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(header, textvariable=self.page_subtitle_var, style="PageSubtitle.TLabel").grid(
            row=1, column=0, sticky="w", pady=(2, 0)
        )
        self.dry_run_badge = status_badge(header, "DRY-RUN", "dryrun")
        self.dry_run_badge.grid(row=0, column=1, sticky="e")

        self.notebook = ttk.Notebook(content, style="Hidden.TNotebook")
        self.notebook.grid(row=1, column=0, sticky="nsew")

        experiment_tab = ttk.Frame(self.notebook, style="Page.TFrame", padding=0)
        setup_tab = ttk.Frame(self.notebook, style="Page.TFrame", padding=0)
        advanced_tab = ttk.Frame(self.notebook, style="Page.TFrame", padding=0)
        for key, page in (
            ("experiment", experiment_tab),
            ("setup", setup_tab),
            ("advanced", advanced_tab),
        ):
            self.notebook.add(page, text=key)

        # Legacy aliases keep API/tests stable without creating legacy navigation.
        self.pages = {
            "experiment": experiment_tab,
            "setup": setup_tab,
            "advanced": advanced_tab,
            "dashboard": experiment_tab,
            "run": experiment_tab,
            "pumps": setup_tab,
            "profiles": advanced_tab,
            "calculator": advanced_tab,
            "recipes": advanced_tab,
        }

        self._build_experiment_tab(experiment_tab)
        self._build_setup_tab(setup_tab)
        self._build_advanced_tab(advanced_tab)

        status = ttk.Frame(self, style="Toolbar.TFrame", padding=(16, 8))
        status.grid(row=1, column=0, columnspan=2, sticky="ew")
        status.columnconfigure(0, weight=1)
        ttk.Label(status, textvariable=self.status_var, style="Card.TLabel").grid(row=0, column=0, sticky="w")
        self.global_stop_button = ttk.Button(
            status,
            text="STOP ALL (Esc)",
            style="Danger.TButton",
            takefocus=False,
            command=self.gui_stop_all_now,
        )
        self.global_stop_button.grid(row=0, column=1, sticky="e", padx=(12, 0))

        self.select_page("experiment")

    def _build_sidebar(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        ttk.Label(parent, text=APP_SHORT_NAME, style="SectionTitle.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 2))
        self.sidebar_version_label = ttk.Label(parent, text=APP_VERSION, style="Subtitle.TLabel")
        self.sidebar_version_label.grid(row=1, column=0, sticky="w", pady=(0, 16))
        items = [
            ("experiment", "Experiment"),
            ("setup", "Setup"),
            ("advanced", "Advanced"),
        ]
        for row, (key, text) in enumerate(items, start=2):
            button = ttk.Button(
                parent,
                text=text,
                style="Nav.TButton",
                takefocus=False,
                command=lambda page=key: self.select_page(page),
            )
            button.grid(row=row, column=0, sticky="ew", pady=3)
            self.nav_buttons[key] = button
        # Internal compatibility aliases; no duplicate buttons are rendered.
        self.nav_buttons.update(
            {
                "dashboard": self.nav_buttons["experiment"],
                "run": self.nav_buttons["experiment"],
                "pumps": self.nav_buttons["setup"],
                "profiles": self.nav_buttons["advanced"],
                "calculator": self.nav_buttons["advanced"],
                "recipes": self.nav_buttons["advanced"],
            }
        )
        ttk.Separator(parent, orient="horizontal").grid(row=20, column=0, sticky="ew", pady=16)
        self.connection_summary_var = tk.StringVar(value="")
        ttk.Label(parent, textvariable=self.connection_summary_var, style="Subtitle.TLabel", justify="left").grid(
            row=21, column=0, sticky="w"
        )

    def select_page(self, page: str) -> None:
        if page not in self.pages:
            return
        self.notebook.select(self.pages[page])
        titles = {
            "experiment": ("Experiment", "Shared config · write profiles · start · stop"),
            "setup": ("Setup", "Active Config, ports, connection tests, and manual control"),
            "advanced": ("Advanced", "Profiles, calculator, and recipes"),
            "dashboard": ("Experiment", "Shared config · write profiles · start · stop"),
            "pumps": ("Setup", "Active Config, ports, connection tests, and manual control"),
            "run": ("Experiment", "Shared config · write profiles · start · stop"),
            "profiles": ("Profiles", "Preview and write A4 speed/time settings"),
            "calculator": ("Calculator", "Calculate volume, speed, time, and write settings"),
            "recipes": ("Recipes", "Build and run repeatable V2 recipes"),
        }
        title, subtitle = titles[page]
        self.page_title_var.set(title)
        self.page_subtitle_var.set(subtitle)
        selected_main = {
            "dashboard": "experiment",
            "run": "experiment",
            "pumps": "setup",
            "profiles": "advanced",
            "calculator": "advanced",
            "recipes": "advanced",
        }.get(page, page)
        for key in ("experiment", "setup", "advanced"):
            button = self.nav_buttons[key]
            button.configure(style="NavSelected.TButton" if key == selected_main else "Nav.TButton")
        if page in {"profiles", "calculator", "recipes"} and hasattr(self, "advanced_notebook"):
            self.advanced_notebook.select({"profiles": 0, "calculator": 1, "recipes": 2}[page])
        self.set_status(f"Ready - {title}")

    def set_status(self, message: str) -> None:
        if threading.current_thread() is not threading.main_thread():
            self.post_ui(self.set_status, message)
            return
        self.status_var.set(message)
        if hasattr(self, "dry_run_badge"):
            if self.dry_run_var.get():
                self.dry_run_badge.configure(text="DRY-RUN", style="BadgeDryRun.TLabel")
            else:
                self.dry_run_badge.configure(text="LIVE", style="BadgeEnabled.TLabel")
        if hasattr(self, "connection_summary_var"):
            dry = "ON" if self.dry_run_var.get() else "OFF"
            out = "enabled" if self.is_pump_enabled("OUT") else "disabled"
            self.connection_summary_var.set(f"IN: {self.port_vars['IN'].get()}\nOUT: {out}\nDry-run: {dry}")
        if hasattr(self, "experiment_pumps_var"):
            out = self.port_vars["OUT"].get() if self.is_pump_enabled("OUT") else "disabled"
            self.experiment_pumps_var.set(
                f"IN: {self.port_vars['IN'].get()}    OUT: {out}    "
                f"{'DRY-RUN' if self.dry_run_var.get() else 'LIVE'}"
            )

    @property
    def _program_running(self) -> bool:
        return self._active_operation == "program"

    @_program_running.setter
    def _program_running(self, value: bool) -> None:
        if value:
            self._active_operation = "program"
        elif self._active_operation == "program":
            self._active_operation = None

    @property
    def _start_running(self) -> bool:
        return self._active_operation in {"start", "schedule"}

    @_start_running.setter
    def _start_running(self, value: bool) -> None:
        if value:
            self._active_operation = "start"
        elif self._active_operation in {"start", "schedule"}:
            self._active_operation = None

    @property
    def _operation_running(self) -> bool:
        return self._active_operation is not None

    @_operation_running.setter
    def _operation_running(self, value: bool) -> None:
        if value and self._active_operation is None:
            self._active_operation = "legacy"
        elif not value:
            self._active_operation = None

    def begin_gui_operation(self, name: str) -> bool:
        if self._closing:
            self.set_status("Application is closing; no new operation accepted")
            return False
        if self._active_operation is not None:
            self.set_status(f"Operation already running: {self._active_operation}")
            return False
        self._active_operation = name
        self.update_runtime_controls(self.perfusion_state_var.get())
        return True

    def finish_gui_operation(self, name: str) -> None:
        if self._active_operation == name:
            self._active_operation = None
        self.update_runtime_controls(self.perfusion_state_var.get())

    def post_ui(self, callback: Callable[..., Any], *args: Any) -> None:
        self._ui_queue.put((callback, args))

    def _drain_ui_queue(self) -> None:
        self._ui_queue_after_id = None
        while True:
            try:
                callback, args = self._ui_queue.get_nowait()
            except queue.Empty:
                break
            try:
                callback(*args)
            except Exception as exc:
                try:
                    self.status_var.set(f"UI callback failed: {exc}")
                except Exception:
                    pass
                print(f"UI callback failed: {exc}")
        if not getattr(self, "_destroyed", False) and self.winfo_exists():
            self._ui_queue_after_id = self.after(25, self._drain_ui_queue)

    def destroy(self) -> None:
        if getattr(self, "_destroyed", False):
            return
        self._destroyed = True
        for attribute in (
            "_preview_after_id",
            "_state_poll_after_id",
            "_ui_queue_after_id",
            "_manual_stop_after_id",
            "_jog_stop_after_id",
        ):
            after_id = getattr(self, attribute, None)
            if after_id is not None:
                try:
                    self.after_cancel(after_id)
                except (tk.TclError, ValueError):
                    pass
                setattr(self, attribute, None)
        super().destroy()

    def _build_experiment_tab(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        parent.columnconfigure(1, weight=1)
        parent.rowconfigure(3, weight=1)

        shared = create_card(parent, "Armed perfusion", "GUI / CLI / NIS share this state. Device settings are not read back.")
        shared.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        shared.columnconfigure(1, weight=1)
        self.experiment_config_var = tk.StringVar(value="")
        ttk.Label(shared, text="State", style="Card.TLabel").grid(row=2, column=0, sticky="w")
        self.perfusion_state_label = ttk.Label(shared, textvariable=self.perfusion_state_var, style="Value.TLabel")
        self.perfusion_state_label.grid(row=2, column=1, sticky="w", padx=(8, 16))
        ttk.Label(shared, textvariable=self.programmed_message_var, style="Value.TLabel").grid(
            row=2, column=2, sticky="e"
        )
        self.experiment_pumps_var = tk.StringVar(value="")
        ttk.Label(shared, textvariable=self.experiment_pumps_var, style="Card.TLabel").grid(
            row=3, column=0, columnspan=3, sticky="w", pady=(4, 0)
        )
        ttk.Label(shared, textvariable=self.experiment_config_var, style="Subtitle.TLabel").grid(
            row=4, column=0, columnspan=3, sticky="ew", pady=(2, 0)
        )
        ttk.Label(shared, textvariable=self.runtime_detail_var, style="Subtitle.TLabel").grid(
            row=5, column=0, columnspan=3, sticky="ew", pady=(2, 0)
        )
        self.dashboard_identity_var = tk.StringVar(value="")
        self.dashboard_plan_var = tk.StringVar(value="")
        self.dashboard_safety_var = tk.StringVar(value="")
        self.dashboard_timing_var = tk.StringVar(value="")
        ttk.Label(shared, textvariable=self.dashboard_identity_var, style="Card.TLabel").grid(
            row=6, column=0, columnspan=3, sticky="ew", pady=(2, 0)
        )
        ttk.Label(shared, textvariable=self.dashboard_plan_var, style="Card.TLabel").grid(
            row=7, column=0, columnspan=3, sticky="ew", pady=(2, 0)
        )
        ttk.Label(shared, textvariable=self.dashboard_timing_var, style="Subtitle.TLabel").grid(
            row=8, column=0, columnspan=3, sticky="ew", pady=(2, 0)
        )
        ttk.Label(shared, textvariable=self.dashboard_safety_var, style="Value.TLabel").grid(
            row=9, column=0, columnspan=3, sticky="ew", pady=(2, 0)
        )

        actions = create_card(parent, "Primary actions", "Setpoint edits only update preview; they never send UART commands.")
        actions.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        for column in range(4):
            actions.columnconfigure(column, weight=1)
        self.scan_ports_button = ttk.Button(
            actions, text="SCAN PORTS", style="Secondary.TButton", command=self.scan_ports_async
        )
        self.scan_ports_button.grid(row=2, column=0, sticky="ew", padx=(0, 4), pady=(4, 0))
        self.experiment_write_button = ttk.Button(
            actions,
            text="PROGRAM / ARM BOTH",
            style="Success.TButton",
            takefocus=False,
            command=self.program_arm_gui,
        )
        self.experiment_write_button.grid(row=2, column=1, sticky="ew", padx=4, pady=(4, 0))
        self.experiment_start_button = ttk.Button(
            actions,
            text="START ARMED",
            style="Primary.TButton",
            takefocus=False,
            command=self.start_armed_gui,
        )
        self.experiment_start_button.grid(row=2, column=2, sticky="ew", padx=4, pady=(4, 0))
        ttk.Button(
            actions,
            text="STOP ALL",
            style="Danger.TButton",
            takefocus=False,
            command=self.gui_stop_all_now,
        ).grid(row=2, column=3, sticky="ew", padx=(4, 0), pady=(4, 0))

        setpoint = create_card(parent, "Perfusion setpoint", "Numeric IN flow is authoritative; slider range is a UI preference.")
        setpoint.grid(row=2, column=0, sticky="nsew", padx=(0, 4), pady=(0, 8))
        for column in range(4):
            setpoint.columnconfigure(column, weight=1)
        self.perfusion_mode_combo = ttk.Combobox(
            setpoint,
            textvariable=self.perfusion_mode_var,
            values=("fixed_volume", "fixed_duration", "bounded_continuous"),
            state="readonly",
        )
        ttk.Label(setpoint, text="Mode", style="Card.TLabel").grid(row=2, column=0, sticky="w")
        self.perfusion_mode_combo.grid(row=2, column=1, columnspan=3, sticky="ew")
        ttk.Label(setpoint, text="IN flow mL/min", style="Card.TLabel").grid(row=3, column=0, sticky="w", pady=2)
        self.in_flow_entry = ttk.Entry(setpoint, textvariable=self.in_flow_var, width=8)
        self.in_flow_entry.grid(row=3, column=1, sticky="ew", pady=2)
        ttk.Button(setpoint, text="-0.1", style="Compact.TButton", command=lambda: self.adjust_flow(-0.1)).grid(
            row=3, column=2, sticky="ew", padx=2
        )
        ttk.Button(setpoint, text="+0.1", style="Compact.TButton", command=lambda: self.adjust_flow(0.1)).grid(
            row=3, column=3, sticky="ew", padx=2
        )
        self.flow_slider = ttk.Scale(
            setpoint,
            from_=self.flow_slider_min,
            to=self.flow_slider_max,
            variable=self.flow_slider_var,
            command=self.on_flow_slider,
        )
        self.flow_slider.grid(row=4, column=0, columnspan=4, sticky="ew", pady=2)
        presets = ttk.Frame(setpoint, style="Card.TFrame")
        presets.grid(row=5, column=0, columnspan=4, sticky="ew")
        for column, value in enumerate((0.5, 1.0, 2.0, 3.0)):
            presets.columnconfigure(column, weight=1)
            ttk.Button(
                presets,
                text=f"{value:.1f}",
                style="Compact.TButton",
                command=lambda selected=value: self.set_flow(selected),
            ).grid(row=0, column=column, sticky="ew", padx=1)
        bound_rows = (
            ("Target volume mL", self.target_volume_ml_var),
            ("Duration sec", self.fixed_duration_s_var),
            ("Maximum sec", self.maximum_duration_s_var),
            ("IN→OUT delay sec", self.in_to_out_delay_var),
        )
        self.bound_entries: list[tk.Widget] = []
        for row, (label, variable) in enumerate(bound_rows, start=6):
            ttk.Label(setpoint, text=label, style="Card.TLabel").grid(row=row, column=0, columnspan=2, sticky="w", pady=1)
            entry = ttk.Entry(setpoint, textvariable=variable)
            entry.grid(row=row, column=2, columnspan=2, sticky="ew", pady=1)
            self.bound_entries.append(entry)

        pair = create_card(parent, "IN / OUT calculation", "IN is forward; OUT is reverse. Unequal flow can change dish volume.")
        pair.grid(row=2, column=1, sticky="nsew", padx=(4, 0), pady=(0, 8))
        pair.columnconfigure(1, weight=1)
        syringe_values = tuple(self.data["syringes"])
        self.in_syringe_combo = ttk.Combobox(pair, textvariable=self.in_syringe_var, values=syringe_values, state="readonly")
        self.out_syringe_combo = ttk.Combobox(pair, textvariable=self.out_syringe_var, values=syringe_values, state="readonly")
        rows = (
            ("IN syringe", self.in_syringe_combo),
            ("OUT syringe", self.out_syringe_combo),
        )
        for row, (label, widget) in enumerate(rows, start=2):
            ttk.Label(pair, text=label, style="Card.TLabel").grid(row=row, column=0, sticky="w", pady=2)
            widget.grid(row=row, column=1, sticky="ew", pady=2)
        self.same_syringe_check = ttk.Checkbutton(
            pair, text="Use same syringe for OUT", variable=self.same_out_syringe_var, command=self.on_same_syringe
        )
        self.same_syringe_check.grid(row=4, column=0, columnspan=2, sticky="w")
        self.ratio_lock_check = ttk.Checkbutton(
            pair, text="Lock OUT/IN ratio", variable=self.out_ratio_locked_var, command=self.update_ratio_widgets
        )
        self.ratio_lock_check.grid(row=5, column=0, columnspan=2, sticky="w")
        ttk.Label(pair, text="OUT/IN ratio", style="Card.TLabel").grid(row=6, column=0, sticky="w")
        self.out_ratio_entry = ttk.Entry(pair, textvariable=self.out_ratio_var)
        self.out_ratio_entry.grid(row=6, column=1, sticky="ew")
        ttk.Label(pair, text="Independent OUT mL/min", style="Card.TLabel").grid(row=7, column=0, sticky="w")
        self.independent_out_flow_entry = ttk.Entry(pair, textvariable=self.independent_out_flow_var)
        self.independent_out_flow_entry.grid(row=7, column=1, sticky="ew")
        ttk.Label(pair, text="Dish ID / Condition", style="Card.TLabel").grid(row=8, column=0, sticky="w")
        metadata = ttk.Frame(pair, style="Card.TFrame")
        metadata.grid(row=8, column=1, sticky="ew")
        metadata.columnconfigure(0, weight=1)
        metadata.columnconfigure(1, weight=1)
        ttk.Entry(metadata, textvariable=self.dish_id_var).grid(row=0, column=0, sticky="ew", padx=(0, 2))
        ttk.Entry(metadata, textvariable=self.condition_var).grid(row=0, column=1, sticky="ew", padx=(2, 0))
        ttk.Label(pair, text="GUI START delay sec (CLI start-armed stays immediate)", style="Card.TLabel").grid(row=9, column=0, sticky="w")
        self.requested_start_delay_entry = ttk.Entry(pair, textvariable=self.requested_start_delay_var)
        self.requested_start_delay_entry.grid(row=9, column=1, sticky="ew")
        ttk.Label(pair, textvariable=self.port_scan_status_var, style="Subtitle.TLabel").grid(
            row=10, column=0, columnspan=2, sticky="w", pady=(2, 0)
        )

        preview = create_card(parent, "Quantized preview", "PROGRAMMED — NOT READ BACK after successful LIVE programming.")
        preview.grid(row=3, column=0, columnspan=2, sticky="nsew")
        preview.columnconfigure(0, weight=1)
        ttk.Label(
            preview,
            textvariable=self.perfusion_preview_var,
            style="Card.TLabel",
            justify="left",
            font=("Consolas", 9),
        ).grid(row=2, column=0, sticky="nw")
        self.run_log = tk.Text(preview, height=2, wrap="word", font=("Consolas", 8))
        self.run_log.grid(row=3, column=0, sticky="ew", pady=(4, 0))
        self.setpoint_widgets = [
            self.perfusion_mode_combo, self.in_flow_entry, self.flow_slider, *self.bound_entries,
            self.in_syringe_combo, self.out_syringe_combo, self.same_syringe_check,
            self.ratio_lock_check, self.out_ratio_entry, self.independent_out_flow_entry,
            self.requested_start_delay_entry,
        ]
        # Compatibility handles for the legacy profile workflow now located in Advanced.
        self.run_mode_combo = ttk.Combobox(parent, textvariable=self.run_mode_var, values=RUN_MODES, state="readonly")
        self.profile_in_combo = ttk.Combobox(parent, textvariable=self.profile_in_var, values=tuple(self.data["profiles"]), state="readonly")
        self.profile_out_combo = ttk.Combobox(parent, textvariable=self.profile_out_var, values=tuple(self.data["profiles"]), state="readonly")
        self.out_delay_entry = ttk.Entry(parent, textvariable=self.out_delay_var)
        self.update_ratio_widgets()

    def _build_setup_tab(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(0, weight=1)
        self.setup_notebook = ttk.Notebook(parent)
        self.setup_notebook.grid(row=0, column=0, sticky="nsew")
        hardware_page = ttk.Frame(self.setup_notebook)
        commissioning_page = ttk.Frame(self.setup_notebook)
        self.setup_notebook.add(hardware_page, text="Hardware setup")
        self.setup_notebook.add(commissioning_page, text="Commissioning")
        hardware_page.columnconfigure(0, weight=1)
        hardware_page.rowconfigure(0, weight=1)
        commissioning_page.columnconfigure(0, weight=1)
        commissioning_page.rowconfigure(0, weight=1)
        self.setup_scroll = ScrollableFrame(hardware_page, height=460)
        self.setup_scroll.grid(row=0, column=0, sticky="nsew")
        inner = self.setup_scroll.inner
        inner.columnconfigure(0, weight=1)

        config_frame = ttk.Frame(inner, style="Page.TFrame")
        config_frame.grid(row=0, column=0, sticky="ew")
        self._build_config_card(config_frame)

        pump_frame = ttk.Frame(inner, style="Page.TFrame")
        pump_frame.grid(row=1, column=0, sticky="ew")
        self._build_pump_tab(pump_frame)

        self.commissioning_page = commissioning_page
        self.commissioning_placeholder = ttk.Label(
            commissioning_page,
            text="Select this tab to load the commissioning workspace.",
            style="Subtitle.TLabel",
        )
        self.commissioning_placeholder.grid(row=0, column=0, sticky="nw", padx=12, pady=12)
        self.setup_notebook.bind("<<NotebookTabChanged>>", self._on_setup_tab_changed, add="+")

    def _on_setup_tab_changed(self, _event: tk.Event[Any] | None = None) -> None:
        if self.setup_notebook.index(self.setup_notebook.select()) == 1:
            self.ensure_commissioning_workspace()

    def ensure_commissioning_workspace(self) -> CommissioningFrame:
        existing = getattr(self, "commissioning_tab", None)
        if existing is not None:
            return existing
        self.commissioning_placeholder.destroy()
        commissioning_scroll = ScrollableFrame(self.commissioning_page, height=460)
        commissioning_scroll.grid(row=0, column=0, sticky="nsew")
        commissioning_scroll.inner.columnconfigure(0, weight=1)
        self.commissioning_tab = CommissioningFrame(commissioning_scroll.inner, self)
        self.commissioning_tab.grid(row=0, column=0, sticky="ew")
        return self.commissioning_tab

    def _build_advanced_tab(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(0, weight=1)
        self.advanced_notebook = ttk.Notebook(parent)
        self.advanced_notebook.grid(row=0, column=0, sticky="nsew")

        profile_scroll = ScrollableFrame(self.advanced_notebook, height=430)
        calc_scroll = ScrollableFrame(self.advanced_notebook, height=430)
        self.recipe_tab = RecipeBuilderFrame(self.advanced_notebook, self)
        self.history_tab = RunHistoryFrame(self.advanced_notebook, self)
        self.advanced_notebook.add(profile_scroll, text="Profiles")
        self.advanced_notebook.add(calc_scroll, text="Calculator")
        self.advanced_notebook.add(self.recipe_tab, text="Recipes")
        self.advanced_notebook.add(self.history_tab, text="Run history")
        self._build_profile_tab(profile_scroll.inner)
        self._build_calc_tab(calc_scroll.inner)

    def _build_config_card(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        card = create_card(parent, "Active Config", "All four JSON files are loaded from this one external directory.")
        card.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        card.columnconfigure(1, weight=1)
        self.active_config_dir_var = tk.StringVar()
        self.active_pumps_path_var = tk.StringVar()
        self.config_source_var = tk.StringVar()
        self.config_writable_var = tk.StringVar()
        self.config_shared_var = tk.StringVar()
        self.nis_cfg_var = tk.StringVar()
        info_rows = (
            ("Active Config Directory", self.active_config_dir_var),
            ("Active pumps.json", self.active_pumps_path_var),
            ("Config source", self.config_source_var),
            ("Writable", self.config_writable_var),
            ("CLI omitted --config-dir", self.config_shared_var),
            ("NIS wrapper CFG", self.nis_cfg_var),
        )
        for row, (label, variable) in enumerate(info_rows, start=2):
            ttk.Label(card, text=label, style="Card.TLabel").grid(row=row, column=0, sticky="nw", padx=(0, 8), pady=2)
            entry = ttk.Entry(card, textvariable=variable, state="readonly")
            entry.grid(row=row, column=1, sticky="ew", pady=2)

        settings = ttk.Frame(card, style="Card.TFrame")
        settings.grid(row=8, column=0, columnspan=2, sticky="ew", pady=(8, 2))
        for column in range(6):
            settings.columnconfigure(column, weight=1)
        for column, (label, variable, values) in enumerate(
            (
                ("Baudrate", self.baudrate_var, None),
                ("Terminator", self.terminator_var, ("", "\\r", "\\n", "\\r\\n")),
                ("Timeout sec", self.timeout_var, None),
            )
        ):
            base = column * 2
            ttk.Label(settings, text=label, style="Card.TLabel").grid(row=0, column=base, sticky="w", padx=3)
            if values is None:
                widget: tk.Widget = ttk.Entry(settings, textvariable=variable)
            else:
                widget = ttk.Combobox(settings, textvariable=variable, values=values, state="readonly")
            widget.grid(row=0, column=base + 1, sticky="ew", padx=3)

        buttons = ttk.Frame(card, style="Card.TFrame")
        buttons.grid(row=9, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        actions = (
            ("Scan ports", self.scan_ports_async),
            ("Save pump settings", self.save_pump_settings_gui),
            ("Reload from JSON", self.reload_from_json),
            ("Open config folder", self.open_config_folder),
            ("Open pumps.json", self.open_pumps_json),
            ("Choose config directory", self.choose_config_directory),
            ("Copy config path", self.copy_config_path),
            ("Copy CLI example", self.copy_cli_example),
            ("Copy NIS CFG line", self.copy_nis_cfg_line),
        )
        for index, (text, command) in enumerate(actions):
            row, column = divmod(index, 3)
            buttons.columnconfigure(column, weight=1)
            ttk.Button(buttons, text=text, style="Secondary.TButton", command=command).grid(
                row=row, column=column, sticky="ew", padx=3, pady=3
            )

    def _build_dashboard_tab(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        parent.columnconfigure(1, weight=1)
        identity_card = create_card(parent, APP_SHORT_NAME, "Syringe pump control for perfusion experiments.")
        identity_card.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 12))
        identity_card.columnconfigure(1, weight=1)
        logo_path = find_asset("logo/app_logo_512.png")
        if logo_path is not None:
            self._logo_image = load_tk_image(logo_path)
            if self._logo_image is not None:
                ttk.Label(identity_card, image=self._logo_image, style="Card.TLabel").grid(
                    row=2, column=0, sticky="w", padx=(0, 12), pady=(8, 0)
                )
        ttk.Label(identity_card, text=APP_VERSION, style="Value.TLabel").grid(row=2, column=1, sticky="w", pady=(8, 0))

        pump_card = create_card(parent, "Connection", "Active pump configuration and dry-run state.")
        pump_card.grid(row=1, column=0, sticky="nsew", padx=(0, 8), pady=(0, 12))
        self.dashboard_connection_var = tk.StringVar(value="")
        ttk.Label(pump_card, textvariable=self.dashboard_connection_var, style="Value.TLabel").grid(
            row=2, column=0, sticky="w", pady=(10, 0)
        )
        action_card = create_card(parent, "Quick actions", "Common safety operations.")
        action_card.grid(row=1, column=1, sticky="nsew", padx=(8, 0), pady=(0, 12))
        ttk.Button(action_card, text="STOP ALL", style="Danger.TButton", takefocus=False, command=self.gui_stop_all_now).grid(
            row=2, column=0, sticky="ew", pady=(10, 0)
        )
        self.update_dashboard()

    def update_dashboard(self) -> None:
        if hasattr(self, "dashboard_connection_var"):
            pumps = ", ".join(self.available_pumps())
            dry = "ON" if self.dry_run_var.get() else "OFF"
            self.dashboard_connection_var.set(f"Pumps: {pumps}\nIN: {self.port_vars['IN'].get()}\nDry-run: {dry}")

    def _build_pump_tab(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        parent.columnconfigure(1, weight=1)
        ports = [value for value in [self.port_vars["IN"].get(), self.port_vars["OUT"].get()] if value]

        in_card = self._build_pump_card(parent, "IN", "Pump IN", ports)
        in_card.grid(row=0, column=0, sticky="nsew", padx=(0, 8), pady=(0, 12))
        out_card = self._build_pump_card(parent, "OUT", "Pump OUT", ports)
        out_card.grid(row=0, column=1, sticky="nsew", padx=(8, 0), pady=(0, 12))
        self.out_card = out_card

        manual = create_card(parent, "Manual / Jog", "Hold-to-run always sends stop on release, leave, Esc, or auto-stop.")
        manual.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 12))
        for col in range(4):
            manual.columnconfigure(col, weight=1)
        ttk.Label(manual, text="Pump selection", style="Card.TLabel").grid(row=2, column=0, sticky="w", padx=4, pady=4)
        self.manual_pump_combo = ttk.Combobox(manual, textvariable=self.manual_pump_var, values=self.available_pumps(), state="readonly")
        self.manual_pump_combo.grid(row=2, column=1, sticky="ew", padx=4, pady=4)
        ttk.Label(manual, text="Auto stop after ms", style="Card.TLabel").grid(row=2, column=2, sticky="w", padx=4, pady=4)
        ttk.Entry(manual, textvariable=self.hold_auto_stop_ms_var, width=10).grid(row=2, column=3, sticky="ew", padx=4, pady=4)

        hold_forward = ttk.Button(manual, text="Hold forward", style="Primary.TButton", takefocus=False)
        hold_reverse = ttk.Button(manual, text="Hold reverse", style="Primary.TButton", takefocus=False)
        hold_forward.grid(row=3, column=0, sticky="ew", padx=4, pady=4)
        hold_reverse.grid(row=3, column=1, sticky="ew", padx=4, pady=4)
        ttk.Button(manual, text="Stop", style="DangerSecondary.TButton", takefocus=False, command=self.manual_stop_selected).grid(
            row=3, column=2, columnspan=2, sticky="ew", padx=4, pady=4
        )

        hold_forward.bind("<ButtonPress-1>", lambda _e: self.on_manual_press("forward"))
        hold_forward.bind("<ButtonRelease-1>", lambda _e: self.on_manual_release())
        hold_forward.bind("<Leave>", lambda _e: self.on_manual_leave())
        hold_reverse.bind("<ButtonPress-1>", lambda _e: self.on_manual_press("reverse"))
        hold_reverse.bind("<ButtonRelease-1>", lambda _e: self.on_manual_release())
        hold_reverse.bind("<Leave>", lambda _e: self.on_manual_leave())

        ttk.Label(manual, text="Jog duration ms", style="Card.TLabel").grid(row=4, column=0, sticky="w", padx=4, pady=4)
        ttk.Entry(manual, textvariable=self.jog_duration_var, width=10).grid(row=4, column=1, sticky="ew", padx=4, pady=4)
        jog_forward = ttk.Button(manual, text="Jog forward", style="Secondary.TButton", takefocus=False, command=lambda: self.start_jog("forward"))
        jog_reverse = ttk.Button(manual, text="Jog reverse", style="Secondary.TButton", takefocus=False, command=lambda: self.start_jog("reverse"))
        jog_forward.grid(row=4, column=2, sticky="ew", padx=4, pady=4)
        jog_reverse.grid(row=4, column=3, sticky="ew", padx=4, pady=4)
        self._jog_buttons = [jog_forward, jog_reverse]

        safety = create_card(parent, "Safety", "STOP ALL is immediate and also bound to Esc.")
        safety.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(0, 12))
        safety.columnconfigure(0, weight=1)
        safety.columnconfigure(1, weight=1)
        safety.columnconfigure(2, weight=1)
        ttk.Checkbutton(
            safety,
            text="Dry-run",
            variable=self.dry_run_var,
            style="Card.TCheckbutton",
            command=self.on_dry_run_changed,
        ).grid(
            row=2, column=0, sticky="w", pady=(8, 0)
        )
        ttk.Button(
            safety,
            text="Test all",
            style="Secondary.TButton",
            takefocus=False,
            command=lambda: self.connection_test_async(),
        ).grid(
            row=2, column=1, sticky="ew", padx=6, pady=(8, 0)
        )
        ttk.Button(safety, text="STOP ALL", style="Danger.TButton", takefocus=False, command=self.gui_stop_all_now).grid(
            row=2, column=2, sticky="ew", pady=(8, 0)
        )
        self.pump_log = self._make_log_box(parent, row=3, columnspan=2)

    def _build_pump_card(self, parent: ttk.Frame, pump_key: str, title: str, ports: list[str]) -> ttk.Frame:
        enabled = self.is_pump_enabled(pump_key)
        card = create_card(parent, title, "9600 baud / 8N1 / CRLF")
        for col in range(3):
            card.columnconfigure(col, weight=1)
        status_badge(card, "ENABLED" if enabled else "DISABLED", "enabled" if enabled else "disabled").grid(
            row=0, column=1, sticky="e"
        )
        if pump_key == "OUT":
            ttk.Checkbutton(
                card,
                text="Use OUT pump",
                variable=self.out_enabled_var,
                style="Card.TCheckbutton",
                command=lambda: self.set_out_enabled(self.out_enabled_var.get()),
            ).grid(row=2, column=0, columnspan=3, sticky="w", pady=(10, 4))
            self.out_disabled_message = ttk.Label(
                card,
                text="Enable this pump for push-pull or waste-line operation.",
                style="Subtitle.TLabel",
                wraplength=320,
            )
            self.out_disabled_message.grid(row=3, column=0, columnspan=3, sticky="w", padx=4, pady=(4, 0))
            self.out_detail_widgets: list[tk.Widget] = []
        port_label = ttk.Label(card, text="COM port", style="Card.TLabel")
        port_label.grid(row=4, column=0, sticky="w", padx=4, pady=4)
        combo = ttk.Combobox(card, textvariable=self.port_vars[pump_key], values=ports)
        combo.grid(row=4, column=1, columnspan=2, sticky="ew", padx=4, pady=4)
        if pump_key == "IN":
            self.in_port_combo = combo
        else:
            self.out_port_combo = combo
            self.out_detail_widgets.extend([port_label, combo])
        metadata_label = ttk.Label(
            card,
            textvariable=self.in_port_metadata_var if pump_key == "IN" else self.out_port_metadata_var,
            style="Subtitle.TLabel",
            wraplength=340,
        )
        metadata_label.grid(row=5, column=0, columnspan=3, sticky="w", padx=4, pady=(0, 4))
        if pump_key == "OUT":
            self.out_detail_widgets.append(metadata_label)
        baud_label = ttk.Label(card, text="Baudrate", style="Card.TLabel")
        baud_label.grid(row=6, column=0, sticky="w", padx=4, pady=4)
        baud_value = ttk.Label(card, text="9600", style="Value.TLabel")
        baud_value.grid(row=6, column=1, sticky="w", padx=4, pady=4)
        test_button = ttk.Button(
            card,
            text=f"Test {pump_key}",
            style="Secondary.TButton",
            takefocus=False,
            command=lambda key=pump_key: self.connection_test_async(key),
        )
        test_button.grid(
            row=7, column=0, columnspan=3, sticky="ew", padx=4, pady=(8, 4)
        )
        if pump_key == "OUT":
            self.out_detail_widgets.extend([baud_label, baud_value, test_button])
        if pump_key == "IN":
            ttk.Button(card, text="Start forward", style="Primary.TButton", takefocus=False, command=lambda: self.gui_send_async("IN", "start-forward")).grid(
                row=8, column=0, sticky="ew", padx=4, pady=4
            )
            ttk.Button(card, text="Stop", style="DangerSecondary.TButton", takefocus=False, command=lambda: self.gui_send_async("IN", "stop")).grid(
                row=8, column=1, columnspan=2, sticky="ew", padx=4, pady=4
            )
        else:
            self.out_start_forward_button = ttk.Button(card, text="Start forward", style="Primary.TButton", takefocus=False, command=lambda: self.gui_send_async("OUT", "start-forward"))
            self.out_start_forward_button.grid(row=8, column=0, sticky="ew", padx=4, pady=4)
            self.out_start_reverse_button = ttk.Button(card, text="Start reverse", style="Primary.TButton", takefocus=False, command=lambda: self.gui_send_async("OUT", "start-reverse"))
            self.out_start_reverse_button.grid(row=8, column=1, sticky="ew", padx=4, pady=4)
            self.out_stop_button = ttk.Button(card, text="Stop", style="DangerSecondary.TButton", takefocus=False, command=lambda: self.gui_send_async("OUT", "stop"))
            self.out_stop_button.grid(row=8, column=2, sticky="ew", padx=4, pady=4)
            self.out_detail_widgets.extend(
                [self.out_start_forward_button, self.out_start_reverse_button, self.out_stop_button]
            )
        return card

    def _build_calc_tab(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        parent.columnconfigure(1, weight=1)
        syringe_keys = list(self.data["syringes"])
        input_card = create_card(parent, "Inputs", "Calculate pump speed, time, and expected volume.")
        input_card.grid(row=0, column=0, sticky="nsew", padx=(0, 8), pady=(0, 12))
        input_card.columnconfigure(1, weight=1)
        result_card = create_card(parent, "Result", "Latest calculation.")
        result_card.grid(row=0, column=1, sticky="nsew", padx=(8, 0), pady=(0, 12))
        result_card.columnconfigure(0, weight=1)

        ttk.Label(input_card, text="Syringe preset", style="Card.TLabel").grid(row=2, column=0, sticky="w", pady=4)
        self.syringe_combo = ttk.Combobox(
            input_card, textvariable=self.syringe_var, values=syringe_keys, state="readonly"
        )
        self.syringe_combo.grid(row=2, column=1, sticky="ew", pady=4)
        self.syringe_combo.bind("<<ComboboxSelected>>", lambda _e: self.update_syringe_info())

        self.syringe_info = ttk.Label(input_card, text="", justify="left", style="Subtitle.TLabel")
        self.syringe_info.grid(row=3, column=0, columnspan=2, sticky="w", pady=4)

        ttk.Label(input_card, text="Input mode", style="Card.TLabel").grid(row=4, column=0, sticky="w", pady=4)
        ttk.Combobox(
            input_card,
            textvariable=self.calc_mode_var,
            values=["volume_duration", "volume_flow", "speed_duration"],
            state="readonly",
        ).grid(row=4, column=1, sticky="ew", pady=4)

        fields = [
            ("Target volume uL", self.volume_var),
            ("Duration sec", self.duration_var),
            ("Flow mL/min", self.flow_var),
            ("Speed mm/min", self.speed_var),
        ]
        for idx, (label, var) in enumerate(fields, start=5):
            ttk.Label(input_card, text=label, style="Card.TLabel").grid(row=idx, column=0, sticky="w", pady=4)
            ttk.Entry(input_card, textvariable=var).grid(row=idx, column=1, sticky="ew", pady=4)

        ttk.Button(input_card, text="Calculate", style="Primary.TButton", takefocus=False, command=self.calculate_gui).grid(
            row=9, column=0, columnspan=2, sticky="ew", pady=(10, 0)
        )
        ttk.Label(result_card, textvariable=self.calc_result_var, justify="left", style="Value.TLabel").grid(
            row=2, column=0, sticky="nw", pady=(10, 0)
        )

        calc_write = create_card(parent, "Write-to-A4", "Write the latest calculated speed/time to the selected pump.")
        calc_write.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 12))
        for col in range(4):
            calc_write.columnconfigure(col, weight=1)
        ttk.Label(calc_write, text="Target pump", style="Card.TLabel").grid(row=2, column=0, sticky="w", padx=4, pady=4)
        self.calc_write_pump_combo = ttk.Combobox(
            calc_write,
            textvariable=self.calc_write_pump_var,
            values=self.available_pumps(),
            state="readonly",
        )
        self.calc_write_pump_combo.grid(row=2, column=1, sticky="ew", padx=4, pady=4)
        ttk.Checkbutton(calc_write, text="Save after write", variable=self.calc_save_after_write_var, style="Card.TCheckbutton").grid(
            row=2, column=2, sticky="w", padx=4, pady=4
        )
        self.calc_write_button = ttk.Button(
            calc_write,
            text="Write calculated settings to A4",
            style="Success.TButton",
            takefocus=False,
            command=self.write_calculated_settings_async,
        )
        self.calc_write_button.grid(
            row=2, column=3, sticky="ew", padx=4, pady=4
        )
        self.calc_write_button.configure(state="disabled")

    def _build_profile_tab(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        parent.columnconfigure(1, weight=1)
        profile_keys = list(self.data["profiles"])
        select_card = create_card(parent, "Profile selection", "Choose a saved profile and preview calculated A4 settings.")
        select_card.grid(row=0, column=0, sticky="nsew", padx=(0, 8), pady=(0, 12))
        select_card.columnconfigure(1, weight=1)
        preview_card = create_card(parent, "Calculated settings preview", "Commands are lowercase and terminated with CRLF.")
        preview_card.grid(row=0, column=1, sticky="nsew", padx=(8, 0), pady=(0, 12))
        preview_card.columnconfigure(0, weight=1)

        ttk.Label(select_card, text="Profile preset", style="Card.TLabel").grid(row=2, column=0, sticky="w", pady=4)
        self.profile_combo = ttk.Combobox(
            select_card, textvariable=self.profile_var, values=profile_keys, state="readonly"
        )
        self.profile_combo.grid(row=2, column=1, sticky="ew", pady=4)
        self.profile_combo.bind("<<ComboboxSelected>>", lambda _e: self.update_profile_info())

        ttk.Label(preview_card, textvariable=self.profile_result_var, justify="left", style="Value.TLabel").grid(
            row=2, column=0, sticky="nw", pady=(10, 0)
        )
        write_frame = create_card(parent, "Write settings to A4", "Default writes and saves only. Start after write is explicit.")
        write_frame.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 12))
        for col in range(4):
            write_frame.columnconfigure(col, weight=1)
        ttk.Label(write_frame, text="Target pump", style="Card.TLabel").grid(row=2, column=0, sticky="w", padx=4, pady=4)
        self.profile_write_pump_combo = ttk.Combobox(
            write_frame,
            textvariable=self.profile_write_pump_var,
            values=self.available_pumps(),
            state="readonly",
        )
        self.profile_write_pump_combo.grid(row=2, column=1, sticky="ew", padx=4, pady=4)
        ttk.Checkbutton(write_frame, text="Save after write", variable=self.profile_save_after_write_var, style="Card.TCheckbutton").grid(
            row=2, column=2, sticky="w", padx=4, pady=4
        )
        ttk.Checkbutton(write_frame, text="Start after write", variable=self.profile_start_after_write_var, style="Card.TCheckbutton").grid(
            row=2, column=3, sticky="w", padx=4, pady=4
        )
        ttk.Label(
            write_frame,
            text="Only starts the pump after settings are written.",
            style="Subtitle.TLabel",
        ).grid(row=3, column=0, columnspan=4, sticky="w", padx=4, pady=(0, 4))
        self.profile_write_button = ttk.Button(
            write_frame,
            text="Write settings to A4",
            style="Success.TButton",
            takefocus=False,
            command=self.write_profile_settings_async,
        )
        self.profile_write_button.grid(row=4, column=0, columnspan=4, sticky="ew", padx=4, pady=(8, 4))
        self.profile_log = self._make_log_box(parent, row=2, columnspan=2)

    def _build_run_tab(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        parent.columnconfigure(1, weight=1)
        mode_card = create_card(parent, "Run mode", "OUT modes are hidden while OUT pump is disabled.")
        mode_card.grid(row=0, column=0, sticky="nsew", padx=(0, 8), pady=(0, 12))
        mode_card.columnconfigure(1, weight=1)
        profile_card = create_card(parent, "Profiles / timing", "Select saved profiles and OUT delay.")
        profile_card.grid(row=0, column=1, sticky="nsew", padx=(8, 0), pady=(0, 12))
        profile_card.columnconfigure(1, weight=1)

        self.run_mode_combo = ttk.Combobox(mode_card, textvariable=self.run_mode_var, values=RUN_MODES, state="readonly")
        metadata_rows = [
            ("Dish ID", ttk.Entry(mode_card, textvariable=self.dish_id_var)),
            ("Condition", ttk.Entry(mode_card, textvariable=self.condition_var)),
            ("Trigger source", ttk.Combobox(mode_card, textvariable=self.trigger_var, values=TRIGGER_SOURCES, state="readonly")),
            ("Mode", self.run_mode_combo),
        ]
        for idx, (label, widget) in enumerate(metadata_rows, start=2):
            ttk.Label(mode_card, text=label, style="Card.TLabel").grid(row=idx, column=0, sticky="w", pady=4)
            widget.grid(row=idx, column=1, sticky="ew", pady=4)

        self.profile_out_combo = ttk.Combobox(profile_card, textvariable=self.profile_out_var, values=list(self.data["profiles"]), state="readonly")
        self.out_delay_entry = ttk.Entry(profile_card, textvariable=self.out_delay_var)
        profile_rows = [
            ("Profile IN", ttk.Combobox(profile_card, textvariable=self.profile_in_var, values=list(self.data["profiles"]), state="readonly")),
            ("Profile OUT", self.profile_out_combo),
            ("Out delay sec", self.out_delay_entry),
        ]
        for idx, (label, widget) in enumerate(profile_rows, start=2):
            ttk.Label(profile_card, text=label, style="Card.TLabel").grid(row=idx, column=0, sticky="w", pady=4)
            widget.grid(row=idx, column=1, sticky="ew", pady=4)

        actions = create_card(parent, "Action buttons", "Start uses saved A4 settings. STOP ALL is immediate.")
        actions.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 12))
        actions.columnconfigure(0, weight=1)
        actions.columnconfigure(1, weight=1)
        ttk.Button(actions, text="Start", style="Primary.TButton", takefocus=False, command=self.start_run_mode_async).grid(
            row=2, column=0, sticky="ew", padx=(0, 6), pady=(8, 0)
        )
        ttk.Button(actions, text="STOP ALL", style="Danger.TButton", takefocus=False, command=self.gui_stop_all_now).grid(
            row=2, column=1, sticky="ew", padx=(6, 0), pady=(8, 0)
        )
        self.run_log = self._make_log_box(parent, row=2, columnspan=2)

    def _make_log_box(self, parent: ttk.Frame, *, row: int, columnspan: int, height: int = 10) -> tk.Text:
        parent.rowconfigure(row, weight=1)
        box = tk.Text(
            parent,
            height=height,
            wrap="word",
            font=("Consolas", 9),
            background="#FFFFFF",
            foreground="#111827",
            relief="flat",
            highlightthickness=1,
            highlightbackground="#E5E7EB",
            padx=8,
            pady=6,
        )
        box.grid(row=row, column=0, columnspan=columnspan, sticky="nsew", pady=8)
        return box

    def refresh_ports(self) -> None:
        """Backward-compatible refresh entry point; scanning remains asynchronous."""
        self.scan_ports_async()

    def scan_ports_async(self) -> None:
        if getattr(self, "_port_scan_running", False):
            return
        self._port_scan_running = True
        self.port_scan_status_var.set("Scanning serial ports…")
        if hasattr(self, "scan_ports_button"):
            self.scan_ports_button.configure(state="disabled")

        def worker() -> None:
            try:
                ports = scan_serial_ports(provider=list_serial_ports)
                self.post_ui(self._apply_port_scan, ports, None)
            except Exception as exc:
                self.post_ui(self._apply_port_scan, [], str(exc))

        threading.Thread(target=worker, daemon=True, name="a4-port-scan").start()

    def _apply_port_scan(self, ports: list[dict[str, Any]], error: str | None) -> None:
        self._port_scan_running = False
        if hasattr(self, "scan_ports_button"):
            self.scan_ports_button.configure(state="normal")
        if error:
            self.port_scan_status_var.set(f"Scan failed: {error}")
            self.set_status(f"Port scan failed: {error}")
            return
        self.detected_ports = ports
        saved = [
            str(self.data["pumps"].get("IN", {}).get("port", "")),
            str(self.data["pumps"].get("OUT", {}).get("port", "")),
        ]
        entered = [self.port_vars["IN"].get(), self.port_vars["OUT"].get()]
        values = merge_port_devices(ports, saved, entered)
        self.in_port_combo.configure(values=values)
        self.out_port_combo.configure(values=values)
        timestamp = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")
        self.port_scan_status_var.set(f"Last scan: {timestamp} · {len(ports)} device(s)")
        self.update_selected_port_metadata()
        if hasattr(self, "pump_log"):
            self.append_log(self.pump_log, f"Ports: {', '.join(values) or '(none)'}")

    def update_selected_port_metadata(self) -> None:
        by_device = {str(port.get("device", "")).casefold(): port for port in self.detected_ports}
        for key, variable in (("IN", self.in_port_metadata_var), ("OUT", self.out_port_metadata_var)):
            device = self.port_vars[key].get().strip()
            port = by_device.get(device.casefold())
            if not device:
                text = "No port selected"
            elif port is None:
                text = f"{device}: NOT DETECTED"
            else:
                metadata = [
                    str(port.get("description", "")).strip(),
                    str(port.get("manufacturer", "")).strip(),
                    str(port.get("product", "")).strip(),
                    f"HWID {port.get('hwid')}" if port.get("hwid") else "",
                ]
                text = f"{device}: DETECTED · " + " · ".join(item for item in metadata if item)
            variable.set(text)

    def _on_perfusion_input_changed(self, *_args: Any) -> None:
        if self._loading_settings:
            return
        if self.same_out_syringe_var.get() and self.out_syringe_var.get() != self.in_syringe_var.get():
            self._loading_settings = True
            self.out_syringe_var.set(self.in_syringe_var.get())
            self._loading_settings = False
        self.schedule_perfusion_preview()
        self.after_idle(self._invalidate_shared_plan, "perfusion setpoint changed")

    def _invalidate_shared_plan(self, reason: str) -> None:
        try:
            invalidate_armed(self.config_resolution.active_config_dir, reason)
        except Exception as exc:
            self.set_status(f"Could not invalidate armed plan: {exc}")

    def schedule_perfusion_preview(self) -> None:
        if self._preview_after_id is not None:
            try:
                self.after_cancel(self._preview_after_id)
            except Exception:
                pass
        self._preview_after_id = self.after(120, self.update_perfusion_preview)

    def build_current_perfusion_setpoint(self) -> PerfusionSetpoint:
        return build_perfusion_setpoint(
            self.data,
            mode=self.perfusion_mode_var.get(),
            in_flow_ml_min=float(self.in_flow_var.get()),
            target_volume_ml=float(self.target_volume_ml_var.get()) if self.target_volume_ml_var.get().strip() else None,
            duration_s=float(self.fixed_duration_s_var.get()) if self.fixed_duration_s_var.get().strip() else None,
            maximum_duration_s=float(self.maximum_duration_s_var.get()) if self.maximum_duration_s_var.get().strip() else None,
            in_syringe_key=self.in_syringe_var.get(),
            out_syringe_key=self.in_syringe_var.get() if self.same_out_syringe_var.get() else self.out_syringe_var.get(),
            out_ratio_locked=self.out_ratio_locked_var.get(),
            out_in_ratio=float(self.out_ratio_var.get()),
            independent_out_flow_ml_min=(
                float(self.independent_out_flow_var.get())
                if self.independent_out_flow_var.get().strip()
                else None
            ),
            in_to_out_delay_s=float(self.in_to_out_delay_var.get()),
            requested_start_delay_s=float(self.requested_start_delay_var.get() or 0),
        )

    def update_perfusion_preview(self) -> None:
        self._preview_after_id = None
        try:
            result = self.build_current_perfusion_setpoint()
            self.current_perfusion_setpoint = result
            in_set, out_set = result.in_setpoint, result.out_setpoint
            outside = ""
            flow = float(self.in_flow_var.get())
            if not self.flow_slider_min <= flow <= self.flow_slider_max:
                outside = f" · OUTSIDE SLIDER RANGE {self.flow_slider_min:g}-{self.flow_slider_max:g}"
            else:
                self.flow_slider_var.set(flow)
            self.perfusion_preview_var.set(
                f"IN  req {in_set.requested_flow_ml_min:.4f} mL/min → "
                f"{in_set.programmed_speed_mm_min:.2f} mm/min → actual {in_set.estimated_actual_flow_ml_min:.4f}; "
                f"{in_set.expected_volume_ml:.4f} mL\n"
                f"OUT req {out_set.requested_flow_ml_min:.4f} mL/min → "
                f"{out_set.programmed_speed_mm_min:.2f} mm/min → actual {out_set.estimated_actual_flow_ml_min:.4f}; "
                f"{out_set.expected_volume_ml:.4f} mL\n"
                f"Duration {result.programmed_duration_s}s · ratio {result.out_in_ratio:.3f} · "
                f"start delay {result.requested_start_delay_s:.1f}s · IN→OUT {result.in_to_out_delay_s:.3f}s{outside}\n"
                f"IN UART: {' '.join(in_set.uart_commands)}\nOUT UART: {' '.join(out_set.uart_commands)}"
            )
        except Exception as exc:
            self.current_perfusion_setpoint = None
            self.perfusion_preview_var.set(f"INVALID SETPOINT: {exc}")
        self.update_runtime_controls(self.perfusion_state_var.get())

    def on_flow_slider(self, value: str) -> None:
        # Slider is preview-only. It only updates the authoritative numeric entry.
        raw = float(value)
        stepped = round(raw / self.flow_slider_step) * self.flow_slider_step
        self.in_flow_var.set(f"{stepped:.6g}")

    def set_flow(self, value: float) -> None:
        self.in_flow_var.set(f"{value:.6g}")

    def adjust_flow(self, delta: float) -> None:
        try:
            self.set_flow(float(self.in_flow_var.get()) + delta)
        except ValueError:
            self.set_status("IN flow is not a valid number")

    def on_same_syringe(self) -> None:
        if self.same_out_syringe_var.get():
            self.out_syringe_var.set(self.in_syringe_var.get())
        self.out_syringe_combo.configure(state="disabled" if self.same_out_syringe_var.get() else "readonly")
        self.schedule_perfusion_preview()

    def update_ratio_widgets(self) -> None:
        if hasattr(self, "out_ratio_entry"):
            self.out_ratio_entry.configure(state="normal" if self.out_ratio_locked_var.get() else "disabled")
        if hasattr(self, "independent_out_flow_entry"):
            self.independent_out_flow_entry.configure(state="disabled" if self.out_ratio_locked_var.get() else "normal")
        if hasattr(self, "out_syringe_combo"):
            self.out_syringe_combo.configure(state="disabled" if self.same_out_syringe_var.get() else "readonly")

    def program_arm_gui(self) -> None:
        if self._operation_running:
            self.set_status(f"Another operation is running: {self._active_operation}")
            return
        try:
            self.apply_gui_pump_settings()
            if not self.out_enabled_var.get():
                raise ValueError("OUT must be enabled to arm paired perfusion")
            path = save_pump_settings(
                self.config_resolution,
                in_port=self.port_vars["IN"].get(),
                out_enabled=True,
                out_port=self.port_vars["OUT"].get(),
                baudrate=self.baudrate_var.get(),
                terminator=self.terminator_var.get(),
                timeout=self.timeout_var.get(),
            )
            self.data = load_config(self.config_resolution)
            preflight = assess_preflight(
                self.config_resolution,
                detected_ports=json.loads(json.dumps(self.detected_ports)),
                dry_run=self.dry_run_var.get(),
            )
            blocking = [
                item for item in preflight["findings"]
                if item["level"] == "BLOCK" and item["code"] != "INVALID_ARMED_PLAN"
            ]
            if blocking:
                raise ValueError(
                    "Software preflight BLOCK:\n"
                    + "\n".join(f"{item['code']}: {item['message']}" for item in blocking)
                )
            setpoint = self.build_current_perfusion_setpoint()
            context = {
                "dry_run": self.dry_run_var.get(),
                "dish_id": self.dish_id_var.get(),
                "condition": self.condition_var.get(),
                "trigger_source": self.trigger_var.get(),
            }
        except Exception as exc:
            messagebox.showerror("Cannot program/arm", str(exc))
            return
        if not self.begin_gui_operation("program"):
            return
        self.set_operational_state("PROGRAMMING")
        self.set_status(f"Programming both pumps using {path}")

        def worker() -> None:
            try:
                state = program_pair(
                    self.config_resolution,
                    setpoint,
                    scanner=lambda: scan_serial_ports(provider=list_serial_ports),
                    **context,
                )
                self.post_ui(self._operation_succeeded, state)
            except Exception as exc:
                self.post_ui(self._operation_failed, "Programming failed", str(exc))

        threading.Thread(target=worker, daemon=True, name="a4-program-pair").start()

    def start_armed_gui(self) -> None:
        if self._operation_running:
            self.set_status(f"Another operation is running: {self._active_operation}")
            return
        if self.dry_run_var.get():
            messagebox.showerror("START refused", "Switch to LIVE and create an ARMED plan first.")
            return
        if get_arm_status(self.config_resolution).get("state") != "ARMED":
            messagebox.showerror("START refused", "The shared perfusion state is not ARMED.")
            return
        if not self._confirm_live_start_preflight():
            return
        context = {
            "dish_id": self.dish_id_var.get(),
            "condition": self.condition_var.get(),
            "trigger_source": self.trigger_var.get(),
        }
        try:
            delay_s = float(self.requested_start_delay_var.get() or 0)
            if delay_s < 0:
                raise ValueError("GUI START delay must be zero or positive")
        except ValueError as exc:
            messagebox.showerror("START refused", str(exc))
            return
        operation_name = "schedule" if delay_s > 0 else "start"
        if not self.begin_gui_operation(operation_name):
            return
        self.set_operational_state("PENDING" if delay_s > 0 else "STARTING")

        def worker() -> None:
            try:
                if delay_s > 0:
                    pending = schedule_armed(
                        self.config_resolution,
                        delay_s=delay_s,
                        scanner=lambda: scan_serial_ports(provider=list_serial_ports),
                        **context,
                    )
                    state = {
                        "state": "PENDING",
                        "run_id": pending["run_id"],
                        "pending": pending,
                        "message": f"Scheduled for {pending['scheduled_for']}",
                    }
                else:
                    state = start_armed_pair(
                        self.config_resolution,
                        scanner=lambda: scan_serial_ports(provider=list_serial_ports),
                        **context,
                    )
                self.post_ui(self._operation_succeeded, state)
            except Exception as exc:
                self.post_ui(self._operation_failed, "Start failed", str(exc))

        threading.Thread(target=worker, daemon=True, name="a4-start-armed").start()

    def _operation_succeeded(self, state: dict[str, Any]) -> None:
        self._active_operation = None
        name = str(state.get("state", "DIRTY"))
        self.set_operational_state(name)
        self.append_log(self.run_log, json.dumps({"state": name, "plan_id": state.get("plan_id"), "run_id": state.get("run_id")}, ensure_ascii=False))
        self.set_status(str(state.get("message") or f"Perfusion state: {name}"))

    def _operation_failed(self, title: str, message: str) -> None:
        self._active_operation = None
        self.set_operational_state("FAULT")
        messagebox.showerror(title, message)

    def poll_runtime_state(self) -> None:
        try:
            status = get_arm_status(self.config_resolution)
            state = str(status.get("state", "DIRTY"))
            if state == "MISSING":
                state = "DIRTY"
            if not self._program_running and not self._start_running:
                self.set_operational_state(state)
            pending = status.get("pending") if isinstance(status.get("pending"), dict) else {}
            if state == "PENDING" and pending:
                remaining = ""
                scheduled_epoch = pending.get("scheduled_for_epoch")
                if scheduled_epoch is not None:
                    remaining_s = max(0, int(float(scheduled_epoch) - datetime.now().astimezone().timestamp()))
                    remaining = f" · remaining ~{remaining_s}s"
                self.runtime_detail_var.set(
                    f"Run {pending.get('run_id', '')} · scheduled {pending.get('scheduled_for', '')}"
                    f"{remaining} · STOP ALL/cancel available"
                )
            else:
                self.runtime_detail_var.set(
                    f"Run {status.get('run_id', '')}" if status.get("run_id") else ""
                )
            self.update_experiment_dashboard(status)
        except Exception as exc:
            self.set_status(f"Runtime state poll failed: {exc}")
        finally:
            if self.winfo_exists():
                self._state_poll_after_id = self.after(400, self.poll_runtime_state)

    def update_experiment_dashboard(self, status: dict[str, Any]) -> None:
        plan = status.get("plan") if isinstance(status.get("plan"), dict) else {}
        pumps = plan.get("pumps") if isinstance(plan.get("pumps"), dict) else {}
        detected = {str(item.get("device", "")).casefold() for item in self.detected_ports}
        in_port = self.port_vars["IN"].get()
        out_port = self.port_vars["OUT"].get()
        in_detected = "detected" if in_port.casefold() in detected else "not detected"
        out_detected = (
            "disabled"
            if not self.out_enabled_var.get()
            else "detected" if out_port.casefold() in detected else "not detected"
        )
        self.dashboard_identity_var.set(
            f"IN {in_port or '(missing)'} ({in_detected}) · "
            f"OUT {out_port or '(missing)'} ({out_detected})"
        )
        in_plan = pumps.get("IN", {})
        out_plan = pumps.get("OUT", {})
        ratio = ""
        try:
            in_flow = float(in_plan.get("requested_flow_ml_min"))
            out_flow = float(out_plan.get("requested_flow_ml_min"))
            ratio = f"{out_flow / in_flow:.3f}"
        except (TypeError, ValueError, ZeroDivisionError):
            in_flow = self.in_flow_var.get()
            out_flow = self.independent_out_flow_var.get()
        self.dashboard_plan_var.set(
            f"Plan {status.get('plan_id', '') or '—'} · Run {status.get('run_id', '') or '—'} · "
            f"IN {in_flow} mL/min · OUT {out_flow} mL/min · ratio {ratio or self.out_ratio_var.get()} · "
            f"duration {plan.get('programmed_duration_s', '—')} s · "
            f"expected IN {in_plan.get('expected_volume_ml', '—')} mL · "
            f"OUT {out_plan.get('expected_volume_ml', '—')} mL"
        )
        now_epoch = datetime.now().astimezone().timestamp()
        pending = status.get("pending") if isinstance(status.get("pending"), dict) else {}
        scheduled = pending.get("scheduled_for", "")
        expected_end = status.get("expected_end", "")
        remaining = ""
        if status.get("expected_end_epoch") is not None:
            remaining = f" · estimated remaining {max(0, int(float(status['expected_end_epoch']) - now_epoch))} s"
        self.dashboard_timing_var.set(
            f"Scheduled {scheduled or '—'} · software start {status.get('actual_started_at', '—')} · "
            f"IN→OUT delay {(plan.get('requested') or {}).get('in_to_out_delay_s', '—')} s · "
            f"expected end {expected_end or '—'}{remaining}"
        )
        validation = self.validation_store.status(
            data=self.data,
            detected_ports=self.detected_ports,
        )
        fault = status.get("fault") or {}
        preflight = assess_preflight(
            self.config_resolution,
            detected_ports=self.detected_ports,
            dry_run=self.dry_run_var.get(),
        )
        self.dashboard_safety_var.set(
            f"Commissioning: {validation['status']} "
            f"(last {validation['last_completed_at'] or 'not completed'}) · "
            f"Preflight: {preflight['summary']} "
            f"({preflight['counts']['BLOCK']} BLOCK, {preflight['counts']['WARN']} WARN) · "
            f"Last fault: {fault.get('error', 'none')} · STOP: "
            f"{'in progress' if self._stop_in_flight else status.get('state', 'ready')}"
        )

    def save_commissioning_policy(self) -> None:
        try:
            persist_ui_preferences(
                {"require_current_commissioning": self.require_current_commissioning_var.get()}
            )
            self._commissioning_acknowledged = False
            self.set_status("Commissioning production policy saved locally")
        except Exception as exc:
            messagebox.showerror("Policy save failed", str(exc))

    def _confirm_live_start_preflight(self) -> bool:
        result = assess_preflight(
            self.config_resolution,
            require_commissioned=self.require_current_commissioning_var.get(),
            detected_ports=json.loads(json.dumps(self.detected_ports)),
            dry_run=False,
        )
        # The shared start/scheduler validator remains authoritative for the
        # armed-plan fingerprint and complete plan schema. This compatibility
        # path lets it report older/incomplete state documents without
        # weakening command emission.
        if any(item["code"] == "INVALID_ARMED_PLAN" for item in result["findings"]):
            return True
        blocks = [
            item for item in result["findings"]
            if item["level"] == "BLOCK" and item["code"] != "INVALID_ARMED_PLAN"
        ]
        if blocks:
            messagebox.showerror(
                "START refused — preflight BLOCK",
                "\n".join(f"{item['code']}: {item['message']}" for item in blocks),
            )
            return False
        commissioning_warnings = [
            item for item in result["findings"]
            if item["code"] in {"COMMISSIONING_INCOMPLETE", "COMMISSIONING_STALE"}
        ]
        if commissioning_warnings and not self._commissioning_acknowledged:
            if not messagebox.askyesno(
                "Physical commissioning incomplete",
                "Software preflight has no BLOCK findings, but physical commissioning is missing or stale.\n\n"
                "This is not hardware validation. A per-session acknowledgement and reason are required.",
            ):
                return False
            reason = simpledialog.askstring(
                "Acknowledgement reason",
                "Enter the reason for proceeding in this session:",
                parent=self,
            )
            if not reason or not reason.strip():
                messagebox.showerror("START refused", "A non-empty acknowledgement reason is required.")
                return False
            operator_var = getattr(getattr(self, "commissioning_tab", None), "operator_var", None)
            operator = (
                operator_var.get().strip() if operator_var is not None else ""
            ) or os.environ.get("USERNAME", "") or "unknown"
            acknowledgement = {
                "event": "live_start_commissioning_acknowledgement",
                "operator": operator,
                "reason": reason.strip(),
                "session_only": True,
                "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
            }
            record = self.validation_store.load() or self.validation_store.create(
                operator=operator,
                detected_ports=json.loads(json.dumps(self.detected_ports)),
            )
            record.setdefault("manual_confirmations", []).append(acknowledgement)
            self.validation_store.save(record, event="live_start_commissioning_acknowledgement")
            self._commissioning_acknowledged = True
        return True

    def set_operational_state(self, state: str) -> None:
        self.perfusion_state_var.set(state)
        if state == "ARMED":
            self.programmed_message_var.set("PROGRAMMED — NOT READ BACK")
        elif state == "DRY_RUN_PREVIEW":
            self.programmed_message_var.set("DRY-RUN PREVIEW — NOT PROGRAMMED")
        else:
            self.programmed_message_var.set("")
        self.update_runtime_controls(state)

    def update_runtime_controls(self, state: str) -> None:
        locked = (
            state in {
                "PROGRAMMING", "PENDING", "STARTING", "STARTED", "RUNNING",
                "RECIPE_RUNNING", "REHEARSAL_PENDING", "STOPPING",
            }
            or self._active_operation is not None
        )
        for widget in getattr(self, "setpoint_widgets", []):
            try:
                if isinstance(widget, ttk.Combobox):
                    widget.configure(state="disabled" if locked else "readonly")
                else:
                    widget.configure(state="disabled" if locked else "normal")
            except tk.TclError:
                pass
        if not locked:
            self.update_ratio_widgets()
        if hasattr(self, "experiment_write_button"):
            self.experiment_write_button.configure(state="disabled" if locked or self.current_perfusion_setpoint is None else "normal")
        if hasattr(self, "experiment_start_button"):
            self.experiment_start_button.configure(
                state="normal"
                if state == "ARMED"
                and not self.dry_run_var.get()
                and self._active_operation is None
                else "disabled"
            )

    def _mark_pump_settings_dirty(self, *_args: Any) -> None:
        if not self._loading_settings:
            self._pump_settings_dirty = True
            self.update_selected_port_metadata()
            self.after_idle(self._invalidate_shared_plan, "pump or port settings changed")

    def refresh_config_display(self) -> None:
        resolution = self.config_resolution
        cli_resolution = resolve_config()
        shared = cli_resolution.active_config_dir == resolution.active_config_dir
        active = str(resolution.active_config_dir)
        pumps = str(resolution.active_pumps_json)
        self.active_config_dir_var.set(active)
        self.active_pumps_path_var.set(pumps)
        self.config_source_var.set(resolution.source)
        self.config_writable_var.set("Writable" if resolution.writable else "Read-only")
        self.config_shared_var.set(
            f"Same directory ({cli_resolution.source})" if shared else f"DIFFERENT: {cli_resolution.active_config_dir}"
        )
        self.nis_cfg_var.set(f'set "CFG={active}"')
        self.experiment_config_var.set(self._short_path(active, 78))
        out_state = "disabled"
        if self.out_enabled_var.get():
            out_state = self.port_vars["OUT"].get() or "(port required)"
        self.experiment_pumps_var.set(
            f"IN: {self.port_vars['IN'].get()}    OUT: {out_state}    "
            f"{'DRY-RUN' if self.dry_run_var.get() else 'LIVE'}"
        )

    @staticmethod
    def _short_path(value: str, limit: int) -> str:
        if len(value) <= limit:
            return value
        return value[: max(8, limit // 2 - 2)] + " … " + value[-max(8, limit // 2 - 3) :]

    def save_pump_settings_gui(self) -> Path | None:
        try:
            self.config_resolution = validate_config_directory(self.config_resolution.active_config_dir)
            path = save_pump_settings(
                self.config_resolution,
                in_port=self.port_vars["IN"].get(),
                out_enabled=self.out_enabled_var.get(),
                out_port=self.port_vars["OUT"].get(),
                baudrate=self.baudrate_var.get(),
                terminator=self.terminator_var.get(),
                timeout=self.timeout_var.get(),
            )
            self.reload_from_json(confirm=False)
            self._pump_settings_dirty = False
            self.set_status(f"Saved: {path} · CLI and GUI now use this file")
            messagebox.showinfo(
                "Pump settings saved",
                f"Saved and verified:\n{path}\n\nCLI and GUI now use this file.",
            )
            return path
        except Exception as exc:
            messagebox.showerror(
                "Save pump settings failed",
                f"{exc}\n\nChoose or create a writable external Active Config directory.",
            )
            return None

    def reload_from_json(self, *, confirm: bool = True) -> bool:
        if confirm and self._pump_settings_dirty:
            if not messagebox.askyesno(
                "Discard unsaved changes?",
                "Reloading pumps.json will discard unsaved pump settings. Continue?",
            ):
                return False
        try:
            old_state = read_state(self.config_resolution.active_config_dir)
            resolution = validate_config_directory(self.config_resolution.active_config_dir)
            if not resolution.required_files_present:
                raise FileNotFoundError(f"Missing files: {', '.join(resolution.missing_files)}")
            data = load_config(resolution)
            self.config_resolution = resolution
            self.validation_store = ValidationStore(resolution)
            if hasattr(self, "commissioning_tab"):
                self.commissioning_tab.store = ValidationStore(resolution)
            self.data = data
            self.ensure_gui_pump_defaults()
            self._loading_settings = True
            in_cfg = self.data["pumps"]["IN"]
            out_cfg = self.data["pumps"]["OUT"]
            self.port_vars["IN"].set(str(in_cfg.get("port", "")))
            self.port_vars["OUT"].set(str(out_cfg.get("port", "")))
            self.out_enabled_var.set(bool(out_cfg.get("enabled", False)))
            self.baudrate_var.set(str(in_cfg.get("baudrate", 9600)))
            self.terminator_var.set(str(in_cfg.get("terminator", "\\r\\n")))
            self.timeout_var.set(str(in_cfg.get("timeout", 1.0)))
            self._loading_settings = False
            self._pump_settings_dirty = False
            self._refresh_config_dependent_widgets()
            values = merge_port_devices(
                self.detected_ports,
                [
                    str(self.data["pumps"]["IN"].get("port", "")),
                    str(self.data["pumps"]["OUT"].get("port", "")),
                ],
                [self.port_vars["IN"].get(), self.port_vars["OUT"].get()],
            )
            self.in_port_combo.configure(values=values)
            self.out_port_combo.configure(values=values)
            self.refresh_ports()
            self.refresh_config_display()
            if hasattr(self, "commissioning_tab"):
                self.commissioning_tab.refresh()
            if (
                old_state
                and old_state.get("state") in {"ARMED", "PENDING", "STARTING", "DRY_RUN_PREVIEW"}
                and (old_state.get("plan") or {}).get("config_fingerprint") != config_fingerprint(resolution.active_config_dir)
            ):
                invalidate_armed(resolution.active_config_dir, "relevant config reload")
            self.set_status(f"Reloaded: {resolution.active_pumps_json}")
            return True
        except Exception as exc:
            self._loading_settings = False
            messagebox.showerror("Reload failed", str(exc))
            return False

    def _refresh_config_dependent_widgets(self) -> None:
        profile_values = tuple(self.data["profiles"])
        syringe_values = tuple(self.data["syringes"])
        for widget_name in ("profile_in_combo", "profile_out_combo", "profile_combo"):
            widget = getattr(self, widget_name, None)
            if widget is not None:
                widget.configure(values=profile_values)
        if hasattr(self, "syringe_combo"):
            self.syringe_combo.configure(values=syringe_values)
        for widget_name in ("in_syringe_combo", "out_syringe_combo"):
            widget = getattr(self, widget_name, None)
            if widget is not None:
                widget.configure(values=syringe_values)
        for variable, values in (
            (self.profile_in_var, profile_values),
            (self.profile_out_var, profile_values),
            (self.profile_var, profile_values),
            (self.syringe_var, syringe_values),
        ):
            if values and variable.get() not in values:
                variable.set(values[0])
        self.update_out_widgets_state()
        self.update_run_mode_options()
        self.update_manual_pump_options()
        self.update_syringe_info()
        self.update_profile_info()
        self.update_dashboard()

    def choose_config_directory(self) -> None:
        selected = filedialog.askdirectory(
            title="Choose Active Config Directory",
            initialdir=str(self.config_resolution.active_config_dir),
            mustexist=True,
        )
        if not selected:
            return
        resolution = validate_config_directory(selected)
        if not resolution.required_files_present:
            messagebox.showerror(
                "Invalid config directory",
                "The directory must contain all four JSON files:\n"
                + "\n".join(resolution.missing_files),
            )
            return
        try:
            invalidate_armed(self.config_resolution.active_config_dir, "Active Config Directory changed")
            persist_active_config_dir(resolution.active_config_dir)
            shared = resolve_config()
            if shared.active_config_dir != resolution.active_config_dir:
                raise ValueError(
                    f"A higher-priority setting selects {shared.active_config_dir}. "
                    "Check A4PUMP_CONFIG_DIR."
                )
            self.config_resolution = shared
            self.reload_from_json(confirm=False)
            messagebox.showinfo(
                "Active Config changed",
                f"GUI and CLI will use:\n{shared.active_config_dir}\n\n"
                "Update the NIS wrapper CFG line to the value shown in Setup.",
            )
        except Exception as exc:
            messagebox.showerror("Could not select config directory", str(exc))

    def _open_path(self, path: Path) -> None:
        try:
            if os.name != "nt":
                raise OSError("Open is supported by the Windows application build")
            os.startfile(str(path))  # type: ignore[attr-defined]
        except Exception as exc:
            messagebox.showerror("Open failed", str(exc))

    def open_config_folder(self) -> None:
        self._open_path(self.config_resolution.active_config_dir)

    def open_pumps_json(self) -> None:
        self._open_path(self.config_resolution.active_pumps_json)

    def _copy_text(self, value: str, label: str) -> None:
        self.clipboard_clear()
        self.clipboard_append(value)
        self.update_idletasks()
        self.set_status(f"Copied {label}: {value}")

    def copy_config_path(self) -> None:
        self._copy_text(str(self.config_resolution.active_config_dir), "config path")

    def copy_cli_example(self) -> None:
        path = self.config_resolution.active_config_dir
        self._copy_text(f'a4ctl.exe --config-dir "{path}" list-ports', "CLI example")

    def copy_nis_cfg_line(self) -> None:
        path = self.config_resolution.active_config_dir
        self._copy_text(f'set "CFG={path}"', "NIS CFG line")

    def write_experiment_profiles(self) -> None:
        self.apply_gui_pump_settings()
        results: list[dict[str, Any]] = []
        results.extend(
            write_profile(
                self.data,
                "IN",
                self.profile_in_var.get(),
                save=True,
                dry_run=self.dry_run_var.get(),
                dish_id=self.dish_id_var.get(),
                condition=self.condition_var.get(),
                trigger_source=self.trigger_var.get(),
            )
        )
        if self.is_pump_enabled("OUT"):
            results.extend(
                write_profile(
                    self.data,
                    "OUT",
                    self.profile_out_var.get(),
                    save=True,
                    dry_run=self.dry_run_var.get(),
                    dish_id=self.dish_id_var.get(),
                    condition=self.condition_var.get(),
                    trigger_source=self.trigger_var.get(),
                )
            )
        self.append_log(self.run_log, json.dumps(results, ensure_ascii=False))
        self.set_status("Profile settings written")

    def connection_test(self, pump_key: str | None = None) -> None:
        try:
            self.apply_gui_pump_settings()
            messages = self._perform_connection_test(
                json.loads(json.dumps(self.data)),
                pump_key,
                self.dry_run_var.get(),
            )
            for message in messages:
                self.append_log(self.pump_log, message)
        except Exception as exc:
            messagebox.showerror("Connection test failed", str(exc))

    def connection_test_async(self, pump_key: str | None = None) -> None:
        try:
            self.apply_gui_pump_settings()
            snapshot = json.loads(json.dumps(self.data))
            dry_run = self.dry_run_var.get()
        except Exception as exc:
            messagebox.showerror("Connection test failed", str(exc))
            return
        if not self.begin_gui_operation("connection_test"):
            return

        def worker() -> None:
            try:
                messages = self._perform_connection_test(snapshot, pump_key, dry_run)
                self.post_ui(self._connection_test_succeeded, messages)
            except Exception as exc:
                self.post_ui(
                    self._serial_operation_failed,
                    "connection_test",
                    "Connection test failed",
                    str(exc),
                )

        threading.Thread(target=worker, daemon=True, name="a4-connection-test").start()

    def _connection_test_succeeded(self, messages: list[str]) -> None:
        self.finish_gui_operation("connection_test")
        for message in messages:
            self.append_log(self.pump_log, message)

    @staticmethod
    def _perform_connection_test(
        data: dict[str, Any],
        pump_key: str | None,
        dry_run: bool,
    ) -> list[str]:
        if dry_run:
            return ["Connection test: dry-run enabled"]
        import serial

        enabled = [key for key, cfg in data["pumps"].items() if cfg.get("enabled", True)]
        pump_keys = [pump_key] if pump_key is not None else enabled
        messages: list[str] = []
        for key in pump_keys:
            if key not in enabled:
                raise ValueError(f"{key} pump is disabled")
            cfg = data["pumps"][key]
            if not str(cfg.get("port", "")).strip():
                raise ValueError(f"{key} port is blank")
            with serial.Serial(
                cfg["port"],
                cfg.get("baudrate", 9600),
                timeout=cfg.get("timeout", 1.0),
            ):
                pass
            messages.append(f"{key}: opened and closed {cfg['port']}")
        return messages

    def is_pump_enabled(self, pump_key: str) -> bool:
        if pump_key == "IN":
            return True
        return bool(self.data["pumps"].get(pump_key, {}).get("enabled", False))

    def available_pumps(self) -> list[str]:
        return [pump_key for pump_key in self.data["pumps"] if self.is_pump_enabled(pump_key)]

    def set_out_enabled(self, enabled: bool) -> None:
        if "OUT" in self.data["pumps"]:
            self.data["pumps"]["OUT"]["enabled"] = enabled
        self.out_enabled_var.set(enabled)
        self.update_out_widgets_state()
        self.update_run_mode_options()
        self.update_manual_pump_options()
        self.update_dashboard()
        self.set_status(f"OUT pump {'enabled' if enabled else 'disabled'}")

    def on_dry_run_changed(self) -> None:
        if not self.dry_run_var.get():
            confirmed = messagebox.askyesno(
                "Switch to LIVE?",
                "LIVE mode can move connected pumps. Confirm ports, tubing, and STOP ALL before continuing.",
            )
            if not confirmed:
                self.dry_run_var.set(True)
        self._invalidate_shared_plan("LIVE / DRY-RUN mode changed")
        self.update_runtime_controls(self.perfusion_state_var.get())
        self.set_status("LIVE mode enabled" if not self.dry_run_var.get() else "DRY-RUN mode enabled")

    def update_out_widgets_state(self) -> None:
        enabled = self.is_pump_enabled("OUT")
        for widget_name in ["out_start_forward_button", "out_start_reverse_button", "out_stop_button", "out_delay_entry"]:
            widget = getattr(self, widget_name, None)
            if widget is not None:
                widget.configure(state="normal" if enabled else "disabled")
        for widget_name in ["out_port_combo", "profile_out_combo"]:
            widget = getattr(self, widget_name, None)
            if widget is not None:
                widget.configure(state="readonly" if enabled else "disabled")
        for widget in getattr(self, "out_detail_widgets", []):
            if enabled:
                widget.grid()
            else:
                widget.grid_remove()
        if hasattr(self, "out_disabled_message"):
            if enabled:
                self.out_disabled_message.grid_remove()
            else:
                self.out_disabled_message.grid()

    def update_run_mode_options(self) -> None:
        modes = RUN_MODES if self.is_pump_enabled("OUT") else ["IN only"]
        if hasattr(self, "run_mode_combo"):
            self.run_mode_combo.configure(values=modes)
        if self.run_mode_var.get() not in modes:
            self.run_mode_var.set("IN only")

    def update_manual_pump_options(self) -> None:
        pumps = self.available_pumps()
        for widget_name in ["manual_pump_combo", "profile_write_pump_combo", "calc_write_pump_combo"]:
            widget = getattr(self, widget_name, None)
            if widget is not None:
                widget.configure(values=pumps)
        for var in [self.manual_pump_var, self.profile_write_pump_var, self.calc_write_pump_var]:
            if var.get() not in pumps:
                var.set("IN")
        recipe_tab = getattr(self, "recipe_tab", None)
        if recipe_tab is not None and hasattr(recipe_tab, "update_available_pumps"):
            recipe_tab.update_available_pumps()

    def require_out_enabled_for_mode(self, mode: str) -> None:
        if mode in {"OUT only", "Push-pull", "Two forward"} and not self.is_pump_enabled("OUT"):
            raise ValueError(f"{mode} requires OUT pump enabled")

    def selected_manual_pump(self) -> str:
        pump_key = self.manual_pump_var.get()
        if pump_key not in self.available_pumps():
            pump_key = "IN"
            self.manual_pump_var.set(pump_key)
        return pump_key

    def on_manual_press(self, direction: str) -> str:
        if self._manual_active or self._jog_active:
            return "break"
        pump_key = self.selected_manual_pump()
        action = "manual-forward" if direction == "forward" else "manual-reverse"
        self._manual_active = True
        try:
            self.gui_send_manual(pump_key, action, mode="manual_hold_start")
            self.start_hold_auto_stop()
        except Exception as exc:
            self._manual_active = False
            self.cancel_hold_auto_stop()
            messagebox.showerror("Manual hold failed", str(exc))
        return "break"

    def on_manual_release(self) -> str:
        if self._manual_active:
            self.manual_stop_selected(mode="manual_hold_stop")
        return "break"

    def on_manual_leave(self) -> str:
        if self._manual_active:
            self.manual_stop_selected(mode="manual_hold_stop")
        return "break"

    def start_hold_auto_stop(self) -> None:
        self.cancel_hold_auto_stop()
        duration_ms = self.parse_ms(self.hold_auto_stop_ms_var.get(), minimum=50, maximum=10000)
        self._manual_stop_after_id = self.after(duration_ms, lambda: self.manual_stop_selected(mode="manual_hold_stop"))

    def cancel_hold_auto_stop(self) -> None:
        if self._manual_stop_after_id is not None:
            try:
                self.after_cancel(self._manual_stop_after_id)
            except Exception:
                pass
            self._manual_stop_after_id = None

    def manual_stop_selected(self, *, mode: str = "manual_hold_stop") -> None:
        self.cancel_hold_auto_stop()
        self.cancel_jog_timer()
        pump_key = self.selected_manual_pump()
        try:
            self.gui_send_manual(pump_key, "stop", mode=mode)
        except Exception as exc:
            messagebox.showerror("Manual stop failed", str(exc))
        finally:
            self._manual_active = False
            self.set_jog_buttons_enabled(True)

    def start_jog(self, direction: str) -> None:
        if self._manual_active or self._jog_active:
            return
        try:
            duration_ms = self.parse_ms(self.jog_duration_var.get(), minimum=50, maximum=10000)
        except Exception as exc:
            messagebox.showerror("Invalid jog duration", str(exc))
            return
        pump_key = self.selected_manual_pump()
        action = "manual-forward" if direction == "forward" else "manual-reverse"
        self._jog_active = True
        self.set_jog_buttons_enabled(False)
        try:
            self.gui_send_manual(pump_key, action, mode="jog_start", jog_duration_ms=duration_ms)
        except Exception as exc:
            try:
                self.gui_send_manual(pump_key, "stop", mode="jog_stop", jog_duration_ms=duration_ms)
            except Exception as stop_exc:
                self.append_log(self.pump_log, f"Jog stop after start failure failed: {stop_exc}")
            self._jog_active = False
            self.set_jog_buttons_enabled(True)
            messagebox.showerror("Jog failed", str(exc))
            return
        self._jog_stop_after_id = self.after(duration_ms, lambda: self.finish_jog(pump_key, duration_ms))

    def finish_jog(self, pump_key: str, duration_ms: int) -> None:
        self._jog_stop_after_id = None
        try:
            self.gui_send_manual(pump_key, "stop", mode="jog_stop", jog_duration_ms=duration_ms)
        except Exception as exc:
            messagebox.showerror("Jog stop failed", str(exc))
        finally:
            self._jog_active = False
            self.set_jog_buttons_enabled(True)

    def cancel_jog_timer(self) -> None:
        if self._jog_stop_after_id is not None:
            try:
                self.after_cancel(self._jog_stop_after_id)
            except Exception:
                pass
            self._jog_stop_after_id = None
        self._jog_active = False

    def set_jog_buttons_enabled(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        for button in self._jog_buttons:
            button.configure(state=state)

    def gui_send_manual(
        self,
        pump_key: str,
        action: str,
        *,
        mode: str,
        jog_duration_ms: int | None = None,
    ) -> None:
        self.apply_gui_pump_settings()
        data = json.loads(json.dumps(self.data))
        dry_run = self.dry_run_var.get()
        context = {
            "dry_run": dry_run,
            "dish_id": self.dish_id_var.get(),
            "condition": self.condition_var.get(),
            "trigger_source": "Manual",
            "mode": mode,
            "jog_duration_ms": jog_duration_ms,
        }
        is_stop = action == "stop"
        if not is_stop and not self.begin_gui_operation("manual"):
            return
        coordinator: OperationCoordinator | None = None
        token: RunToken | None = None
        if not is_stop and not dry_run:
            try:
                coordinator = OperationCoordinator(self.config_resolution)
                token = coordinator.begin_recipe(data, operation_type="manual")
                self._manual_coordinator = coordinator
                self._manual_token = token
            except Exception:
                self.finish_gui_operation("manual")
                raise

        def worker() -> None:
            try:
                if dry_run:
                    result = send_action(data, pump_key, action, **context)
                elif is_stop:
                    stop_coordinator = self._manual_coordinator or OperationCoordinator(
                        self.config_resolution
                    )
                    stopped = stop_coordinator.emergency_stop(
                        metadata={"trigger_source": "Manual", "reason": mode},
                        fallback_data=data,
                    )
                    result = {"response": stopped.get("state", ""), "state": stopped}
                else:
                    assert coordinator is not None and token is not None
                    pump = coordinator.pump_factory(pump_key, data["pumps"][pump_key])
                    direction = "reverse" if action == "manual-reverse" else "forward"
                    result = coordinator.emit_manual(token, pump_key, pump, direction)
                    self.post_ui(self._manual_started, coordinator, token)
                self.post_ui(
                    self._manual_command_succeeded,
                    pump_key,
                    action,
                    mode,
                    result,
                    is_stop,
                )
            except Exception as exc:
                self.post_ui(
                    self._manual_command_failed,
                    action,
                    str(exc),
                    is_stop,
                )

        threading.Thread(
            target=worker,
            daemon=True,
            name=f"a4-manual-{pump_key.casefold()}-{action}",
        ).start()

    def _manual_started(
        self,
        coordinator: OperationCoordinator,
        token: RunToken,
    ) -> None:
        self._manual_coordinator = coordinator
        self._manual_token = token

    def _manual_command_succeeded(
        self,
        pump_key: str,
        action: str,
        mode: str,
        result: dict[str, Any],
        is_stop: bool,
    ) -> None:
        self.append_log(self.pump_log, json.dumps(result, ensure_ascii=False))
        self.set_status(f"{pump_key} {action}: {mode}")
        if is_stop:
            self._manual_coordinator = None
            self._manual_token = None
            self.finish_gui_operation("manual")

    def _manual_command_failed(self, action: str, message: str, is_stop: bool) -> None:
        if not is_stop:
            self.finish_gui_operation("manual")
        messagebox.showerror(f"Manual {action} failed", message)

    def on_escape_stop(self, _event: tk.Event[Any] | None = None) -> str:
        self.gui_stop_all_now()
        return "break"

    def on_close(self) -> None:
        if self._closing:
            return
        self._closing = True
        self.cancel_hold_auto_stop()
        self.cancel_jog_timer()
        recipe_tab = getattr(self, "recipe_tab", None)
        if recipe_tab is not None and hasattr(recipe_tab, "cancel_execution"):
            recipe_tab.cancel_execution()
        commissioning_tab = getattr(self, "commissioning_tab", None)
        if commissioning_tab is not None and hasattr(commissioning_tab, "cancel_execution"):
            commissioning_tab.cancel_execution()
        if self._state_poll_after_id is not None:
            try:
                self.after_cancel(self._state_poll_after_id)
            except Exception:
                pass
            self._state_poll_after_id = None
        try:
            persist_ui_preferences(
                {
                    "flow_slider_min": self.flow_slider_min,
                    "flow_slider_max": self.flow_slider_max,
                    "flow_slider_step": self.flow_slider_step,
                    "require_current_commissioning": self.require_current_commissioning_var.get(),
                }
            )
        except Exception as exc:
            print(f"Could not save UI preferences: {exc}")
        try:
            self.apply_gui_pump_settings()
        except Exception as exc:
            print(f"Close using last valid pump settings: {exc}")
        context = {
            "dry_run": self.dry_run_var.get(),
            "dish_id": self.dish_id_var.get(),
            "condition": self.condition_var.get(),
            "trigger_source": "Manual",
        }
        self.set_status("Closing: cancelling operations and sending emergency STOP")
        deadline = datetime.now().astimezone().timestamp() + 5.0

        def close_worker() -> None:
            try:
                result = stop_all_safe(self.config_resolution, **context)
                self.post_ui(self._finish_close_stop, result, None)
            except Exception as exc:
                self.post_ui(self._finish_close_stop, None, str(exc))

        if not self._stop_in_flight:
            self._stop_in_flight = True
            threading.Thread(
                target=close_worker,
                daemon=True,
                name="a4-close-stop",
            ).start()
        self._close_deadline = deadline
        self.after(50, self._poll_close_completion)

    def _finish_close_stop(
        self,
        result: dict[str, Any] | None,
        error: str | None,
    ) -> None:
        self._stop_in_flight = False
        self._close_stop_result = result
        self._close_stop_error = error

    def _poll_close_completion(self) -> None:
        if not self._closing or getattr(self, "_destroyed", False):
            return
        error = getattr(self, "_close_stop_error", None)
        result = getattr(self, "_close_stop_result", None)
        if error is not None:
            self._closing = False
            messagebox.showerror(
                "Close cancelled — STOP failed",
                f"{error}\n\nThe window remains open because safe stopping was not confirmed.",
            )
            return
        if result is not None:
            if result.get("state") == "STOPPED":
                self.destroy()
                return
            self._closing = False
            messagebox.showerror(
                "Close cancelled — STOP incomplete",
                "One or more pump STOP attempts failed. The window remains open.",
            )
            return
        if datetime.now().astimezone().timestamp() >= self._close_deadline:
            self._closing = False
            messagebox.showerror(
                "Close cancelled — STOP timeout",
                "Emergency STOP did not finish within 5 seconds. "
                "The window remains open and no new START is permitted by persisted cancellation.",
            )
            return
        self.after(50, self._poll_close_completion)

    def update_syringe_info(self) -> None:
        syringe = self.data["syringes"][self.syringe_var.get()]
        calibrated = syringe.get("calibrated_ul_per_mm")
        nominal = syringe["nominal_inner_diameter_mm"]
        nominal_ul = ul_per_mm_from_inner_diameter(float(nominal))
        text = (
            f"calibrated_ul_per_mm: {calibrated if calibrated is not None else 'not set'}\n"
            f"nominal inner diameter: {nominal} mm\n"
            f"nominal ul_per_mm: {nominal_ul:.2f}"
        )
        self.syringe_info.configure(text=text)

    def calculate_gui(self) -> None:
        try:
            syringe_key = self.syringe_var.get()
            syringe = self.data["syringes"][syringe_key]
            ul_per_mm = syringe.get("calibrated_ul_per_mm")
            if ul_per_mm is None:
                ul_per_mm = ul_per_mm_from_inner_diameter(float(syringe["nominal_inner_diameter_mm"]))
            result = calculate(
                self.calc_mode_var.get(),
                float(ul_per_mm),
                volume_ul=self.float_or_none(self.volume_var.get()),
                duration_s=self.float_or_none(self.duration_var.get()),
                flow_ml_min=self.float_or_none(self.flow_var.get()),
                speed_mm_min=self.float_or_none(self.speed_var.get()),
                syringe_key=syringe_key,
            )
            self.last_calc_result = result_to_dict(result)
            self.calc_result_var.set(self.format_result(self.last_calc_result))
            if hasattr(self, "calc_write_button"):
                self.calc_write_button.configure(state="normal")
            self.set_status("Calculation updated")
        except Exception as exc:
            messagebox.showerror("Calculation failed", str(exc))

    def update_profile_info(self) -> None:
        try:
            key = self.profile_var.get()
            profile = self.data["profiles"][key]
            syringe_key = profile["syringe"]
            result = calculate_profile(profile, self.data["syringes"][syringe_key], syringe_key)
            lines = [
                f"{profile['display_name']}",
                f"syringe: {syringe_key}",
                f"direction: {profile.get('direction', 'forward')}",
                "",
                "Manual A4 settings:",
                f"speed mm/min: {result.speed_mm_min:.3f}" if result.speed_mm_min is not None else "speed mm/min:",
                f"time sec: {result.duration_s:.1f}" if result.duration_s is not None else "time sec:",
                f"estimated volume uL: {result.estimated_volume_ul:.1f}"
                if result.estimated_volume_ul is not None
                else "estimated volume uL:",
                f"warning: {result.warning}" if result.warning else "",
                "",
                "Use Write settings to A4 to send these values.",
            ]
            self.profile_result_var.set("\n".join(line for line in lines if line != ""))
        except Exception as exc:
            self.profile_result_var.set(f"ERROR: {exc}")

    def write_profile_settings_async(self) -> None:
        try:
            self.apply_gui_pump_settings()
            profile_key = self.profile_var.get()
            pump_key = self.profile_write_pump_var.get()
            profile = dict(self.data["profiles"][profile_key])
            syringe_key = profile["syringe"]
            calc = calculate_profile(
                profile, self.data["syringes"][syringe_key], syringe_key
            )
            if calc.speed_mm_min is None or calc.duration_s is None:
                raise ValueError(f"profile {profile_key} does not provide speed/time settings")
            save = self.profile_save_after_write_var.get()
            start_after_write = self.profile_start_after_write_var.get()
            commands = format_settings_commands(calc.speed_mm_min, calc.duration_s, save=save)
            if start_after_write:
                commands.append(
                    "q6h3d" if profile.get("direction", "forward") == "reverse" else "q6h2d"
                )
            if not self.confirm_settings_write(
                calc.speed_mm_min,
                calc.duration_s,
                commands,
                start_after_write=start_after_write,
            ):
                return
            data = json.loads(json.dumps(self.data))
            context = {
                "dry_run": self.dry_run_var.get(),
                "dish_id": self.dish_id_var.get(),
                "condition": self.condition_var.get(),
                "trigger_source": "Manual",
            }
        except Exception as exc:
            messagebox.showerror("Profile write failed", str(exc))
            return
        if not self.begin_gui_operation("profile_write"):
            return

        def worker() -> None:
            try:
                results = write_profile(
                    data,
                    pump_key,
                    profile_key,
                    save=save,
                    start_after_write=start_after_write,
                    **context,
                )
                self.post_ui(self._serial_operation_succeeded, "profile_write", self.profile_log, results)
            except Exception as exc:
                self.post_ui(self._serial_operation_failed, "profile_write", "Profile write failed", str(exc))

        threading.Thread(target=worker, daemon=True, name="a4-profile-write").start()

    def write_calculated_settings_async(self) -> None:
        try:
            self.apply_gui_pump_settings()
            if self.last_calc_result is None:
                raise ValueError("Run Calculate before writing settings.")
            speed = self.last_calc_result.get("speed_mm_min")
            duration = self.last_calc_result.get("duration_s")
            if speed is None or duration is None:
                raise ValueError("calculation result does not include speed/time")
            save = self.calc_save_after_write_var.get()
            if not self.confirm_settings_write(
                float(speed),
                float(duration),
                format_settings_commands(float(speed), float(duration), save=save),
            ):
                return
            data = json.loads(json.dumps(self.data))
            pump_key = self.calc_write_pump_var.get()
            context = {
                "dry_run": self.dry_run_var.get(),
                "dish_id": self.dish_id_var.get(),
                "condition": self.condition_var.get(),
                "trigger_source": "Manual",
            }
        except Exception as exc:
            messagebox.showerror("Calculated write failed", str(exc))
            return
        if not self.begin_gui_operation("calculator_write"):
            return

        def worker() -> None:
            try:
                results = write_settings(
                    data,
                    pump_key,
                    float(speed),
                    float(duration),
                    save=save,
                    **context,
                )
                self.post_ui(self._serial_operation_succeeded, "calculator_write", self.pump_log, results)
            except Exception as exc:
                self.post_ui(self._serial_operation_failed, "calculator_write", "Calculated write failed", str(exc))

        threading.Thread(target=worker, daemon=True, name="a4-calculator-write").start()

    def _serial_operation_succeeded(
        self,
        name: str,
        log_box: tk.Text,
        result: Any,
    ) -> None:
        self.finish_gui_operation(name)
        self.append_log(log_box, json.dumps(result, ensure_ascii=False))
        self.set_status(f"{name.replace('_', ' ')} completed")

    def _serial_operation_failed(self, name: str, title: str, message: str) -> None:
        self.finish_gui_operation(name)
        messagebox.showerror(title, message)

    def write_profile_settings_gui(self, *, confirm: bool = True) -> list[dict[str, Any]] | None:
        self.apply_gui_pump_settings()
        profile_key = self.profile_var.get()
        profile = self.data["profiles"][profile_key]
        syringe_key = profile["syringe"]
        calc = calculate_profile(profile, self.data["syringes"][syringe_key], syringe_key)
        if calc.speed_mm_min is None or calc.duration_s is None:
            raise ValueError(f"profile {profile_key} does not provide speed/time settings")
        save = self.profile_save_after_write_var.get()
        start_after_write = self.profile_start_after_write_var.get()
        commands = format_settings_commands(calc.speed_mm_min, calc.duration_s, save=save)
        if start_after_write:
            commands.append("q6h3d" if profile.get("direction", "forward") == "reverse" else "q6h2d")
        if confirm and not self.confirm_settings_write(
            calc.speed_mm_min,
            calc.duration_s,
            commands,
            start_after_write=start_after_write,
        ):
            return None
        results = write_profile(
            self.data,
            self.profile_write_pump_var.get(),
            profile_key,
            save=save,
            start_after_write=start_after_write,
            dry_run=self.dry_run_var.get(),
            dish_id=self.dish_id_var.get(),
            condition=self.condition_var.get(),
            trigger_source="Manual",
        )
        self.append_log(self.profile_log, json.dumps(results, ensure_ascii=False))
        self.set_status("Profile settings write completed")
        return results

    def write_calculated_settings_gui(self, *, confirm: bool = True) -> list[dict[str, Any]] | None:
        self.apply_gui_pump_settings()
        if self.last_calc_result is None:
            messagebox.showerror("No calculated settings", "Run Calculate before writing settings.")
            return None
        speed = self.last_calc_result.get("speed_mm_min")
        duration = self.last_calc_result.get("duration_s")
        if speed is None or duration is None:
            raise ValueError("calculation result does not include speed_mm_min and duration_s")
        save = self.calc_save_after_write_var.get()
        commands = format_settings_commands(float(speed), float(duration), save=save)
        if confirm and not self.confirm_settings_write(float(speed), float(duration), commands):
            return None
        results = write_settings(
            self.data,
            self.calc_write_pump_var.get(),
            float(speed),
            float(duration),
            save=save,
            dry_run=self.dry_run_var.get(),
            dish_id=self.dish_id_var.get(),
            condition=self.condition_var.get(),
            trigger_source="Manual",
        )
        self.append_log(self.pump_log, json.dumps(results, ensure_ascii=False))
        self.set_status("Calculated settings write completed")
        return results

    def confirm_settings_write(
        self,
        speed_mm_min: float,
        duration_s: float,
        commands: list[str],
        *,
        start_after_write: bool = False,
    ) -> bool:
        seconds = int(round(duration_s))
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        secs = seconds % 60
        lines = []
        if start_after_write:
            lines.extend(["WARNING: Start after write is ON.", ""])
        lines.extend(
            [
                f"Speed: {speed_mm_min:.2f} mm/min",
                f"Time:  {hours:02d}:{minutes:02d}:{secs:02d}",
                "",
                "Commands:",
                *[f"  {command}" for command in commands],
            ]
        )
        text = "\n".join(lines)
        return messagebox.askokcancel("Write settings to A4", text)

    def gui_send(self, pump_key: str, action: str) -> None:
        self.apply_gui_pump_settings()
        result = send_action(
            self.data,
            pump_key,
            action,
            dry_run=self.dry_run_var.get(),
            dish_id=self.dish_id_var.get(),
            condition=self.condition_var.get(),
            trigger_source="Manual",
        )
        self.append_log(self.pump_log, json.dumps(result, ensure_ascii=False))
        self.set_status(f"{pump_key} {action}: {result.get('response', '')}")

    def gui_send_async(self, pump_key: str, action: str) -> None:
        try:
            self.apply_gui_pump_settings()
            data = json.loads(json.dumps(self.data))
            context = {
                "dry_run": self.dry_run_var.get(),
                "dish_id": self.dish_id_var.get(),
                "condition": self.condition_var.get(),
                "trigger_source": "Manual",
            }
        except Exception as exc:
            messagebox.showerror("Operation failed", str(exc))
            return
        operation_name = f"{pump_key.casefold()}_{action}"
        is_stop = action == "stop"
        if not is_stop and not self.begin_gui_operation(operation_name):
            return
        coordinator: OperationCoordinator | None = None
        token: RunToken | None = None
        if not is_stop and not context["dry_run"] and action.startswith("start-"):
            try:
                coordinator = OperationCoordinator(self.config_resolution)
                token = coordinator.begin_recipe(data, operation_type="manual_start")
            except Exception as exc:
                self.finish_gui_operation(operation_name)
                messagebox.showerror("Operation failed", str(exc))
                return

        def worker() -> None:
            try:
                if is_stop and not context["dry_run"]:
                    state = OperationCoordinator(self.config_resolution).emergency_stop(
                        metadata={"trigger_source": "Manual", "reason": f"{pump_key} stop"},
                        fallback_data=data,
                    )
                    result = {"response": state.get("state", ""), "state": state}
                elif coordinator is not None and token is not None:
                    pump = coordinator.pump_factory(pump_key, data["pumps"][pump_key])
                    result = coordinator.emit_start(
                        token,
                        pump_key,
                        pump,
                        "reverse" if action == "start-reverse" else "forward",
                    )
                else:
                    result = send_action(data, pump_key, action, **context)
                self.post_ui(
                    self._gui_send_succeeded,
                    pump_key,
                    action,
                    result,
                    operation_name if not is_stop else "",
                )
            except Exception as exc:
                self.post_ui(self._serial_operation_failed, operation_name, "Operation failed", str(exc))

        threading.Thread(target=worker, daemon=True, name=f"a4-{pump_key.casefold()}-{action}").start()

    def _gui_send_succeeded(
        self,
        pump_key: str,
        action: str,
        result: dict[str, Any],
        operation_name: str = "",
    ) -> None:
        if operation_name:
            self.finish_gui_operation(operation_name)
        self.append_log(self.pump_log, json.dumps(result, ensure_ascii=False))
        self.set_status(f"{pump_key} {action}: {result.get('response', '')}")

    def gui_stop_all_now(self) -> None:
        self.cancel_hold_auto_stop()
        self.cancel_jog_timer()
        self.set_jog_buttons_enabled(True)
        self._manual_active = False
        recipe_tab = getattr(self, "recipe_tab", None)
        if recipe_tab is not None and hasattr(recipe_tab, "cancel_execution"):
            recipe_tab.cancel_execution()
        commissioning_tab = getattr(self, "commissioning_tab", None)
        if commissioning_tab is not None and hasattr(commissioning_tab, "cancel_execution"):
            commissioning_tab.cancel_execution()
        if self._stop_in_flight:
            self.set_status("STOPPING — cancellation request already queued")
            return
        try:
            self.apply_gui_pump_settings()
        except Exception as exc:
            # Safety stop must remain usable while an edit field is incomplete.
            self.set_status(f"STOP ALL using last valid settings ({exc})")
        context = {
            "dry_run": self.dry_run_var.get(),
            "dish_id": self.dish_id_var.get(),
            "condition": self.condition_var.get(),
            "trigger_source": self.trigger_var.get(),
        }
        # STOP ALL bypasses the regular-operation guard and remains available.
        self._stop_in_flight = True
        self.set_operational_state("STOPPING")
        self.set_status("STOPPING — cancellation request queued")
        threading.Thread(
            target=self._stop_all_worker,
            args=(context,),
            daemon=True,
            name="a4-emergency-stop",
        ).start()

    def _stop_all_worker(self, context: dict[str, Any] | None = None) -> None:
        common = context or {
            "dry_run": False,
            "dish_id": "",
            "condition": "",
            "trigger_source": "GUI",
        }
        try:
            results = stop_all_safe(self.config_resolution, **common)
            self.post_ui(self._stop_all_succeeded, results)
        except Exception as exc:
            self.post_ui(self._stop_all_failed, str(exc))

    def _stop_all_succeeded(self, results: dict[str, Any]) -> None:
        self._stop_in_flight = False
        if self._closing:
            self._close_stop_result = results
            return
        self._active_operation = None
        self._manual_coordinator = None
        self._manual_token = None
        self.append_log(self.pump_log, json.dumps(results, ensure_ascii=False))
        self.append_log(self.run_log, json.dumps(results, ensure_ascii=False))
        state = str(results.get("state", "STOPPED"))
        self.set_operational_state(state)
        self.set_status("STOP ALL completed" if state == "STOPPED" else f"STOP ALL: {state}")

    def _stop_all_failed(self, message: str) -> None:
        self._stop_in_flight = False
        if self._closing:
            self._close_stop_error = message
            return
        self.set_status(f"STOP ALL failed: {message}")
        messagebox.showerror("STOP ALL failed", message)

    def start_run_mode(self) -> None:
        captured = self._capture_run_mode()
        result = self._execute_run_mode(*captured)
        self.append_log(self.run_log, json.dumps(result, ensure_ascii=False))
        self.set_status(f"Run mode completed: {captured[1]}")

    def start_run_mode_async(self) -> None:
        if self._operation_running:
            self.set_status("An experiment operation is already running")
            return
        try:
            captured = self._capture_run_mode()
        except Exception as exc:
            messagebox.showerror("Operation failed", str(exc))
            return
        self._operation_running = True

        def worker() -> None:
            try:
                result = self._execute_run_mode(*captured)
                self.post_ui(self._run_mode_succeeded, captured[1], result)
            except Exception as exc:
                self.post_ui(self._run_mode_failed, str(exc))

        threading.Thread(target=worker, daemon=True, name="a4-legacy-run-mode").start()

    def _capture_run_mode(self) -> tuple[dict[str, Any], str, str, str, float, dict[str, Any]]:
        self.apply_gui_pump_settings()
        mode = self.run_mode_var.get()
        self.require_out_enabled_for_mode(mode)
        common = {
            "dry_run": self.dry_run_var.get(),
            "dish_id": self.dish_id_var.get(),
            "condition": self.condition_var.get(),
            "trigger_source": self.trigger_var.get(),
        }
        return (
            json.loads(json.dumps(self.data)),
            mode,
            self.profile_in_var.get(),
            self.profile_out_var.get(),
            float(self.out_delay_var.get()),
            common,
        )

    @staticmethod
    def _execute_run_mode(
        data: dict[str, Any],
        mode: str,
        profile_in: str,
        profile_out: str,
        out_delay: float,
        common: dict[str, Any],
    ) -> Any:
        if mode == "IN only":
            result: Any = run_profile(data, "IN", profile_in, **common)
        elif mode == "OUT only":
            result = run_profile(data, "OUT", profile_out, **common)
        elif mode == "Push-pull":
            result = pushpull(
                data,
                in_pump="IN",
                out_pump="OUT",
                profile_in=profile_in,
                profile_out=profile_out,
                out_delay=out_delay,
                **common,
            )
        elif mode == "Two forward":
            result = [
                run_profile(data, "IN", profile_in, **common),
                send_action(
                    data,
                    "OUT",
                    "start-forward",
                    profile_key=profile_out,
                    profile_calc={},
                    **common,
                ),
            ]
        else:
            raise ValueError(f"Unknown mode: {mode}")
        return result

    def _run_mode_succeeded(self, mode: str, result: Any) -> None:
        self._operation_running = False
        self.append_log(self.run_log, json.dumps(result, ensure_ascii=False))
        self.set_status(f"Run mode completed: {mode}")

    def _run_mode_failed(self, message: str) -> None:
        self._operation_running = False
        messagebox.showerror("Operation failed", message)

    def apply_gui_pump_settings(self) -> None:
        values = validate_pump_settings(
            in_port=self.port_vars["IN"].get(),
            out_enabled=self.out_enabled_var.get(),
            out_port=self.port_vars["OUT"].get(),
            baudrate=self.baudrate_var.get(),
            terminator=self.terminator_var.get(),
            timeout=self.timeout_var.get(),
        )
        self.data["pumps"]["IN"]["enabled"] = True
        self.data["pumps"]["IN"]["port"] = values["in_port"]
        self.data["pumps"]["IN"]["baudrate"] = values["baudrate"]
        self.data["pumps"]["IN"]["terminator"] = values["terminator"]
        self.data["pumps"]["IN"]["timeout"] = values["timeout"]
        self.data["pumps"]["IN"].setdefault("commands", DEFAULT_COMMANDS.copy())

        if "OUT" in self.data["pumps"]:
            self.data["pumps"]["OUT"]["enabled"] = values["out_enabled"]
            self.data["pumps"]["OUT"]["port"] = values["out_port"]
            self.data["pumps"]["OUT"]["baudrate"] = values["baudrate"]
            self.data["pumps"]["OUT"]["terminator"] = values["terminator"]
            self.data["pumps"]["OUT"]["timeout"] = values["timeout"]
            self.data["pumps"]["OUT"].setdefault("commands", DEFAULT_COMMANDS.copy())
        self.port_vars["IN"].set(values["in_port"])
        self.port_vars["OUT"].set(values["out_port"])
        self.terminator_var.set(values["terminator"])

    def run_thread(self, func: Callable[..., None], *args: Any) -> None:
        guarded = func in {self.start_run_mode, self.write_experiment_profiles}
        if guarded and self._operation_running:
            self.set_status("An experiment operation is already running")
            return
        if guarded:
            self._operation_running = True
            if hasattr(self, "experiment_start_button"):
                self.experiment_start_button.configure(state="disabled")

        def worker() -> None:
            try:
                func(*args)
            except Exception as exc:
                message = str(exc)
                self.post_ui(messagebox.showerror, "Operation failed", message)
            finally:
                if guarded:
                    def finish() -> None:
                        self._operation_running = False
                        if hasattr(self, "experiment_start_button"):
                            self.experiment_start_button.configure(state="normal")

                    self.post_ui(finish)

        threading.Thread(target=worker, daemon=True).start()

    def append_log(self, box: tk.Text, text: str) -> None:
        def update() -> None:
            box.insert("end", text + "\n")
            box.see("end")

        if threading.current_thread() is threading.main_thread():
            update()
        else:
            self.post_ui(update)

    @staticmethod
    def float_or_none(value: str) -> float | None:
        stripped = value.strip()
        return None if stripped == "" else float(stripped)

    @staticmethod
    def parse_ms(value: str, *, minimum: int, maximum: int) -> int:
        duration_ms = int(value.strip())
        if duration_ms < minimum or duration_ms > maximum:
            raise ValueError(f"value must be between {minimum} and {maximum} ms")
        return duration_ms

    @staticmethod
    def format_result(result: dict[str, Any]) -> str:
        lines = []
        for key in [
            "required_travel_mm",
            "speed_mm_min",
            "duration_s",
            "estimated_volume_ul",
            "target_volume_ul",
            "warning",
        ]:
            value = result.get(key)
            if value not in (None, ""):
                if isinstance(value, float):
                    lines.append(f"{key}: {value:.3f}")
                else:
                    lines.append(f"{key}: {value}")
        return "\n".join(lines)


def main() -> None:
    app = A4PumpApp()
    app.mainloop()


if __name__ == "__main__":
    main()
