from __future__ import annotations

import time
import tkinter as tk

from syringe_perfusion.gui import A4PumpApp


def make_app() -> A4PumpApp:
    last_exc: tk.TclError | None = None
    for _attempt in range(3):
        try:
            app = A4PumpApp()
            app.withdraw()
            return app
        except tk.TclError as exc:
            last_exc = exc
            time.sleep(0.05)
    assert last_exc is not None
    raise last_exc
