from syringe_perfusion.a4 import A4Pump, DEFAULT_COMMANDS


def test_manual_forward_sends_lowercase_command() -> None:
    result = A4Pump(name="IN", port="COM5", dry_run=True).manual_forward()
    assert result["command"] == "q6h4d"


def test_manual_reverse_sends_lowercase_command() -> None:
    result = A4Pump(name="IN", port="COM5", dry_run=True).manual_reverse()
    assert result["command"] == "q6h5d"


def test_stop_sends_lowercase_command() -> None:
    result = A4Pump(name="IN", port="COM5", dry_run=True).stop()
    assert result["command"] == "q6h6d"


def test_default_commands_are_lowercase() -> None:
    assert DEFAULT_COMMANDS == {
        "start_forward": "q6h2d",
        "start_reverse": "q6h3d",
        "manual_forward": "q6h4d",
        "manual_reverse": "q6h5d",
        "stop": "q6h6d",
        "save": "q6h1d",
    }
    assert all(command == command.lower() for command in DEFAULT_COMMANDS.values())
