from __future__ import annotations

import json
import locale
import os
import string
import sys
import warnings
import weakref
from pathlib import Path
from typing import Any, Iterable, Mapping


SUPPORTED_LANGUAGES = ("en", "ja")
LANGUAGE_PREFERENCES = ("auto", "ja", "en")
DEFAULT_LANGUAGE = "en"

STATE_KEYS = {
    "ARMED": "state.armed",
    "DIRTY": "state.dirty",
    "PENDING": "state.pending",
    "STARTING": "state.starting",
    "STARTED": "state.started",
    "STOPPING": "state.stopping",
    "STOPPED": "state.stopped",
    "FAULT": "state.fault",
    "STOP_FAILED": "state.stop_failed",
    "COMPLETED_ESTIMATED": "state.completed_estimated",
    "CANCELLED": "state.cancelled",
    "IDLE": "state.idle",
}

DISPLAY_VALUE_KEYS = {
    "fixed_volume": "value.fixed_volume",
    "fixed_duration": "value.fixed_duration",
    "bounded_continuous": "value.bounded_continuous",
    "forward": "value.forward",
    "reverse": "value.reverse",
    "IN": "value.in",
    "OUT": "value.out",
    "PASS": "value.pass",
    "FAILED": "value.failed",
    "STALE": "value.stale",
    "NOT VALIDATED": "value.not_validated",
    "BLOCK": "value.block",
    "WARN": "value.warn",
    "INFO": "value.info",
    "SOFTWARE CHECK": "value.software_check",
    "UART COMMAND COMPLETED": "value.uart_completed",
    "MANUAL PHYSICAL CONFIRMATION": "value.manual_confirmation",
    "MEASURED RESULT": "value.measured_result",
    "SOFTWARE READY — HARDWARE VALIDATION INCOMPLETE": "value.software_ready_hardware_incomplete",
    "COMMISSIONING PARTIAL": "value.commissioning_partial",
    "COMMISSIONING CURRENT": "value.commissioning_current",
    "COMMISSIONING FAILED": "value.commissioning_failed",
    "COMMISSIONING STALE": "value.commissioning_stale",
}


def locale_resource_directories() -> list[Path]:
    result = [Path(__file__).resolve().parent / "locales"]
    bundle = getattr(sys, "_MEIPASS", None)
    if bundle:
        result.extend(
            (
                Path(bundle) / "syringe_perfusion" / "locales",
                Path(bundle) / "locales",
            )
        )
    return result


def load_catalog(
    language: str,
    *,
    resource_directories: Iterable[str | Path] | None = None,
) -> dict[str, str]:
    requested = language if language in SUPPORTED_LANGUAGES else DEFAULT_LANGUAGE
    directories = (
        [Path(item) for item in resource_directories]
        if resource_directories is not None
        else locale_resource_directories()
    )
    for directory in directories:
        path = directory / f"{requested}.json"
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(value, dict) or not all(
                isinstance(key, str) and isinstance(text, str) for key, text in value.items()
            ):
                raise ValueError("catalog must be a string-to-string object")
            return dict(value)
        except FileNotFoundError:
            continue
        except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
            warnings.warn(f"Locale catalog {path} could not be loaded: {exc}", RuntimeWarning)
    if requested != DEFAULT_LANGUAGE:
        return load_catalog(DEFAULT_LANGUAGE, resource_directories=directories)
    warnings.warn("English locale catalog is unavailable; localization keys will be shown.", RuntimeWarning)
    return {}


def detect_system_language(locale_name: str | None = None) -> str:
    try:
        detected = locale_name
        if detected is None:
            detected = locale.getlocale()[0]
        if not detected:
            detected = os.environ.get("LANG", "")
        normalized = str(detected or "").replace("-", "_").casefold()
        return (
            "ja"
            if normalized == "ja" or normalized.startswith("ja_") or normalized.startswith("japanese")
            else "en"
        )
    except Exception:
        return DEFAULT_LANGUAGE


def resolve_language(preference: str | None, *, locale_name: str | None = None) -> str:
    normalized = str(preference or "auto").casefold()
    if normalized == "auto":
        return detect_system_language(locale_name)
    return normalized if normalized in SUPPORTED_LANGUAGES else DEFAULT_LANGUAGE


def placeholder_names(template: str) -> set[str]:
    return {
        field_name.split(".", 1)[0].split("[", 1)[0]
        for _, field_name, _, _ in string.Formatter().parse(template)
        if field_name
    }


def validate_catalog_pair(english: Mapping[str, str], japanese: Mapping[str, str]) -> list[str]:
    errors: list[str] = []
    if set(english) != set(japanese):
        missing_ja = sorted(set(english) - set(japanese))
        missing_en = sorted(set(japanese) - set(english))
        if missing_ja:
            errors.append(f"missing Japanese keys: {', '.join(missing_ja)}")
        if missing_en:
            errors.append(f"missing English keys: {', '.join(missing_en)}")
    for key in sorted(set(english) & set(japanese)):
        if placeholder_names(english[key]) != placeholder_names(japanese[key]):
            errors.append(f"placeholder mismatch: {key}")
    return errors


