from __future__ import annotations

import json
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Any

from .config import app_base_dir
from .profiles import calculate_profile
from .run_history import recent_runs
from .ui_theme import ScrollableFrame, create_card


WORKFLOW_STATES = (
    "UNSET",
    "INPUT_COMPLETE",
    "NEEDS_PROGRAMMING",
    "PROGRAMMED",
    "NEEDS_NIS",
    "READY",
    "RUNNING",
    "STOPPED",
    "REVIEW",
    "FAULT",
)


class GuidedExperimentFrame(ttk.Frame):
    """Presentation-only guide derived from the authoritative application state."""

    WIDE_BREAKPOINT = 860
    ACTIVE_STATES = {"PENDING", "STARTING", "STARTED", "RUNNING"}
    PROGRAMMED_STATES = {
        "ARMED",
        "PENDING",
        "STARTING",
        "STARTED",
        "RUNNING",
        "STOPPING",
    }

    def __init__(self, parent: tk.Widget, app: Any) -> None:
        super().__init__(parent, style="Page.TFrame")
        self.app = app
        self.current_step = 1
        self.layout_mode = "narrow"
        self._layout_job: str | None = None
        self._technical_visible = False
        self._nis_ready = False
        self._invalidation_reason = ""
        self._connection_checked = False
        self._programming_observed = False
        self._last_conditions: dict[str, str] | None = None
        self.step_status_vars = {index: tk.StringVar() for index in range(1, 5)}
        self.step_buttons: dict[int, ttk.Button] = {}
        self.step_frames: dict[int, ttk.Frame] = {}
        self.workflow_status_var = tk.StringVar()
        self.notice_var = tk.StringVar()
        self.summary_condition_var = tk.StringVar()
        self.summary_flow_var = tk.StringVar()
        self.summary_target_var = tk.StringVar()
        self.summary_ports_var = tk.StringVar()
        self.summary_status_var = tk.StringVar()
        self.step2_port_summary_vars = {"IN": tk.StringVar(), "OUT": tk.StringVar()}
        self.connection_result_var = tk.StringVar()
        self.programming_result_var = tk.StringVar()
        self.nis_wrapper_var = tk.StringVar()
        self.nis_destination_var = tk.StringVar()
        self.nis_config_var = tk.StringVar()
        self.run_instruction_var = tk.StringVar()
        self.run_state_var = tk.StringVar()
        self.run_readiness_var = tk.StringVar()
        self.run_programming_var = tk.StringVar()
        self.run_start_mode_var = tk.StringVar()
        self.template_display_var = tk.StringVar()
        self.start_mode_var = tk.StringVar(
            value="nis" if self.app.trigger_var.get().casefold() == "nis" else "gui"
        )
        self.start_timing_var = tk.StringVar(
            value="delayed" if self._start_delay() > 0 else "immediate"
        )
        self.checklist_vars = {
            "imaging": tk.BooleanVar(value=False),
            "fluid_path": tk.BooleanVar(value=False),
            "nis_macro": tk.BooleanVar(value=False),
        }
        self._build()
        self.notice_var.trace_add("write", self._on_notice_visibility_changed)
        self._on_notice_visibility_changed()
        for variable in self.checklist_vars.values():
            variable.trace_add("write", self._on_checklist_changed)
        self.bind("<Configure>", self._schedule_layout, add="+")
        self.after_idle(self._apply_layout)
        self.refresh_language()
        self.refresh()

    def t(self, key: str, **parameters: Any) -> str:
        return self.app.t(key, **parameters)

    def _bind_label(self, parent: tk.Widget, key: str, **kwargs: Any) -> ttk.Label:
        return self.app.localizer.bind(ttk.Label(parent, **kwargs), key)

    def _bind_button(
        self,
        parent: tk.Widget,
        key: str,
        command: Any,
        *,
        style: str = "Neutral.TButton",
    ) -> ttk.Button:
        return self.app.localizer.bind(ttk.Button(parent, command=command, style=style), key)

    def _build(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        self.progress_card = create_card(self, self.t("workflow.progress.title"))
        self.progress_card.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        self.progress_legend = self._bind_label(
            self.progress_card,
            "workflow.progress.legend",
            style="Subtitle.TLabel",
        )
        self.progress_legend.grid(row=2, column=0, sticky="w", pady=(0, 4))
        self.progress_buttons_frame = ttk.Frame(self.progress_card, style="Card.TFrame")
        self.progress_buttons_frame.grid(row=3, column=0, sticky="ew")
        for index in range(1, 5):
            button = ttk.Button(
                self.progress_buttons_frame,
                textvariable=self.step_status_vars[index],
                style="NeutralCompact.TButton",
                command=lambda step=index: self.go_to_step(step),
            )
            self.step_buttons[index] = button

        self.workspace = ttk.Frame(self, style="Page.TFrame")
        self.workspace.grid(row=1, column=0, sticky="nsew")
        self.workspace.rowconfigure(0, weight=1)

        self.step_scroll = ScrollableFrame(self.workspace, height=360)
        self.step_scroll.inner.columnconfigure(0, weight=1)
        self.app.experiment_scroll = self.step_scroll
        self.step_container = self.step_scroll.inner

        self.summary_card = create_card(self.workspace, self.t("workflow.summary.title"))
        self.summary_card.columnconfigure(0, weight=1)
        self.compact_summary_var = tk.StringVar()
        self.compact_summary_label = ttk.Label(
            self.summary_card,
            textvariable=self.compact_summary_var,
            style="Card.TLabel",
            justify="left",
            anchor="w",
        )
        self.compact_summary_label.grid(row=2, column=0, sticky="ew", pady=(0, 3))
        self.summary_labels: list[ttk.Label] = []
        summary_rows = (
            self.summary_condition_var,
            self.summary_flow_var,
            self.summary_target_var,
            self.summary_ports_var,
            self.summary_status_var,
        )
        for row, variable in enumerate(summary_rows, start=2):
            label = ttk.Label(
                self.summary_card,
                textvariable=variable,
                style="Value.TLabel" if row in {2, 6} else "Card.TLabel",
                justify="left",
                anchor="w",
            )
            label._responsive_wrap_margin = 16  # type: ignore[attr-defined]
            label.grid(row=row, column=0, sticky="ew", pady=(0, 3))
            self.summary_labels.append(label)
        self.technical_toggle_button = self._bind_button(
            self.step_container,
            "workflow.action.show_technical",
            self.toggle_technical_details,
            style="Outline.TButton",
        )
        self.technical_toggle_button.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        self.app.experiment_pair_card = self.summary_card
        self.app.perfusion_state_label = self.compact_summary_label

        self._build_step1()
        self._build_step2()
        self._build_step3()
        self._build_step4()
        self._build_technical_details()

        self.notice_label = ttk.Label(
            self,
            textvariable=self.notice_var,
            style="Warning.TLabel",
            justify="left",
            anchor="w",
        )
        self.notice_label._responsive_wrap_margin = 32  # type: ignore[attr-defined]
        self.notice_label.grid(row=2, column=0, sticky="ew", pady=(6, 0))

        actions = create_card(self)
        actions.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        actions.columnconfigure(0, weight=1)
        actions.columnconfigure(1, weight=0)
        self.app.experiment_action_strip = actions
        self.primary_action_button = ttk.Button(
            actions,
            style="Primary.TButton",
            command=self.activate_primary_action,
        )
        self.primary_action_button.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.app.experiment_stop_button = self._bind_button(
            actions,
            "action.stop_all",
            self.app.gui_stop_all_now,
            style="Danger.TButton",
        )
        self.app.experiment_stop_button.grid(row=0, column=1, sticky="e")

    def _build_step1(self) -> None:
        card = create_card(
            self.step_container,
            self.t("workflow.step1.title"),
            self.t("workflow.step1.description"),
        )
        self.step_frames[1] = card
        card.columnconfigure(1, weight=1)
        row = 2
        for key, variable in (
            ("workflow.field.condition", self.app.condition_var),
            ("workflow.field.dish_id", self.app.dish_id_var),
        ):
            self._bind_label(card, key, style="Card.TLabel").grid(row=row, column=0, sticky="w", pady=3)
            ttk.Entry(card, textvariable=variable).grid(row=row, column=1, sticky="ew", pady=3)
            row += 1

        shortcuts = ttk.Frame(card, style="Card.TFrame")
        shortcuts.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(6, 8))
        for column in range(3):
            shortcuts.columnconfigure(column, weight=1)
        self._bind_button(shortcuts, "workflow.action.use_previous", self.use_previous_conditions).grid(
            row=0, column=0, sticky="ew", padx=(0, 3)
        )
        self._bind_button(shortcuts, "workflow.action.choose_recent", self.choose_recent_conditions).grid(
            row=0, column=1, sticky="ew", padx=3
        )
        self._bind_button(shortcuts, "workflow.action.choose_template", self.focus_template).grid(
            row=0, column=2, sticky="ew", padx=(3, 0)
        )
        row += 1

        self._bind_label(card, "workflow.field.in_flow", style="Card.TLabel").grid(row=row, column=0, sticky="w", pady=3)
        flow = ttk.Frame(card, style="Card.TFrame")
        flow.grid(row=row, column=1, sticky="ew", pady=3)
        flow.columnconfigure(0, weight=1)
        self.app.in_flow_entry = ttk.Entry(flow, textvariable=self.app.in_flow_var, width=10)
        self.app.in_flow_entry.grid(row=0, column=0, sticky="ew")
        ttk.Label(flow, text="mL/min", style="Card.TLabel").grid(row=0, column=1, padx=(6, 0))
        row += 1
        presets = ttk.Frame(card, style="Card.TFrame")
        presets.grid(row=row, column=1, sticky="ew", pady=(0, 6))
        for column, value in enumerate((0.5, 1.0, 2.0, 3.0)):
            presets.columnconfigure(column, weight=1)
            ttk.Button(
                presets,
                text=f"{value:.1f}",
                style="NeutralCompact.TButton",
                command=lambda selected=value: self.app.set_flow(selected),
            ).grid(row=0, column=column, sticky="ew", padx=(0 if column == 0 else 2, 0))
        row += 1

        self.app.perfusion_mode_display_var = tk.StringVar(
            value=self.app.localizer.display_value(self.app.perfusion_mode_var.get())
        )
        self._bind_label(card, "workflow.field.target_type", style="Card.TLabel").grid(row=row, column=0, sticky="w", pady=3)
        self.app.perfusion_mode_combo = ttk.Combobox(
            card,
            textvariable=self.app.perfusion_mode_display_var,
            state="readonly",
        )
        self.app.perfusion_mode_combo.grid(row=row, column=1, sticky="ew", pady=3)
        self.app.perfusion_mode_combo.bind("<<ComboboxSelected>>", self.app._on_perfusion_mode_display_selected, add="+")
        row += 1

        self.target_volume_label = self._bind_label(card, "workflow.field.target_volume", style="Card.TLabel")
        self.target_volume_label.grid(row=row, column=0, sticky="w", pady=3)
        self.target_volume_entry = ttk.Entry(card, textvariable=self.app.target_volume_ml_var)
        self.target_volume_entry.grid(row=row, column=1, sticky="ew", pady=3)
        row += 1
        self.duration_label = self._bind_label(card, "workflow.field.duration", style="Card.TLabel")
        self.duration_label.grid(row=row, column=0, sticky="w", pady=3)
        self.duration_entry = ttk.Entry(card, textvariable=self.app.fixed_duration_s_var)
        self.duration_entry.grid(row=row, column=1, sticky="ew", pady=3)
        row += 1

        self._bind_label(card, "workflow.field.out_method", style="Card.TLabel").grid(row=row, column=0, sticky="w", pady=3)
        out_mode = ttk.Frame(card, style="Card.TFrame")
        out_mode.grid(row=row, column=1, sticky="ew", pady=3)
        self.ratio_lock_check = ttk.Checkbutton(
            out_mode,
            text=self.t("workflow.field.use_ratio"),
            variable=self.app.out_ratio_locked_var,
            command=self.app.update_ratio_widgets,
        )
        self.ratio_lock_check.grid(row=0, column=0, sticky="w")
        row += 1
        self.out_ratio_label = self._bind_label(card, "workflow.field.out_ratio", style="Card.TLabel")
        self.out_ratio_label.grid(row=row, column=0, sticky="w", pady=3)
        self.app.out_ratio_entry = ttk.Entry(card, textvariable=self.app.out_ratio_var)
        self.app.out_ratio_entry.grid(row=row, column=1, sticky="ew", pady=3)
        row += 1
        self.independent_out_label = self._bind_label(card, "workflow.field.out_flow", style="Card.TLabel")
        self.independent_out_label.grid(row=row, column=0, sticky="w", pady=3)
        self.app.independent_out_flow_entry = ttk.Entry(card, textvariable=self.app.independent_out_flow_var)
        self.app.independent_out_flow_entry.grid(row=row, column=1, sticky="ew", pady=3)
        row += 1

        syringe_values = tuple(self.app.data["syringes"])
        self._bind_label(card, "workflow.field.in_syringe", style="Card.TLabel").grid(row=row, column=0, sticky="w", pady=3)
        self.app.in_syringe_combo = ttk.Combobox(
            card, textvariable=self.app.in_syringe_var, values=syringe_values, state="readonly"
        )
        self.app.in_syringe_combo.grid(row=row, column=1, sticky="ew", pady=3)
        row += 1
        self.same_syringe_check = ttk.Checkbutton(
            card,
            text=self.t("workflow.field.same_out_syringe"),
            variable=self.app.same_out_syringe_var,
            command=self.app.on_same_syringe,
        )
        self.same_syringe_check.grid(row=row, column=0, columnspan=2, sticky="w", pady=3)
        row += 1
        self.out_syringe_row = row
        self.out_syringe_label = self._bind_label(card, "workflow.field.out_syringe", style="Card.TLabel")
        self.out_syringe_label.grid(row=row, column=0, sticky="w", pady=3)
        self.app.out_syringe_combo = ttk.Combobox(
            card, textvariable=self.app.out_syringe_var, values=syringe_values, state="readonly"
        )
        self.app.out_syringe_combo.grid(row=row, column=1, sticky="ew", pady=3)
        row += 1

        self._bind_label(card, "workflow.field.start_mode", style="Card.TLabel").grid(row=row, column=0, sticky="w", pady=3)
        start_source = ttk.Frame(card, style="Card.TFrame")
        start_source.grid(row=row, column=1, sticky="ew", pady=3)
        self.start_source_nis = ttk.Radiobutton(
            start_source, variable=self.start_mode_var, value="nis", command=self._on_start_source_changed
        )
        self.start_source_gui = ttk.Radiobutton(
            start_source, variable=self.start_mode_var, value="gui", command=self._on_start_source_changed
        )
        self.start_source_nis.grid(row=0, column=0, sticky="w", padx=(0, 12))
        self.start_source_gui.grid(row=0, column=1, sticky="w")
        row += 1
        self._bind_label(card, "workflow.field.start_timing", style="Card.TLabel").grid(row=row, column=0, sticky="w", pady=3)
        timing = ttk.Frame(card, style="Card.TFrame")
        timing.grid(row=row, column=1, sticky="ew", pady=3)
        self.start_immediate = ttk.Radiobutton(
            timing, variable=self.start_timing_var, value="immediate", command=self._on_start_timing_changed
        )
        self.start_delayed = ttk.Radiobutton(
            timing, variable=self.start_timing_var, value="delayed", command=self._on_start_timing_changed
        )
        self.start_immediate.grid(row=0, column=0, sticky="w", padx=(0, 12))
        self.start_delayed.grid(row=0, column=1, sticky="w")
        row += 1
        self.delay_label = self._bind_label(card, "workflow.field.delay", style="Card.TLabel")
        self.delay_label.grid(row=row, column=0, sticky="w", pady=3)
        self.app.requested_start_delay_entry = ttk.Entry(card, textvariable=self.app.requested_start_delay_var)
        self.app.requested_start_delay_entry.grid(row=row, column=1, sticky="ew", pady=3)
        row += 1

        self._bind_label(card, "workflow.field.template", style="Card.TLabel").grid(row=row, column=0, sticky="w", pady=3)
        template = ttk.Frame(card, style="Card.TFrame")
        template.grid(row=row, column=1, sticky="ew", pady=3)
        template.columnconfigure(0, weight=1)
        self.template_combo = ttk.Combobox(template, textvariable=self.template_display_var, state="readonly")
        self.template_combo.grid(row=0, column=0, sticky="ew")
        self.apply_template_button = self._bind_button(
            template, "workflow.action.apply_template", self.apply_selected_template
        )
        self.apply_template_button.grid(row=0, column=1, padx=(6, 0))

        self.app.flow_slider = ttk.Scale(card, from_=0.1, to=3.0, variable=self.app.flow_slider_var)
        self.app.bound_entries = [self.target_volume_entry, self.duration_entry]
        self.app.setpoint_widgets = [
            self.app.perfusion_mode_combo,
            self.app.in_flow_entry,
            self.target_volume_entry,
            self.duration_entry,
            self.app.in_syringe_combo,
            self.app.out_syringe_combo,
            self.same_syringe_check,
            self.ratio_lock_check,
            self.app.out_ratio_entry,
            self.app.independent_out_flow_entry,
            self.app.requested_start_delay_entry,
        ]
        # Preserve the widget aliases used by the existing presentation refresh
        # code.  These are views over the same canonical Tk variables.
        self.app.same_syringe_check = self.same_syringe_check
        self.app.ratio_lock_check = self.ratio_lock_check
        self.app.experiment_setpoint_card = card

    def _build_step2(self) -> None:
        card = create_card(
            self.step_container,
            self.t("workflow.step2.title"),
            self.t("workflow.step2.description"),
        )
        self.step_frames[2] = card
        card.columnconfigure(1, weight=1)
        for row, role in enumerate(("IN", "OUT"), start=2):
            self._bind_label(card, f"workflow.field.{role.casefold()}_port", style="Card.TLabel").grid(
                row=row, column=0, sticky="w", pady=3
            )
            combo = ttk.Combobox(card, textvariable=self.app.port_vars[role], state="readonly")
            combo.grid(row=row, column=1, sticky="ew", pady=3)
            if role == "IN":
                self.workflow_in_port_combo = combo
            else:
                self.workflow_out_port_combo = combo
            ttk.Label(card, textvariable=self.step2_port_summary_vars[role], style="Subtitle.TLabel").grid(
                row=row + 2, column=1, sticky="ew", pady=(0, 4)
            )
        actions = ttk.Frame(card, style="Card.TFrame")
        actions.grid(row=6, column=0, columnspan=2, sticky="ew", pady=(10, 4))
        for column in range(3):
            actions.columnconfigure(column, weight=1)
        self.app.scan_ports_button = self._bind_button(
            actions, "action.scan_ports", self.app.scan_ports_async
        )
        self.app.scan_ports_button.grid(row=0, column=0, sticky="ew", padx=(0, 3))
        self.connection_test_button = self._bind_button(
            actions, "workflow.action.connection_check", lambda: self.app.connection_test_async(None)
        )
        self.connection_test_button.grid(row=0, column=1, sticky="ew", padx=3)
        self.app.experiment_write_button = self._bind_button(
            actions, "action.program_arm", self.app.program_arm_gui, style="Success.TButton"
        )
        self.app.experiment_write_button.grid(row=0, column=2, sticky="ew", padx=(3, 0))
        ttk.Label(card, textvariable=self.connection_result_var, style="Card.TLabel").grid(
            row=7, column=0, columnspan=2, sticky="ew", pady=(4, 0)
        )
        ttk.Label(card, textvariable=self.programming_result_var, style="Value.TLabel").grid(
            row=8, column=0, columnspan=2, sticky="ew", pady=(4, 0)
        )

    def _build_step3(self) -> None:
        card = create_card(
            self.step_container,
            self.t("workflow.step3.title"),
            self.t("workflow.step3.description"),
        )
        self.step_frames[3] = card
        card.columnconfigure(1, weight=1)
        for row, (key, variable) in enumerate(
            (
                ("workflow.field.selected_start", self.nis_wrapper_var),
                ("workflow.field.command_destination", self.nis_destination_var),
                ("workflow.field.config_agreement", self.nis_config_var),
            ),
            start=2,
        ):
            self._bind_label(card, key, style="Card.TLabel").grid(row=row, column=0, sticky="nw", pady=3)
            value = ttk.Label(card, textvariable=variable, style="Value.TLabel", justify="left", anchor="w")
            value._responsive_wrap_margin = 24  # type: ignore[attr-defined]
            value.grid(row=row, column=1, sticky="ew", pady=3)
        actions = ttk.Frame(card, style="Card.TFrame")
        actions.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(8, 8))
        for column in range(2):
            actions.columnconfigure(column, weight=1)
        for index, (key, command) in enumerate(
            (
                ("workflow.action.copy_start", self.copy_start_command),
                ("workflow.action.copy_stop", self.copy_stop_command),
                ("workflow.action.open_command_folder", self.open_command_folder),
                ("workflow.action.check_nis_config", self.check_nis_config),
            )
        ):
            self._bind_button(actions, key, command).grid(
                row=index // 2,
                column=index % 2,
                sticky="ew",
                padx=(0 if index % 2 == 0 else 3, 3 if index % 2 == 0 else 0),
                pady=3,
            )
        self._bind_label(card, "workflow.checklist.title", style="SectionTitle.TLabel").grid(
            row=6, column=0, columnspan=2, sticky="w", pady=(8, 4)
        )
        self.checklist_widgets: dict[str, ttk.Checkbutton] = {}
        for row, key in enumerate(("imaging", "fluid_path", "nis_macro"), start=7):
            widget = ttk.Checkbutton(card, variable=self.checklist_vars[key], style="Card.TCheckbutton")
            self.app.localizer.bind(widget, f"workflow.checklist.{key}")
            widget.grid(row=row, column=0, columnspan=2, sticky="w", pady=3)
            self.checklist_widgets[key] = widget
        warning = self._bind_label(card, "workflow.checklist.not_evidence", style="Warning.TLabel")
        warning._responsive_wrap_margin = 24  # type: ignore[attr-defined]
        warning.grid(row=10, column=0, columnspan=2, sticky="ew", pady=(8, 0))

    def _build_step4(self) -> None:
        card = create_card(
            self.step_container,
            self.t("workflow.step4.title"),
            self.t("workflow.step4.description"),
        )
        self.step_frames[4] = card
        card.columnconfigure(0, weight=1)
        instruction = ttk.Label(
            card, textvariable=self.run_instruction_var, style="Value.TLabel", justify="left", anchor="w"
        )
        instruction._responsive_wrap_margin = 24  # type: ignore[attr-defined]
        instruction.grid(row=2, column=0, sticky="ew", pady=(0, 10))
        for row, variable in enumerate(
            (
                self.run_readiness_var,
                self.run_programming_var,
                self.run_start_mode_var,
                self.run_state_var,
            ),
            start=3,
        ):
            label = ttk.Label(card, textvariable=variable, style="Value.TLabel", justify="left", anchor="w")
            label._responsive_wrap_margin = 24  # type: ignore[attr-defined]
            label.grid(row=row, column=0, sticky="ew", pady=3)
        self.app.experiment_start_button = self._bind_button(
            card, "workflow.action.gui_start_alternative", self.app.start_armed_gui, style="Outline.TButton"
        )
        self.app.experiment_start_button.grid(row=7, column=0, sticky="ew", pady=(12, 4))

    def _build_technical_details(self) -> None:
        card = create_card(
            self.step_container,
            self.t("workflow.technical.title"),
            self.t("workflow.technical.description"),
        )
        card.columnconfigure(0, weight=1)
        self.app.experiment_preview_card = card
        preview = ttk.Label(
            card,
            textvariable=self.app.perfusion_preview_var,
            style="Card.TLabel",
            justify="left",
            anchor="w",
            font=("Consolas", 9),
        )
        preview._responsive_wrap_margin = 24  # type: ignore[attr-defined]
        preview.grid(row=2, column=0, sticky="ew")
        self.full_config_var = tk.StringVar(value=str(self.app.config_resolution.active_config_dir))
        ttk.Entry(card, textvariable=self.full_config_var, state="readonly").grid(
            row=3, column=0, sticky="ew", pady=(8, 0)
        )
        self._bind_button(card, "action.copy_path", self.app.copy_config_path).grid(
            row=4, column=0, sticky="w", pady=(5, 0)
        )
        self.app.run_log = tk.Text(card, height=4, wrap="word", font=("Consolas", 8))
        self.app.run_log.grid(row=5, column=0, sticky="ew", pady=(8, 0))
        self.app.dashboard_fault_actions = ttk.Frame(card, style="Card.TFrame")
        self.app.dashboard_fault_actions.grid(row=6, column=0, sticky="ew", pady=(6, 0))
        self.app.fault_details_button = self._bind_button(
            self.app.dashboard_fault_actions,
            "fault.technical_details",
            self.app.toggle_fault_details,
            style="NeutralCompact.TButton",
        )
        self.app.fault_details_button.pack(side="left")
        self.app.fault_ack_button = self._bind_button(
            self.app.dashboard_fault_actions,
            "fault.acknowledge",
            self.app.acknowledge_historical_fault,
            style="NeutralCompact.TButton",
        )
        self.app.fault_raw_label = ttk.Label(
            card,
            textvariable=self.app.dashboard_fault_raw_var,
            style="Subtitle.TLabel",
            justify="left",
            anchor="w",
        )
        self.app.fault_raw_label._responsive_wrap_margin = 24  # type: ignore[attr-defined]
        card.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        card.grid_remove()
        self.technical_card = card

    def _schedule_layout(self, _event: tk.Event | None = None) -> None:
        if self._layout_job is not None:
            try:
                self.after_cancel(self._layout_job)
            except tk.TclError:
                pass
        self._layout_job = self.after(70, self._apply_layout)

    def _apply_layout(self) -> None:
        self._layout_job = None
        width = max(1, self.winfo_width())
        wide = width >= self.WIDE_BREAKPOINT
        self.step_scroll.grid_forget()
        self.summary_card.grid_forget()
        if wide:
            self.workspace.columnconfigure(0, weight=3)
            self.workspace.columnconfigure(1, weight=1, minsize=260)
            self.workspace.rowconfigure(0, weight=1)
            self.workspace.rowconfigure(1, weight=0)
            self.step_scroll.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
            self.summary_card.grid(row=0, column=1, sticky="nsew")
            self.compact_summary_label.grid_remove()
            for row, label in enumerate(self.summary_labels, start=2):
                label.grid(row=row, column=0, sticky="ew", pady=(0, 3))
            self.layout_mode = "wide"
        else:
            self.workspace.columnconfigure(0, weight=1)
            self.workspace.columnconfigure(1, weight=0, minsize=0)
            self.workspace.rowconfigure(0, weight=1)
            self.workspace.rowconfigure(1, weight=0)
            self.step_scroll.grid(row=0, column=0, sticky="nsew")
            self.summary_card.grid(row=1, column=0, sticky="ew", pady=(8, 0))
            for label in self.summary_labels:
                label.grid_remove()
            self.compact_summary_label.grid(row=2, column=0, sticky="ew", pady=(0, 3))
            self.layout_mode = "narrow"
        for button in self.step_buttons.values():
            button.grid_forget()
        for column in range(4):
            self.progress_buttons_frame.columnconfigure(column, weight=1)
        for index, button in self.step_buttons.items():
            button.grid(row=0, column=index - 1, sticky="ew", padx=(0 if index == 1 else 3, 0))
        self.step_scroll.canvas.configure(scrollregion=self.step_scroll.canvas.bbox("all"))

    def conditions_complete(self) -> bool:
        return bool(
            self.app.current_perfusion_setpoint is not None
            and self.app.condition_var.get().strip()
            and self.app.dish_id_var.get().strip()
        )

    def programmed(self) -> bool:
        return str(self.app._operational_state).upper() in self.PROGRAMMED_STATES

    def checklist_complete(self) -> bool:
        return all(variable.get() for variable in self.checklist_vars.values())

    def highest_accessible_step(self) -> int:
        if not self.conditions_complete():
            return 1
        if not self.programmed():
            return 2
        if not self._nis_ready:
            return 3
        return 4

    def can_enter_step(self, step: int) -> bool:
        return 1 <= step <= self.highest_accessible_step() or step < self.current_step

    def go_to_step(self, step: int) -> bool:
        if not self.can_enter_step(step):
            self.notice_var.set(self.t("workflow.notice.prerequisites"))
            return False
        self.current_step = step
        for index, frame in self.step_frames.items():
            if index == step:
                frame.grid(row=0, column=0, sticky="ew")
            else:
                frame.grid_remove()
        if self._technical_visible:
            self.technical_card.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        self.step_scroll.scroll_home()
        self.refresh()
        return True

    def activate_primary_action(self) -> None:
        if self.current_step == 1:
            if not self.conditions_complete():
                self.notice_var.set(self.t("workflow.notice.complete_conditions"))
                return
            self._last_conditions = self._condition_snapshot()
            self.go_to_step(2)
        elif self.current_step == 2:
            if not self.programmed():
                self.notice_var.set(self.t("workflow.notice.program_first"))
                return
            self.go_to_step(3)
        elif self.current_step == 3:
            if not self.checklist_complete():
                self.notice_var.set(self.t("workflow.notice.complete_checklist"))
                return
            if not self.nis_timing_supported():
                self.notice_var.set(self.t("workflow.notice.nis_delay_unsupported"))
                return
            self._nis_ready = True
            self._invalidation_reason = ""
            self.go_to_step(4)
        else:
            if self.start_mode_var.get() == "gui":
                self.app.start_armed_gui()
            else:
                self.copy_start_command()

    def invalidate_after_conditions(self, message_key: str = "workflow.notice.conditions_changed") -> None:
        if getattr(self.app, "_loading_settings", False):
            return
        requires_explanation = (
            self._programming_observed
            or self.programmed()
            or self._nis_ready
            or self.current_step > 1
        )
        self._nis_ready = False
        for variable in self.checklist_vars.values():
            variable.set(False)
        self._invalidation_reason = message_key if requires_explanation else ""
        if self.current_step > 2:
            self.current_step = 1
        self.refresh()

    def invalidate_after_hardware(self) -> None:
        self._connection_checked = False
        self.connection_result_var.set(self.t("workflow.connection.not_checked"))
        self.invalidate_after_conditions("workflow.notice.hardware_changed")

    def _on_checklist_changed(self, *_args: Any) -> None:
        if not self.checklist_complete():
            self._nis_ready = False
        self.refresh()

    def _on_notice_visibility_changed(self, *_args: Any) -> None:
        if self.notice_var.get().strip():
            self.notice_label.grid()
        else:
            self.notice_label.grid_remove()

    def on_connection_succeeded(self, messages: list[str]) -> None:
        self._connection_checked = True
        self.connection_result_var.set(self.t("workflow.connection.complete", count=len(messages)))
        self.refresh()

    def on_programming_succeeded(self) -> None:
        self._programming_observed = True
        self._invalidation_reason = ""
        self.refresh()

    def refresh(self) -> None:
        state = str(self.app._operational_state).upper()
        if state == "ARMED":
            self._programming_observed = True
        if state in {"FAULT", "STOP_FAILED"}:
            workflow_state = "FAULT"
        elif state in self.ACTIVE_STATES:
            workflow_state = "RUNNING"
        elif state == "STOPPED":
            workflow_state = "STOPPED"
        elif self._invalidation_reason:
            workflow_state = "REVIEW"
        elif not self.conditions_complete():
            workflow_state = "UNSET"
        elif self.current_step == 1 and not self.programmed():
            workflow_state = "INPUT_COMPLETE"
        elif not self.programmed():
            workflow_state = "NEEDS_PROGRAMMING"
        elif self.current_step <= 2 and not self._nis_ready:
            workflow_state = "PROGRAMMED"
        elif not self._nis_ready:
            workflow_state = "NEEDS_NIS"
        else:
            workflow_state = "READY"
        self.workflow_status_var.set(self.t(f"workflow.status.{workflow_state.casefold()}"))
        self.notice_var.set(self.t(self._invalidation_reason) if self._invalidation_reason else "")
        self._update_progress(state)
        self._update_summary()
        self._update_step_controls()
        self._update_nis()
        self._update_run_status()
        self._update_target_fields()
        self._update_out_fields()
        self._show_current_step()

    def _update_progress(self, runtime_state: str) -> None:
        complete = {
            1: self.conditions_complete(),
            2: self.programmed(),
            3: self._nis_ready,
            4: runtime_state in self.ACTIVE_STATES | {"STOPPED", "COMPLETED_ESTIMATED"},
        }
        highest = self.highest_accessible_step()
        for index in range(1, 5):
            if complete[index]:
                icon = "✓"
                status_key = "workflow.progress.completed"
            elif index == self.current_step:
                icon = "●"
                status_key = "workflow.progress.current"
            elif index <= highest:
                icon = "○"
                status_key = "workflow.progress.review"
            else:
                icon = "!"
                status_key = "workflow.progress.blocked"
            title = self.t(f"workflow.step{index}.progress")
            self.step_status_vars[index].set(
                self.t("workflow.progress.item", icon=icon, step=index, title=title, status=self.t(status_key))
            )
            self.step_buttons[index].configure(
                state="normal" if self.can_enter_step(index) else "disabled",
                style="Primary.TButton" if index == self.current_step else "Neutral.TButton",
            )

    def _update_summary(self) -> None:
        condition = self.app.condition_var.get().strip() or self.t("workflow.value.not_set")
        dish = self.app.dish_id_var.get().strip() or self.t("workflow.value.not_set")
        self.summary_condition_var.set(self.t("workflow.summary.condition", condition=condition, dish=dish))
        result = self.app.current_perfusion_setpoint
        if result is None:
            in_flow = out_flow = duration = in_volume = out_volume = self.t("workflow.value.not_set")
        else:
            in_flow = f"{result.in_setpoint.requested_flow_ml_min:g}"
            out_flow = (
                f"{result.out_setpoint.requested_flow_ml_min:g}"
                if self.app.is_pump_enabled("OUT")
                else self.t("label.disabled")
            )
            duration = f"{result.programmed_duration_s:g}"
            in_volume = f"{result.in_setpoint.expected_volume_ml:g}"
            out_volume = (
                f"{result.out_setpoint.expected_volume_ml:g}"
                if self.app.is_pump_enabled("OUT")
                else self.t("label.disabled")
            )
        out_enabled = self.app.is_pump_enabled("OUT")
        if out_enabled:
            self.summary_flow_var.set(self.t("workflow.summary.flow", in_flow=in_flow, out_flow=out_flow))
            self.summary_target_var.set(
                self.t(
                    "workflow.summary.target",
                    duration=duration,
                    in_volume=in_volume,
                    out_volume=out_volume,
                )
            )
        else:
            self.summary_flow_var.set(self.t("workflow.summary.flow_in_only", in_flow=in_flow))
            self.summary_target_var.set(
                self.t("workflow.summary.target_in_only", duration=duration, in_volume=in_volume)
            )
        out_port = self.app.port_vars["OUT"].get() if self.app.is_pump_enabled("OUT") else self.t("label.disabled")
        self.summary_ports_var.set(
            self.t(
                "workflow.summary.ports",
                in_port=self.app.port_vars["IN"].get() or self.t("workflow.value.not_set"),
                out_port=out_port or self.t("workflow.value.not_set"),
            )
        )
        self.summary_status_var.set(self.t("workflow.summary.status", status=self.workflow_status_var.get()))
        compact_key = "workflow.summary.compact" if out_enabled else "workflow.summary.compact_in_only"
        self.compact_summary_var.set(
            self.t(
                compact_key,
                condition=condition,
                in_flow=in_flow,
                out_flow=out_flow,
                duration=duration,
                in_port=self.app.port_vars["IN"].get() or self.t("workflow.value.not_set"),
                out_port=out_port or self.t("workflow.value.not_set"),
                status=self.workflow_status_var.get(),
            )
        )

    def _update_step_controls(self) -> None:
        primary = {
            1: "workflow.action.next_setup",
            2: "workflow.action.next_nis",
            3: "workflow.action.ready",
            4: "workflow.action.copy_start" if self.start_mode_var.get() == "nis" else "workflow.action.gui_start",
        }[self.current_step]
        self.primary_action_button.configure(text=self.t(primary))
        enabled = {
            1: self.conditions_complete(),
            2: self.programmed(),
            3: self.programmed() and self.checklist_complete() and self.nis_timing_supported(),
            4: self._nis_ready and str(self.app._operational_state).upper() == "ARMED",
        }[self.current_step]
        self.primary_action_button.configure(state="normal" if enabled else "disabled")
        self.app.experiment_start_button.configure(
            text=self.t("workflow.action.gui_start_alternative"),
            style="Outline.TButton" if self.start_mode_var.get() == "nis" else "Primary.TButton",
        )
        self.programming_result_var.set(
            self.t("label.programmed_not_read")
            if self.programmed()
            else self.t("workflow.programming.required")
        )

    def _update_nis(self) -> None:
        wrapper = self._start_wrapper_name()
        delay = self._start_delay()
        timing = (
            self.t("workflow.value.delayed", seconds=f"{delay:g}")
            if delay > 0
            else self.t("workflow.value.immediate")
        )
        self.nis_wrapper_var.set(self.t("workflow.nis.selection", timing=timing, wrapper=wrapper))
        self.nis_destination_var.set(wrapper)
        expected = (app_base_dir() / "config").resolve()
        active = self.app.config_resolution.active_config_dir.resolve()
        config_text = self.t("workflow.nis.config_match" if active == expected else "workflow.nis.config_review")
        if not self.nis_timing_supported():
            config_text += "\n" + self.t("workflow.nis.delay_unsupported", seconds=f"{delay:g}")
        self.nis_config_var.set(config_text)

    def _update_run_status(self) -> None:
        nis = self.start_mode_var.get() == "nis"
        self.run_instruction_var.set(
            self.t("workflow.run.start_from_nis" if nis else "workflow.run.gui_alternative")
        )
        self.run_state_var.set(
            self.t("workflow.run.state", state=self.app.localizer.state_label(self.app._operational_state))
        )
        self.run_programming_var.set(
            self.t(
                "workflow.run.programming",
                result=self.t("label.programmed_not_read") if self.programmed() else self.t("workflow.programming.required"),
            )
        )
        self.run_start_mode_var.set(
            self.t(
                "workflow.run.start_mode",
                mode=self.t("workflow.value.nis" if nis else "workflow.value.gui"),
                timing=self.t("workflow.value.immediate")
                if self._start_delay() == 0
                else self.t("workflow.value.delayed", seconds=f"{self._start_delay():g}"),
            )
        )
        safety = getattr(self.app, "dashboard_safety_var", None)
        safety_text = safety.get() if safety is not None else ""
        self.run_readiness_var.set(
            self.t("workflow.run.readiness", readiness=self.workflow_status_var.get(), safety=safety_text)
        )
        show_timing = str(self.app._operational_state).upper() in self.ACTIVE_STATES
        if show_timing and self.app.runtime_detail_var.get():
            self.run_readiness_var.set(self.run_readiness_var.get() + "\n" + self.app.runtime_detail_var.get())

    def _update_target_fields(self) -> None:
        mode = self.app.perfusion_mode_var.get()
        self.target_volume_entry.configure(state="normal" if mode == "fixed_volume" else "disabled")
        self.duration_entry.configure(state="normal" if mode == "fixed_duration" else "disabled")
        delayed = self.start_timing_var.get() == "delayed"
        self.app.requested_start_delay_entry.configure(state="normal" if delayed else "disabled")

    def _update_out_fields(self) -> None:
        enabled = self.app.is_pump_enabled("OUT")
        out_state = "readonly" if enabled else "disabled"
        self.workflow_out_port_combo.configure(state=out_state)
        self.app.out_syringe_combo.configure(state=out_state if not self.app.same_out_syringe_var.get() else "disabled")
        self.same_syringe_check.configure(state="normal" if enabled else "disabled")
        self.ratio_lock_check.configure(state="normal" if enabled else "disabled")
        if not enabled:
            self.app.out_ratio_entry.configure(state="disabled")
            self.app.independent_out_flow_entry.configure(state="disabled")
        else:
            self.app.update_ratio_widgets()
        self._refresh_port_summaries()

    def _refresh_port_summaries(self) -> None:
        by_device = {str(item.get("device", "")).casefold(): item for item in self.app.detected_ports}
        for role in ("IN", "OUT"):
            if role == "OUT" and not self.app.is_pump_enabled("OUT"):
                self.step2_port_summary_vars[role].set(self.t("workflow.port.disabled"))
                continue
            device = self.app.port_vars[role].get().strip()
            metadata = by_device.get(device.casefold())
            if not device:
                text = self.t("workflow.port.missing")
            elif metadata is None:
                text = self.t("workflow.port.not_detected", device=device)
            else:
                identity = str(metadata.get("description") or metadata.get("product") or "").strip()
                text = self.t("workflow.port.detected", device=device, identity=identity or "—")
            self.step2_port_summary_vars[role].set(text)

    def _show_current_step(self) -> None:
        for index, frame in self.step_frames.items():
            if index == self.current_step:
                if not frame.winfo_manager():
                    frame.grid(row=0, column=0, sticky="ew")
            else:
                frame.grid_remove()

    def toggle_technical_details(self) -> None:
        self._technical_visible = not self._technical_visible
        if self._technical_visible:
            self.technical_card.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        else:
            self.technical_card.grid_remove()
        self.technical_toggle_button.configure(
            text=self.t("workflow.action.hide_technical" if self._technical_visible else "workflow.action.show_technical")
        )
        self.step_scroll.canvas.configure(scrollregion=self.step_scroll.canvas.bbox("all"))

    @property
    def technical_details_visible(self) -> bool:
        return self._technical_visible

    def _start_delay(self) -> float:
        try:
            return max(0.0, float(self.app.requested_start_delay_var.get() or 0))
        except ValueError:
            return 0.0

    def nis_timing_supported(self) -> bool:
        if self.start_mode_var.get() != "nis":
            return True
        delay = self._start_delay()
        return delay == 0.0 or abs(delay - 300.0) < 1e-9

    def _start_wrapper_name(self) -> str:
        return "pump_start_armed_after_300s.cmd" if self._start_delay() > 0 else "pump_start_armed.cmd"

    def _wrapper_path(self, filename: str) -> Path:
        return (app_base_dir() / "nis_cmd" / filename).resolve()

    def _nis_command(self, filename: str) -> str:
        return f'Int_ExecProgram("{self._wrapper_path(filename)}");'

    def copy_start_command(self) -> None:
        self.app._copy_text(self._nis_command(self._start_wrapper_name()), self.t("workflow.copy.start_label"))

    def copy_stop_command(self) -> None:
        self.app._copy_text(self._nis_command("pump_stop_all.cmd"), self.t("workflow.copy.stop_label"))

    def open_command_folder(self) -> None:
        self.app._open_path((app_base_dir() / "nis_cmd").resolve())

    def check_nis_config(self) -> None:
        expected = (app_base_dir() / "config").resolve()
        active = self.app.config_resolution.active_config_dir.resolve()
        key = "workflow.dialog.config_match" if active == expected else "workflow.dialog.config_review"
        messagebox.showinfo(
            self.t("workflow.dialog.nis_title"),
            self.t(key, active=str(active), expected=str(expected)),
            parent=self.app,
        )

    def _on_start_source_changed(self) -> None:
        self.app.trigger_var.set("NIS" if self.start_mode_var.get() == "nis" else "Manual")
        self.invalidate_after_conditions("workflow.notice.start_changed")

    def _on_start_timing_changed(self) -> None:
        self.app.requested_start_delay_var.set("300" if self.start_timing_var.get() == "delayed" else "0")

    def _on_template_selected(self, _event: tk.Event | None = None) -> None:
        return

    def _template_key(self) -> str | None:
        display = self.template_display_var.get()
        for key, profile in self.app.data["profiles"].items():
            if self._template_display(key, profile) == display:
                return key
        return None

    @staticmethod
    def _template_display(key: str, profile: dict[str, Any]) -> str:
        return f"{profile.get('display_name', key)} [{key}]"

    def focus_template(self) -> None:
        self.template_combo.focus_set()

    def apply_selected_template(self) -> None:
        key = self._template_key()
        if key is None:
            self.notice_var.set(self.t("workflow.notice.select_template"))
            return
        profile = self.app.data["profiles"][key]
        syringe_key = str(profile.get("syringe") or self.app.in_syringe_var.get())
        result = calculate_profile(profile, self.app.data["syringes"][syringe_key], syringe_key)
        if result.flow_ml_min is not None:
            flow = result.flow_ml_min
        elif result.estimated_volume_ul is not None and result.duration_s:
            flow = result.estimated_volume_ul / 1000.0 / (result.duration_s / 60.0)
        else:
            self.notice_var.set(self.t("workflow.notice.template_unusable"))
            return
        self.app.in_syringe_var.set(syringe_key)
        self.app.in_flow_var.set(f"{flow:g}")
        if result.duration_s:
            self.app.perfusion_mode_var.set("fixed_duration")
            self.app.fixed_duration_s_var.set(f"{result.duration_s:g}")
        elif result.target_volume_ul:
            self.app.perfusion_mode_var.set("fixed_volume")
            self.app.target_volume_ml_var.set(f"{result.target_volume_ul / 1000.0:g}")
        self.notice_var.set(self.t("workflow.notice.template_applied", template=profile.get("display_name", key)))

    def _condition_snapshot(self) -> dict[str, str]:
        return {
            "condition": self.app.condition_var.get(),
            "dish_id": self.app.dish_id_var.get(),
            "in_flow": self.app.in_flow_var.get(),
            "out_ratio": self.app.out_ratio_var.get(),
            "out_flow": self.app.independent_out_flow_var.get(),
            "duration": self.app.fixed_duration_s_var.get(),
            "volume": self.app.target_volume_ml_var.get(),
        }

    def use_previous_conditions(self) -> None:
        if self._last_conditions is not None:
            self._apply_condition_snapshot(self._last_conditions)
            return
        runs = recent_runs(self.app.config_resolution, limit=1)
        if not runs:
            self.notice_var.set(self.t("workflow.notice.no_recent"))
            return
        self._apply_recent_run(runs[0])

    def choose_recent_conditions(self) -> None:
        runs = recent_runs(self.app.config_resolution, limit=20)
        if not runs:
            self.notice_var.set(self.t("workflow.notice.no_recent"))
            return
        dialog = tk.Toplevel(self.app)
        dialog.title(self.t("workflow.recent.title"))
        dialog.transient(self.app)
        dialog.geometry("680x360")
        dialog.columnconfigure(0, weight=1)
        dialog.rowconfigure(0, weight=1)
        tree = ttk.Treeview(dialog, columns=("dish", "condition", "flow", "duration"), show="headings")
        for column, key in (
            ("dish", "workflow.field.dish_id"),
            ("condition", "workflow.field.condition"),
            ("flow", "workflow.field.in_flow"),
            ("duration", "workflow.field.duration"),
        ):
            tree.heading(column, text=self.t(key))
        for index, run in enumerate(runs):
            tree.insert(
                "",
                "end",
                iid=str(index),
                values=(run.get("dish_id", ""), run.get("condition", ""), run.get("in_flow_ml_min", ""), run.get("duration_s", "")),
            )
        tree.grid(row=0, column=0, sticky="nsew", padx=12, pady=12)

        def apply() -> None:
            selected = tree.selection()
            if selected:
                self._apply_recent_run(runs[int(selected[0])])
                dialog.destroy()

        self._bind_button(dialog, "workflow.action.use_selected", apply, style="Primary.TButton").grid(
            row=1, column=0, sticky="e", padx=12, pady=(0, 12)
        )
        if tree.get_children():
            tree.selection_set(tree.get_children()[0])
        tree.focus_set()

    def _apply_recent_run(self, run: dict[str, Any]) -> None:
        self.app.dish_id_var.set(str(run.get("dish_id", "")))
        self.app.condition_var.set(str(run.get("condition", "")))
        if run.get("in_flow_ml_min"):
            self.app.in_flow_var.set(str(run["in_flow_ml_min"]))
        if run.get("out_flow_ml_min") and run.get("in_flow_ml_min"):
            try:
                ratio = float(run["out_flow_ml_min"]) / float(run["in_flow_ml_min"])
                self.app.out_ratio_locked_var.set(True)
                self.app.out_ratio_var.set(f"{ratio:g}")
            except (TypeError, ValueError, ZeroDivisionError):
                pass
        if run.get("duration_s"):
            self.app.perfusion_mode_var.set("fixed_duration")
            self.app.fixed_duration_s_var.set(str(run["duration_s"]))

    def _apply_condition_snapshot(self, snapshot: dict[str, str]) -> None:
        self.app.condition_var.set(snapshot["condition"])
        self.app.dish_id_var.set(snapshot["dish_id"])
        self.app.in_flow_var.set(snapshot["in_flow"])
        self.app.out_ratio_var.set(snapshot["out_ratio"])
        self.app.independent_out_flow_var.set(snapshot["out_flow"])
        self.app.fixed_duration_s_var.set(snapshot["duration"])
        self.app.target_volume_ml_var.set(snapshot["volume"])

    def refresh_language(self) -> None:
        self.progress_card._card_title_label.configure(text=self.t("workflow.progress.title"))  # type: ignore[attr-defined]
        self.summary_card._card_title_label.configure(text=self.t("workflow.summary.title"))  # type: ignore[attr-defined]
        for index, frame in self.step_frames.items():
            frame._card_title_label.configure(text=self.t(f"workflow.step{index}.title"))  # type: ignore[attr-defined]
            frame._card_description_label.configure(text=self.t(f"workflow.step{index}.description"))  # type: ignore[attr-defined]
        self.technical_card._card_title_label.configure(text=self.t("workflow.technical.title"))  # type: ignore[attr-defined]
        self.technical_card._card_description_label.configure(text=self.t("workflow.technical.description"))  # type: ignore[attr-defined]
        self.ratio_lock_check.configure(text=self.t("workflow.field.use_ratio"))
        self.same_syringe_check.configure(text=self.t("workflow.field.same_out_syringe"))
        self.start_source_nis.configure(text=self.t("workflow.value.nis"))
        self.start_source_gui.configure(text=self.t("workflow.value.gui"))
        self.start_immediate.configure(text=self.t("workflow.value.immediate"))
        self.start_delayed.configure(text=self.t("workflow.value.delayed_short"))
        self.technical_toggle_button.configure(
            text=self.t("workflow.action.hide_technical" if self._technical_visible else "workflow.action.show_technical")
        )
        templates = [self._template_display(key, profile) for key, profile in self.app.data["profiles"].items()]
        self.template_combo.configure(values=templates)
        if templates and self.template_display_var.get() not in templates:
            self.template_display_var.set(templates[0])
        self.app.perfusion_mode_combo.configure(
            values=tuple(self.app.localizer.display_value(value) for value in ("fixed_volume", "fixed_duration", "bounded_continuous"))
        )
        self.app.perfusion_mode_display_var.set(self.app.localizer.display_value(self.app.perfusion_mode_var.get()))
        self.refresh()
