from __future__ import annotations

import tkinter as tk
import tkinter.font as tkfont
import weakref
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


def select_ui_font(families: set[str] | list[str] | tuple[str, ...]) -> str:
    """Choose a font that can render Japanese without bundling a font."""
    available = {str(name).casefold(): str(name) for name in families}
    for candidate in ("Yu Gothic UI", "Meiryo UI", "Meiryo", "Segoe UI"):
        if candidate.casefold() in available:
            return available[candidate.casefold()]
    return "TkDefaultFont"


def apply_theme(root: tk.Tk | tk.Toplevel) -> ttk.Style:
    try:
        family = select_ui_font(tkfont.families(root))
    except tk.TclError:
        family = "TkDefaultFont"
    FONTS.update(
        {
            "body": (family, 10),
            "body_bold": (family, 10, "bold"),
            "title": (family, 16, "bold"),
            "section": (family, 12, "bold"),
            "subtitle": (family, 9),
            "value": (family, 14, "bold"),
            "badge": (family, 8, "bold"),
        }
    )
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
        title_label = ttk.Label(outer, text=title, style="SectionTitle.TLabel")
        title_label._responsive_wrap_margin = 8  # type: ignore[attr-defined]
        title_label.grid(row=0, column=0, sticky="ew")
        outer._card_title_label = title_label  # type: ignore[attr-defined]
    if description:
        description_label = ttk.Label(
            outer,
            text=description,
            style="Subtitle.TLabel",
            wraplength=wraplength,
            justify="left",
        )
        description_label._responsive_wrap_margin = 8  # type: ignore[attr-defined]
        description_label.grid(row=1 if title else 0, column=0, sticky="ew", pady=(4, 10))
        outer._card_description_label = description_label  # type: ignore[attr-defined]
    outer.bind("<Configure>", lambda _event, card=outer: _span_card_headers(card), add="+")
    return outer


def _span_card_headers(card: ttk.Frame) -> None:
    try:
        columns = max(1, card.grid_size()[0])
        for attribute in ("_card_title_label", "_card_description_label"):
            label = getattr(card, attribute, None)
            if label is not None and int(label.grid_info().get("columnspan", 1)) != columns:
                label.grid_configure(columnspan=columns)
    except (AttributeError, tk.TclError):
        return


