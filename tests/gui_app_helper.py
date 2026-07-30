from __future__ import annotations

import time
import tkinter as tk

from syringe_perfusion.gui import A4PumpApp


def make_app() -> A4PumpApp:
    last_exc: tk.TclError | None = None
    for _attempt in range(3):
        try:
            app = A4PumpApp()
            # Existing GUI behavior tests use stable English labels regardless
            # of the developer workstation UI locale.
            app.localizer.set_preference("en")
            app._refresh_localized_display_values()
            app.withdraw()
            return app
        except tk.TclError as exc:
            last_exc = exc
            time.sleep(0.05)
    assert last_exc is not None
    raise last_exc
