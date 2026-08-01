from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from syringe_perfusion import app_info
from syringe_perfusion.cli import build_parser, main
from syringe_perfusion.commissioning import dependency_snapshot, staleness_reasons
from syringe_perfusion.config import REQUIRED_CONFIG_FILES
from syringe_perfusion.diagnostics import export_diagnostics, sanitize_text
from syringe_perfusion.release_engineering import (
    assemble_release_directory,
    create_release_zip,
    generate_build_manifest,
    prepare_upgrade,
    release_directory_name,
    validate_manifest,
    validate_release_tree,
)
from syringe_perfusion.validation_store import ValidationStore


ROOT = Path(__file__).resolve().parents[1]


def active_config(tmp_path: Path) -> Path:
    root = tmp_path / "config"
    root.mkdir()
    for filename in REQUIRED_CONFIG_FILES:
        (root / filename).write_bytes((ROOT / "config" / filename).read_bytes())
    return root


def test_canonical_pep440_and_human_version_consistency() -> None:
    assert app_info.package_version() == "0.2.0b5"
    assert app_info.human_version() == "0.2.0-beta.5"
    assert app_info.future_tag_name() == "v0.2.0-beta.5"
    assert app_info.APP_VERSION == "0.2.0-beta.5"
    assert 'version = "0.2.0b5"' in (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    for path in (
        ROOT / "README.md",
        ROOT / "CHANGELOG.md",
        ROOT / "docs" / "releases" / "v0.2.0-beta.5.md",
    ):
        assert "0.2.0-beta.5" in path.read_text(encoding="utf-8")


def test_source_fallback_and_embedded_build_info_loading(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        app_info.importlib.metadata,
        "version",
        lambda _name: (_ for _ in ()).throw(app_info.importlib.metadata.PackageNotFoundError()),
    )
    assert app_info.package_version() == "0.2.0b5"
    valid = app_info.source_build_info(build_type="test")
    path = tmp_path / "build_info.json"
    path.write_text(json.dumps(valid), encoding="utf-8")
    loaded = app_info.load_embedded_build_info([path])
    assert loaded is not None
    assert loaded["human_version"] == "0.2.0-beta.5"
    missing = app_info.load_embedded_build_info([tmp_path / "missing.json"])
    assert missing is None
    path.write_text("{malformed", encoding="utf-8")
    assert app_info.load_embedded_build_info([path]) is None


def test_release_build_identity_refuses_dirty_source(monkeypatch) -> None:
    monkeypatch.setattr(
        app_info,
        "source_build_info",
        lambda **_kwargs: {
            "git_commit": "abcdef",
            "git_dirty": True,
        },
    )
    with pytest.raises(RuntimeError, match="clean tracked source tree"):
        app_info.create_build_info(build_type="release-candidate", require_clean=True)


def test_cli_version_has_traceable_fields(capsys) -> None:
    parser = build_parser()
    with pytest.raises(SystemExit) as exc:
        parser.parse_args(["--version"])
    assert exc.value.code == 0
    output = capsys.readouterr().out
    assert "A4PumpControl 0.2.0-beta.5" in output
    assert "commit " in output
    assert "control compatibility 1" in output
    assert "package 0.2.0b5" in output


def test_validation_schema_v1_read_and_build_identity_report(tmp_path: Path) -> None:
    root = active_config(tmp_path)
    store = ValidationStore(root, now=lambda: "2026-01-01T00:00:00+00:00")
    legacy = {
        "schema_version": 1,
        "validation_id": "LEGACY",
        "status": "COMMISSIONING PARTIAL",
        "operator": "operator",
        "dependencies": dependency_snapshot(
            json.loads((root / "pumps.json").read_text(encoding="utf-8"))
            | {
                "syringes": json.loads((root / "syringes.json").read_text(encoding="utf-8"))["syringes"],
                "profiles": json.loads((root / "profiles.json").read_text(encoding="utf-8"))["profiles"],
                "recipes": json.loads((root / "recipes.json").read_text(encoding="utf-8"))["recipes"],
            },
            config_dir=str(root),
            application_version="legacy",
        ),
        "test_results": [],
        "measurement_results": [],
        "manual_confirmations": [],
        "overrides": [],
        "failures": [],
        "unknown_future_field": {"keep": True},
    }
    legacy["dependencies"].pop("control_compatibility_version")
    (root / "validation").mkdir()
    (root / "validation" / "commissioning_state.json").write_text(
        json.dumps(legacy),
        encoding="utf-8",
    )
    loaded = store.load()
    assert loaded is not None
    assert loaded["schema_version"] == 1
    assert loaded["unknown_future_field"] == {"keep": True}
    assert "predates control compatibility" in " ".join(store.status()["stale_reasons"])

    record = store.create(operator="operator", build_id="abcdef012345")
    assert record["schema_version"] == 2
    assert record["package_version"] == "0.2.0b5"
    assert record["control_compatibility_version"] == 1
    assert record["build_commit"] == "abcdef012345"
    store.save(record)
    report = store.export("markdown", tmp_path / "report.md").read_text(encoding="utf-8")
    assert "Package version: 0.2.0b5" in report
    assert "Control compatibility: 1" in report
    assert "Build fingerprint:" in report


def test_documentation_only_build_does_not_stale_but_material_control_change_does(
    tmp_path: Path,
) -> None:
    root = active_config(tmp_path)
    from syringe_perfusion.config import load_config

    data = load_config(root)
    old = dependency_snapshot(
        data,
        config_dir=str(root),
        application_version="0.2.0-beta.1+docs-a",
        control_compatibility_version=1,
    )
    docs_only = dependency_snapshot(
        data,
        config_dir=str(root),
        application_version="0.2.0-beta.1+docs-b",
        control_compatibility_version=1,
    )
    assert staleness_reasons(old, docs_only) == []
    material = dict(docs_only)
    material["control_compatibility_version"] = 2
    assert staleness_reasons(old, material) == [
        "validation-sensitive control compatibility changed"
    ]


def test_diagnostics_are_read_only_sanitized_and_include_build_identity(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = active_config(tmp_path)
    constructed: list[bool] = []
    monkeypatch.setattr(
        "syringe_perfusion.a4.A4Pump.__init__",
        lambda *_args, **_kwargs: constructed.append(True),
    )
    output = export_diagnostics(root, tmp_path / "diagnostics.zip", port_provider=lambda: [])
    assert constructed == []
    with zipfile.ZipFile(output) as archive:
        names = archive.namelist()
        assert "build_info.json" in names
        assert "preflight.json" in names
        assert "validation-report.md" in names
        combined = b"\n".join(archive.read(name) for name in names if not name.endswith(".zip"))
    text = combined.decode("utf-8", errors="replace")
    assert app_info.human_version() in text
    assert str(Path.home()) not in text
    assert "<USER_HOME>" in text
    assert sanitize_text(str(Path.home() / "private")) == "<USER_HOME>\\private"
    assert main(["--config-dir", str(root), "diagnostics-summary"]) == 0
    assert main(
        [
            "--config-dir",
            str(root),
            "export-diagnostics",
            "--output",
            str(tmp_path / "cli-diagnostics.zip"),
        ]
    ) == 0
    assert constructed == []


def fake_stage(tmp_path: Path) -> Path:
    stage = tmp_path / "stage"
    gui = stage / "A4PumpGUI"
    cli = stage / "a4ctl"
    (gui / "_internal").mkdir(parents=True)
    (cli / "_internal").mkdir(parents=True)
    (gui / "A4PumpGUI.exe").write_bytes(b"GUI")
    (cli / "a4ctl.exe").write_bytes(b"CLI")
    info = app_info.source_build_info(build_type="release-candidate")
    info["git_dirty"] = False
    info["build_timestamp_utc"] = "2026-07-30T00:00:00+00:00"
    info["build_identity_fingerprint"] = app_info.build_identity_fingerprint(info)
    for root in (gui, cli):
        (root / "_internal" / "build_info.json").write_text(
            json.dumps(info),
            encoding="utf-8",
        )
    return stage


def test_release_artifact_manifest_zip_and_forbidden_content(tmp_path: Path) -> None:
    stage = fake_stage(tmp_path)
    release_root = tmp_path / "release"
    directory = assemble_release_directory(
        repository_root=ROOT,
        pyinstaller_stage=stage,
        release_root=release_root,
    )
    assert directory.name == release_directory_name()
    assert not (directory / "config" / "runtime").exists()
    assert not (directory / "config" / "validation").exists()
    assert sorted(path.name for path in (directory / "config").iterdir()) == sorted(
        REQUIRED_CONFIG_FILES
    )
    assert (directory / "docs" / "SYRINGE_LIBRARY.md").is_file()
    archive = create_release_zip(directory, release_root / f"{directory.name}.zip")
    info = json.loads((directory / "_internal" / "build_info.json").read_text(encoding="utf-8"))
    first = generate_build_manifest(
        release_directory=directory,
        zip_path=archive,
        build_info=info,
        test_summary="174 passed",
    )
    second = generate_build_manifest(
        release_directory=directory,
        zip_path=archive,
        build_info=info,
        test_summary="174 passed",
    )
    assert first == second
    assert "build_info_path" not in first["build_identity"]
    assert str(tmp_path) not in json.dumps(first)
    assert [item["path"] for item in first["files"]] == sorted(
        item["path"] for item in first["files"]
    )
    validate_manifest(directory, archive, first)
    assert first["top_level_zip_sha256"]

    bad = tmp_path / "bad-release"
    bad.mkdir()
    (bad / "config").mkdir()
    (bad / "config" / "pumps.json").write_text('{"port":"COM9"}', encoding="utf-8")
    with pytest.raises(ValueError, match="hard-coded numeric COM"):
        validate_release_tree(bad)

    contaminated_stage = fake_stage(tmp_path / "contaminated")
    (contaminated_stage / "A4PumpGUI" / "config" / "runtime").mkdir(parents=True)
    with pytest.raises(ValueError, match="contains writable config"):
        assemble_release_directory(
            repository_root=ROOT,
            pyinstaller_stage=contaminated_stage,
            release_root=tmp_path / "rejected-release",
        )


def test_upgrade_preserves_external_config_validation_runtime_and_local_wrappers(
    tmp_path: Path,
) -> None:
    new = tmp_path / "new"
    (new / "config").mkdir(parents=True)
    (new / "nis_cmd").mkdir()
    (new / "config" / "pumps.json").write_text("new default", encoding="utf-8")
    (new / "nis_cmd" / "standard.cmd").write_text("new standard", encoding="utf-8")
    existing = tmp_path / "existing"
    (existing / "config" / "runtime").mkdir(parents=True)
    (existing / "config" / "validation" / "reports").mkdir(parents=True)
    (existing / "nis_logs").mkdir()
    (existing / "nis_cmd" / "local").mkdir(parents=True)
    (existing / "config" / "pumps.json").write_text("operator config", encoding="utf-8")
    (existing / "config" / "runtime" / "state.json").write_text("state", encoding="utf-8")
    (existing / "config" / "validation" / "record.json").write_text("evidence", encoding="utf-8")
    (existing / "config" / "validation" / "reports" / "report.md").write_text("report", encoding="utf-8")
    (existing / "nis_logs" / "nis.log").write_text("history", encoding="utf-8")
    (existing / "nis_cmd" / "local" / "site.cmd").write_text("local", encoding="utf-8")
    destination = prepare_upgrade(
        new_release_directory=new,
        existing_installation=existing,
        destination=tmp_path / "upgraded",
    )
    assert (destination / "config" / "pumps.json").read_text(encoding="utf-8") == "operator config"
    assert (destination / "config" / "runtime" / "state.json").exists()
    assert (destination / "config" / "validation" / "record.json").exists()
    assert (destination / "config" / "validation" / "reports" / "report.md").exists()
    assert (destination / "nis_logs" / "nis.log").exists()
    assert (destination / "nis_cmd" / "local" / "site.cmd").exists()
    assert (destination / "nis_cmd" / "standard.cmd").read_text(encoding="utf-8") == "new standard"
