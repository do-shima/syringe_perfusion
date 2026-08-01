from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

from .app_info import APPLICATION_ID, SOURCE_REPOSITORY, human_version, package_version
from .config import REQUIRED_CONFIG_FILES
from .diagnostics import PERSONAL_PATH_PATTERNS


RELEASE_MANIFEST_SCHEMA_VERSION = 1
RELEASE_PLATFORM_SUFFIX = "win-x64"
FORBIDDEN_PARTS = {
    ".git",
    "__pycache__",
    ".pytest_cache",
    ".venv",
    "venv",
}
FORBIDDEN_SUFFIXES = {".bak", ".pyc", ".pyo", ".log"}
SECRET_FILENAMES = {".env", "id_rsa", "id_ed25519", "credentials.json", "secrets.json"}


def release_directory_name(version: str | None = None) -> str:
    return f"{APPLICATION_ID}-{version or human_version()}-{RELEASE_PLATFORM_SUFFIX}"


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def assemble_release_directory(
    *,
    repository_root: str | Path,
    pyinstaller_stage: str | Path,
    release_root: str | Path,
) -> Path:
    repository = Path(repository_root).resolve()
    stage = Path(pyinstaller_stage).resolve()
    output_root = Path(release_root).resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    target = output_root / release_directory_name()
    _safe_replace_directory(target, output_root)
    gui_stage = stage / "A4PumpGUI"
    cli_stage = stage / "a4ctl"
    if not (gui_stage / "A4PumpGUI.exe").is_file():
        raise FileNotFoundError(f"GUI executable missing: {gui_stage}")
    if not (cli_stage / "a4ctl.exe").is_file():
        raise FileNotFoundError(f"CLI executable missing: {cli_stage}")
    shutil.copytree(gui_stage, target)
    shutil.copytree(cli_stage, target / "a4ctl")
    config_target = target / "config"
    if config_target.exists():
        raise ValueError(
            "PyInstaller staging output contains writable config; "
            "refusing to package possible runtime or validation evidence"
        )
    config_target.mkdir()
    for filename in REQUIRED_CONFIG_FILES:
        shutil.copy2(repository / "config" / filename, config_target / filename)
    wrapper_target = target / "nis_cmd"
    wrapper_target.mkdir()
    shutil.copy2(repository / "nis_cmd" / "README.md", wrapper_target / "README.md")
    for wrapper in sorted((repository / "nis_cmd").glob("*.cmd"), key=lambda item: item.name.casefold()):
        if wrapper.name.casefold().endswith(("_local.cmd", ".local.cmd")):
            continue
        shutil.copy2(wrapper, wrapper_target / wrapper.name)
    docs = target / "docs"
    docs.mkdir()
    shutil.copy2(repository / "README.md", docs / "README.txt")
    for filename in (
        "HARDWARE_COMMISSIONING.md",
        "HIL_OPERATOR_CHECKLIST.md",
        "HIL_VALIDATION_SESSION.md",
        "NIS_Elements_6_02.md",
        "SYRINGE_LIBRARY.md",
    ):
        shutil.copy2(repository / "docs" / filename, docs / filename)
    release_notes = repository / "docs" / "releases" / f"v{human_version()}.md"
    shutil.copy2(release_notes, docs / "RELEASE_NOTES.md")
    validate_release_tree(target)
    return target


