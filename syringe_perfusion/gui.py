from __future__ import annotations

import json
import threading
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any, Callable

from .a4 import DEFAULT_COMMANDS, format_settings_commands, list_serial_ports
from .cli import pushpull, run_profile, send_action, stop_all, write_profile, write_settings
from .config import load_config
from .gui_recipe import RecipeBuilderFrame
from .profiles import calculate, calculate_profile, result_to_dict, ul_per_mm_from_inner_diameter
from .ui_theme import apply_theme, create_card, status_badge


TRIGGER_SOURCES = ["Manual", "Foot pedal comparable", "NIS", "TTL"]
RUN_MODES = ["IN only", "OUT only", "Push-pull", "Two forward"]


class A4PumpApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("A4 Syringe Pump Control")
        self.geometry("1180x760")
        self.minsize(1040, 680)
        self.style = apply_theme(self)
        self.data = load_config()
        self.ensure_gui_pump_defaults()

        self.port_vars = {
            "IN": tk.StringVar(value=self.data["pumps"]["IN"]["port"]),
            "OUT": tk.StringVar(value=self.data["pumps"].get("OUT", {}).get("port", "")),
        }
        self.terminator_var = tk.StringVar(value=self.data["pumps"]["IN"].get("terminator", "\\r\\n"))
        self.dry_run_var = tk.BooleanVar(value=True)
        self.out_enabled_var = tk.BooleanVar(value=self.data["pumps"].get("OUT", {}).get("enabled", False))
        self.manual_pump_var = tk.StringVar(value="IN")
        self.jog_duration_var = tk.StringVar(value="1000")
        self.hold_auto_stop_ms_var = tk.StringVar(value="4000")
        self._manual_active = False
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
        self.page_title_var = tk.StringVar(value="Dashboard")
        self.page_subtitle_var = tk.StringVar(value="Ready")
        self.status_var = tk.StringVar(value="Ready")
        self.nav_buttons: dict[str, ttk.Button] = {}
        self.pages: dict[str, tk.Widget] = {}

        self._build()
        self.bind_all("<Escape>", self.on_escape_stop)
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.update_out_widgets_state()
        self.update_run_mode_options()
        self.update_manual_pump_options()
        self.update_syringe_info()
        self.update_profile_info()

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

        dashboard_tab = ttk.Frame(self.notebook, style="Page.TFrame", padding=0)
        pump_tab = ttk.Frame(self.notebook, style="Page.TFrame", padding=0)
        run_tab = ttk.Frame(self.notebook, style="Page.TFrame", padding=0)
        profile_tab = ttk.Frame(self.notebook, style="Page.TFrame", padding=0)
        calc_tab = ttk.Frame(self.notebook, style="Page.TFrame", padding=0)
        self.recipe_tab = RecipeBuilderFrame(self.notebook, self)

        self.pages = {
            "dashboard": dashboard_tab,
            "pumps": pump_tab,
            "run": run_tab,
            "profiles": profile_tab,
            "calculator": calc_tab,
            "recipes": self.recipe_tab,
        }
        for key, page in self.pages.items():
            self.notebook.add(page, text=key)

        self._build_dashboard_tab(dashboard_tab)
        self._build_pump_tab(pump_tab)
        self._build_run_tab(run_tab)
        self._build_profile_tab(profile_tab)
        self._build_calc_tab(calc_tab)

        status = ttk.Frame(self, style="Toolbar.TFrame", padding=(16, 8))
        status.grid(row=1, column=0, columnspan=2, sticky="ew")
        status.columnconfigure(0, weight=1)
        ttk.Label(status, textvariable=self.status_var, style="Card.TLabel").grid(row=0, column=0, sticky="w")

        self.select_page("dashboard")

    def _build_sidebar(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        ttk.Label(parent, text="A4 Pump", style="SectionTitle.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 2))
        ttk.Label(parent, text="V3.0", style="Subtitle.TLabel").grid(row=1, column=0, sticky="w", pady=(0, 16))
        items = [
            ("dashboard", "Dashboard"),
            ("pumps", "Pumps"),
            ("run", "Run"),
            ("profiles", "Profiles"),
            ("calculator", "Calculator"),
            ("recipes", "Recipes"),
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
            "dashboard": ("Dashboard", "Connection and run summary"),
            "pumps": ("Pumps", "Ports, manual controls, jog, and STOP ALL"),
            "run": ("Run", "Start saved profiles and coordinated pump modes"),
            "profiles": ("Profiles", "Preview and write A4 speed/time settings"),
            "calculator": ("Calculator", "Calculate volume, speed, time, and write settings"),
            "recipes": ("Recipes", "Build and run repeatable V2 recipes"),
        }
        title, subtitle = titles[page]
        self.page_title_var.set(title)
        self.page_subtitle_var.set(subtitle)
        for key, button in self.nav_buttons.items():
            button.configure(style="NavSelected.TButton" if key == page else "Nav.TButton")
        self.set_status(f"Ready - {title}")

    def set_status(self, message: str) -> None:
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

    def _build_dashboard_tab(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        parent.columnconfigure(1, weight=1)
        pump_card = create_card(parent, "Connection", "Active pump configuration and dry-run state.")
        pump_card.grid(row=0, column=0, sticky="nsew", padx=(0, 8), pady=(0, 12))
        self.dashboard_connection_var = tk.StringVar(value="")
        ttk.Label(pump_card, textvariable=self.dashboard_connection_var, style="Value.TLabel").grid(
            row=2, column=0, sticky="w", pady=(10, 0)
        )
        action_card = create_card(parent, "Quick actions", "Common safety operations.")
        action_card.grid(row=0, column=1, sticky="nsew", padx=(8, 0), pady=(0, 12))
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
        ttk.Checkbutton(safety, text="Dry-run", variable=self.dry_run_var, style="Card.TCheckbutton", command=lambda: self.set_status("Dry-run updated")).grid(
            row=2, column=0, sticky="w", pady=(8, 0)
        )
        ttk.Button(safety, text="STOP ALL", style="Danger.TButton", takefocus=False, command=self.gui_stop_all_now).grid(
            row=2, column=1, sticky="ew", pady=(8, 0)
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
        baud_label = ttk.Label(card, text="Baudrate", style="Card.TLabel")
        baud_label.grid(row=5, column=0, sticky="w", padx=4, pady=4)
        baud_value = ttk.Label(card, text="9600", style="Value.TLabel")
        baud_value.grid(row=5, column=1, sticky="w", padx=4, pady=4)
        test_button = ttk.Button(card, text="Connection test", style="Secondary.TButton", takefocus=False, command=self.connection_test)
        test_button.grid(
            row=6, column=0, columnspan=3, sticky="ew", padx=4, pady=(8, 4)
        )
        if pump_key == "OUT":
            self.out_detail_widgets.extend([baud_label, baud_value, test_button])
        if pump_key == "IN":
            ttk.Button(card, text="Start forward", style="Primary.TButton", takefocus=False, command=lambda: self.run_thread(self.gui_send, "IN", "start-forward")).grid(
                row=7, column=0, sticky="ew", padx=4, pady=4
            )
            ttk.Button(card, text="Stop", style="DangerSecondary.TButton", takefocus=False, command=lambda: self.run_thread(self.gui_send, "IN", "stop")).grid(
                row=7, column=1, columnspan=2, sticky="ew", padx=4, pady=4
            )
        else:
            self.out_start_forward_button = ttk.Button(card, text="Start forward", style="Primary.TButton", takefocus=False, command=lambda: self.run_thread(self.gui_send, "OUT", "start-forward"))
            self.out_start_forward_button.grid(row=7, column=0, sticky="ew", padx=4, pady=4)
            self.out_start_reverse_button = ttk.Button(card, text="Start reverse", style="Primary.TButton", takefocus=False, command=lambda: self.run_thread(self.gui_send, "OUT", "start-reverse"))
            self.out_start_reverse_button.grid(row=7, column=1, sticky="ew", padx=4, pady=4)
            self.out_stop_button = ttk.Button(card, text="Stop", style="DangerSecondary.TButton", takefocus=False, command=lambda: self.run_thread(self.gui_send, "OUT", "stop"))
            self.out_stop_button.grid(row=7, column=2, sticky="ew", padx=4, pady=4)
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
        syringe_combo = ttk.Combobox(parent, textvariable=self.syringe_var, values=syringe_keys, state="readonly")
        syringe_combo = ttk.Combobox(input_card, textvariable=self.syringe_var, values=syringe_keys, state="readonly")
        syringe_combo.grid(row=2, column=1, sticky="ew", pady=4)
        syringe_combo.bind("<<ComboboxSelected>>", lambda _e: self.update_syringe_info())

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
            command=self.write_calculated_settings_gui,
        )
        self.calc_write_button.grid(
            row=2, column=3, sticky="ew", padx=4, pady=4
        )
        self.calc_write_button.configure(state="disabled")

    def _build_profile_tab(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        parent.columnconfigure(1, weight=1)
        profile_keys = ["fast30_1ml", "fast20_1ml", "gentle60_1ml", "gentle120_1ml", "drain30_1ml"]
        select_card = create_card(parent, "Profile selection", "Choose a saved profile and preview calculated A4 settings.")
        select_card.grid(row=0, column=0, sticky="nsew", padx=(0, 8), pady=(0, 12))
        select_card.columnconfigure(1, weight=1)
        preview_card = create_card(parent, "Calculated settings preview", "Commands are lowercase and terminated with CRLF.")
        preview_card.grid(row=0, column=1, sticky="nsew", padx=(8, 0), pady=(0, 12))
        preview_card.columnconfigure(0, weight=1)

        ttk.Label(select_card, text="Profile preset", style="Card.TLabel").grid(row=2, column=0, sticky="w", pady=4)
        profile_combo = ttk.Combobox(parent, textvariable=self.profile_var, values=profile_keys, state="readonly")
        profile_combo = ttk.Combobox(select_card, textvariable=self.profile_var, values=profile_keys, state="readonly")
        profile_combo.grid(row=2, column=1, sticky="ew", pady=4)
        profile_combo.bind("<<ComboboxSelected>>", lambda _e: self.update_profile_info())

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
            command=self.write_profile_settings_gui,
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
        ttk.Button(actions, text="Start", style="Primary.TButton", takefocus=False, command=lambda: self.run_thread(self.start_run_mode)).grid(
            row=2, column=0, sticky="ew", padx=(0, 6), pady=(8, 0)
        )
        ttk.Button(actions, text="STOP ALL", style="Danger.TButton", takefocus=False, command=self.gui_stop_all_now).grid(
            row=2, column=1, sticky="ew", padx=(6, 0), pady=(8, 0)
        )
        self.run_log = self._make_log_box(parent, row=2, columnspan=2)

    def _make_log_box(self, parent: ttk.Frame, *, row: int, columnspan: int) -> tk.Text:
        parent.rowconfigure(row, weight=1)
        box = tk.Text(
            parent,
            height=10,
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
        try:
            ports = [port["device"] for port in list_serial_ports()]
        except Exception as exc:
            messagebox.showerror("List ports failed", str(exc))
            return
        values = ports or [value for value in [self.port_vars["IN"].get(), self.port_vars["OUT"].get()] if value]
        self.in_port_combo.configure(values=values)
        self.out_port_combo.configure(values=values)
        self.append_log(self.pump_log, f"Ports: {', '.join(values)}")

    def connection_test(self) -> None:
        if self.dry_run_var.get():
            self.append_log(self.pump_log, "Connection test: dry-run enabled")
            return
        try:
            import serial

            self.apply_gui_pump_settings()
            for pump_key in self.available_pumps():
                cfg = self.data["pumps"][pump_key]
                if not str(cfg.get("port", "")).strip():
                    raise ValueError(f"{pump_key} port is blank")
                with serial.Serial(cfg["port"], cfg.get("baudrate", 9600), timeout=1):
                    pass
                self.append_log(self.pump_log, f"{pump_key}: opened and closed {cfg['port']}")
        except Exception as exc:
            messagebox.showerror("Connection test failed", str(exc))

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
        result = send_action(
            self.data,
            pump_key,
            action,
            dry_run=self.dry_run_var.get(),
            dish_id=self.dish_id_var.get(),
            condition=self.condition_var.get(),
            trigger_source="Manual",
            mode=mode,
            jog_duration_ms=jog_duration_ms,
        )
        self.append_log(self.pump_log, json.dumps(result, ensure_ascii=False))
        self.set_status(f"{pump_key} {action}: {mode}")

    def on_escape_stop(self, _event: tk.Event[Any] | None = None) -> str:
        self.gui_stop_all_now()
        return "break"

    def on_close(self) -> None:
        self.cancel_hold_auto_stop()
        self.cancel_jog_timer()
        try:
            self.apply_gui_pump_settings()
            results = stop_all(
                self.data,
                dry_run=self.dry_run_var.get(),
                dish_id=self.dish_id_var.get(),
                condition=self.condition_var.get(),
                trigger_source="Manual",
                note="WM_DELETE_WINDOW",
            )
            self.pump_log.insert("end", json.dumps(results, ensure_ascii=False) + "\n")
        except Exception as exc:
            try:
                self.pump_log.insert("end", f"Close stop_all failed: {exc}\n")
            except Exception:
                pass
            print(f"Close stop_all failed: {exc}")
        finally:
            self.destroy()

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

    def gui_stop_all_now(self) -> None:
        self.cancel_hold_auto_stop()
        self.cancel_jog_timer()
        self.set_jog_buttons_enabled(True)
        self._manual_active = False
        self.run_thread(self._stop_all_worker)

    def _stop_all_worker(self) -> None:
        self.apply_gui_pump_settings()
        results = stop_all(
            self.data,
            dry_run=self.dry_run_var.get(),
            dish_id=self.dish_id_var.get(),
            condition=self.condition_var.get(),
            trigger_source=self.trigger_var.get(),
        )
        self.append_log(self.pump_log, json.dumps(results, ensure_ascii=False))
        self.append_log(self.run_log, json.dumps(results, ensure_ascii=False))
        self.set_status("STOP ALL sent")

    def start_run_mode(self) -> None:
        self.apply_gui_pump_settings()
        mode = self.run_mode_var.get()
        self.require_out_enabled_for_mode(mode)
        common = {
            "dry_run": self.dry_run_var.get(),
            "dish_id": self.dish_id_var.get(),
            "condition": self.condition_var.get(),
            "trigger_source": self.trigger_var.get(),
        }
        if mode == "IN only":
            result: Any = run_profile(self.data, "IN", self.profile_in_var.get(), **common)
        elif mode == "OUT only":
            result = run_profile(self.data, "OUT", self.profile_out_var.get(), **common)
        elif mode == "Push-pull":
            result = pushpull(
                self.data,
                in_pump="IN",
                out_pump="OUT",
                profile_in=self.profile_in_var.get(),
                profile_out=self.profile_out_var.get(),
                out_delay=float(self.out_delay_var.get()),
                **common,
            )
        elif mode == "Two forward":
            result = [
                run_profile(self.data, "IN", self.profile_in_var.get(), **common),
                send_action(
                    self.data,
                    "OUT",
                    "start-forward",
                    profile_key=self.profile_out_var.get(),
                    profile_calc={},
                    **common,
                ),
            ]
        else:
            raise ValueError(f"Unknown mode: {mode}")
        self.append_log(self.run_log, json.dumps(result, ensure_ascii=False))
        self.set_status(f"Run mode completed: {mode}")

    def apply_gui_pump_settings(self) -> None:
        in_port = self.port_vars["IN"].get().strip()
        if not in_port:
            raise ValueError("IN port is required")
        self.data["pumps"]["IN"]["enabled"] = True
        self.data["pumps"]["IN"]["port"] = in_port
        self.data["pumps"]["IN"]["terminator"] = "\\r\\n"
        self.data["pumps"]["IN"].setdefault("commands", DEFAULT_COMMANDS.copy())

        if "OUT" in self.data["pumps"]:
            out_enabled = self.out_enabled_var.get()
            out_port = self.port_vars["OUT"].get().strip()
            self.data["pumps"]["OUT"]["enabled"] = out_enabled
            self.data["pumps"]["OUT"]["port"] = out_port
            self.data["pumps"]["OUT"]["terminator"] = "\\r\\n"
            self.data["pumps"]["OUT"].setdefault("commands", DEFAULT_COMMANDS.copy())
            if out_enabled and not out_port:
                raise ValueError("OUT port is required when OUT pump is enabled")
        self.terminator_var.set("\\r\\n")

    def run_thread(self, func: Callable[..., None], *args: Any) -> None:
        def worker() -> None:
            try:
                func(*args)
            except Exception as exc:
                message = str(exc)
                self.after(0, lambda: messagebox.showerror("Operation failed", message))

        threading.Thread(target=worker, daemon=True).start()

    def append_log(self, box: tk.Text, text: str) -> None:
        def update() -> None:
            box.insert("end", text + "\n")
            box.see("end")

        self.after(0, update)

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
