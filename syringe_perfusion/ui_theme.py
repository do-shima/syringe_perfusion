from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Literal


COLORS = {
    "background": "#F7F8FA",
    "card": "#FFFFFF",
    "surface": "#FFFFFF",
    "surface_muted": "#F3F4F6",
    "border": "#E3E7EE",
    "border_soft": "#E5E7EB",
    "border_subtle": "#EEF2F7",
    "text": "#1F2937",
    "muted": "#6B7280",
    "accent": "#2563EB",
    "primary": "#2563EB",
    "primary_hover": "#1D4ED8",
    "success": "#059669",
    "warning": "#D97706",
    "danger": "#DC2626",
    "danger_soft": "#FEE2E2",
    "success_soft": "#D1FAE5",
    "warning_soft": "#FEF3C7",
    "selection": "#E8F0FE",
    "sidebar": "#FFFFFF",
}

FONTS = {
    "body": ("Segoe UI", 10),
    "body_bold": ("Segoe UI", 10, "bold"),
    "title": ("Segoe UI", 16, "bold"),
    "section": ("Segoe UI", 12, "bold"),
    "subtitle": ("Segoe UI", 9),
    "value": ("Segoe UI", 14, "bold"),
    "badge": ("Segoe UI", 8, "bold"),
}


def apply_theme(root: tk.Tk | tk.Toplevel) -> ttk.Style:
    root.configure(background=COLORS["background"])
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass

    style.configure(".", font=FONTS["body"], foreground=COLORS["text"])
    style.configure("TFrame", background=COLORS["background"])
    style.configure("Page.TFrame", background=COLORS["background"])
    style.configure("Card.TFrame", background=COLORS["card"], relief="flat", borderwidth=0)
    style.configure("CardBorder.TFrame", background=COLORS["card"], relief="solid", borderwidth=1)
    style.configure("Sidebar.TFrame", background=COLORS["sidebar"], relief="solid", borderwidth=1)
    style.configure("Toolbar.TFrame", background=COLORS["card"])
    style.configure("StepCard.TFrame", background=COLORS["surface"], relief="flat", borderwidth=0)
    style.configure("StepCardSelected.TFrame", background=COLORS["selection"], relief="flat", borderwidth=0)
    style.configure("Log.TFrame", background=COLORS["surface"])
    style.configure("TLabel", background=COLORS["background"], foreground=COLORS["text"])
    style.configure("Card.TLabel", background=COLORS["card"], foreground=COLORS["text"])
    style.configure("StepCard.TLabel", background=COLORS["surface"], foreground=COLORS["text"])
    style.configure("StepCardSelected.TLabel", background=COLORS["selection"], foreground=COLORS["text"])
    style.configure("SectionTitle.TLabel", font=FONTS["section"], background=COLORS["card"], foreground=COLORS["text"])
    style.configure("PageTitle.TLabel", font=FONTS["title"], background=COLORS["background"], foreground=COLORS["text"])
    style.configure("Subtitle.TLabel", font=FONTS["subtitle"], background=COLORS["card"], foreground=COLORS["muted"])
    style.configure("PageSubtitle.TLabel", font=FONTS["subtitle"], background=COLORS["background"], foreground=COLORS["muted"])
    style.configure("Value.TLabel", font=FONTS["value"], background=COLORS["card"], foreground=COLORS["text"])
    style.configure("Muted.TLabel", font=FONTS["subtitle"], background=COLORS["background"], foreground=COLORS["muted"])

    _button(style, "TButton", "#FFFFFF", COLORS["text"], COLORS["border_soft"])
    _button(style, "Secondary.TButton", "#FFFFFF", COLORS["text"], COLORS["border_soft"])
    _button(style, "Ghost.TButton", COLORS["surface"], COLORS["text"], COLORS["surface"])
    _button(style, "Nav.TButton", COLORS["sidebar"], COLORS["text"], COLORS["sidebar"])
    _button(style, "NavSelected.TButton", COLORS["selection"], COLORS["primary"], COLORS["selection"])
    _button(style, "Sidebar.TButton", COLORS["sidebar"], COLORS["text"], COLORS["sidebar"])
    _button(style, "SidebarSelected.TButton", COLORS["selection"], COLORS["primary"], COLORS["selection"])
    _button(style, "Primary.TButton", COLORS["primary"], "#FFFFFF", COLORS["primary"], active=COLORS["primary_hover"])
    _button(style, "Accent.TButton", COLORS["primary"], "#FFFFFF", COLORS["primary"], active=COLORS["primary_hover"])
    _button(style, "Success.TButton", COLORS["success"], "#FFFFFF", COLORS["success"])
    _button(style, "Danger.TButton", COLORS["danger"], "#FFFFFF", COLORS["danger"])
    _button(style, "DangerSecondary.TButton", COLORS["danger_soft"], COLORS["danger"], COLORS["danger_soft"])
    _button(style, "Compact.TButton", "#FFFFFF", COLORS["text"], COLORS["border_soft"], padding=(8, 5))

    style.configure("TCheckbutton", background=COLORS["background"], foreground=COLORS["text"])
    style.configure("Card.TCheckbutton", background=COLORS["card"], foreground=COLORS["text"])
    style.configure("TEntry", fieldbackground="#FFFFFF", bordercolor=COLORS["border"], lightcolor=COLORS["border"])
    style.configure("TCombobox", fieldbackground="#FFFFFF", bordercolor=COLORS["border"], lightcolor=COLORS["border"])
    style.configure("TNotebook", background=COLORS["background"], borderwidth=0)
    style.configure("Hidden.TNotebook", background=COLORS["background"], borderwidth=0)
    style.layout("Hidden.TNotebook.Tab", [])

    style.configure("BadgeEnabled.TLabel", font=FONTS["badge"], background=COLORS["success_soft"], foreground=COLORS["success"], padding=(8, 3))
    style.configure("BadgeDisabled.TLabel", font=FONTS["badge"], background=COLORS["surface_muted"], foreground=COLORS["muted"], padding=(8, 3))
    style.configure("BadgeDryRun.TLabel", font=FONTS["badge"], background=COLORS["warning_soft"], foreground=COLORS["warning"], padding=(8, 3))
    style.configure("BadgeDanger.TLabel", font=FONTS["badge"], background=COLORS["danger_soft"], foreground=COLORS["danger"], padding=(8, 3))
    return style


