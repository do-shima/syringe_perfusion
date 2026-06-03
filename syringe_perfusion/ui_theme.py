from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Literal


COLORS = {
    "background": "#F7F8FA",
    "card": "#FFFFFF",
    "border": "#E3E7EE",
    "text": "#1F2937",
    "muted": "#6B7280",
    "accent": "#2563EB",
    "success": "#059669",
    "warning": "#D97706",
    "danger": "#DC2626",
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
    style.configure("Card.TFrame", background=COLORS["card"], relief="solid", borderwidth=1)
    style.configure("Sidebar.TFrame", background=COLORS["sidebar"], relief="solid", borderwidth=1)
    style.configure("Toolbar.TFrame", background=COLORS["card"])
    style.configure("TLabel", background=COLORS["background"], foreground=COLORS["text"])
    style.configure("Card.TLabel", background=COLORS["card"], foreground=COLORS["text"])
    style.configure("SectionTitle.TLabel", font=FONTS["section"], background=COLORS["card"], foreground=COLORS["text"])
    style.configure("PageTitle.TLabel", font=FONTS["title"], background=COLORS["background"], foreground=COLORS["text"])
    style.configure("Subtitle.TLabel", font=FONTS["subtitle"], background=COLORS["card"], foreground=COLORS["muted"])
    style.configure("PageSubtitle.TLabel", font=FONTS["subtitle"], background=COLORS["background"], foreground=COLORS["muted"])
    style.configure("Value.TLabel", font=FONTS["value"], background=COLORS["card"], foreground=COLORS["text"])
    style.configure("Muted.TLabel", font=FONTS["subtitle"], background=COLORS["background"], foreground=COLORS["muted"])

    _button(style, "TButton", "#FFFFFF", COLORS["text"], COLORS["border"])
    _button(style, "Secondary.TButton", "#FFFFFF", COLORS["text"], COLORS["border"])
    _button(style, "Sidebar.TButton", COLORS["sidebar"], COLORS["text"], COLORS["sidebar"])
    _button(style, "SidebarSelected.TButton", COLORS["selection"], COLORS["accent"], COLORS["selection"])
    _button(style, "Accent.TButton", COLORS["accent"], "#FFFFFF", COLORS["accent"])
    _button(style, "Success.TButton", COLORS["success"], "#FFFFFF", COLORS["success"])
    _button(style, "Danger.TButton", COLORS["danger"], "#FFFFFF", COLORS["danger"])

    style.configure("TCheckbutton", background=COLORS["background"], foreground=COLORS["text"])
    style.configure("Card.TCheckbutton", background=COLORS["card"], foreground=COLORS["text"])
    style.configure("TEntry", fieldbackground="#FFFFFF", bordercolor=COLORS["border"], lightcolor=COLORS["border"])
    style.configure("TCombobox", fieldbackground="#FFFFFF", bordercolor=COLORS["border"], lightcolor=COLORS["border"])
    style.configure("TNotebook", background=COLORS["background"], borderwidth=0)
    style.configure("Hidden.TNotebook", background=COLORS["background"], borderwidth=0)
    style.layout("Hidden.TNotebook.Tab", [])

    style.configure("BadgeEnabled.TLabel", font=FONTS["badge"], background="#D1FAE5", foreground=COLORS["success"], padding=(8, 3))
    style.configure("BadgeDisabled.TLabel", font=FONTS["badge"], background="#F3F4F6", foreground=COLORS["muted"], padding=(8, 3))
    style.configure("BadgeDryRun.TLabel", font=FONTS["badge"], background="#FEF3C7", foreground=COLORS["warning"], padding=(8, 3))
    return style


def _button(style: ttk.Style, name: str, background: str, foreground: str, border: str) -> None:
    style.configure(
        name,
        background=background,
        foreground=foreground,
        bordercolor=border,
        lightcolor=border,
        darkcolor=border,
        padding=(12, 8),
        relief="flat",
    )
    style.map(
        name,
        background=[("disabled", "#F3F4F6"), ("active", background)],
        foreground=[("disabled", "#9CA3AF"), ("active", foreground)],
    )


def create_card(parent: tk.Widget, title: str | None = None, description: str | None = None) -> ttk.Frame:
    outer = ttk.Frame(parent, style="Card.TFrame", padding=12)
    outer.columnconfigure(0, weight=1)
    if title:
        ttk.Label(outer, text=title, style="SectionTitle.TLabel").grid(row=0, column=0, sticky="w")
    if description:
        ttk.Label(outer, text=description, style="Subtitle.TLabel", wraplength=620).grid(
            row=1 if title else 0, column=0, sticky="w", pady=(2, 8)
        )
    return outer


def create_section_header(parent: tk.Widget, title: str, subtitle: str | None = None) -> ttk.Frame:
    frame = ttk.Frame(parent, style="Page.TFrame")
    frame.columnconfigure(0, weight=1)
    ttk.Label(frame, text=title, style="PageTitle.TLabel").grid(row=0, column=0, sticky="w")
    if subtitle:
        ttk.Label(frame, text=subtitle, style="PageSubtitle.TLabel").grid(row=1, column=0, sticky="w", pady=(2, 0))
    return frame


def status_badge(parent: tk.Widget, text: str, kind: Literal["enabled", "disabled", "dryrun"] = "enabled") -> ttk.Label:
    style = {
        "enabled": "BadgeEnabled.TLabel",
        "disabled": "BadgeDisabled.TLabel",
        "dryrun": "BadgeDryRun.TLabel",
    }[kind]
    return ttk.Label(parent, text=text, style=style)