def validate_release_tree(root: str | Path) -> list[str]:
    base = Path(root).resolve()
    errors: list[str] = []
    required = (
        "A4PumpGUI.exe",
        "a4ctl/a4ctl.exe",
        *[f"config/{filename}" for filename in REQUIRED_CONFIG_FILES],
        "nis_cmd/README.md",
        "docs/README.txt",
        "docs/HARDWARE_COMMISSIONING.md",
        "docs/HIL_OPERATOR_CHECKLIST.md",
        "docs/HIL_VALIDATION_SESSION.md",
        "docs/NIS_Elements_6_02.md",
        "docs/SYRINGE_LIBRARY.md",
        "docs/RELEASE_NOTES.md",
        "_internal/build_info.json",
    )
    for relative in required:
        if not (base / PurePosixPath(relative)).is_file():
            errors.append(f"missing required file: {relative}")
    for path in sorted(base.rglob("*")):
        relative = path.relative_to(base)
        lower_parts = {part.casefold() for part in relative.parts}
        if lower_parts & FORBIDDEN_PARTS:
            errors.append(f"forbidden directory or file: {relative.as_posix()}")
        if path.is_dir():
            if relative.as_posix().casefold() in {"config/runtime", "config/validation"}:
                errors.append(f"runtime evidence included: {relative.as_posix()}")
            if relative.as_posix().casefold() == "nis_cmd/local":
                errors.append(f"local wrapper directory included: {relative.as_posix()}")
            continue
        if path.suffix.casefold() in FORBIDDEN_SUFFIXES:
            errors.append(f"forbidden generated file: {relative.as_posix()}")
        if path.name.casefold() in SECRET_FILENAMES:
            errors.append(f"secret-like file included: {relative.as_posix()}")
        if path.name.casefold().endswith(".local.cmd"):
            errors.append(f"local wrapper included: {relative.as_posix()}")
        if _is_text_file(path):
            text = path.read_text(encoding="utf-8", errors="replace")
            if any(pattern.search(text) for pattern in PERSONAL_PATH_PATTERNS):
                errors.append(f"personal path leakage: {relative.as_posix()}")
            if (
                path.name.casefold() == "pumps.json"
                or (relative.parts and relative.parts[0].casefold() == "nis_cmd")
            ):
                if re.search(r"(?i)\bCOM\d+\b", text):
                    errors.append(f"hard-coded numeric COM port: {relative.as_posix()}")
    if errors:
        raise ValueError("release tree validation failed:\n" + "\n".join(errors))
    return errors


