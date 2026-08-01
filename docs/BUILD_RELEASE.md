# Windows Release Build and Upgrade

## Version policy

`pyproject.toml` is the sole current package-version source. PEP 440 `0.2.0b5` is rendered as human version `0.2.0-beta.5` and future tag `v0.2.0-beta.5`. Frozen applications read `_internal\build_info.json`; they do not query Git or the network at startup. Control compatibility remains `1`.

## Release build

Use a clean Windows checkout with Python, pytest, PyInstaller, and pyserial installed:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\build_release_windows.ps1
```

The script refuses tracked or untracked source changes and has no release-mode dirty override. It runs tests, `git diff --check`, both PyInstaller builds, packaged non-hardware smoke tests, wrapper/public-default scans, manifest generation, ZIP creation, and ZIP/checksum revalidation.

Generated files under `release\` include the versioned directory and ZIP, artifact checksum, `SHA256SUMS.txt`, `build-manifest.json`, and release notes. Binaries are unsigned.

The beta.5 package includes `syringe_perfusion\locales\en.json` and `ja.json` inside each frozen application. The strict release scan excludes local settings (including daily assignment locks), runtime state, validation evidence, logs, and numeric local COM assignments. Existing beta.1 through beta.4 versioned artifacts are not renamed or relabeled.

## Safe installation and upgrade

Do not overwrite an entire working microscope installation with the ZIP.

Preferred upgrade:

1. Verify the ZIP SHA-256.
2. Extract the new release into a new versioned directory.
3. Run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\upgrade_windows.ps1 `
  -NewRelease "<NEW_VERSION_DIRECTORY>" `
  -ExistingInstallation "<CURRENT_INSTALLATION>" `
  -Destination "<NEW_WORKING_INSTALLATION>"
```

4. Confirm that external `config`, `config\runtime`, `config\validation`, commissioning reports, `nis_logs`, and local wrappers were preserved.
5. Standard tracked wrappers are refreshed. Keep local customizations in `nis_cmd\local`, `*_local.cmd`, or `*.local.cmd`.
6. Run `a4ctl\a4ctl.exe --version`, `config-path`, `preflight`, and `validation-status`.
7. Reconfirm the commissioning build identity before hardware use.

The helper refuses an existing destination so rollback remains the old installation directory.

## Continuous integration

GitHub Actions runs Windows and Linux tests, wrapper/static safety checks, and a Windows PyInstaller smoke build for pull requests and pushes to `main`. CI sets explicit dry-run markers, requires no secrets, never publishes releases or tags, and uploads only the clean PyInstaller staging output.
