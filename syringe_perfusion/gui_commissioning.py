from __future__ import annotations

import json
import os
import threading
import tkinter as tk
from pathlib import Path
from threading import Event
from tkinter import filedialog, messagebox, simpledialog, ttk
from typing import Any

from .app_info import format_build_identity, get_build_info
from .calibration import (
    apply_syringe_calibration,
    balance_result,
    calculate_replicate,
    calibration_statistics,
    direct_volume_ul,
    exclude_replicate,
    gravimetric_volume_ul,
)
from .commissioning import (
    MANUAL_CONFIRMATION,
    MEASURED_RESULT,
    CommissioningService,
    commissioning_flow_points,
    make_test_result,
    probable_identity_matches,
)
from .coordinator import OperationCoordinator
from .config import load_config
from .flow_control import calibrated_ul_per_mm
from .perfusion_state import now_iso
from .ui_theme import create_card
from .validation_store import ValidationStore


class CommissioningFrame(ttk.Frame):
    """Setup subpage for bounded hardware checks and evidence entry."""

    def __init__(self, parent: tk.Widget, app: Any) -> None:
        super().__init__(parent)
        self.app = app
        self.store = ValidationStore(app.config_resolution)
        self.cancel_event = Event()
        self.operator_var = tk.StringVar(value=os.environ.get("USERNAME", ""))
        self.note_var = tk.StringVar(value="")
        self.progress_var = tk.StringVar(value="No commissioning record")
        self.direction_duration_var = tk.StringVar(value="750")
        self.rehearsal_delay_var = tk.StringVar(value="5")
        self.measurement_role_var = tk.StringVar(value="IN")
        self.measurement_method_var = tk.StringVar(value="direct_volume")
        self.measured_volume_var = tk.StringVar(value="")
        self.volume_unit_var = tk.StringVar(value="mL")
        self.initial_mass_var = tk.StringVar(value="")
        self.final_mass_var = tk.StringVar(value="")
        self.mass_unit_var = tk.StringVar(value="g")
        self.density_var = tk.StringVar(value="0.998")
        self.requested_flow_var = tk.StringVar(value="1.0")
        self.programmed_speed_var = tk.StringVar(value="7.67")
        self.programmed_duration_var = tk.StringVar(value="60")
        self.minimum_replicates_var = tk.StringVar(value="3")
        self.maximum_cv_var = tk.StringVar(value="5")
        self.maximum_flow_error_var = tk.StringVar(value="5")
        self.balance_in_var = tk.StringVar(value="1.0")
        self.balance_out_var = tk.StringVar(value="1.0")
        self.balance_duration_var = tk.StringVar(value="60")
        self.balance_measured_in_var = tk.StringVar(value="")
        self.balance_measured_out_var = tk.StringVar(value="")
        self.balance_starting_dish_var = tk.StringVar(value="")
        self.balance_ending_dish_var = tk.StringVar(value="")
        self.balance_dish_method_var = tk.StringVar(value="volume")
        self.balance_dish_unit_var = tk.StringVar(value="mL")
        self.balance_dish_density_var = tk.StringVar(value="0.998")
        self.balance_tubing_var = tk.StringVar(value="")
        self.balance_chamber_var = tk.StringVar(value="")
        self.balance_fluid_var = tk.StringVar(value="")
        self.balance_priming_var = tk.StringVar(value="")
        self.balance_bubbles_var = tk.StringVar(value="")
        self.balance_leakage_var = tk.StringVar(value="")
        self.balance_note_var = tk.StringVar(value="")
        self._build()
        self.refresh()

    def _build(self) -> None:
        self.columnconfigure(0, weight=1)
        header = create_card(
            self,
            "Commissioning and validation",
            "Software/UART completion is never treated as physical confirmation. All movement is bounded.",
        )
        header.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        header.columnconfigure(1, weight=1)
        ttk.Label(header, text="Operator", style="Card.TLabel").grid(row=2, column=0, sticky="w")
        ttk.Entry(header, textvariable=self.operator_var).grid(row=2, column=1, sticky="ew", padx=4)
        ttk.Button(header, text="New record", command=self.new_record).grid(row=2, column=2, padx=4)
        ttk.Button(header, text="Refresh", command=self.refresh).grid(row=2, column=3)
        ttk.Label(header, text="Lab/workstation note", style="Card.TLabel").grid(row=3, column=0, sticky="w")
        ttk.Entry(header, textvariable=self.note_var).grid(row=3, column=1, columnspan=3, sticky="ew", padx=4)
        ttk.Label(header, textvariable=self.progress_var, style="Value.TLabel").grid(
            row=4, column=0, columnspan=4, sticky="w", pady=(6, 0)
        )
        ttk.Checkbutton(
            header,
            text="Require current commissioning for LIVE armed start",
            variable=self.app.require_current_commissioning_var,
            command=self.app.save_commissioning_policy,
        ).grid(row=5, column=0, columnspan=4, sticky="w", pady=(4, 0))
        self.build_identity_var = tk.StringVar(value=format_build_identity(get_build_info()))
        ttk.Label(
            header,
            textvariable=self.build_identity_var,
            style="Card.TLabel",
            justify="left",
        ).grid(row=6, column=0, columnspan=3, sticky="w", pady=(6, 0))
        ttk.Button(
            header,
            text="Copy build identity",
            command=lambda: self.app._copy_text(
                self.build_identity_var.get(),
                "commissioning build identity",
            ),
        ).grid(row=6, column=3, sticky="e", padx=4)

        identity = create_card(
            self,
            "1–2. Environment and port identity",
            "Confirm physical adapters by metadata; roles are never inferred from COM numbers.",
        )
        identity.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        identity.columnconfigure(0, weight=1)
        self.identity_text = tk.Text(identity, height=5, wrap="word", font=("Consolas", 8))
        self.identity_text.grid(row=2, column=0, columnspan=3, sticky="ew")
        ttk.Button(identity, text="Rescan ports", command=self.app.scan_ports_async).grid(row=3, column=0, sticky="ew", padx=(0, 3), pady=4)
        ttk.Button(identity, text="Confirm IN adapter", command=lambda: self.confirm_identity("IN")).grid(row=3, column=1, sticky="ew", padx=3, pady=4)
        ttk.Button(identity, text="Confirm OUT adapter", command=lambda: self.confirm_identity("OUT")).grid(row=3, column=2, sticky="ew", padx=(3, 0), pady=4)
        ttk.Button(identity, text="Use probable IN match…", command=lambda: self.apply_probable_port("IN")).grid(row=4, column=1, sticky="ew", padx=3, pady=2)
        ttk.Button(identity, text="Use probable OUT match…", command=lambda: self.apply_probable_port("OUT")).grid(row=4, column=2, sticky="ew", padx=3, pady=2)

        movement = create_card(
            self,
            "3–5. Direction, emergency STOP, and cancellation",
            "LIVE checks show PROGRAMMED — NOT READ BACK and always send STOP after a bounded interval.",
        )
        movement.grid(row=2, column=0, sticky="ew", pady=(0, 8))
        for column in range(4):
            movement.columnconfigure(column, weight=1)
        ttk.Label(movement, text="Bounded jog ms", style="Card.TLabel").grid(row=2, column=0, sticky="w")
        ttk.Entry(movement, textvariable=self.direction_duration_var).grid(row=2, column=1, sticky="ew", padx=3)
        ttk.Button(movement, text="Validate IN forward", command=lambda: self.direction_check("IN", "forward")).grid(row=3, column=0, sticky="ew", padx=3, pady=3)
        ttk.Button(movement, text="Validate OUT reverse", command=lambda: self.direction_check("OUT", "reverse")).grid(row=3, column=1, sticky="ew", padx=3, pady=3)
        ttk.Button(movement, text="Bounded IN STOP test", command=lambda: self.stop_check("IN", "forward")).grid(row=3, column=2, sticky="ew", padx=3, pady=3)
        ttk.Button(movement, text="Bounded OUT STOP test", command=lambda: self.stop_check("OUT", "reverse")).grid(row=3, column=3, sticky="ew", padx=3, pady=3)
        ttk.Button(movement, text="Bounded STOP-both test", command=self.stop_both_check).grid(row=4, column=0, columnspan=4, sticky="ew", padx=3, pady=3)
        ttk.Label(movement, text="DRY-RUN rehearsal delay s", style="Card.TLabel").grid(row=5, column=0, sticky="w")
        ttk.Entry(movement, textvariable=self.rehearsal_delay_var).grid(row=5, column=1, sticky="ew", padx=3)
        ttk.Button(movement, text="Start cancellation rehearsal", command=self.start_rehearsal).grid(row=5, column=2, sticky="ew", padx=3)
        ttk.Button(movement, text="Cancel rehearsal / STOP", style="Danger.TButton", command=self.cancel_rehearsal).grid(row=5, column=3, sticky="ew", padx=3)

        measurement = create_card(
            self,
            "6. Flow measurement",
            "Direct volume or gravimetric input. Density is editable and recorded.",
        )
        measurement.grid(row=3, column=0, sticky="ew", pady=(0, 8))
        for column in range(6):
            measurement.columnconfigure(column, weight=1)
        fields = (
            ("Role", self.measurement_role_var, ("IN", "OUT")),
            ("Method", self.measurement_method_var, ("direct_volume", "gravimetric")),
            ("Volume", self.measured_volume_var, None),
            ("Volume unit", self.volume_unit_var, ("µL", "mL")),
            ("Initial mass", self.initial_mass_var, None),
            ("Final mass", self.final_mass_var, None),
            ("Mass unit", self.mass_unit_var, ("mg", "g", "kg")),
            ("Density g/mL", self.density_var, None),
            ("Requested mL/min", self.requested_flow_var, None),
            ("Programmed mm/min", self.programmed_speed_var, None),
            ("Duration s", self.programmed_duration_var, None),
            ("Minimum replicates", self.minimum_replicates_var, None),
            ("Maximum CV %", self.maximum_cv_var, None),
            ("Maximum mean error %", self.maximum_flow_error_var, None),
        )
        for index, (label, variable, values) in enumerate(fields):
            row = 2 + index // 3
            column = (index % 3) * 2
            ttk.Label(measurement, text=label, style="Card.TLabel").grid(row=row, column=column, sticky="w")
            widget: tk.Widget
            if values:
                widget = ttk.Combobox(measurement, textvariable=variable, values=values, state="readonly")
            else:
                widget = ttk.Entry(measurement, textvariable=variable)
            widget.grid(row=row, column=column + 1, sticky="ew", padx=3, pady=2)
        ttk.Button(measurement, text="Record replicate", command=self.record_measurement).grid(
            row=7, column=2, sticky="ew", padx=3, pady=3
        )
        ttk.Button(measurement, text="Run bounded measurement", command=self.run_flow_measurement).grid(
            row=7, column=0, columnspan=2, sticky="ew", padx=3, pady=3
        )
        self.exclude_replicate_button = ttk.Button(
            measurement,
            text="Exclude latest…",
            command=self.exclude_latest_replicate,
        )
        self.exclude_replicate_button.grid(row=7, column=3, sticky="ew", padx=3, pady=3)
        ttk.Button(measurement, text="Apply candidate to syringe…", command=self.apply_candidate).grid(
            row=7, column=4, columnspan=2, sticky="ew", padx=3, pady=3
        )
        point_bar = ttk.Frame(measurement, style="Card.TFrame")
        point_bar.grid(row=8, column=0, columnspan=6, sticky="ew")
        for column, value in enumerate((0.5, 1.0, 2.0, 3.0)):
            point_bar.columnconfigure(column, weight=1)
            ttk.Button(
                point_bar,
                text=f"Template {value:.1f} mL/min",
                command=lambda flow=value: self.select_flow_template(flow),
            ).grid(row=0, column=column, sticky="ew", padx=2)

        balance = create_card(
            self,
            "7–9. Balance, workstation, review",
            "Balance conclusions require measured volumes or explicit observation.",
        )
        balance.grid(row=4, column=0, sticky="ew", pady=(0, 8))
        for column in range(6):
            balance.columnconfigure(column, weight=1)
        balance_fields = (
            ("IN mL/min", self.balance_in_var),
            ("OUT mL/min", self.balance_out_var),
            ("Duration s", self.balance_duration_var),
            ("Measured IN mL", self.balance_measured_in_var),
            ("Measured OUT mL", self.balance_measured_out_var),
            ("Dish method", self.balance_dish_method_var),
            ("Dish unit", self.balance_dish_unit_var),
            ("Dish density g/mL", self.balance_dish_density_var),
            ("Starting dish value (optional)", self.balance_starting_dish_var),
            ("Ending dish value (optional)", self.balance_ending_dish_var),
        )
        for index, (label, variable) in enumerate(balance_fields):
            row = 2 + index // 3
            column = (index % 3) * 2
            ttk.Label(balance, text=label, style="Card.TLabel").grid(row=row, column=column, sticky="w")
            values = None
            if variable is self.balance_dish_method_var:
                values = ("volume", "mass")
            elif variable is self.balance_dish_unit_var:
                values = ("µL", "mL", "mg", "g", "kg")
            if values:
                widget = ttk.Combobox(balance, textvariable=variable, values=values, state="readonly")
            else:
                widget = ttk.Entry(balance, textvariable=variable)
            widget.grid(row=row, column=column + 1, sticky="ew", padx=3)
        detail_fields = (
            ("Tubing", self.balance_tubing_var),
            ("Chamber", self.balance_chamber_var),
            ("Fluid", self.balance_fluid_var),
            ("Priming state", self.balance_priming_var),
            ("Visible bubbles", self.balance_bubbles_var),
            ("Leakage", self.balance_leakage_var),
            ("Operator notes", self.balance_note_var),
        )
        for index, (label, variable) in enumerate(detail_fields):
            row = 6 + index // 3
            column = (index % 3) * 2
            ttk.Label(balance, text=label, style="Card.TLabel").grid(row=row, column=column, sticky="w")
            ttk.Entry(balance, textvariable=variable).grid(row=row, column=column + 1, sticky="ew", padx=3)
        ttk.Button(balance, text="Record paired balance", command=self.record_balance).grid(row=9, column=0, columnspan=2, sticky="ew", padx=3, pady=3)
        ttk.Button(balance, text="Confirm NIS/workstation checklist", command=self.confirm_workstation).grid(row=9, column=2, columnspan=2, sticky="ew", padx=3, pady=3)
        ttk.Button(balance, text="Export report…", command=self.export_report).grid(row=9, column=4, columnspan=2, sticky="ew", padx=3, pady=3)
        self.result_text = tk.Text(balance, height=5, wrap="word", font=("Consolas", 8))
        self.result_text.grid(row=10, column=0, columnspan=6, sticky="ew", pady=(4, 0))

    def new_record(self) -> None:
        operator = self.operator_var.get().strip()
        if not operator:
            messagebox.showerror("Operator required", "Enter the operator name.")
            return
        record = self.store.create(
            operator=operator,
            laboratory_note=self.note_var.get(),
            detected_ports=json.loads(json.dumps(self.app.detected_ports)),
        )
        for role, key in (
            ("IN", self.app.in_syringe_var.get()),
            ("OUT", self.app.out_syringe_var.get()),
        ):
            syringe = self.app.data.get("syringes", {}).get(key, {})
            record["selected_syringes"][role] = {
                "key": key,
                "calibrated_ul_per_mm": syringe.get("calibrated_ul_per_mm"),
            }
        self.store.save(record, event="commissioning_created")
        self.refresh()

    def refresh(self) -> None:
        status = self.store.status(
            data=json.loads(json.dumps(self.app.data)),
            detected_ports=json.loads(json.dumps(self.app.detected_ports)),
        )
        reasons = "; ".join(status["stale_reasons"])
        self.progress_var.set(
            f"{status['status']} · last completed {status['last_completed_at'] or 'not completed'}"
            + (f" · STALE: {reasons}" if reasons else "")
        )
        self.identity_text.delete("1.0", "end")
        detected = {item.get("device"): item for item in self.app.detected_ports}
        for role in ("IN", "OUT"):
            port = self.app.port_vars[role].get()
            metadata = detected.get(port, {})
            self.identity_text.insert(
                "end",
                f"{role}: {port or '(missing)'} | {metadata.get('description', 'not detected')} | "
                f"HWID={metadata.get('hwid', '')} | serial={metadata.get('serial_number', '')} | "
                f"VID={metadata.get('vid', '')} PID={metadata.get('pid', '')} location={metadata.get('location', '')}\n",
            )
            record = status.get("record") or {}
            stored = (record.get("pumps", {}).get(role, {}).get("hardware_identity") or {})
            matches = probable_identity_matches(stored, self.app.detected_ports)
            moved = [item for item in matches if item.get("device") != port]
            if moved:
                self.identity_text.insert(
                    "end",
                    f"  Probable stable-identity match now at {moved[0].get('device')}; "
                    "explicit confirmation is required before pumps.json changes.\n",
                )

    def apply_probable_port(self, role: str) -> None:
        record = self._require_record()
        if record is None:
            return
        stored = record.get("pumps", {}).get(role, {}).get("hardware_identity") or {}
        current = self.app.port_vars[role].get()
        matches = [
            item for item in probable_identity_matches(stored, self.app.detected_ports)
            if item.get("device") != current
        ]
        if len(matches) != 1:
            messagebox.showerror(
                "No unique probable match",
                "A single adapter with matching stable serial/HWID metadata was not detected.",
            )
            return
        candidate = str(matches[0]["device"])
        if not messagebox.askyesno(
            "Update port assignment",
            f"The stored {role} adapter identity probably matches {candidate}.\n\n"
            f"Current port: {current}\nCandidate: {candidate}\n\n"
            "Confirm the physical adapter before updating pumps.json.",
        ):
            return
        self.app.port_vars[role].set(candidate)
        if self.app.save_pump_settings_gui() is None:
            return
        self.store.append_event(
            {
                "event": "probable_port_match_applied",
                "validation_id": record.get("validation_id", ""),
                "pump_role": role,
                "old_port": current,
                "new_port": candidate,
                "operator": self.operator_var.get().strip(),
                "identity": matches[0],
            }
        )
        self.refresh()

    def confirm_identity(self, role: str) -> None:
        record = self._require_record()
        if record is None:
            return
        port = self.app.port_vars[role].get()
        metadata = next((item for item in self.app.detected_ports if item.get("device") == port), None)
        if metadata is None:
            messagebox.showerror("Identity unavailable", f"{role} port {port!r} is not detected.")
            return
        if not messagebox.askyesno(
            "Manual physical confirmation",
            f"Confirm that the physical adapter on {port} is connected to pump {role}.\n\n"
            f"{json.dumps(metadata, ensure_ascii=False, indent=2)}",
        ):
            return
        result = make_test_result(
            f"port_identity_{role.casefold()}",
            pump_role=role,
            evidence_type=MANUAL_CONFIRMATION,
            operator_confirmation={
                "observation": "confirmed",
                "operator": self.operator_var.get().strip(),
                "timestamp": now_iso(),
                "evidence": metadata,
            },
            completed_at=now_iso(),
        )
        self._record_test(record, result)

    def direction_check(self, role: str, direction: str) -> None:
        self._start_bounded_check(role, direction, f"direction_{role.casefold()}", stop_test=False)

    def stop_check(self, role: str, direction: str) -> None:
        self._start_bounded_check(role, direction, f"stop_{role.casefold()}", stop_test=True)

    def stop_both_check(self) -> None:
        record = self._require_record()
        if record is None:
            return
        if self.app.dry_run_var.get():
            messagebox.showerror("LIVE confirmation required", "The physical paired STOP check requires LIVE mode.")
            return
        try:
            duration_ms = int(self.direction_duration_var.get())
        except ValueError:
            messagebox.showerror("Invalid duration", "Enter a bounded duration in milliseconds.")
            return
        if not messagebox.askyesno(
            "LIVE paired STOP commissioning",
            f"Both pumps will move for at most {duration_ms} ms before independent STOP attempts.\n"
            "IN: forward delivery\nOUT: reverse withdrawal\n"
            "Programmed speed/flow: manual-jog setting on each device, NOT READ BACK\n"
            "Expected volume: not scientifically estimated for manual jog\n\n"
            "PROGRAMMED — NOT READ BACK\n\nProceed?",
        ):
            return
        if not self.app.begin_gui_operation("commissioning"):
            return
        snapshot = json.loads(json.dumps(self.app.data))
        cancel_event = Event()
        self.cancel_event = cancel_event

        def worker() -> None:
            try:
                result = CommissioningService(
                    OperationCoordinator(self.app.config_resolution), snapshot
                ).bounded_pair_stop_check(
                    duration_ms=duration_ms,
                    cancel_event=cancel_event,
                )
                self.app.post_ui(self._bounded_complete, record, "stop_both", "BOTH", "paired", result, True)
            except Exception as exc:
                self.app.post_ui(self._bounded_failed, record, "stop_both", "BOTH", "paired", str(exc))

        threading.Thread(target=worker, daemon=True, name="a4-commissioning-stop-both").start()

    def _start_bounded_check(self, role: str, direction: str, test_id: str, *, stop_test: bool) -> None:
        record = self._require_record()
        if record is None:
            return
        if self.app.dry_run_var.get():
            messagebox.showerror("LIVE confirmation required", "Physical direction/STOP checks require LIVE mode.")
            return
        try:
            duration_ms = int(self.direction_duration_var.get())
        except ValueError:
            messagebox.showerror("Invalid duration", "Enter a bounded duration in milliseconds.")
            return
        target = self.app.data["pumps"][role]
        if not messagebox.askyesno(
            "LIVE bounded commissioning movement",
            f"Pump: {role}\nCOM: {target.get('port')}\nDirection: {direction}\n"
            f"Maximum duration: {duration_ms} ms\n"
            "Programmed speed/flow: manual-jog setting on device, NOT READ BACK\n"
            "Expected volume: not scientifically estimated for manual jog\n"
            "STOP ALL remains globally available.\n\n"
            "PROGRAMMED — NOT READ BACK\n\nProceed?",
        ):
            return
        if not self.app.begin_gui_operation("commissioning"):
            return
        snapshot = json.loads(json.dumps(self.app.data))
        cancel_event = Event()
        self.cancel_event = cancel_event

        def worker() -> None:
            try:
                service = CommissioningService(
                    OperationCoordinator(self.app.config_resolution),
                    snapshot,
                )
                result = service.bounded_direction_check(
                    role=role,
                    direction=direction,
                    duration_ms=duration_ms,
                    cancel_event=cancel_event,
                )
                self.app.post_ui(self._bounded_complete, record, test_id, role, direction, result, stop_test)
            except Exception as exc:
                self.app.post_ui(self._bounded_failed, record, test_id, role, direction, str(exc))

        threading.Thread(target=worker, daemon=True, name="a4-commissioning-bounded").start()

    def _bounded_complete(
        self,
        record: dict[str, Any],
        test_id: str,
        role: str,
        direction: str,
        uart: dict[str, Any],
        stop_test: bool,
    ) -> None:
        self.app.finish_gui_operation("commissioning")
        question = (
            f"Did pump {role} physically stop when STOP was issued?"
            if stop_test
            else f"Did pump {role} visibly move in the expected {direction} direction?"
        )
        answer = messagebox.askyesnocancel(
            "Manual physical observation",
            question + "\n\nYes = correct/stopped, No = incorrect/failed, Cancel = uncertain.",
        )
        observation = (
            "stopped" if stop_test and answer is True else
            "correct" if answer is True else
            "incorrect" if answer is False else
            "uncertain"
        )
        result = make_test_result(
            test_id,
            pump_role=role,
            direction=direction,
            evidence_type=MANUAL_CONFIRMATION,
            commanded_values={"maximum_duration_ms": int(self.direction_duration_var.get())},
            measured_values={"software_uart_timeline": uart},
            operator_confirmation={
                "observation": observation,
                "operator": self.operator_var.get().strip(),
                "timestamp": now_iso(),
            },
            uart_completed=True,
            completed_at=now_iso(),
            run_id=uart.get("run_id", ""),
            note="UART sequence completed; physical outcome is based only on operator observation.",
        )
        self._record_test(record, result)

    def _bounded_failed(
        self,
        record: dict[str, Any],
        test_id: str,
        role: str,
        direction: str,
        error: str,
    ) -> None:
        self.app.finish_gui_operation("commissioning")
        result = make_test_result(
            test_id,
            pump_role=role,
            direction=direction,
            evidence_type=MANUAL_CONFIRMATION,
            error=error,
            completed_at=now_iso(),
            note="Use the pump's physical controls and disconnect drive power if movement continues.",
        )
        self._record_test(record, result)
        messagebox.showerror(
            "Commissioning STOP/movement failed",
            f"{error}\n\nUse the physical emergency procedure. The result is FAILED.",
        )

    def start_rehearsal(self) -> None:
        record = self._require_record()
        if record is None:
            return
        try:
            delay = float(self.rehearsal_delay_var.get())
        except ValueError:
            messagebox.showerror("Invalid delay", "Enter a bounded delay.")
            return
        if not self.app.begin_gui_operation("commissioning"):
            return
        self.cancel_event = Event()
        snapshot = json.loads(json.dumps(self.app.data))
        event = self.cancel_event

        def worker() -> None:
            try:
                result = CommissioningService(
                    OperationCoordinator(self.app.config_resolution),
                    snapshot,
                ).cancellation_rehearsal(delay_s=delay, cancel_event=event)
                self.app.post_ui(self._rehearsal_complete, record, result)
            except Exception as exc:
                self.app.post_ui(self._bounded_failed, record, "delayed_cancellation", "", "", str(exc))

        threading.Thread(target=worker, daemon=True, name="a4-commissioning-rehearsal").start()

    def cancel_rehearsal(self) -> None:
        self.cancel_event.set()
        self.app.gui_stop_all_now()

    def _rehearsal_complete(self, record: dict[str, Any], result: dict[str, Any]) -> None:
        self.app.finish_gui_operation("commissioning")
        test = make_test_result(
            "delayed_cancellation",
            commanded_values=result,
            software_pass=bool(result.get("software_pass")),
            completed_at=now_iso(),
            run_id=result.get("run_id", ""),
        )
        self._record_test(record, test)

    def record_measurement(self) -> None:
        record = self._require_record()
        if record is None:
            return
        try:
            criteria = self._acceptance_criteria()
            method = self.measurement_method_var.get()
            if method == "gravimetric":
                volume = gravimetric_volume_ul(
                    float(self.initial_mass_var.get()),
                    float(self.final_mass_var.get()),
                    mass_unit=self.mass_unit_var.get(),
                    density_g_ml=float(self.density_var.get()),
                )
                density: float | None = float(self.density_var.get())
            else:
                volume = direct_volume_ul(float(self.measured_volume_var.get()), self.volume_unit_var.get())
                density = None
            role = self.measurement_role_var.get()
            syringe_key = self.app.in_syringe_var.get() if role == "IN" else self.app.out_syringe_var.get()
            replicate = calculate_replicate(
                measured_volume_ul=volume,
                requested_flow_ml_min=float(self.requested_flow_var.get()),
                programmed_speed_mm_min=float(self.programmed_speed_var.get()),
                programmed_duration_s=float(self.programmed_duration_var.get()),
                pump_role=role,
                direction="forward" if role == "IN" else "reverse",
                syringe_key=syringe_key,
                operator=self.operator_var.get().strip(),
                method=method,
                density_g_ml=density,
                note=self.note_var.get(),
            )
        except Exception as exc:
            messagebox.showerror("Measurement invalid", str(exc))
            return
        record.setdefault("measurement_results", []).append(replicate)
        same = [
            item for item in record["measurement_results"]
            if item.get("pump_role") == role and item.get("syringe_key") == syringe_key
        ]
        statistics_result = calibration_statistics(same, criteria=criteria)
        test = make_test_result(
            "flow_in" if role == "IN" else "flow_out",
            pump_role=role,
            direction="forward" if role == "IN" else "reverse",
            evidence_type=MEASURED_RESULT,
            measured_values={"latest": replicate, "statistics": statistics_result},
            acceptance_criteria=statistics_result["criteria"],
            criteria_met=statistics_result["accepted"],
            completed_at=now_iso(),
        )
        record["test_results"] = [
            item for item in record.get("test_results", []) if item.get("test_id") != test["test_id"]
        ]
        record["test_results"].append(test)
        self.store.append_measurement(replicate)
        self.store.save(record, event="flow_measurement_recorded")
        self._show_json(statistics_result)
        self.refresh()

    def _acceptance_criteria(self) -> dict[str, Any]:
        minimum = int(self.minimum_replicates_var.get())
        maximum_cv = float(self.maximum_cv_var.get())
        maximum_error = float(self.maximum_flow_error_var.get())
        if minimum < 1:
            raise ValueError("minimum replicates must be at least 1")
        if maximum_cv < 0 or maximum_error < 0:
            raise ValueError("acceptance percentages cannot be negative")
        return {
            "minimum_replicates": minimum,
            "maximum_cv_percent": maximum_cv,
            "maximum_abs_mean_flow_error_percent": maximum_error,
        }

    def exclude_latest_replicate(self) -> None:
        record = self._require_record()
        if record is None:
            return
        role = self.measurement_role_var.get()
        syringe_key = (
            self.app.in_syringe_var.get()
            if role == "IN"
            else self.app.out_syringe_var.get()
        )
        matching = [
            (index, item)
            for index, item in enumerate(record.get("measurement_results", []))
            if item.get("pump_role") == role
            and item.get("syringe_key") == syringe_key
            and not item.get("excluded")
        ]
        if not matching:
            messagebox.showerror("No replicate", "There is no accepted replicate to exclude.")
            return
        reason = simpledialog.askstring(
            "Exclude replicate",
            "Enter the required reason for excluding the latest replicate:",
            parent=self,
        )
        if reason is None:
            return
        try:
            criteria = self._acceptance_criteria()
            index, latest = matching[-1]
            record["measurement_results"][index] = exclude_replicate(latest, reason)
        except Exception as exc:
            messagebox.showerror("Cannot exclude replicate", str(exc))
            return
        same = [
            item
            for item in record["measurement_results"]
            if item.get("pump_role") == role and item.get("syringe_key") == syringe_key
        ]
        statistics_result = calibration_statistics(same, criteria=criteria)
        test_id = "flow_in" if role == "IN" else "flow_out"
        test = make_test_result(
            test_id,
            pump_role=role,
            direction="forward" if role == "IN" else "reverse",
            evidence_type=MEASURED_RESULT,
            measured_values={"latest": record["measurement_results"][index], "statistics": statistics_result},
            acceptance_criteria=statistics_result["criteria"],
            criteria_met=statistics_result["accepted"],
            completed_at=now_iso(),
            note=f"Latest replicate excluded with recorded reason: {reason.strip()}",
        )
        record["test_results"] = [
            item for item in record.get("test_results", []) if item.get("test_id") != test_id
        ]
        record["test_results"].append(test)
        self.store.save(record, event="flow_measurement_excluded")
        self.store.append_event(
            {
                "event": "flow_measurement_excluded",
                "validation_id": record.get("validation_id", ""),
                "operator": self.operator_var.get().strip(),
                "replicate_timestamp": latest.get("timestamp", ""),
                "reason": reason.strip(),
            }
        )
        self._show_json(statistics_result)
        self.refresh()

    def run_flow_measurement(self) -> None:
        record = self._require_record()
        if record is None:
            return
        if self.app.dry_run_var.get():
            messagebox.showerror("LIVE confirmation required", "A physical flow run requires LIVE mode.")
            return
        try:
            role = self.measurement_role_var.get()
            speed = float(self.programmed_speed_var.get())
            duration = int(float(self.programmed_duration_var.get()))
            syringe_key = self.app.in_syringe_var.get() if role == "IN" else self.app.out_syringe_var.get()
            conversion = calibrated_ul_per_mm(self.app.data["syringes"][syringe_key])
            travel = speed * duration / 60.0
            expected_ml = travel * conversion / 1000.0
            direction = "forward" if role == "IN" else "reverse"
            port = self.app.data["pumps"][role].get("port", "")
        except Exception as exc:
            messagebox.showerror("Invalid bounded flow run", str(exc))
            return
        if not messagebox.askyesno(
            "LIVE bounded flow measurement",
            f"Pump: {role}\nCOM: {port}\nDirection: {direction}\n"
            f"Programmed speed: {speed} mm/min\nMaximum duration: {duration} s\n"
            f"Programmed travel: {travel:.4f} mm\nExpected volume: {expected_ml:.4f} mL\n"
            "STOP ALL remains globally available.\n\nPROGRAMMED — NOT READ BACK\n\nProceed?",
        ):
            return
        if not self.app.begin_gui_operation("commissioning"):
            return
        snapshot = json.loads(json.dumps(self.app.data))
        event = Event()
        self.cancel_event = event

        def worker() -> None:
            try:
                result = CommissioningService(
                    OperationCoordinator(self.app.config_resolution), snapshot
                ).bounded_flow_run(
                    role=role,
                    direction=direction,
                    speed_mm_min=speed,
                    duration_s=duration,
                    cancel_event=event,
                )
                self.app.post_ui(self._flow_run_complete, record, result)
            except Exception as exc:
                self.app.post_ui(
                    self._bounded_failed,
                    record,
                    "flow_in" if role == "IN" else "flow_out",
                    role,
                    direction,
                    str(exc),
                )

        threading.Thread(target=worker, daemon=True, name="a4-commissioning-flow").start()

    def _flow_run_complete(self, record: dict[str, Any], result: dict[str, Any]) -> None:
        self.app.finish_gui_operation("commissioning")
        self.store.append_event(
            {
                "event": "commissioning_flow_uart_completed",
                "validation_id": record.get("validation_id", ""),
                "operator": self.operator_var.get().strip(),
                "run_id": result.get("run_id", ""),
                "result": result,
                "evidence_type": "UART COMMAND COMPLETED",
                "physical_pass": False,
            }
        )
        self._show_json(result)
        self.app.set_status("Flow run UART sequence completed; enter the measured result to evaluate it")

    def select_flow_template(self, flow: float) -> None:
        role = self.measurement_role_var.get()
        syringe_key = self.app.in_syringe_var.get() if role == "IN" else self.app.out_syringe_var.get()
        try:
            points = commissioning_flow_points(self.app.data, syringe_key=syringe_key)
            point = next(item for item in points if item["flow_ml_min"] == flow)
            if not point["supported"]:
                raise ValueError(point["error"])
            self.requested_flow_var.set(str(flow))
            self.programmed_speed_var.set(str(point["speed_mm_min"]))
            self.app.set_status(
                f"Commissioning template {flow:.1f} mL/min selected; verify bounded duration before programming"
            )
        except Exception as exc:
            messagebox.showerror("Flow point unsupported", str(exc))

    def record_balance(self) -> None:
        record = self._require_record()
        if record is None:
            return
        try:
            starting_dish = self._optional_dish_volume_ml(
                self.balance_starting_dish_var.get()
            )
            ending_dish = self._optional_dish_volume_ml(
                self.balance_ending_dish_var.get()
            )
            result = balance_result(
                requested_in_flow_ml_min=float(self.balance_in_var.get()),
                requested_out_flow_ml_min=float(self.balance_out_var.get()),
                duration_s=float(self.balance_duration_var.get()),
                measured_in_volume_ml=float(self.balance_measured_in_var.get()),
                measured_out_volume_ml=float(self.balance_measured_out_var.get()),
                starting_dish_volume_ml=starting_dish,
                ending_dish_volume_ml=ending_dish,
            )
            result.update(
                {
                    "dish_measurement_method": self.balance_dish_method_var.get(),
                    "dish_measurement_unit": self.balance_dish_unit_var.get(),
                    "dish_density_g_ml": (
                        float(self.balance_dish_density_var.get())
                        if self.balance_dish_method_var.get() == "mass"
                        else None
                    ),
                    "tubing": self.balance_tubing_var.get(),
                    "chamber": self.balance_chamber_var.get(),
                    "fluid": self.balance_fluid_var.get(),
                    "priming_state": self.balance_priming_var.get(),
                    "visible_bubbles": self.balance_bubbles_var.get(),
                    "leakage": self.balance_leakage_var.get(),
                    "operator_notes": self.balance_note_var.get(),
                }
            )
        except Exception as exc:
            messagebox.showerror("Balance result invalid", str(exc))
            return
        test = make_test_result(
            "balance",
            evidence_type=MEASURED_RESULT,
            measured_values=result,
            acceptance_criteria={"operator_review_required": True},
            criteria_met=False,
            completed_at=now_iso(),
            note="Recorded for review; liquid-level stability is not inferred automatically.",
        )
        self._record_test(record, test)

    def _optional_dish_volume_ml(self, value: str) -> float | None:
        if not value.strip():
            return None
        if self.balance_dish_method_var.get() == "mass":
            return gravimetric_volume_ul(
                0.0,
                float(value),
                mass_unit=self.balance_dish_unit_var.get(),
                density_g_ml=float(self.balance_dish_density_var.get()),
            ) / 1000.0
        return direct_volume_ul(
            float(value),
            self.balance_dish_unit_var.get(),
        ) / 1000.0

    def apply_candidate(self) -> None:
        record = self._require_record()
        if record is None:
            return
        role = self.measurement_role_var.get()
        syringe_key = self.app.in_syringe_var.get() if role == "IN" else self.app.out_syringe_var.get()
        replicates = [
            item for item in record.get("measurement_results", [])
            if item.get("pump_role") == role and item.get("syringe_key") == syringe_key
        ]
        try:
            stats = calibration_statistics(
                replicates,
                criteria=self._acceptance_criteria(),
            )
        except Exception as exc:
            messagebox.showerror("Acceptance criteria invalid", str(exc))
            return
        candidate = stats.get("candidate_calibrated_ul_per_mm")
        if candidate is None:
            messagebox.showerror("No candidate", "Record valid replicates before applying calibration.")
            return
        old = self.app.data["syringes"][syringe_key].get("calibrated_ul_per_mm")
        if not messagebox.askyesno(
            "Apply candidate calibration",
            f"Syringe: {syringe_key}\nOld calibrated_ul_per_mm: {old}\n"
            f"Candidate: {candidate:.6g}\nReplicates: {stats['n']}\n"
            f"CV: {stats['coefficient_of_variation_percent']}\n"
            f"Mean flow error: {stats['mean_percent_error']}%\n\n"
            "This atomically updates syringes.json, creates a backup, invalidates any ARMED plan, "
            "and makes dependent validation stale. Apply?",
        ):
            return
        if not self.app.begin_gui_operation("commissioning_config"):
            return
        root = self.app.config_resolution.active_config_dir
        validation_id = str(record.get("validation_id", ""))
        operator = self.operator_var.get().strip()

        def worker() -> None:
            try:
                path = apply_syringe_calibration(
                    root,
                    syringe_key=syringe_key,
                    candidate_ul_per_mm=float(candidate),
                    validation_id=validation_id,
                    method="commissioning accepted replicates",
                    statistics_result=stats,
                    confirmed=True,
                )
                self.store.append_event(
                    {
                        "event": "syringe_calibration_applied",
                        "validation_id": validation_id,
                        "syringe_key": syringe_key,
                        "old_calibrated_ul_per_mm": old,
                        "new_calibrated_ul_per_mm": candidate,
                        "operator": operator,
                    }
                )
                self.app.post_ui(self._calibration_applied, path)
            except Exception as exc:
                self.app.post_ui(self._calibration_failed, str(exc))

        threading.Thread(target=worker, daemon=True, name="a4-calibration-apply").start()

    def _calibration_applied(self, path: Path) -> None:
        self.app.finish_gui_operation("commissioning_config")
        self.app.data = load_config(self.app.config_resolution)
        self.app.current_perfusion_setpoint = None
        self.app.schedule_perfusion_preview()
        self.app.set_status(f"Applied calibration to {path}; ARMED state invalidated")
        self.refresh()

    def _calibration_failed(self, message: str) -> None:
        self.app.finish_gui_operation("commissioning_config")
        messagebox.showerror("Calibration update failed", message)

    def confirm_workstation(self) -> None:
        record = self._require_record()
        if record is None:
            return
        if not messagebox.askyesno(
            "Manual workstation confirmation",
            "Confirm that all applicable items were manually reviewed:\n\n"
            "• Built GUI starts; built CLI resolves expected config\n"
            "• NIS ROOT and CFG match GUI Active Config\n"
            "• Immediate/delayed/cancel/STOP wrappers and Int_ExecProgram result\n"
            "• 100%, 125%, and 150% scaling\n"
            "• 900×600 constrained display\n\n"
            "Software path checks do not prove NIS execution or display appearance.",
        ):
            return
        test = make_test_result(
            "nis_workstation",
            evidence_type=MANUAL_CONFIRMATION,
            operator_confirmation={
                "observation": "confirmed",
                "operator": self.operator_var.get().strip(),
                "timestamp": now_iso(),
                "evidence": {
                    "built_gui": True,
                    "built_cli_config": True,
                    "nis_root_cfg": True,
                    "armed_wrappers": True,
                    "nis_int_execprogram": True,
                    "scaling_100_125_150": True,
                    "constrained_900x600": True,
                },
            },
            completed_at=now_iso(),
        )
        self._record_test(record, test)

    def export_report(self) -> None:
        path = filedialog.asksaveasfilename(
            title="Export commissioning report",
            defaultextension=".md",
            filetypes=[("Markdown", "*.md"), ("JSON", "*.json"), ("CSV", "*.csv")],
        )
        if not path:
            return
        suffix = Path(path).suffix.casefold()
        format = "json" if suffix == ".json" else "csv" if suffix == ".csv" else "markdown"

        def worker() -> None:
            try:
                result = self.store.export(format, path)
                self.app.post_ui(self.app.set_status, f"Commissioning report exported: {result}")
            except Exception as exc:
                self.app.post_ui(messagebox.showerror, "Report export failed", str(exc))

        threading.Thread(target=worker, daemon=True, name="a4-validation-export").start()

    def cancel_execution(self) -> None:
        self.cancel_event.set()

    def _record_test(self, record: dict[str, Any], result: dict[str, Any]) -> None:
        record["test_results"] = [
            item for item in record.get("test_results", []) if item.get("test_id") != result["test_id"]
        ]
        record["test_results"].append(result)
        if result.get("outcome") == "FAILED":
            record.setdefault("failures", []).append(
                {"test_id": result["test_id"], "at": now_iso(), "note": result.get("note", "")}
            )
        self.store.save(record, event="commissioning_test_recorded")
        self._show_json(result)
        self.refresh()

    def _require_record(self) -> dict[str, Any] | None:
        record = self.store.load()
        if record is None:
            messagebox.showerror("Commissioning record required", "Create a commissioning record first.")
        return record

    def _show_json(self, value: dict[str, Any]) -> None:
        self.result_text.delete("1.0", "end")
        self.result_text.insert("end", json.dumps(value, ensure_ascii=False, indent=2))
