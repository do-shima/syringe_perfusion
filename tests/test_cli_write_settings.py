import json

from syringe_perfusion.cli import main


def test_write_settings_dry_run_outputs_settings_commands(capsys) -> None:
    code = main(
        [
            "write-settings",
            "--pump",
            "IN",
            "--speed-mm-min",
            "15.37",
            "--duration-s",
            "30",
            "--save",
            "--dry-run",
        ]
    )
    assert code == 0
    results = json.loads(capsys.readouterr().out)
    assert [result["command"] for result in results] == [
        "q1h15d",
        "q2h37d",
        "q3h00d",
        "q4h00d",
        "q5h30d",
        "q6h1d",
    ]


def test_write_profile_dry_run_outputs_fast30_commands(capsys) -> None:
    code = main(["write-profile", "--pump", "IN", "--profile", "fast30_1ml", "--dry-run"])
    assert code == 0
    results = json.loads(capsys.readouterr().out)
    assert [result["command"] for result in results] == [
        "q1h15d",
        "q2h37d",
        "q3h00d",
        "q4h00d",
        "q5h30d",
        "q6h1d",
    ]


def test_write_profile_start_after_write_adds_start_forward(capsys) -> None:
    code = main(
        [
            "write-profile",
            "--pump",
            "IN",
            "--profile",
            "fast30_1ml",
            "--start-after-write",
            "--dry-run",
        ]
    )
    assert code == 0
    results = json.loads(capsys.readouterr().out)
    assert [result["command"] for result in results][-1] == "q6h2d"
