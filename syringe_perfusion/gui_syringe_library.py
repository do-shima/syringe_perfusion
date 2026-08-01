from __future__ import annotations

import json
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk
from typing import Any

from .config import load_config
from .syringe_library import (
    CSV_FIELDS,
    ImportPreview,
    apply_import,
    armed_syringe_keys,
    calibration_basis,
    export_library_csv,
    export_library_json,
    load_syringe_document,
    max_expected_volume_ml,
    parse_import_csv,
    parse_import_json,
    preview_import,
    syringe_display_name,
)
from .ui_theme import ScrollableFrame, create_card


class SyringeLibraryFrame(ttk.Frame):
    """Management UI over the pure, preview-first syringe library service."""

    def __init__(self, parent: tk.Widget, app: Any) -> None:
        super().__init__(parent, style="Page.TFrame")
        self.app = app
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        self.status_var = tk.StringVar()
        self._build()
        self.refresh_language()
        self.refresh()

    def t(self, key: str, **parameters: Any) -> str:
        return self.app.t(key, **parameters)

    def _build(self) -> None:
        header = create_card(self, self.t("syringe.library.title"), self.t("syringe.library.description"))
        header.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        self.header_card = header
        actions = ttk.Frame(header, style="Card.TFrame")
        actions.grid(row=2, column=0, sticky="ew")
        for column in range(4):
            actions.columnconfigure(column, weight=1)
        definitions = (
            ("syringe.action.import_json", self.import_json),
            ("syringe.action.import_csv", self.import_csv),
            ("syringe.action.export_json", self.export_json),
            ("syringe.action.export_csv", self.export_csv),
            ("syringe.action.add", self.add_manual),
            ("syringe.action.duplicate", self.duplicate_selected),
            ("syringe.action.edit", self.edit_selected),
            ("syringe.action.deactivate", self.deactivate_selected),
        )
        self.action_buttons: list[tuple[ttk.Button, str]] = []
        for index, (key, command) in enumerate(definitions):
            button = ttk.Button(actions, style="Neutral.TButton", command=command)
            button.grid(row=index // 4, column=index % 4, sticky="ew", padx=3, pady=3)
            self.action_buttons.append((button, key))
        self.provenance_button = ttk.Button(
            header,
            style="Outline.TButton",
            command=self.show_provenance,
        )
        self.provenance_button.grid(row=3, column=0, sticky="w", pady=(6, 0))

        table = ttk.Frame(self, style="Page.TFrame")
        table.grid(row=1, column=0, sticky="nsew")
        table.columnconfigure(0, weight=1)
        table.rowconfigure(0, weight=1)
        columns = ("key", "name", "label", "capacity", "basis", "active")
        self.tree = ttk.Treeview(table, columns=columns, show="headings", selectmode="browse")
        self.tree.grid(row=0, column=0, sticky="nsew")
        vertical = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        horizontal = ttk.Scrollbar(table, orient="horizontal", command=self.tree.xview)
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        self.tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        widths = {"key": 150, "name": 240, "label": 130, "capacity": 90, "basis": 130, "active": 80}
        for column in columns:
            self.tree.column(column, width=widths[column], minwidth=70, stretch=column in {"name", "label"})
        self.tree.bind("<Double-1>", lambda _event: self.edit_selected(), add="+")
        ttk.Label(self, textvariable=self.status_var, style="Subtitle.TLabel").grid(
            row=2, column=0, sticky="ew", pady=(6, 0)
        )

    def refresh(self) -> None:
        selected = self.tree.selection()
        selected_key = selected[0] if selected else ""
        self.tree.delete(*self.tree.get_children())
        for key, record in self.app.data.get("syringes", {}).items():
            basis = calibration_basis(record)
            capacity = record.get("nominal_volume_ml")
            self.tree.insert(
                "",
                "end",
                iid=key,
                values=(
                    key,
                    syringe_display_name(key, record),
                    record.get("physical_label", ""),
                    "" if capacity in (None, "") else f"{float(capacity):g} mL",
                    self.t(f"syringe.status.{basis['kind']}"),
                    self.t("syringe.value.active" if record.get("active", True) else "syringe.value.inactive"),
                ),
            )
        if selected_key and self.tree.exists(selected_key):
            self.tree.selection_set(selected_key)
        self.status_var.set(
            self.t("syringe.library.count", count=len(self.app.data.get("syringes", {})))
        )

    def refresh_language(self) -> None:
        self.header_card._card_title_label.configure(text=self.t("syringe.library.title"))  # type: ignore[attr-defined]
        self.header_card._card_description_label.configure(text=self.t("syringe.library.description"))  # type: ignore[attr-defined]
        for button, key in self.action_buttons:
            button.configure(text=self.t(key))
        self.provenance_button.configure(text=self.t("syringe.action.provenance"))
        for column, key in (
            ("key", "syringe.column.key"),
            ("name", "syringe.column.name"),
            ("label", "syringe.column.physical_label"),
            ("capacity", "syringe.column.capacity"),
            ("basis", "syringe.column.calibration"),
            ("active", "syringe.column.active"),
        ):
            self.tree.heading(column, text=self.t(key))
        self.refresh()

    def selected_key(self) -> str | None:
        selected = self.tree.selection()
        return selected[0] if selected else None

    def import_json(self) -> None:
        self._choose_import("json")

    def import_csv(self) -> None:
        self._choose_import("csv")

    def _choose_import(self, format_name: str) -> None:
        suffix = ".json" if format_name == "json" else ".csv"
        path = filedialog.askopenfilename(
            parent=self.app,
            title=self.t(f"syringe.action.import_{format_name}"),
            filetypes=[(format_name.upper(), f"*{suffix}")],
        )
        if not path:
            return
        try:
            text = Path(path).read_text(encoding="utf-8-sig")
            imported = parse_import_json(text) if format_name == "json" else parse_import_csv(text)
            document = load_syringe_document(self.app.config_resolution.active_config_dir)
            selected = {
                self.app.in_syringe_var.get(),
                self.app.out_syringe_var.get(),
                *armed_syringe_keys(self.app.config_resolution.active_config_dir),
            }
            preview = preview_import(document, imported, selected_keys=selected)
            self._show_import_preview(preview, Path(path).name, selected)
        except Exception as exc:
            messagebox.showerror(self.t("syringe.import.failed"), str(exc), parent=self.app)

    def _show_import_preview(
        self,
        preview: ImportPreview,
        source_name: str,
        selected_keys: set[str],
    ) -> None:
        dialog = tk.Toplevel(self.app)
        dialog.title(self.t("syringe.import.preview_title"))
        dialog.transient(self.app)
        dialog.geometry("820x460")
        dialog.columnconfigure(0, weight=1)
        dialog.rowconfigure(1, weight=1)
        counts = preview.counts
        ttk.Label(
            dialog,
            text=self.t(
                "syringe.import.summary",
                create=counts["create"],
                update=counts["update"],
                skip=counts["skip"],
                errors=counts["errors"],
            ),
            style="Value.TLabel",
        ).grid(row=0, column=0, sticky="ew", padx=12, pady=12)
        tree = ttk.Treeview(dialog, columns=("key", "action", "calibration", "selected"), show="headings")
        tree.grid(row=1, column=0, sticky="nsew", padx=12)
        choices = {item.key: item.default_action for item in preview.records}
        for column, key in (
            ("key", "syringe.column.key"),
            ("action", "syringe.import.action"),
            ("calibration", "syringe.column.calibration"),
            ("selected", "syringe.import.affected_selection"),
        ):
            tree.heading(column, text=self.t(key))
        for item in preview.records:
            tree.insert(
                "",
                "end",
                iid=item.key,
                values=(
                    item.key,
                    self.t(f"syringe.import.choice.{item.default_action}"),
                    self.t("syringe.import.changed" if item.calibration_changed else "syringe.import.unchanged"),
                    self.t("syringe.value.yes" if item.affects_selected else "syringe.value.no"),
                ),
            )
        errors = "\n".join(preview.errors)
        if errors:
            ttk.Label(dialog, text=errors, style="Danger.TLabel", justify="left").grid(
                row=2, column=0, sticky="ew", padx=12, pady=6
            )
        controls = ttk.Frame(dialog)
        controls.grid(row=3, column=0, sticky="ew", padx=12, pady=12)
        for column in range(5):
            controls.columnconfigure(column, weight=1)

        def set_choice(choice: str) -> None:
            selected = tree.selection()
            if not selected:
                return
            key = selected[0]
            choices[key] = choice  # type: ignore[assignment]
            values = list(tree.item(key, "values"))
            values[1] = self.t(f"syringe.import.choice.{choice}")
            tree.item(key, values=values)

        for column, choice in enumerate(("create_new", "update", "skip")):
            ttk.Button(
                controls,
                text=self.t(f"syringe.import.choice.{choice}"),
                style="Neutral.TButton",
                command=lambda value=choice: set_choice(value),
            ).grid(row=0, column=column, sticky="ew", padx=3)

        def apply() -> None:
            try:
                result = apply_import(
                    self.app.config_resolution.active_config_dir,
                    preview,
                    choices=choices,  # type: ignore[arg-type]
                    selected_keys=selected_keys,
                    source_name=source_name,
                )
                dialog.destroy()
                self._reload_after_apply(result)
            except Exception as exc:
                messagebox.showerror(self.t("syringe.import.failed"), str(exc), parent=dialog)

        ttk.Button(
            controls,
            text=self.t("syringe.import.apply"),
            style="Success.TButton",
            command=apply,
            state="disabled" if preview.errors else "normal",
        ).grid(row=0, column=3, sticky="ew", padx=3)
        ttk.Button(
            controls,
            text=self.t("action.close"),
            style="Neutral.TButton",
            command=dialog.destroy,
        ).grid(row=0, column=4, sticky="ew", padx=3)

    def add_manual(self) -> None:
        self._edit_dialog(None)

    def edit_selected(self) -> None:
        key = self.selected_key()
        if key:
            self._edit_dialog(key)

    def duplicate_selected(self) -> None:
        source = self.selected_key()
        if source is None:
            return
        key = simpledialog.askstring(
            self.t("syringe.duplicate.title"),
            self.t("syringe.duplicate.key"),
            parent=self.app,
        )
        if not key:
            return
        record = dict(self.app.data["syringes"][source])
        record["key"] = key.strip()
        record["physical_label"] = ""
        self._apply_rows([record], source_name=f"duplicate:{source}")

    def deactivate_selected(self) -> None:
        key = self.selected_key()
        if key is None:
            return
        if not messagebox.askyesno(
            self.t("syringe.deactivate.title"),
            self.t("syringe.deactivate.message", key=key),
            parent=self.app,
        ):
            return
        record = {"key": key, **dict(self.app.data["syringes"][key]), "active": False}
        self._apply_rows([record], source_name="manual-deactivate")

    def _edit_dialog(self, key: str | None) -> None:
        original = dict(self.app.data["syringes"].get(key, {})) if key else {}
        dialog = tk.Toplevel(self.app)
        dialog.title(self.t("syringe.edit.title" if key else "syringe.add.title"))
        dialog.transient(self.app)
        dialog.geometry("680x560")
        dialog.columnconfigure(0, weight=1)
        dialog.rowconfigure(0, weight=1)
        scroll = ScrollableFrame(dialog, height=450)
        scroll.grid(row=0, column=0, sticky="nsew", padx=12, pady=12)
        scroll.inner.columnconfigure(1, weight=1)
        variables: dict[str, tk.StringVar] = {}
        fields = (
            "key", "display_name", "manufacturer", "model", "physical_label",
            "nominal_volume_ml", "nominal_inner_diameter_mm", "calibrated_ul_per_mm",
            "calibration_date", "calibration_method", "calibration_validation_id",
            "replicate_count", "coefficient_of_variation_percent", "mean_error_percent",
            "maximum_usable_stroke_mm", "notes",
        )
        for row, field in enumerate(fields):
            ttk.Label(scroll.inner, text=self.t(f"syringe.field.{field}"), style="Card.TLabel").grid(
                row=row, column=0, sticky="nw", padx=(0, 8), pady=3
            )
            variable = tk.StringVar(value=str(key if field == "key" and key else original.get(field, "") or ""))
            variables[field] = variable
            ttk.Entry(scroll.inner, textvariable=variable, state="readonly" if field == "key" and key else "normal").grid(
                row=row, column=1, sticky="ew", pady=3
            )

        def save() -> None:
            row: dict[str, Any] = dict(original)
            for field, variable in variables.items():
                row[field] = variable.get().strip()
            try:
                self._apply_rows([row], source_name="manual-entry")
                dialog.destroy()
            except Exception as exc:
                messagebox.showerror(self.t("syringe.import.failed"), str(exc), parent=dialog)

        ttk.Button(dialog, text=self.t("action.apply"), style="Success.TButton", command=save).grid(
            row=1, column=0, sticky="e", padx=12, pady=(0, 12)
        )

    def _apply_rows(self, rows: list[dict[str, Any]], *, source_name: str) -> None:
        document = load_syringe_document(self.app.config_resolution.active_config_dir)
        selected = {
            self.app.in_syringe_var.get(),
            self.app.out_syringe_var.get(),
            *armed_syringe_keys(self.app.config_resolution.active_config_dir),
        }
        preview = preview_import(document, rows, selected_keys=selected)
        result = apply_import(
            self.app.config_resolution.active_config_dir,
            preview,
            selected_keys=selected,
            source_name=source_name,
        )
        self._reload_after_apply(result)

    def _reload_after_apply(self, result: dict[str, Any]) -> None:
        self.app.data = load_config(self.app.config_resolution)
        self.app._refresh_config_dependent_widgets()
        self.app.schedule_perfusion_preview()
        self.refresh()
        self.status_var.set(
            self.t("syringe.import.complete", count=len(result.get("applied", [])))
        )

    def export_json(self) -> None:
        output = filedialog.asksaveasfilename(
            parent=self.app,
            title=self.t("syringe.action.export_json"),
            defaultextension=".json",
            filetypes=[("JSON", "*.json")],
        )
        if output:
            export_library_json(self.app.config_resolution.active_config_dir, output)

    def export_csv(self) -> None:
        output = filedialog.asksaveasfilename(
            parent=self.app,
            title=self.t("syringe.action.export_csv"),
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv")],
        )
        if output:
            export_library_csv(self.app.config_resolution.active_config_dir, output)

    def show_provenance(self) -> None:
        key = self.selected_key()
        if key is None:
            return
        record = self.app.data["syringes"][key]
        basis = calibration_basis(record)
        maximum = max_expected_volume_ml(record)
        details = {
            "key": key,
            "calibration_basis": basis,
            "maximum_expected_volume_ml": maximum,
            "calibration_date": record.get("calibration_date", ""),
            "calibration_method": record.get("calibration_method", ""),
            "calibration_validation_id": record.get("calibration_validation_id", ""),
            "import_provenance": record.get("import_provenance", []),
            "notes": record.get("notes", record.get("calibration_note", "")),
            "csv_fields": CSV_FIELDS,
        }
        messagebox.showinfo(
            self.t("syringe.provenance.title"),
            json.dumps(details, ensure_ascii=False, indent=2),
            parent=self.app,
        )
