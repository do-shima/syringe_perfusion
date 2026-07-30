from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from syringe_perfusion.app_info import human_version, load_embedded_build_info
from syringe_perfusion.release_engineering import (
    assemble_release_directory,
    create_release_zip,
    generate_build_manifest,
    prepare_upgrade,
    release_directory_name,
    validate_manifest,
    write_checksums,
    write_json,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    assemble = subparsers.add_parser("assemble")
    assemble.add_argument("--repo", required=True)
    assemble.add_argument("--stage", required=True)
    assemble.add_argument("--release-root", required=True)
    assemble.add_argument("--test-summary", required=True)
    verify = subparsers.add_parser("verify")
    verify.add_argument("--release-root", required=True)
    upgrade = subparsers.add_parser("upgrade")
    upgrade.add_argument("--new-release", required=True)
    upgrade.add_argument("--existing", required=True)
    upgrade.add_argument("--destination", required=True)
    args = parser.parse_args()

    if args.command == "upgrade":
        print(
            prepare_upgrade(
                new_release_directory=args.new_release,
                existing_installation=args.existing,
                destination=args.destination,
            )
        )
        return 0

    root = Path(args.release_root).resolve()
    directory = root / release_directory_name()
    zip_path = root / f"{release_directory_name()}.zip"
    manifest_path = root / "build-manifest.json"
    if args.command == "assemble":
        directory = assemble_release_directory(
            repository_root=args.repo,
            pyinstaller_stage=args.stage,
            release_root=root,
        )
        build_info = load_embedded_build_info([directory / "_internal" / "build_info.json"])
        if build_info is None:
            raise RuntimeError("embedded build_info.json is missing or malformed")
        create_release_zip(directory, zip_path)
        manifest = generate_build_manifest(
            release_directory=directory,
            zip_path=zip_path,
            build_info=build_info,
            test_summary=args.test_summary,
        )
        write_json(manifest_path, manifest)
        notes = Path(args.repo).resolve() / "docs" / "releases" / f"v{human_version()}.md"
        release_notes = root / "RELEASE_NOTES.md"
        release_notes.write_bytes(notes.read_bytes())
        write_checksums(
            release_root=root,
            zip_path=zip_path,
            manifest_path=manifest_path,
            release_notes_path=release_notes,
        )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    validate_manifest(directory, zip_path, manifest)
    print(directory)
    print(zip_path)
    print(manifest_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
