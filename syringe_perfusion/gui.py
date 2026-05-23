from __future__ import annotations

import json
import threading
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any, Callable

from .a4 import list_serial_ports
from .cli import pushpull, run_profile, send_action, stop_all
from .config import load_config
from .gui_recipe import RecipeBuilderFrame
from .profiles import calculate, calculate_profile, result_to_dict, ul_per_mm_from_inner_diameter


TERMINATORS = ["", "\\r", "\\n", "\\r\\n"]
TRIGGER_SOURCES = ["Manual", "Foot pedal comparable", "NIS", "TTL"]
RUN_MODES = ["IN only", "OUT only", "Push-pull", "Two forward"]


class A4PumpApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("A4 Syringe Pump Control")
        self.geometry("980x720")
        self.minsize(860, 620)
        self.data = load_config()

        self.port_vars = {
            "IN": tk.StringVar(value=self.data["pumps"]["IN"]["port"]),
            "OUT": tk.StringVar(value=self.data["pumps"]["OUT"]["port"]),
        }
        self.terminator_var = tk.StringVar(value=self.data["pumps"]["IN"].get("terminator", "\\r\\n"))
        self.dry_run_var = tk.BooleanVar(value=True)

        self.syringe_var = tk.StringVar(value="terumo_ss05lz_5ml")
        self.calc_mode_var = tk.StringVar(value="volume_duration")
        self.volume_var = tk.StringVar(value="1000")
        self.duration_var = tk.StringVar(value="30")
        self.flow_var = tk.StringVar(value="2.0")
        self.speed_var = tk.StringVar(value="15.37")
        self.calc_result_var = tk.StringVar(value="")

        self.profile_var = tk.StringVar(value="fast30_1ml")
        self.profile_result_var = tk.StringVar(value="")

        self.dish_id_var = tk.StringVar(value="")
        self.condition_var = tk.StringVar(value="")
        self.trigger_var = tk.StringVar(value="Manual")
        self.run_mode_var = tk.StringVar(value="IN only")
        self.profile_in_var = tk.StringVar(value="fast30_1ml")
        self.profile_out_var = tk.StringVar(value="drain30_1ml")
        self.out_delay_var = tk.StringVar(value="0.5")

        self._build()
        self.update_syringe_info()
        self.update_profile_info()

    def _build(self) -> None:
        tabs = ttk.Notebook(self)
        tabs.pack(fill="both", expand=True, padx=10, pady=10)

        pump_tab = ttk.Frame(tabs, padding=12)
        calc_tab = ttk.Frame(tabs, padding=12)
        profile_tab = ttk.Frame(tabs, padding=12)
        run_tab = ttk.Frame(tabs, padding=12)
        recipe_tab = RecipeBuilderFrame(tabs, self)
        tabs.add(pump_tab, text="Pump")
        tabs.add(calc_tab, text="Syringe / Calculator")
        tabs.add(profile_tab, text="Profile")
        tabs.add(run_tab, text="Run")
        tabs.add(recipe_tab, text="Recipe Builder")

        self._build_pump_tab(pump_tab)
        self._build_calc_tab(calc_tab)
        self._build_profile_tab(profile_tab)
        self._build_run_tab(run_tab)

    def _build_pump_tab(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(1, weight=1)
        ports = [self.port_vars["IN"].get(), self.port_vars["OUT"].get()]

        ttk.Label(parent, text="Pump IN COM").grid(row=0, column=0, sticky="w", pady=4)
        self.in_port_combo = ttk.Combobox(parent, textvariable=self.port_vars["IN"], values=ports)
        self.in_port_combo.grid(row=0, column=1, sticky="ew", pady=4)

        ttk.Label(parent, text="Pump OUT COM").grid(row=1, column=0, sticky="w", pady=4)
        self.out_port_combo = ttk.Combobox(parent, textvariable=self.port_vars["OUT"], values=ports)
        self.out_port_combo.grid(row=1, column=1, sticky="ew", pady=4)

        ttk.Label(parent, text="Baudrate").grid(row=2, column=0, sticky="w", pady=4)
        ttk.Label(parent, text="9600").grid(row=2, column=1, sticky="w", pady=4)

        ttk.Label(parent, text="Terminator").grid(row=3, column=0, sticky="w", pady=4)
        ttk.Combobox(parent, textvariable=self.terminator_var, values=TERMINATORS, state="readonly").grid(
            row=3, column=1, sticky="w", pady=4
        )

        ttk.Checkbutton(parent, text="Dry-run", variable=self.dry_run_var).grid(row=4, column=1, sticky="w", pady=4)

        button_row = ttk.Frame(parent)
        button_row.grid(row=5, column=0, columnspan=2, sticky="ew", pady=10)
        ttk.Button(button_row, text="List ports", command=self.refresh_ports).pack(side="left", padx=(0, 8))
        ttk.Button(button_row, text="Connection test", command=self.connection_test).pack(side="left")

        actions = ttk.LabelFrame(parent, text="Commands", padding=10)
        actions.grid(row=6, column=0, columnspan=2, sticky="ew", pady=8)
        for col in range(3):
            actions.columnconfigure(col, weight=1)
        ttk.Button(actions, text="IN start forward", command=lambda: self.run_thread(self.gui_send, "IN", "start-forward")).grid(
            row=0, column=0, sticky="ew", padx=4, pady=4
        )
        ttk.Button(actions, text="IN stop", command=lambda: self.run_thread(self.gui_send, "IN", "stop")).grid(
            row=0, column=1, sticky="ew", padx=4, pady=4
        )
        ttk.Button(actions, text="OUT start forward", command=lambda: self.run_thread(self.gui_send, "OUT", "start-forward")).grid(
            row=1, column=0, sticky="ew", padx=4, pady=4
        )
        ttk.Button(actions, text="OUT start reverse", command=lambda: self.run_thread(self.gui_send, "OUT", "start-reverse")).grid(
            row=1, column=1, sticky="ew", padx=4, pady=4
        )
        ttk.Button(actions, text="OUT stop", command=lambda: self.run_thread(self.gui_send, "OUT", "stop")).grid(
            row=1, column=2, sticky="ew", padx=4, pady=4
        )

        stop_button = tk.Button(parent, text="STOP ALL", bg="#b00020", fg="white", height=2, command=self.gui_stop_all_now)
        stop_button.grid(row=7, column=0, columnspan=2, sticky="ew", pady=12)

        self.pump_log = self._make_log_box(parent, row=8, columnspan=2)

    def _build_calc_tab(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(1, weight=1)
        syringe_keys = list(self.data["syringes"])
        ttk.Label(parent, text="Syringe preset").grid(row=0, column=0, sticky="w", pady=4)
        syringe_combo = ttk.Combobox(parent, textvariable=self.syringe_var, values=syringe_keys, state="readonly")
        syringe_combo.grid(row=0, column=1, sticky="ew", pady=4)
        syringe_combo.bind("<<ComboboxSelected>>", lambda _e: self.update_syringe_info())

        self.syringe_info = ttk.Label(parent, text="", justify="left")
        self.syringe_info.grid(row=1, column=0, columnspan=2, sticky="w", pady=4)

        ttk.Label(parent, text="Input mode").grid(row=2, column=0, sticky="w", pady=4)
        ttk.Combobox(
            parent,
            textvariable=self.calc_mode_var,
            values=["volume_duration", "volume_flow", "speed_duration"],
            state="readonly",
        ).grid(row=2, column=1, sticky="w", pady=4)

        fields = [
            ("Target volume uL", self.volume_var),
            ("Duration sec", self.duration_var),
            ("Flow mL/min", self.flow_var),
            ("Speed mm/min", self.speed_var),
        ]
        for idx, (label, var) in enumerate(fields, start=3):
            ttk.Label(parent, text=label).grid(row=idx, column=0, sticky="w", pady=4)
            ttk.Entry(parent, textvariable=var).grid(row=idx, column=1, sticky="ew", pady=4)

        ttk.Button(parent, text="Calculate", command=self.calculate_gui).grid(row=7, column=1, sticky="e", pady=8)
        ttk.Label(parent, textvariable=self.calc_result_var, justify="left").grid(
            row=8, column=0, columnspan=2, sticky="nw", pady=8
        )

    def _build_profile_tab(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(1, weight=1)
        profile_keys = ["fast30_1ml", "fast20_1ml", "gentle60_1ml", "gentle120_1ml", "drain30_1ml"]
        ttk.Label(parent, text="Profile preset").grid(row=0, column=0, sticky="w", pady=4)
        profile_combo = ttk.Combobox(parent, textvariable=self.profile_var, values=profile_keys, state="readonly")
        profile_combo.grid(row=0, column=1, sticky="ew", pady=4)
        profile_combo.bind("<<ComboboxSelected>>", lambda _e: self.update_profile_info())

        ttk.Label(parent, textvariable=self.profile_result_var, justify="left").grid(
            row=1, column=0, columnspan=2, sticky="nw", pady=8
        )
        # Future extension: enable this only after A4 Q1H..Q6H1D setting commands are confirmed.
        ttk.Button(parent, text="Write settings to A4", state="disabled").grid(row=2, column=1, sticky="e", pady=8)

    def _build_run_tab(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(1, weight=1)
        rows = [
            ("Dish ID", ttk.Entry(parent, textvariable=self.dish_id_var)),
            ("Condition", ttk.Entry(parent, textvariable=self.condition_var)),
            ("Trigger source", ttk.Combobox(parent, textvariable=self.trigger_var, values=TRIGGER_SOURCES, state="readonly")),
            ("Mode", ttk.Combobox(parent, textvariable=self.run_mode_var, values=RUN_MODES, state="readonly")),
            ("Profile IN", ttk.Combobox(parent, textvariable=self.profile_in_var, values=list(self.data["profiles"]), state="readonly")),
            ("Profile OUT", ttk.Combobox(parent, textvariable=self.profile_out_var, values=list(self.data["profiles"]), state="readonly")),
            ("Out delay sec", ttk.Entry(parent, textvariable=self.out_delay_var)),
        ]
        for idx, (label, widget) in enumerate(rows):
            ttk.Label(parent, text=label).grid(row=idx, column=0, sticky="w", pady=4)
            widget.grid(row=idx, column=1, sticky="ew", pady=4)

        button_row = ttk.Frame(parent)
        button_row.grid(row=7, column=0, columnspan=2, sticky="ew", pady=8)
        ttk.Button(button_row, text="Start", command=lambda: self.run_thread(self.start_run_mode)).pack(side="left")
        tk.Button(button_row, text="Stop all", bg="#b00020", fg="white", command=self.gui_stop_all_now).pack(
            side="left", padx=8
        )
        self.run_log = self._make_log_box(parent, row=8, columnspan=2)

    def _make_log_box(self, parent: ttk.Frame, *, row: int, columnspan: int) -> tk.Text:
        parent.rowconfigure(row, weight=1)
        box = tk.Text(parent, height=12, wrap="word")
        box.grid(row=row, column=0, columnspan=columnspan, sticky="nsew", pady=8)
        return box

    def refresh_ports(self) -> None:
        try:
            ports = [port["device"] for port in list_serial_ports()]
        except Exception as exc:
            messagebox.showerror("List ports failed", str(exc))
            return
        values = ports or [self.port_vars["IN"].get(), self.port_vars["OUT"].get()]
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
            for pump_key in ["IN", "OUT"]:
                cfg = self.data["pumps"][pump_key]
                with serial.Serial(cfg["port"], cfg.get("baudrate", 9600), timeout=1):
                    pass
                self.append_log(self.pump_log, f"{pump_key}: opened and closed {cfg['port']}")
        except Exception as exc:
            messagebox.showerror("Connection test failed", str(exc))

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
            self.calc_result_var.set(self.format_result(result_to_dict(result)))
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
                "Initial version does not write speed/time settings to A4.",
            ]
            self.profile_result_var.set("\n".join(line for line in lines if line != ""))
        except Exception as exc:
            self.profile_result_var.set(f"ERROR: {exc}")

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

    def gui_stop_all_now(self) -> None:
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

    def start_run_mode(self) -> None:
        self.apply_gui_pump_settings()
        mode = self.run_mode_var.get()
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

    def apply_gui_pump_settings(self) -> None:
        for pump_key, var in self.port_vars.items():
            self.data["pumps"][pump_key]["port"] = var.get()
            self.data["pumps"][pump_key]["terminator"] = self.terminator_var.get()

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
