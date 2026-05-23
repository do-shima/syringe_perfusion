from syringe_perfusion.config import config_dir, decode_terminator, load_config


def test_config_loading() -> None:
    data = load_config()
    assert "IN" in data["pumps"]
    assert "terumo_ss05lz_5ml" in data["syringes"]
    assert "fast30_1ml" in data["profiles"]
    assert "pushpull_fast30" in data["recipes"]


def test_config_dir_exists() -> None:
    assert (config_dir() / "pumps.json").exists()


def test_decode_terminator() -> None:
    assert decode_terminator("") == ""
    assert decode_terminator("\\r") == "\r"
    assert decode_terminator("\\n") == "\n"
    assert decode_terminator("\\r\\n") == "\r\n"