def _button(
    style: ttk.Style,
    name: str,
    background: str,
    foreground: str,
    border: str,
    *,
    active: str | None = None,
    padding: tuple[int, int] = (14, 8),
) -> None:
    style.configure(
        name,
        background=background,
        foreground=foreground,
        bordercolor=border,
        lightcolor=border,
        darkcolor=border,
        padding=padding,
        relief="flat",
    )
    style.map(
        name,
        background=[("disabled", "#F3F4F6"), ("active", active or background)],
        foreground=[("disabled", "#9CA3AF"), ("active", foreground)],
    )


def create_card(
    parent: tk.Widget,
    title: str | None = None,
    description: str | None = None,
    *,
    wraplength: int = 620,
) -> ttk.Frame:
    outer = ttk.Frame(parent, style="Card.TFrame", padding=16)
    outer.columnconfigure(0, weight=1)
    if title:
        ttk.Label(outer, text=title, style="SectionTitle.TLabel").grid(row=0, column=0, sticky="w")
    if description:
        ttk.Label(outer, text=description, style="Subtitle.TLabel", wraplength=wraplength).grid(
            row=1 if title else 0, column=0, sticky="w", pady=(4, 10)
        )
    return outer


def create_section_header(parent: tk.Widget, title: str, subtitle: str | None = None) -> ttk.Frame:
    frame = ttk.Frame(parent, style="Page.TFrame")
    frame.columnconfigure(0, weight=1)
    ttk.Label(frame, text=title, style="PageTitle.TLabel").grid(row=0, column=0, sticky="w")
    if subtitle:
        ttk.Label(frame, text=subtitle, style="PageSubtitle.TLabel").grid(row=1, column=0, sticky="w", pady=(2, 0))
    return frame


def status_badge(
    parent: tk.Widget,
    text: str,
    kind: Literal["enabled", "disabled", "dryrun", "danger"] = "enabled",
) -> ttk.Label:
    style = {
        "enabled": "BadgeEnabled.TLabel",
        "disabled": "BadgeDisabled.TLabel",
        "dryrun": "BadgeDryRun.TLabel",
        "danger": "BadgeDanger.TLabel",
    }[kind]
    return ttk.Label(parent, text=text, style=style)


class ScrollableFrame(ttk.Frame):
    def __init__(self, parent: tk.Widget, *, height: int = 360) -> None:
        super().__init__(parent, style="Card.TFrame")
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.canvas = tk.Canvas(
            self,
            borderwidth=0,
            highlightthickness=0,
            background=COLORS["card"],
            height=height,
        )
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = ttk.Frame(self.canvas, style="Card.TFrame")
        self.window_id = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.scrollbar.grid(row=0, column=1, sticky="ns")
        self.inner.bind("<Configure>", self._on_inner_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self.canvas.bind("<Enter>", self._bind_mousewheel)
        self.canvas.bind("<Leave>", self._unbind_mousewheel)

    def _on_inner_configure(self, _event: tk.Event) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_configure(self, event: tk.Event) -> None:
        self.canvas.itemconfigure(self.window_id, width=event.width)

    def _bind_mousewheel(self, _event: tk.Event) -> None:
        self.bind_all("<MouseWheel>", self._on_mousewheel)
        self.bind_all("<Button-4>", self._on_mousewheel)
        self.bind_all("<Button-5>", self._on_mousewheel)

    def _unbind_mousewheel(self, _event: tk.Event) -> None:
        self.unbind_all("<MouseWheel>")
        self.unbind_all("<Button-4>")
        self.unbind_all("<Button-5>")

    def _on_mousewheel(self, event: tk.Event) -> str:
        number = getattr(event, "num", None)
        if number == 4:
            units = -1
        elif number == 5:
            units = 1
        else:
            delta = int(getattr(event, "delta", 0))
            units = -1 if delta > 0 else 1
        self.canvas.yview_scroll(units, "units")
        return "break"
