from syringe_perfusion.gui import A4PumpApp


def make_app() -> A4PumpApp:
    app = A4PumpApp()
    app.withdraw()
    return app


def test_profile_write_button_is_enabled() -> None:
    app = make_app()
    try:
        assert "disabled" not in app.profile_write_button.state()
    finally:
        app.destroy()


def test_profile_write_dry_run_does_not_start_by_default() -> None:
    app = make_app()
    try:
        app.profile_start_after_write_var.set(False)
        results = app.write_profile_settings_gui(confirm=False)
        assert results is not None
        commands = [result["command"] for result in results]
        assert commands == ["q1h15d", "q2h37d", "q3h00d", "q4h00d", "q5h30d", "q6h1d"]
    finally:
        app.destroy()


def test_profile_write_dry_run_can_start_after_write() -> None:
    app = make_app()
    try:
        app.profile_start_after_write_var.set(True)
        results = app.write_profile_settings_gui(confirm=False)
        assert results is not None
        assert [result["command"] for result in results][-1] == "q6h2d"
    finally:
        app.destroy()