def create_section_header(parent: tk.Widget, title: str, subtitle: str | None = None) -> ttk.Frame:
    frame = ttk.Frame(parent, style="Page.TFrame")
    frame.columnconfigure(0, weight=1)
    title_label = ttk.Label(frame, text=title, style="PageTitle.TLabel")
    title_label._responsive_wrap_margin = 8  # type: ignore[attr-defined]
    title_label.grid(row=0, column=0, sticky="ew")
    if subtitle:
        subtitle_label = ttk.Label(
            frame,
            text=subtitle,
            style="PageSubtitle.TLabel",
            justify="left",
        )
        subtitle_label._responsive_wrap_margin = 8  # type: ignore[attr-defined]
        subtitle_label.grid(row=1, column=0, sticky="ew", pady=(2, 0))
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
    """A vertically scrollable frame with one safe dispatcher per toplevel.

    Mouse and keyboard events are routed to the registered region below the
    pointer (or containing keyboard focus).  This deliberately avoids
    ``bind_all``/``unbind_all`` so independent workspaces cannot remove one
    another's bindings.
    """

    def __init__(self, parent: tk.Widget, *, height: int = 360) -> None:
        super().__init__(parent, style="Card.TFrame")
        self._wrap_job: str | None = None
        self._destroyed = False
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
        self.canvas.bind("<Enter>", self._on_enter, add="+")
        self.canvas.bind("<Leave>", self._on_leave, add="+")
        self.bind("<Destroy>", self._on_destroy, add="+")
        self._dispatcher = _ScrollDispatcher.for_toplevel(self.winfo_toplevel())
        self._dispatcher.register(self)

    def _on_inner_configure(self, _event: tk.Event) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        self._schedule_wrap_update()

    def _on_canvas_configure(self, event: tk.Event) -> None:
        self.canvas.itemconfigure(self.window_id, width=event.width)
        self._schedule_wrap_update()

    def _on_enter(self, _event: tk.Event) -> None:
        self._dispatcher.active = weakref.ref(self)

    def _on_leave(self, _event: tk.Event) -> None:
        active = self._dispatcher.active() if self._dispatcher.active else None
        if active is self:
            self._dispatcher.active = None

    def _on_mousewheel(self, event: tk.Event) -> str:
        number = getattr(event, "num", None)
        if number == 4:
            units = -1
        elif number == 5:
            units = 1
        else:
            delta = int(getattr(event, "delta", 0))
            if not delta:
                return ""
            magnitude = max(1, abs(delta) // 120)
            units = -magnitude if delta > 0 else magnitude
        self.canvas.yview_scroll(units, "units")
        return "break"

    def scroll_page(self, direction: int) -> str:
        self.canvas.yview_scroll(direction, "pages")
        return "break"

    def scroll_home(self) -> str:
        self.canvas.yview_moveto(0.0)
        return "break"

    def scroll_end(self) -> str:
        self.canvas.yview_moveto(1.0)
        return "break"

    def _schedule_wrap_update(self) -> None:
        if self._destroyed:
            return
        if self._wrap_job is not None:
            try:
                self.after_cancel(self._wrap_job)
            except tk.TclError:
                pass
        self._wrap_job = self.after(60, self._update_wraplengths)

    def _update_wraplengths(self) -> None:
        self._wrap_job = None
        width = max(120, self.canvas.winfo_width())
        for widget in _walk_widgets(self.inner):
            margin = getattr(widget, "_responsive_wrap_margin", None)
            if margin is None:
                continue
            try:
                local_width = widget.master.winfo_width()
                target = max(100, min(width, local_width or width) - int(margin))
                widget.configure(wraplength=target)
            except (AttributeError, tk.TclError):
                continue

    def _on_destroy(self, event: tk.Event) -> None:
        if event.widget is not self or self._destroyed:
            return
        self._destroyed = True
        if self._wrap_job is not None:
            try:
                self.after_cancel(self._wrap_job)
            except tk.TclError:
                pass
            self._wrap_job = None
        self._dispatcher.unregister(self)


def _walk_widgets(parent: tk.Widget):
    for child in parent.winfo_children():
        yield child
        yield from _walk_widgets(child)


def _is_descendant(widget: tk.Widget | None, ancestor: tk.Widget) -> bool:
    current = widget
    while current is not None:
        if current is ancestor:
            return True
        try:
            parent_name = current.winfo_parent()
            current = current._nametowidget(parent_name) if parent_name else None
        except (KeyError, tk.TclError):
            return False
    return False


class _ScrollDispatcher:
    _attribute = "_a4_scroll_dispatcher"

    def __init__(self, toplevel: tk.Misc) -> None:
        self.toplevel = toplevel
        self.frames: weakref.WeakSet[ScrollableFrame] = weakref.WeakSet()
        self.active: weakref.ReferenceType[ScrollableFrame] | None = None
        self._bindings: dict[str, str] = {}
        callbacks = {
            "<MouseWheel>": self._mouse,
            "<Button-4>": self._mouse,
            "<Button-5>": self._mouse,
            "<Prior>": lambda event: self._key(event, -1, "page"),
            "<Next>": lambda event: self._key(event, 1, "page"),
            "<Home>": lambda event: self._key(event, 0, "home"),
            "<End>": lambda event: self._key(event, 0, "end"),
        }
        for sequence, callback in callbacks.items():
            binding_id = toplevel.bind(sequence, callback, add="+")
            if binding_id:
                self._bindings[sequence] = binding_id

    @classmethod
    def for_toplevel(cls, toplevel: tk.Misc) -> "_ScrollDispatcher":
        dispatcher = getattr(toplevel, cls._attribute, None)
        if dispatcher is None:
            dispatcher = cls(toplevel)
            setattr(toplevel, cls._attribute, dispatcher)
        return dispatcher

    def register(self, frame: ScrollableFrame) -> None:
        self.frames.add(frame)

    def unregister(self, frame: ScrollableFrame) -> None:
        self.frames.discard(frame)
        active = self.active() if self.active else None
        if active is frame:
            self.active = None
        if self.frames:
            return
        for sequence, binding_id in self._bindings.items():
            try:
                self.toplevel.unbind(sequence, binding_id)
            except tk.TclError:
                pass
        self._bindings.clear()
        try:
            delattr(self.toplevel, self._attribute)
        except AttributeError:
            pass

    def _under_pointer(self, event: tk.Event) -> ScrollableFrame | None:
        try:
            widget = self.toplevel.winfo_containing(event.x_root, event.y_root)
        except (AttributeError, tk.TclError):
            widget = None
        matches = [frame for frame in self.frames if _is_descendant(widget, frame)]
        if matches:
            return max(matches, key=lambda frame: len(str(frame).split(".")))
        if widget is not None:
            return None
        active = self.active() if self.active else None
        return active if active in self.frames else None

    def _mouse(self, event: tk.Event) -> str | None:
        try:
            widget = self.toplevel.winfo_containing(event.x_root, event.y_root)
        except (AttributeError, tk.TclError):
            widget = None
        if isinstance(widget, (tk.Text, tk.Listbox, tk.Entry, ttk.Entry, ttk.Combobox, ttk.Spinbox)):
            return None
        frame = self._under_pointer(event)
        return frame._on_mousewheel(event) if frame is not None else None

    def _key(self, event: tk.Event, direction: int, action: str) -> str | None:
        try:
            focus = self.toplevel.focus_get()
        except tk.TclError:
            focus = None
        if isinstance(focus, (tk.Entry, tk.Text, ttk.Entry, ttk.Combobox, ttk.Spinbox)):
            return None
        matches = [frame for frame in self.frames if _is_descendant(focus, frame)]
        frame = max(matches, key=lambda item: len(str(item).split("."))) if matches else None
        if frame is None:
            frame = self.active() if self.active else None
        if frame is None or frame not in self.frames:
            return None
        if action == "home":
            return frame.scroll_home()
        if action == "end":
            return frame.scroll_end()
        return frame.scroll_page(direction)