class Localizer:
    """Central translation service with safe English fallback and widget bindings."""

    def __init__(
        self,
        preference: str = "auto",
        *,
        locale_name: str | None = None,
        resource_directories: Iterable[str | Path] | None = None,
    ) -> None:
        self.preference = preference if preference in LANGUAGE_PREFERENCES else "auto"
        self.locale_name = locale_name
        self._directories = list(resource_directories) if resource_directories is not None else None
        self.english = load_catalog("en", resource_directories=self._directories)
        self.japanese = load_catalog("ja", resource_directories=self._directories)
        self.language = resolve_language(self.preference, locale_name=locale_name)
        self._bindings: list[tuple[weakref.ReferenceType[Any], str, str]] = []
        self._bound_widget_ids: set[int] = set()
        self._missing: set[str] = set()
        self._literal_keys = {value: key for key, value in self.english.items()}
        self._literal_keys.update({value: key for key, value in self.japanese.items()})

    @property
    def catalog(self) -> Mapping[str, str]:
        return self.japanese if self.language == "ja" else self.english

    def t(self, key: str, **parameters: Any) -> str:
        template = self.catalog.get(key)
        if template is None:
            template = self.english.get(key)
            if key not in self._missing:
                self._missing.add(key)
                warnings.warn(f"Missing localization key: {key}", RuntimeWarning)
        if template is None:
            template = key
        try:
            return template.format(**parameters)
        except (KeyError, ValueError, IndexError) as exc:
            warnings.warn(f"Localization formatting failed for {key}: {exc}", RuntimeWarning)
            return self.english.get(key, key)

    def set_preference(self, preference: str, *, locale_name: str | None = None) -> bool:
        normalized = preference if preference in LANGUAGE_PREFERENCES else "auto"
        new_language = resolve_language(
            normalized,
            locale_name=self.locale_name if locale_name is None else locale_name,
        )
        changed = normalized != self.preference or new_language != self.language
        self.preference = normalized
        self.language = new_language
        if changed:
            self.refresh_bindings()
        return changed

    def bind(self, widget: Any, key: str, *, option: str = "text") -> Any:
        widget.configure(**{option: self.t(key)})
        identity = id(widget)
        if identity not in self._bound_widget_ids:
            self._bindings.append((weakref.ref(widget), key, option))
            self._bound_widget_ids.add(identity)
        return widget

    def bind_literal_tree(self, root: Any) -> None:
        """Register legacy literal widgets whose English text exists in the catalog."""
        widgets = [root]
        while widgets:
            widget = widgets.pop()
            try:
                widgets.extend(widget.winfo_children())
                if "text" not in widget.keys() or str(widget.cget("textvariable")):
                    continue
                current = str(widget.cget("text"))
            except Exception:
                continue
            key = self._literal_keys.get(current)
            if key is not None:
                self.bind(widget, key)

    def refresh_bindings(self) -> None:
        retained: list[tuple[weakref.ReferenceType[Any], str, str]] = []
        retained_ids: set[int] = set()
        for reference, key, option in self._bindings:
            widget = reference()
            if widget is None:
                continue
            try:
                if not widget.winfo_exists():
                    continue
                widget.configure(**{option: self.t(key)})
                retained.append((reference, key, option))
                retained_ids.add(id(widget))
            except Exception:
                continue
        self._bindings = retained
        self._bound_widget_ids = retained_ids

    def display_value(self, value: str) -> str:
        key = DISPLAY_VALUE_KEYS.get(value)
        return self.t(key) if key else value

    def translate_literal(self, value: str) -> str:
        key = self._literal_keys.get(value)
        return self.t(key) if key else value

    def canonical_value(self, display: str, candidates: Iterable[str]) -> str | None:
        for value in candidates:
            if self.display_value(value) == display:
                return value
        return None

    def state_label(self, state: str, *, include_code: bool = True) -> str:
        canonical = str(state or "IDLE").upper()
        key = STATE_KEYS.get(canonical)
        translated = self.t(key) if key else canonical
        if self.language == "ja" and include_code and translated != canonical:
            return f"{translated}（{canonical}）"
        return translated

    def language_choice(self, preference: str) -> str:
        return self.t(f"language.{preference}")

    def language_preference_from_display(self, display: str) -> str | None:
        for preference in LANGUAGE_PREFERENCES:
            if self.language_choice(preference) == display:
                return preference
        return None


GLOSSARY = {
    "Experiment": "実験",
    "Setup": "設定",
    "Advanced": "詳細設定",
    "Commissioning": "実機検証",
    "Preflight": "事前確認",
    "IN": "IN（送液側）",
    "OUT": "OUT（回収側）",
}
