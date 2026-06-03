import json

from syringe_perfusion.cli import main


def test_cli_jog_forward_dry_run_outputs_manual_forward_and_stop(capsys) -> None:
    code = main(["jog", "--pump", "IN", "--direction", "forward", "--duration-ms", "1000", "--dry-run"])
    assert code == 0
    output = capsys.readouterr().out
    results = json.loads(output)
    assert [result["command"] for result in results] == ["q6h4d", "q6h6d"]