def create_release_zip(release_directory: str | Path, output: str | Path) -> Path:
    root = Path(release_directory).resolve()
    destination = Path(output).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=destination.name + ".", suffix=".tmp", dir=destination.parent)
    os.close(fd)
    temporary = Path(name)
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for path in _distributed_files(root):
                relative = PurePosixPath(root.name) / PurePosixPath(path.relative_to(root).as_posix())
                info = zipfile.ZipInfo(relative.as_posix(), date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o100644 << 16
                archive.writestr(info, path.read_bytes())
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination


def generate_build_manifest(
    *,
    release_directory: str | Path,
    zip_path: str | Path,
    build_info: dict[str, Any],
    test_summary: str,
) -> dict[str, Any]:
    root = Path(release_directory).resolve()
    archive = Path(zip_path).resolve()
    files = [
        {
            "path": path.relative_to(root).as_posix(),
            "size": path.stat().st_size,
            "sha256": sha256_file(path),
        }
        for path in _distributed_files(root)
    ]
    public_build_info = {
        key: value
        for key, value in build_info.items()
        if key not in {"build_info_path"}
    }
    return {
        "schema_version": RELEASE_MANIFEST_SCHEMA_VERSION,
        "release_version": human_version(),
        "package_version": package_version(),
        "future_tag": f"v{human_version()}",
        "source_repository": SOURCE_REPOSITORY,
        "source_commit": public_build_info.get("git_commit", ""),
        "dirty": public_build_info.get("git_dirty"),
        "build_identity": public_build_info,
        "artifact_directory": root.name,
        "artifact_zip": archive.name,
        "artifact_zip_size": archive.stat().st_size,
        "top_level_zip_sha256": sha256_file(archive),
        "files": files,
        "expected_directory_layout": [
            "A4PumpGUI.exe",
            "a4ctl/a4ctl.exe",
            "config/",
            "nis_cmd/",
            "docs/",
            "_internal/",
        ],
        "required_external_writable_directories": [
            "config/runtime/",
            "config/validation/",
            "config/diagnostics/",
            "logs/",
            "nis_logs/",
        ],
        "python_version": public_build_info.get("python_version", ""),
        "pyinstaller_version": public_build_info.get("pyinstaller_version", ""),
        "code_signing": public_build_info.get("code_signing", "unsigned"),
        "test_summary": test_summary,
    }


def write_json(path: str | Path, value: Any) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    _write_text(destination, text, encoding="utf-8")
    return destination


def validate_manifest(
    release_directory: str | Path,
    zip_path: str | Path,
    manifest: dict[str, Any],
) -> None:
    root = Path(release_directory).resolve()
    archive_path = Path(zip_path).resolve()
    manifest_text = json.dumps(manifest, ensure_ascii=False)
    if re.search(r"(?i)(?:[A-Z]:\\|/(?:Users|home)/)", manifest_text):
        raise ValueError("absolute build-machine path appears in manifest")
    validate_release_tree(root)
    actual = {
        path.relative_to(root).as_posix(): (path.stat().st_size, sha256_file(path))
        for path in _distributed_files(root)
    }
    listed = {
        str(item["path"]): (int(item["size"]), str(item["sha256"]))
        for item in manifest.get("files", [])
    }
    if list(listed) != sorted(listed):
        raise ValueError("manifest file ordering is not deterministic")
    if actual != listed:
        raise ValueError("manifest file list, sizes, or checksums do not match release directory")
    zip_hash = sha256_file(archive_path)
    if manifest.get("top_level_zip_sha256") != zip_hash:
        raise ValueError("ZIP checksum does not match manifest")
    expected_entries = {
        f"{root.name}/{relative}" for relative in actual
    }
    with zipfile.ZipFile(archive_path) as archive:
        names = archive.namelist()
        if any(PurePosixPath(name).is_absolute() or ".." in PurePosixPath(name).parts for name in names):
            raise ValueError("unsafe ZIP member path")
        if set(names) != expected_entries:
            raise ValueError("ZIP contents do not match manifest")
        for relative, (_size, expected_hash) in listed.items():
            member = f"{root.name}/{relative}"
            if hashlib.sha256(archive.read(member)).hexdigest() != expected_hash:
                raise ValueError(f"ZIP member checksum mismatch: {relative}")


def write_checksums(
    *,
    release_root: str | Path,
    zip_path: str | Path,
    manifest_path: str | Path,
    release_notes_path: str | Path,
) -> tuple[Path, Path]:
    root = Path(release_root).resolve()
    archive = Path(zip_path).resolve()
    checksum = sha256_file(archive)
    artifact_checksum = root / f"{archive.stem}.sha256"
    _write_text(artifact_checksum, f"{checksum}  {archive.name}\n", encoding="ascii")
    paths = [archive, Path(manifest_path).resolve(), Path(release_notes_path).resolve()]
    sums = root / "SHA256SUMS.txt"
    _write_text(
        sums,
        "".join(f"{sha256_file(path)}  {path.name}\n" for path in sorted(paths, key=lambda item: item.name)),
        encoding="ascii",
    )
    return artifact_checksum, sums


def prepare_upgrade(
    *,
    new_release_directory: str | Path,
    existing_installation: str | Path,
    destination: str | Path,
) -> Path:
    source = Path(new_release_directory).resolve()
    existing = Path(existing_installation).resolve()
    target = Path(destination).resolve()
    if target.exists():
        raise FileExistsError(f"upgrade destination already exists: {target}")
    if target == existing or target == source:
        raise ValueError("upgrade destination must be a new versioned directory")
    shutil.copytree(source, target)
    existing_config = existing / "config"
    if existing_config.is_dir():
        shutil.copytree(existing_config, target / "config", dirs_exist_ok=True)
    existing_nis_logs = existing / "nis_logs"
    if existing_nis_logs.is_dir():
        shutil.copytree(existing_nis_logs, target / "nis_logs", dirs_exist_ok=True)
    local_wrapper_sources = [
        existing / "nis_cmd" / "local",
        *sorted((existing / "nis_cmd").glob("*_local.cmd")),
        *sorted((existing / "nis_cmd").glob("*.local.cmd")),
    ]
    for item in local_wrapper_sources:
        if item.is_dir():
            shutil.copytree(item, target / "nis_cmd" / item.name, dirs_exist_ok=True)
        elif item.is_file():
            shutil.copy2(item, target / "nis_cmd" / item.name)
    return target


def _safe_replace_directory(target: Path, allowed_parent: Path) -> None:
    resolved_target = target.resolve()
    resolved_parent = allowed_parent.resolve()
    if resolved_target.parent != resolved_parent or not resolved_target.name.startswith(APPLICATION_ID + "-"):
        raise ValueError(f"refusing to replace unsafe release target: {resolved_target}")
    if resolved_target.exists():
        shutil.rmtree(resolved_target)


def _distributed_files(root: Path) -> list[Path]:
    return sorted(
        (path for path in root.rglob("*") if path.is_file()),
        key=lambda path: path.relative_to(root).as_posix(),
    )


def _is_text_file(path: Path) -> bool:
    return path.suffix.casefold() in {
        ".bat",
        ".cmd",
        ".csv",
        ".json",
        ".md",
        ".ps1",
        ".txt",
        ".xml",
        ".yaml",
        ".yml",
    }


def _write_text(path: Path, value: str, *, encoding: str) -> None:
    with path.open("w", encoding=encoding, newline="\n") as handle:
        handle.write(value)
